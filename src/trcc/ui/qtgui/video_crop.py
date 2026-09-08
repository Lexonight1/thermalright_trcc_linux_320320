"""VideoCropDialog — choose start/end, preview, export to Theme.zt.

A modal :class:`QDialog` over the ``ExportVideoClip`` Command:

* Frame preview (single ffmpeg seek per scrub).
* Timeline with in/out handles + click-to-seek.
* Time labels (current / duration / clip start / clip end).
* Fit-width / fit-height / rotate / preview-play / export buttons.
* Progress bar fed by ``VideoExportProgress`` events.

The dialog never blocks the GUI, and no longer owns a thread to
achieve that.  It used to run :class:`VideoExporter` in a private
``_ExportThread`` — a window owning the encode, invisible to the CLI,
the API and to any other client of the same daemon, and a crash under
``TRCC_DAEMON=1`` where the file may not even be on this machine.  Now
it dispatches, matches the token it gets back, and watches the bus.

Successful exports leave the produced ``Theme.zt`` on disk; the caller
reads :meth:`output_path` to find it.  Cancel returns ``None``.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import ExportVideoClip, ProbeVideoDuration
from ...core.models import (
    ZT_FPS as EXPORT_FPS,
)
from ...core.models import (
    ZT_MAX_DURATION_MS as MAX_DURATION_MS,
)

if TYPE_CHECKING:
    from ...app import App
    from ..bus_bridge import BusBridge

log = logging.getLogger(__name__)


_PREVIEW_W = 480
_PREVIEW_H = 300
_TIMELINE_W = 480
_TIMELINE_H = 22
_HANDLE_W = 12
_FRAME_INTERVAL_MS = int(1000 / EXPORT_FPS)


def _format_ms(ms: int) -> str:
    """``hh:mm:ss`` (we never display milliseconds — too fiddly to read)."""
    s = max(0, int(ms / 1000))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class _TimelineBar(QWidget):
    """Painted timeline with two draggable handles + click-to-seek."""

    start_changed = Signal(int)  # ms
    end_changed = Signal(int)    # ms
    seek_requested = Signal(int)  # ms

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_TIMELINE_W, _TIMELINE_H)
        self.setMouseTracking(True)
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._dragging: str | None = None

    # ── Public API ───────────────────────────────────────────────────

    def set_range(self, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        self._start_ms = 0
        self._end_ms = min(self._duration_ms, MAX_DURATION_MS)
        self.update()

    def set_start(self, start_ms: int) -> None:
        self._start_ms = max(0, min(start_ms, self._end_ms - 1))
        self.update()

    def set_end(self, end_ms: int) -> None:
        self._end_ms = max(self._start_ms + 1, min(end_ms, self._duration_ms))
        self.update()

    def clip_ms(self) -> tuple[int, int]:
        return self._start_ms, self._end_ms

    # ── Geometry ─────────────────────────────────────────────────────

    def _ms_to_x(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return 0
        return int(ms / self._duration_ms * _TIMELINE_W)

    def _x_to_ms(self, x: int) -> int:
        if self._duration_ms <= 0:
            return 0
        x = max(0, min(_TIMELINE_W, x))
        return int(x / _TIMELINE_W * self._duration_ms)

    # ── Painting ─────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#555"), 1))
        p.setBrush(QBrush(QColor("#2a2a2a")))
        p.drawRect(0, 0, _TIMELINE_W - 1, _TIMELINE_H - 1)

        if self._duration_ms > 0:
            sx = self._ms_to_x(self._start_ms)
            ex = self._ms_to_x(self._end_ms)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(50, 130, 70, 160)))
            p.drawRect(sx, 1, max(1, ex - sx), _TIMELINE_H - 2)

            # Start handle
            p.setPen(QPen(QColor("#88ff88"), 1))
            p.setBrush(QBrush(QColor("#226633")))
            p.drawRect(sx, 0, _HANDLE_W, _TIMELINE_H - 1)
            # End handle
            p.setPen(QPen(QColor("#ff8888"), 1))
            p.setBrush(QBrush(QColor("#662222")))
            p.drawRect(ex - _HANDLE_W, 0, _HANDLE_W, _TIMELINE_H - 1)
        p.end()

    # ── Mouse ────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration_ms <= 0:
            return
        x = int(event.position().x())
        sx = self._ms_to_x(self._start_ms)
        ex = self._ms_to_x(self._end_ms)
        if sx <= x <= sx + _HANDLE_W:
            self._dragging = "start"
        elif ex - _HANDLE_W <= x <= ex:
            self._dragging = "end"
        else:
            self.seek_requested.emit(self._x_to_ms(x))

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging or self._duration_ms <= 0:
            return
        ms = self._x_to_ms(int(event.position().x()))
        if self._dragging == "start":
            self._start_ms = max(0, min(ms, self._end_ms - 1))
            if self._end_ms - self._start_ms > MAX_DURATION_MS:
                self._end_ms = self._start_ms + MAX_DURATION_MS
            self.start_changed.emit(self._start_ms)
            self.end_changed.emit(self._end_ms)
            self.seek_requested.emit(self._start_ms)
        else:
            self._end_ms = max(self._start_ms + 1, min(ms, self._duration_ms))
            if self._end_ms - self._start_ms > MAX_DURATION_MS:
                self._start_ms = self._end_ms - MAX_DURATION_MS
            self.start_changed.emit(self._start_ms)
            self.end_changed.emit(self._end_ms)
            self.seek_requested.emit(self._end_ms)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None


class VideoCropDialog(QDialog):
    """Modal: load a video, trim it, export a ``Theme.zt``.

    Usage::

        dialog = VideoCropDialog(app, bus, key, parent)
        dialog.load_video(Path("clip.mp4"))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            zt_path = dialog.output_path()

    Takes the *key* rather than a resolution: the canvas is the panel's
    own, and ``ExportVideoClip`` already resolves it from the device or
    the product registry.  A caller passing dimensions would be a second
    place that lookup could be got wrong.
    """

    def __init__(
        self,
        app: App,
        bus: BusBridge,
        key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop video → Theme.zt")
        self.setModal(True)

        self._app = app
        self._bus = bus
        self._key = key
        self._video_path: Path | None = None
        self._duration_ms = 0
        self._rotation = 0
        self._preview_pix: QPixmap | None = None
        self._output: Path | None = None
        self._exporting = False
        #: The export this dialog started.  Every client of one daemon sees
        #: every export event, so a dialog that reacted to all of them would
        #: track a stranger's progress bar.
        self._token = ""
        self._playing = False
        self._play_pos_ms = 0
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)
        self._build()
        # Queued: the runner publishes from its worker thread, and a Qt
        # widget may only be touched on the main one.
        self._bus.video_export_progress.connect(
            self._on_export_progress, Qt.ConnectionType.QueuedConnection)
        self._bus.video_export_finished.connect(
            self._on_export_finished, Qt.ConnectionType.QueuedConnection)

    # ── Public API ───────────────────────────────────────────────────

    def load_video(self, path: Path) -> bool:
        """Load *path* for trimming.  Returns ``False`` on failure.

        The duration comes from ``ProbeVideoDuration`` rather than from
        ``probe_duration_ms``: under ``TRCC_DAEMON=1`` this process may
        not be the one that can read the file, and the Command runs
        where it can.  The Result already carries a worded message, so
        this method no longer invents one.
        """
        log.info("load_video: path=%s key=%s", path, self._key)
        self._video_path = path
        self._rotation = 0
        probe = self._app.dispatch(ProbeVideoDuration(path=path))
        self._duration_ms = probe.duration_ms
        if not probe.ok:
            log.warning("load_video: %s — %s", path, probe.message)
            self._info.setText(f"{path.name}: {probe.message}")
            return False
        self._target_label.setText(f"Source: {path.name}")
        self._duration_label.setText(_format_ms(self._duration_ms))
        self._timeline.set_range(self._duration_ms)
        self._start_label.setText(_format_ms(0))
        self._end_label.setText(_format_ms(
            min(self._duration_ms, MAX_DURATION_MS),
        ))
        self._seek_preview(0)
        return True

    def output_path(self) -> Path | None:
        """Path to the produced Theme.zt after Accept, else ``None``."""
        return self._output

    # ── UI build ─────────────────────────────────────────────────────

    def _build(self) -> None:
        toolbar = QToolBar(self)
        act_rotate = QAction("Rotate 90°", self)
        act_rotate.triggered.connect(self._on_rotate)
        toolbar.addAction(act_rotate)
        toolbar.addSeparator()
        self._play_action = QAction("Play", self)
        self._play_action.triggered.connect(self._toggle_play)
        toolbar.addAction(self._play_action)

        self._target_label = QLabel("Target: (load a video)", self)
        self._target_label.setStyleSheet("color: #aaa;")

        self._preview = QLabel(self)
        self._preview.setFixedSize(_PREVIEW_W, _PREVIEW_H)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background-color: #000; border: 1px solid #333;",
        )
        self._preview.setText("Preview")

        self._timeline = _TimelineBar(self)
        self._timeline.start_changed.connect(self._on_start_changed)
        self._timeline.end_changed.connect(self._on_end_changed)
        self._timeline.seek_requested.connect(self._seek_preview)

        self._current_label = QLabel("00:00:00", self)
        self._current_label.setStyleSheet("color: #6c6;")
        self._duration_label = QLabel("00:00:00", self)
        self._duration_label.setStyleSheet("color: #ccc;")
        self._start_label = QLabel("00:00:00", self)
        self._start_label.setStyleSheet("color: #6c6;")
        self._end_label = QLabel("00:00:00", self)
        self._end_label.setStyleSheet("color: #c66;")

        clock_row = QHBoxLayout()
        clock_row.addWidget(QLabel("Cursor:", self))
        clock_row.addWidget(self._current_label)
        clock_row.addStretch(1)
        clock_row.addWidget(QLabel("Duration:", self))
        clock_row.addWidget(self._duration_label)

        clip_row = QHBoxLayout()
        clip_row.addWidget(QLabel("Clip in:", self))
        clip_row.addWidget(self._start_label)
        clip_row.addStretch(1)
        clip_row.addWidget(QLabel("Clip out:", self))
        clip_row.addWidget(self._end_label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)

        self._info = QLabel("", self)
        self._info.setStyleSheet("color: #aaa;")
        self._info.setWordWrap(True)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok,
        ).setText("Export")
        self._buttons.accepted.connect(self._on_export_clicked)
        self._buttons.rejected.connect(self._on_cancel_clicked)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(toolbar)
        root.addWidget(self._target_label)
        root.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._timeline, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addLayout(clock_row)
        root.addLayout(clip_row)
        root.addWidget(self._progress)
        root.addWidget(self._info)
        root.addWidget(self._buttons)

    # ── Frame preview (ffmpeg seek) ──────────────────────────────────

    def _seek_preview(self, ms: int) -> None:
        if self._video_path is None:
            return
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-ss", f"{ms / 1000.0}",
                    "-i", str(self._video_path),
                    "-vframes", "1",
                    "-f", "image2pipe", "-vcodec", "bmp",
                    "-v", "error", "-y", "-",
                ],
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log.debug("video preview seek failed: %s", e)
            return
        if result.returncode != 0 or not result.stdout:
            return
        img = QImage.fromData(result.stdout)
        if img.isNull():
            return
        if self._rotation:
            img = img.transformed(QTransform().rotate(self._rotation))
        scaled = img.scaled(
            _PREVIEW_W, _PREVIEW_H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_pix = QPixmap.fromImage(scaled)
        self._preview.setPixmap(self._preview_pix)
        self._current_label.setText(_format_ms(ms))

    # ── Signal handlers ──────────────────────────────────────────────

    def _on_start_changed(self, ms: int) -> None:
        log.info("_on_start_changed: ms=%s", ms)
        self._start_label.setText(_format_ms(ms))

    def _on_end_changed(self, ms: int) -> None:
        log.info("_on_end_changed: ms=%s", ms)
        self._end_label.setText(_format_ms(ms))

    def _on_rotate(self) -> None:
        log.info("_on_rotate")
        self._rotation = (self._rotation + 90) % 360
        start, _ = self._timeline.clip_ms()
        self._seek_preview(start)

    def _toggle_play(self) -> None:
        if self._playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self) -> None:
        if self._video_path is None:
            return
        self._playing = True
        self._play_action.setText("Pause")
        start, _ = self._timeline.clip_ms()
        self._play_pos_ms = start
        self._play_timer.start(_FRAME_INTERVAL_MS)

    def _stop_play(self) -> None:
        self._playing = False
        self._play_action.setText("Play")
        self._play_timer.stop()

    def _on_play_tick(self) -> None:
        log.debug("_on_play_tick")
        start, end = self._timeline.clip_ms()
        if self._play_pos_ms >= end:
            self._play_pos_ms = start
        self._seek_preview(self._play_pos_ms)
        self._play_pos_ms += _FRAME_INTERVAL_MS

    # ── Export ───────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        log.info("_on_export_clicked: key=%s rotation=%d",
                 self._key, self._rotation)
        if self._video_path is None:
            self._info.setText("Load a video first.")
            return
        if self._exporting:
            log.debug("_on_export_clicked: already exporting — ignored")
            return
        self._stop_play()
        start, end = self._timeline.clip_ms()
        result = self._app.dispatch(ExportVideoClip(
            key=self._key,
            path=self._video_path,
            start_ms=start,
            end_ms=end,
            rotation=self._rotation,
        ))
        if not result.ok:
            # Every guard answers here, at the click, rather than arriving
            # as a failed event once the worker gets to it.
            log.warning("_on_export_clicked: refused — %s", result.message)
            self._info.setText(result.message)
            return
        self._token = result.token
        self._exporting = True
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok,
        ).setEnabled(False)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._target_label.setText(
            f"Target: {result.target_w}×{result.target_h}px • "
            f"Source: {self._video_path.name}",
        )
        self._info.setText("Exporting…")

    def _on_cancel_clicked(self) -> None:
        log.info("_on_cancel_clicked: exporting=%s", self._exporting)
        # A running export is NOT killed.  It belongs to the app, not to
        # this window: another client may be watching it, and under
        # TRCC_DAEMON=1 it is not even this process's to terminate.  The
        # old code called ``QThread.terminate`` on its private worker.
        self._token = ""
        self._stop_play()
        self.reject()

    def _on_export_progress(self, event: object) -> None:
        token = getattr(event, "token", "")
        if token != self._token:
            return
        percent = getattr(event, "percent", 0)
        message = getattr(event, "message", "")
        log.debug("_on_export_progress: %d%% %s", percent, message)
        self._progress.setValue(percent)
        self._info.setText(message)

    def _on_export_finished(self, event: object) -> None:
        if getattr(event, "token", "") != self._token:
            return
        ok = bool(getattr(event, "ok", False))
        message = getattr(event, "message", "")
        path = getattr(event, "path", "")
        log.info("_on_export_finished: ok=%s path=%s message=%s",
                 ok, path, message)
        self._exporting = False
        self._token = ""
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok,
        ).setEnabled(True)
        if not ok:
            self._info.setText(f"Export failed: {message}")
            self._progress.setVisible(False)
            return
        self._output = Path(path)
        self._info.setText(message)
        self.accept()


