"""The gui skin's CONNECT-restore seam — the path with no coverage at all.

``LCDHandler.apply_device_config`` -> ``_refresh`` ->
``_restore_theme_and_preview(first_load=True)`` is what puts a theme on the
panel when the app starts with a device attached.  Measured 2026-09-03: **no
test drove either method.**  The nearest one
(``test_gui_overlay_restore``) claims in its docstring to drive "the whole
chain -- RestoreLastTheme -> the overlay restore -> Settings", but calls
``_restore_overlay_editor`` directly and never reaches the restore itself.

METHOD_UI.md's entry contract is "at any display-start -> RestoreDeviceState",
which is FOUR steps: no-op if already active, ``RestoreLastTheme``, auto-load
the first theme, then replay the persisted ``background_path`` video.  gui
dispatches only the second, so a user's cloud/user video background never
comes back after a restart -- cli and api both restore it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from trcc.adapters.render.qt import QtRenderer
from trcc.app import App
from trcc.core.commands import ConnectDevice

from .mock_platform import MockPlatform

_SPEC = {"type": "lcd", "vid": "0402", "pid": "3922",
         "pm": 101, "sub": 0, "fbl": 0}
_KEY = "0402:3922"
_RES = (320, 320)


class _Widget:
    """Permissive stand-in for a shared GUI widget — records nothing it is
    not asked about, so the handler runs without a real Qt panel."""

    def __getattr__(self, name: str) -> Any:
        def _noop(*a: Any, **k: Any) -> None:
            return None
        return _noop


class _Widgets(dict):
    def __missing__(self, key: str) -> Any:
        self[key] = _Widget()
        return self[key]


class _FakeTimer:
    def isActive(self) -> bool:          # Qt API shape, not PEP 8's call
        return False

    def __getattr__(self, name: str) -> Any:
        def _noop(*a: Any, **k: Any) -> None:
            return None
        return _noop


def _jpeg(w: int, h: int) -> bytes:
    """One real solid JPEG — playbacks hold ENCODED frames."""
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QImage

    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0xFF0000)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG")
    return bytes(data)


def _write_theme(directory: Path, name: str) -> Path:
    """A minimal loadable theme at the canonical filenames."""
    theme = directory / name
    theme.mkdir(parents=True, exist_ok=True)
    (theme / "trcc.json").write_text(json.dumps({
        "name": name, "width": _RES[0], "height": _RES[1],
        "overlay_enabled": False, "elements": [],
    }))
    (theme / "00.png").write_bytes(_jpeg(*_RES))
    return theme


@pytest.fixture
def handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real ``LCDHandler`` over a real ``App``, plus the media call log.

    ``MediaService.load_video`` is stubbed the way ``test_video_playback``
    does it, so no ffmpeg runs and the test can assert WHAT was asked for.
    """
    from trcc.services.media import MediaService, Playback
    from trcc.ui.gui.lcd_handler import LCDHandler

    app = App(MockPlatform([_SPEC], tmp_path), renderer=QtRenderer())
    app.attach(0x0402, 0x3922)
    assert app.dispatch(ConnectDevice(key=_KEY)).ok

    decoded: list[Path] = []

    def _fake_load(self, device_key: str, path: Path, size, **kwargs):
        decoded.append(Path(path))
        playback = Playback(frames=[_jpeg(*_RES)], fps=kwargs.get("fps", 15))
        self._playbacks[device_key] = playback
        return playback

    monkeypatch.setattr(MediaService, "load_video", _fake_load)

    h = LCDHandler(_KEY, _Widgets(), lambda cb, *a, **k: _FakeTimer(),
                   tmp_path, app=app, lcd_idx=_KEY)
    h._pm.ui_active = True
    return h, app, decoded


def test_connect_restore_replays_the_persisted_video_background(
    handler, tmp_path: Path,
) -> None:
    """A cloud/user video background must survive a restart.

    ``SetBackground`` persists ``DeviceSettings.background_path`` and then
    delegates to ``PlayVideo`` -- so the gui WRITES this value every time a
    user picks a video.  Nothing in either GUI ever reads it back: the only
    two mentions of ``background_path`` in ``ui/gui`` are comments.  cli and
    api replay it through ``RestoreDeviceState`` step 4.

    Fresh ``active_themes`` is the point -- that is what a restart looks like,
    and it is what makes ``RestoreDeviceState`` do the work instead of
    no-opping on an already-active theme.
    """
    h, app, decoded = handler
    theme = _write_theme(app.platform.paths().theme_dir(*_RES), "Aurora")
    app.settings.set_current_theme(_KEY, str(theme.resolve()))

    video = tmp_path / "my_background.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")      # magic only; decode is stubbed
    app.settings.set_background_path(_KEY, str(video))
    assert not app.active_themes, "fixture drift: a restart starts with none"

    h._restore_theme_and_preview(first_load=True)

    assert video in decoded, (
        "the persisted video background was never replayed on connect — the "
        "user's background is lost on every restart, while cli and api "
        "restore it"
    )


def test_connect_restore_still_loads_the_persisted_theme(handler) -> None:
    """Characterisation: the behaviour that must NOT change.

    Whatever the restore dispatches, a persisted theme still has to end up
    active — this is the whole job of the connect path and the reason the
    swap is confined to the ``first_load=True`` branch.
    """
    h, app, _decoded = handler
    theme = _write_theme(app.platform.paths().theme_dir(*_RES), "Aurora")
    app.settings.set_current_theme(_KEY, str(theme.resolve()))

    h._restore_theme_and_preview(first_load=True)

    assert app.active_themes.get(_KEY) is not None, (
        "the connect restore no longer loads the persisted theme"
    )
