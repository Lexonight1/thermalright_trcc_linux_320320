"""``AppProxy.events`` — the client half of the observe channel.

Both Qt skins build a ``BusBridge(app.events)`` at construction.  Until this
existed that was an ``AttributeError`` on a proxy, so a GUI could not run as a
daemon client at all — which is the whole reason ``TRCC_DAEMON=1`` stayed off
by default and the Command bus stayed optional rather than mandatory.

What is pinned here is what a reader cannot see from the code: that events
arrive as REAL typed instances (``BusBridge`` subscribes by type, so a dict
would silently deliver nothing), that opening the stream is lazy (a CLI
one-shot must not pay for a subscription it never reads), and that a dead
stream is surfaced rather than leaving a GUI looking connected while every
panel quietly stops updating.
"""
from __future__ import annotations

import threading
import time

import pytest

from trcc.app import App
from trcc.core.events import DeviceConnected, ThemeLoaded
from trcc.ipc import IPCServer
from trcc.proxy import AppProxy


@pytest.fixture()
def daemon(fake_platform, tmp_path, monkeypatch):
    """A real IPCServer on a throwaway socket, plus a real AppProxy."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    app = App(fake_platform)
    srv = IPCServer(app)
    srv.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, srv, AppProxy()
    srv.shutdown()


def _wait(seen: list, n: int = 1, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while len(seen) < n and time.monotonic() < deadline:
        time.sleep(0.02)


def test_a_proxy_observes_events_published_daemon_side(daemon) -> None:
    app, _srv, proxy = daemon
    seen: list = []
    proxy.events.subscribe(DeviceConnected, seen.append)
    time.sleep(0.4)                      # reader attaches

    app.events.publish(DeviceConnected(key="0402:3922", resolution=(320, 320)))
    _wait(seen)

    assert len(seen) == 1
    assert seen[0].key == "0402:3922"


def test_events_arrive_as_typed_instances_not_dicts(daemon) -> None:
    """``BusBridge`` subscribes BY TYPE — a dict would deliver nothing."""
    app, _srv, proxy = daemon
    seen: list = []
    proxy.events.subscribe(ThemeLoaded, seen.append)
    time.sleep(0.4)

    app.events.publish(ThemeLoaded(key="k", theme_name="Theme3"))
    _wait(seen)

    assert isinstance(seen[0], ThemeLoaded)
    assert seen[0].theme_name == "Theme3"


def test_type_routing_is_preserved_across_the_wire(daemon) -> None:
    """A subscriber for one type must not receive another."""
    app, _srv, proxy = daemon
    themes: list = []
    connects: list = []
    proxy.events.subscribe(ThemeLoaded, themes.append)
    proxy.events.subscribe(DeviceConnected, connects.append)
    time.sleep(0.4)

    app.events.publish(ThemeLoaded(key="k", theme_name="A"))
    _wait(themes)

    assert len(themes) == 1
    assert connects == [], "an event was delivered to the wrong subscriber"


def test_the_stream_is_lazy(daemon) -> None:
    """A CLI one-shot that never observes must not open a subscription."""
    _app, srv, proxy = daemon
    proxy.dispatch
    time.sleep(0.2)
    assert not srv._subscribers, "the stream opened without anyone asking"

    proxy.events
    time.sleep(0.4)
    assert srv._subscribers, "accessing .events did not open the stream"


def test_events_is_the_same_bus_every_time(daemon) -> None:
    """Two panels subscribing must land on ONE bus, not two streams."""
    _app, srv, proxy = daemon
    first, second = proxy.events, proxy.events
    time.sleep(0.4)
    assert first is second
    assert len(srv._subscribers) == 1


def test_a_dead_daemon_is_surfaced_not_silent(daemon, caplog) -> None:
    """A GUI must not sit there looking connected while nothing updates."""
    import logging

    _app, srv, proxy = daemon
    proxy.events.subscribe(DeviceConnected, lambda _e: None)
    time.sleep(0.4)

    with caplog.at_level(logging.WARNING, logger="trcc.proxy"):
        srv.shutdown()
        deadline = time.monotonic() + 5.0
        while proxy._stream_open and time.monotonic() < deadline:
            time.sleep(0.05)

    assert not proxy._stream_open
    assert any("event stream CLOSED" in r.message for r in caplog.records), (
        "the stream died silently — that is the failure mode this guards"
    )


def test_dispatch_still_works_alongside_a_live_stream(daemon) -> None:
    """The two halves share a daemon; neither may starve the other."""
    from trcc.core.commands import ListLanguages

    _app, _srv, proxy = daemon
    proxy.events.subscribe(DeviceConnected, lambda _e: None)
    time.sleep(0.4)

    result = proxy.dispatch(ListLanguages())
    assert result.ok and result.languages
