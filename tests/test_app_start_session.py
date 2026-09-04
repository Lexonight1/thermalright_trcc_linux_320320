"""``App.start_session`` — the partner of ``App.close``.

Its four calls used to be copy-pasted into ``run_daemon``, ``run_gui`` and
``run_qtgui``; the API had none of them, and the daemon's copy was missing
``metrics_loop.start()`` — a reporter ran ``trccd.service`` and watched a
connected device stay permanently blank (#148).

The coldplug half is the one the daemon never had at all: only Linux's hotplug
monitor replays already-present devices, so on Windows / macOS / BSD a daemon
came up owning USB with nothing connected.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FakePlatform
from trcc.app import App


@pytest.fixture
def app(tmp_home: Path) -> App:
    return App(platform=FakePlatform(tmp_home))


def _spy_on_coldplug(monkeypatch) -> list[object]:
    """Record each ``discover_and_connect`` call, still running the real one.

    Replacing it outright would drop the ``_coldplug_done`` side effect that
    ``start_session`` reads — the double would then model the contract wrong
    and the test would fail against correct code.
    """
    calls: list[object] = []
    real = App.discover_and_connect

    def spy(self: App, on_progress=None) -> None:
        calls.append(on_progress)
        real(self, on_progress)

    monkeypatch.setattr(App, "discover_and_connect", spy)
    return calls


def test_start_session_runs_the_coldplug(app: App, monkeypatch) -> None:
    """The half the daemon never had — without it a device is never connected
    on any OS whose hotplug monitor reports only NEW devices."""
    calls = _spy_on_coldplug(monkeypatch)

    app.start_session()

    assert calls == [None], "start_session must coldplug"


def test_start_session_starts_all_three_loops(app: App) -> None:
    """#148 was one missing line out of these three."""
    app.start_session()
    try:
        assert app.metrics_loop.is_running, "metrics loop not started (#148)"
        assert app.led_animation_loop.is_running, "LED animation loop not started"
        assert app.platform.hotplug().is_running, "hotplug listener not started"
    finally:
        app.close()


def test_a_coldplug_that_already_ran_is_not_repeated(app: App, monkeypatch) -> None:
    """gui discovers on its splash worker and then calls start_session.  A
    second coldplug would re-attempt every device that failed and record its
    failure twice."""
    calls = _spy_on_coldplug(monkeypatch)

    app.discover_and_connect()          # the splash worker's call
    app.start_session()

    assert len(calls) == 1, "start_session repeated a coldplug the splash did"


def test_start_session_is_idempotent(app: App, monkeypatch) -> None:
    seen = _spy_on_coldplug(monkeypatch)
    try:
        app.start_session()
        app.start_session()
        assert len(seen) == 1
        assert app.metrics_loop.is_running
    finally:
        app.close()


def test_on_progress_reaches_the_coldplug(app: App, monkeypatch) -> None:
    """qtgui passes nothing; gui's splash passes a Qt signal so per-device
    status shows while connecting."""
    seen = _spy_on_coldplug(monkeypatch)

    sink: list[str] = []
    app.start_session(sink.append)

    assert seen == [sink.append]


def test_close_undoes_start_session(app: App) -> None:
    """The two are a pair; close must stop everything start_session began."""
    app.start_session()
    app.close()

    assert not app.metrics_loop.is_running
    assert not app.led_animation_loop.is_running
    assert not app.platform.hotplug().is_running
