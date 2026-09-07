"""Event fan-out over the daemon socket (Phase B, increment 4).

Daemon mode had Command dispatch and no events at all, which is why a GUI
cannot be a pure bus client: both skins build a ``BusBridge`` from
``app.events``, and ``AppProxy`` has no such attribute.  This is the server
half -- a client can now ask for a stream and receive real events.

What is pinned here is the behaviour a reader cannot see from the code: that
the handler does not do the work, that one event is encoded once for many
listeners, that a dead client is evicted rather than blocking the daemon, and
that a full queue drops events instead of growing memory.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from trcc.app import App
from trcc.core.events import DeviceConnected, FrameSent, SensorsUpdated
from trcc.ipc import IPCServer, decode_event, socket_path


def _server(app: App) -> IPCServer:
    srv = IPCServer(app)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _client() -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect(str(socket_path()))
    return s


def _subscribe(sock: socket.socket, types: list[str]) -> dict:
    sock.sendall(json.dumps({"subscribe": types}).encode() + b"\n")
    return json.loads(sock.makefile("rb").readline().decode())


@pytest.fixture()
def server(fake_platform, tmp_path, monkeypatch):
    """A real IPCServer on a throwaway socket."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    app = App(fake_platform)
    srv = _server(app)
    yield app, srv
    srv.shutdown()


def _await_event(reader, timeout: float = 5.0):
    line = reader.readline()
    assert line, "stream closed before an event arrived"
    return decode_event(json.loads(line.decode()))


def test_a_subscriber_receives_a_real_event(server) -> None:
    app, _srv = server
    sock = _client()
    ack = _subscribe(sock, ["DeviceConnected"])
    assert ack["ok"] and ack["subscribed"] == ["DeviceConnected"]

    reader = sock.makefile("rb")
    app.events.publish(DeviceConnected(key="0402:3922", resolution=(320, 320)))

    event = _await_event(reader)
    assert isinstance(event, DeviceConnected)
    assert event.key == "0402:3922"
    assert event.resolution == (320, 320)
    sock.close()


def test_star_subscribes_to_everything(server) -> None:
    app, _srv = server
    sock = _client()
    ack = _subscribe(sock, ["*"])
    assert ack["ok"]

    reader = sock.makefile("rb")
    app.events.publish(SensorsUpdated(readings={"cpu:temp": 42.0}))
    assert isinstance(_await_event(reader), SensorsUpdated)
    sock.close()


def test_an_unknown_event_name_is_refused_not_silently_accepted(server) -> None:
    """A typo'd type would otherwise look like a subscription that never fires."""
    sock = _client()
    ack = _subscribe(sock, ["NoSuchEvent"])
    assert not ack["ok"]
    assert "NoSuchEvent" in ack["message"]
    sock.close()


def test_an_empty_subscription_is_refused(server) -> None:
    sock = _client()
    ack = _subscribe(sock, [])
    assert not ack["ok"]
    sock.close()


def test_one_event_reaches_every_listener(server) -> None:
    """Two clients, one publish -- both get it (encoded once, written twice)."""
    app, _srv = server
    a, b = _client(), _client()
    assert _subscribe(a, ["DeviceConnected"])["ok"]
    assert _subscribe(b, ["*"])["ok"]
    ra, rb = a.makefile("rb"), b.makefile("rb")

    app.events.publish(DeviceConnected(key="0416:5302", resolution=(480, 480)))

    for reader in (ra, rb):
        assert _await_event(reader).key == "0416:5302"
    a.close()
    b.close()


def test_a_subscriber_only_gets_the_types_it_asked_for(server) -> None:
    app, _srv = server
    sock = _client()
    assert _subscribe(sock, ["DeviceConnected"])["ok"]
    reader = sock.makefile("rb")

    app.events.publish(SensorsUpdated(readings={"cpu:temp": 1.0}))   # not wanted
    app.events.publish(DeviceConnected(key="k", resolution=(1, 1)))  # wanted

    event = _await_event(reader)
    assert isinstance(event, DeviceConnected), "an unwanted type leaked through"
    sock.close()


def test_a_dead_client_is_evicted_and_dispatch_keeps_working(server) -> None:
    """The daemon must survive a subscriber vanishing mid-stream."""
    from trcc.core.commands import ListLanguages
    from trcc.ipc import decode_result, encode_command

    app, srv = server
    sock = _client()
    assert _subscribe(sock, ["*"])["ok"]
    sock.close()                      # vanish without unsubscribing

    # Publishing must not raise, and must eventually drop the subscriber.
    for _ in range(50):
        app.events.publish(DeviceConnected(key="k", resolution=(1, 1)))
    deadline = time.monotonic() + 5.0
    while srv._subscribers and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not srv._subscribers, "a closed client was never evicted"

    # And the request/response half still answers.
    c = _client()
    c.sendall(json.dumps(encode_command(ListLanguages())).encode() + b"\n")
    reply = decode_result(json.loads(c.makefile("rb").readline().decode()))
    assert reply.ok
    c.close()


def test_the_handler_never_encodes_on_the_publishing_thread(server) -> None:
    """``_on_bus_event`` must only enqueue.

    It runs synchronously on whichever thread published -- the render tick for
    ``FrameSent``, the udev thread for eleven others.  Encoding or writing
    there is the defect this design exists to avoid.
    """
    import trcc.ipc as ipc_mod

    _app, srv = server

    def _explode(_event):
        raise AssertionError(
            "encode_event was called on the publishing thread — the handler "
            "must only enqueue",
        )

    monkey = ipc_mod.encode_event
    ipc_mod.encode_event = _explode          # type: ignore[assignment]
    try:
        srv._on_bus_event(FrameSent(key="k", bytes_sent=1))
    finally:
        ipc_mod.encode_event = monkey        # type: ignore[assignment]
    # Buffered, not encoded and not written.
    assert srv._event_q.qsize() == 1


def test_a_full_queue_drops_instead_of_blocking(server) -> None:
    """A stalled subscriber must not be able to grow the daemon's memory."""
    from trcc.ipc import _EVENT_QUEUE_MAX

    _app, srv = server
    for _ in range(_EVENT_QUEUE_MAX + 50):
        srv._on_bus_event(FrameSent(key="k", bytes_sent=1))

    assert srv._event_q.qsize() <= _EVENT_QUEUE_MAX
    assert srv._dropped >= 50


def test_shutdown_releases_subscriber_streams(server) -> None:
    """Otherwise the daemon cannot exit while a GUI is attached."""
    _app, srv = server
    sock = _client()
    assert _subscribe(sock, ["*"])["ok"]
    assert srv._subscribers

    srv.shutdown()
    assert not srv._subscribers
    sock.close()
