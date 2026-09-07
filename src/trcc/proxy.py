"""AppProxy — client-side drop-in for ``App`` that talks to the daemon.

UIs hold a typed ``App`` and never distinguish; in daemon mode the
``_boot.trcc()`` factory hands them an ``AppProxy`` instead.  Only
``dispatch(cmd) -> Result`` is real — every call serializes the Command,
sends it over the Unix socket, and reconstructs the typed Result.

``events`` is the ONE other attribute that is real, and it has to be: both
Qt skins build a ``BusBridge(app.events)`` at construction, so without it a
GUI cannot run as a daemon client at all — which is what kept
``TRCC_DAEMON=1`` off by default and the bus optional.  The proxy answers it
with a LOCAL ``EventBus`` fed by the daemon's stream, so every existing
subscriber works unchanged and nothing in ``ui/`` needs to know.

Other ``App`` attributes (``platform`` / ``settings`` / ``devices`` /
``display``) are not exposed by the proxy.  UIs that need state should
dispatch a Command (``DiscoverDevices`` / ``GetPlatformInfo`` /
``ReadSensors``) — that's the API contract daemon mode honors.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import TypeVar

from . import ipc
from .core.commands import Command
from .core.events import EventBus
from .core.results import Result

log = logging.getLogger(__name__)


R = TypeVar("R", bound=Result)


class AppProxy:
    """Forwards every ``dispatch(cmd)`` call to a running daemon.

    Construction is cheap (no socket connection until the first
    dispatch) so import-time use of ``_boot.trcc()`` doesn't pay
    a round-trip per invocation.
    """

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._events: EventBus | None = None
        self._reader: threading.Thread | None = None
        self._stream_open = False

    def dispatch(self, cmd: Command[R]) -> R:
        """Serialize *cmd*, round-trip through the daemon, return the Result."""
        envelope = ipc.encode_command(cmd)
        response = ipc.one_shot_request(envelope, timeout=self._timeout)
        result = ipc.decode_result(response)
        log.debug("AppProxy.dispatch: %s -> %s",
                  type(cmd).__name__, type(result).__name__)
        return result  # type: ignore[return-value]   # caller's TypeVar binds the subclass

    # ── The observe half ────────────────────────────────────────────────

    @property
    def events(self) -> EventBus:
        """A local bus carrying the daemon's events.

        Lazily opens the stream on first access, so a CLI one-shot that never
        observes anything pays nothing.  Subscribers registered here receive
        real reconstructed ``Event`` instances — ``BusBridge`` subscribes BY
        TYPE, so decoding to the concrete class (not a dict) is what makes the
        Qt skins work untouched.
        """
        if self._events is None:
            log.info("AppProxy.events: opening the daemon event stream")
            self._events = EventBus()
            self._start_reader()
        return self._events

    def _start_reader(self) -> None:
        """Spawn the background reader that feeds the local bus."""
        log.info("AppProxy._start_reader: starting reader thread")
        self._reader = threading.Thread(
            target=self._read_events, daemon=True, name="trcc-proxy-events",
        )
        self._reader.start()

    def _read_events(self) -> None:
        """Read the stream until EOF, republishing onto the local bus.

        EOF is SURFACED, not swallowed: a GUI whose daemon died would
        otherwise sit there looking connected while every panel silently
        stopped updating.  The warning names the count so a report shows how
        far it got.
        """
        seen = 0
        try:
            sock = ipc.open_event_stream(timeout=self._timeout)
        except (OSError, ConnectionError) as e:
            log.warning("AppProxy._read_events: cannot open the event stream "
                        "(%s: %s) — this client will receive no events",
                        type(e).__name__, e)
            return
        self._stream_open = True
        try:
            with sock, sock.makefile("rb") as reader:
                for line in reader:
                    if not line.strip():
                        continue
                    try:
                        event = ipc.decode_event(json.loads(line.decode()))
                    except (ValueError, KeyError) as e:
                        log.warning("AppProxy._read_events: undecodable event "
                                    "dropped (%s: %s)", type(e).__name__, e)
                        continue
                    seen += 1
                    assert self._events is not None
                    self._events.publish(event)
        except OSError as e:
            log.warning("AppProxy._read_events: stream failed after %d "
                        "event(s) — %s: %s", seen, type(e).__name__, e)
        finally:
            self._stream_open = False
            log.warning("AppProxy._read_events: event stream CLOSED after %d "
                        "event(s); this client is no longer observing",
                        seen)

    # ── Attributes that a real App exposes but the proxy can't ──────────

    def __getattr__(self, name: str) -> object:
        raise AttributeError(
            f"AppProxy has no attribute {name!r} — daemon mode only exposes "
            "dispatch(cmd); use a Command to query App state remotely"
        )
