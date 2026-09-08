"""``AppProxy.dispatch`` — three outcomes, three shapes.

The shapes were chosen from measurement, not taste.  Two facts decided it:

* **198 of 492 dispatch sites never check ``.ok``.**  So a failure returned as
  ``Result(ok=False)`` is read as data — ``DiscoverResult(ok=False)`` carries
  ``products=[]``, which renders "no devices" on a screen whose daemon just
  died.
* **Neither failure is new.**  A dead daemon already raised a bare
  ``ConnectionRefusedError``; a Command that raised daemon-side already
  produced a base ``Result`` that threw ``AttributeError`` on first field
  access.  Both were unsurvivable already — they were just illegible.
"""
from __future__ import annotations

import socket
from typing import TYPE_CHECKING, cast

import pytest

from trcc import ipc
from trcc.core.commands import ListDevices
from trcc.core.errors import (
    DaemonUnavailableError,
    RemoteCommandError,
    TransportError,
    TrccError,
)
from trcc.core.results import DevicesListResult
from trcc.proxy import AppProxy

if TYPE_CHECKING:
    from trcc.app import App

_HAS_AF_UNIX = hasattr(socket, "AF_UNIX")
pytestmark = pytest.mark.skipif(not _HAS_AF_UNIX, reason="IPC requires AF_UNIX")


def test_a_successful_command_still_returns_its_typed_result(monkeypatch) -> None:
    """The happy path is untouched — this is the shape 4700 tests rely on."""
    monkeypatch.setattr(
        ipc, "one_shot_request",
        lambda env, timeout=0: ipc.encode_result(
            DevicesListResult(ok=True, message="fine"),
        ),
    )
    result = AppProxy(timeout=1).dispatch(ListDevices())
    assert isinstance(result, DevicesListResult)
    assert result.ok and result.devices == []


def test_a_dead_daemon_raises_a_named_error_not_an_empty_result(monkeypatch) -> None:
    """Every transport failure becomes one named error a caller can catch.

    Without this the caller saw ``ConnectionRefusedError``/``TimeoutError``
    with no hint that a daemon was even involved — and could not distinguish
    it from a device I/O error.
    """
    for exc in (ConnectionRefusedError(111, "refused"),
                FileNotFoundError(2, "no socket"),
                ConnectionResetError(104, "reset"),
                TimeoutError("timed out")):
        def boom(env, timeout=0, _e=exc):
            raise _e
        monkeypatch.setattr(ipc, "one_shot_request", boom)
        with pytest.raises(DaemonUnavailableError) as caught:
            AppProxy(timeout=1).dispatch(ListDevices())
        assert "ListDevices was not run" in str(caught.value)
        # Catchable by the family a caller already handles.
        assert isinstance(caught.value, TransportError)


def test_a_command_that_raised_daemon_side_re_raises_here(monkeypatch) -> None:
    """In-process a raising Command propagates; over the socket it must too.

    The daemon has to catch (one client's bad Command cannot kill the process
    that owns USB), so the CLIENT is where the shape is restored.
    """
    monkeypatch.setattr(
        ipc, "one_shot_request",
        lambda env, timeout=0: {
            "type": "Result", "ok": False,
            "message": "RuntimeError: boom",
            ipc._ERROR_KEY: "RuntimeError: boom",
        },
    )
    with pytest.raises(RemoteCommandError) as caught:
        AppProxy(timeout=1).dispatch(ListDevices())
    assert "ListDevices" in str(caught.value)
    assert "RuntimeError: boom" in str(caught.value)
    assert isinstance(caught.value, TrccError)


def test_a_command_that_FAILED_is_not_confused_with_one_that_RAISED(monkeypatch) -> None:
    """``ok=False`` is data; a raise is not.  The marker is what separates them.

    This is the whole point of the distinction: ``SetBrightness`` on an unknown
    key legitimately answers ``ok=False`` and callers handle it.  Turning that
    into an exception would break every guard already written against it.
    """
    monkeypatch.setattr(
        ipc, "one_shot_request",
        lambda env, timeout=0: ipc.encode_result(
            DevicesListResult(ok=False, message="no devices attached"),
        ),
    )
    result = AppProxy(timeout=1).dispatch(ListDevices())
    assert isinstance(result, DevicesListResult)
    assert result.ok is False
    assert result.message == "no devices attached"


def test_the_error_marker_is_ignored_by_older_decoders() -> None:
    """Adding the key must not change how a Result decodes.

    ``_build_dataclass`` reads only declared fields, so the marker rides along
    invisibly — an older client decodes exactly what it always did.
    """
    envelope = ipc.encode_result(DevicesListResult(ok=True, message="hi"))
    with_marker = {**envelope, ipc._ERROR_KEY: "RuntimeError: boom"}
    assert ipc.decode_result(with_marker) == ipc.decode_result(envelope)


# ── The DAEMON side of the distinction ───────────────────────────────
#
# The tests above monkeypatch the transport, so they never reach
# ``_dispatch_envelope`` — and a mutation that marked EVERY response as a
# raise passed all five.  These two gate the half that mutation exposed.


class _FailingApp:
    """Its Command reports failure the normal way — a Result with ok=False."""

    def dispatch(self, cmd: object) -> DevicesListResult:
        return DevicesListResult(ok=False, message="none attached")


class _RaisingApp:
    """Its Command blows up."""

    def dispatch(self, cmd: object) -> DevicesListResult:
        raise RuntimeError("boom")


def test_a_failing_command_carries_NO_error_marker() -> None:
    """``ok=False`` is data.  Marking it would turn every handled failure —
    ``SetBrightness`` on an unknown key, a theme that will not load — into an
    exception, breaking every guard already written against it."""
    server = ipc.IPCServer(cast("App", _FailingApp()))
    envelope = server._dispatch_envelope(ipc.encode_command(ListDevices()))

    assert envelope["ok"] is False
    assert ipc._ERROR_KEY not in envelope


def test_a_raising_command_carries_the_error_marker() -> None:
    """A raise is not data, and the marker is the only thing that says so."""
    server = ipc.IPCServer(cast("App", _RaisingApp()))
    envelope = server._dispatch_envelope(ipc.encode_command(ListDevices()))

    assert envelope["ok"] is False
    assert envelope[ipc._ERROR_KEY] == "RuntimeError: boom"
