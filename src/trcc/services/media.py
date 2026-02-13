"""Video/animation playback service.

Pure Python (FFmpeg via media_player), no Qt dependencies.
Absorbed from VideoController + VideoModel in controllers.py/models.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..core.models import PlaybackState, VideoState

log = logging.getLogger(__name__)


class MediaService:
    """Video/animation lifecycle: load, play, pause, stop, advance."""

    # LCD send interval: send every Nth frame.
    LCD_SEND_INTERVAL = 1

    def __init__(self) -> None:
        self._state = VideoState()
        self._frames: list[Any] = []
        self._source_path: Path | None = None
        self._target_size: tuple[int, int] = (320, 320)
        self._player: Any = None
        self._frame_counter = 0
        self._progress_counter = 0

    # ── Target size ──────────────────────────────────────────────────

    def set_target_size(self, width: int, height: int) -> None:
        self._target_size = (width, height)

    # ── Load ─────────────────────────────────────────────────────────

    def load(self, path: Path, preload: bool = True) -> bool:
        """Load video/animation file (.mp4, .gif, .zt).

        Returns True if loaded successfully.
        """
        self.stop()
        self._source_path = path
        self._frames.clear()

        try:
            from ..media_player import ThemeZtPlayer, VideoPlayer

            suffix = path.suffix.lower()
            if suffix == '.zt':
                self._player = ThemeZtPlayer(str(path), self._target_size)
            else:
                self._player = VideoPlayer(str(path), self._target_size)

            self._state.total_frames = self._player.frame_count
            self._state.fps = self._player.fps if self._player.fps > 0 else 16
            self._state.current_frame = 0
            self._state.state = PlaybackState.STOPPED

            if preload and hasattr(self._player, 'frames'):
                self._frames = self._player.frames

            return True
        except Exception as e:
            log.error("Failed to load video: %s", e)
            return False

    # ── Playback control ─────────────────────────────────────────────

    def play(self) -> None:
        if self._player:
            self._player.play()
            self._state.state = PlaybackState.PLAYING
            self._frame_counter = 0

    def pause(self) -> None:
        if self._player:
            self._player.pause()
            self._state.state = PlaybackState.PAUSED

    def stop(self) -> None:
        if self._player:
            self._player.stop()
        self._state.state = PlaybackState.STOPPED
        self._state.current_frame = 0

    def toggle(self) -> None:
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def seek(self, percent: float) -> None:
        if self._state.total_frames > 0:
            frame = int((percent / 100) * self._state.total_frames)
            self._state.current_frame = max(
                0, min(frame, self._state.total_frames - 1))

    # ── Frame access ─────────────────────────────────────────────────

    def get_frame(self, index: int | None = None) -> Any | None:
        """Get frame at index (or current frame)."""
        if index is None:
            index = self._state.current_frame

        if self._frames and 0 <= index < len(self._frames):
            return self._frames[index]

        if self._player:
            self._player.current_frame = index
            return self._player.get_current_frame()

        return None

    def advance_frame(self) -> Any | None:
        """Advance to next frame and return it.

        Returns PIL Image or None if not playing.
        """
        if self._state.state != PlaybackState.PLAYING:
            return None

        frame = self.get_frame()

        self._state.current_frame += 1
        if self._state.current_frame >= self._state.total_frames:
            if self._state.loop:
                self._state.current_frame = 0
            else:
                self._state.state = PlaybackState.STOPPED

        return frame

    def tick(self) -> tuple[Any | None, bool, tuple[float, str, str] | None]:
        """Called by timer to advance one frame.

        Returns:
            (frame, should_send_to_lcd, progress_tuple_or_none)
        """
        if not self.is_playing:
            return None, False, None

        frame = self.advance_frame()
        if not frame:
            return None, False, None

        # Progress update at ~2fps (every 8th frame)
        progress_info = None
        self._progress_counter += 1
        if self._progress_counter >= 8:
            self._progress_counter = 0
            progress_info = (
                self._state.progress,
                self._state.current_time_str,
                self._state.total_time_str,
            )

        # LCD send with frame skipping
        should_send = False
        self._frame_counter += 1
        if self._frame_counter >= self.LCD_SEND_INTERVAL:
            self._frame_counter = 0
            should_send = True

        return frame, should_send, progress_info

    # ── Properties ───────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self._state.state == PlaybackState.PLAYING

    @property
    def frame_interval_ms(self) -> int:
        return self._state.frame_interval_ms

    @property
    def source_path(self) -> Path | None:
        return self._source_path

    @property
    def progress(self) -> float:
        return self._state.progress

    @property
    def current_time_str(self) -> str:
        return self._state.current_time_str

    @property
    def total_time_str(self) -> str:
        return self._state.total_time_str

    @property
    def has_frames(self) -> bool:
        return bool(self._frames)

    @property
    def state(self) -> VideoState:
        return self._state
