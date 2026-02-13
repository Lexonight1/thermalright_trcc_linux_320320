"""Media frame decoders for TRCC Linux.

Pure infrastructure — decodes video/animation files into frames + metadata.
No playback state (play/pause/stop/seek). That belongs in MediaService.

Decoders:
    VideoDecoder   — FFmpeg pipe → list of PIL frames + fps
    ThemeZtDecoder — Theme.zt binary → list of PIL frames + per-frame delays
"""

from __future__ import annotations

import io
import logging
import os
import struct
import subprocess

from PIL import Image

log = logging.getLogger(__name__)


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available in PATH."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


FFMPEG_AVAILABLE = _check_ffmpeg()


class VideoDecoder:
    """Decode video frames via FFmpeg pipe. No playback state."""

    def __init__(self, video_path: str, target_size: tuple[int, int] = (320, 320)) -> None:
        if not FFMPEG_AVAILABLE:
            raise RuntimeError(
                "FFmpeg not available. Install: sudo dnf install ffmpeg"
            )
        self.frames: list[Image.Image] = []
        self.fps: int = 16  # Windows: originalImageHz = 16

        self._decode(video_path, target_size)

    def _decode(self, video_path: str, target_size: tuple[int, int]) -> None:
        """Decode all frames through FFmpeg pipe."""
        w, h = target_size
        result = subprocess.run([
            'ffmpeg', '-i', video_path,
            '-r', str(self.fps),
            '-vf', f'scale={w}:{h}',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-loglevel', 'error', 'pipe:1',
        ], capture_output=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()[:200]}")

        raw = result.stdout
        frame_size = w * h * 3
        for i in range(0, len(raw), frame_size):
            chunk = raw[i:i + frame_size]
            if len(chunk) < frame_size:
                break
            self.frames.append(Image.frombytes('RGB', (w, h), chunk))

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def close(self) -> None:
        self.frames = []

    @staticmethod
    def extract_frames(
        video_path: str,
        output_dir: str,
        target_size: tuple[int, int] = (320, 320),
        max_frames: int | None = None,
    ) -> int:
        """Extract video frames to PNG files via FFmpeg."""
        if not FFMPEG_AVAILABLE:
            log.warning("FFmpeg not available for video extraction")
            return 0

        os.makedirs(output_dir, exist_ok=True)
        w, h = target_size

        cmd = [
            'ffmpeg', '-i', video_path, '-y',
            '-vf', f'scale={w}:{h}',
        ]
        if max_frames:
            cmd.extend(['-vframes', str(max_frames)])
        cmd.extend(['-f', 'image2', os.path.join(output_dir, 'frame_%04d.png')])

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode != 0:
                log.error("FFmpeg error: %s", result.stderr.decode()[:200])
                return 0
        except subprocess.TimeoutExpired:
            log.error("FFmpeg timed out")
            return 0
        except Exception:
            log.exception("FFmpeg failed")
            return 0

        extracted = len([
            f for f in os.listdir(output_dir)
            if f.startswith('frame_') and f.endswith('.png')
        ])
        log.info("Extracted %d frames to %s", extracted, output_dir)
        return extracted


class ThemeZtDecoder:
    """Decode Theme.zt animation files. No playback state.

    Theme.zt format (Windows UCVideoCut.BmpToThemeFile):
    - byte: 0xDC magic (220)
    - int32: frame_count
    - int32[frame_count]: timestamps in ms
    - for each frame: int32 size + JPEG bytes
    """

    def __init__(self, zt_path: str, target_size: tuple[int, int] | None = None) -> None:
        self.frames: list[Image.Image] = []
        self.timestamps: list[int] = []
        self.delays: list[int] = []

        with open(zt_path, 'rb') as f:
            magic = struct.unpack('B', f.read(1))[0]
            if magic != 0xDC:
                raise ValueError(f"Invalid Theme.zt magic: 0x{magic:02X}, expected 0xDC")

            frame_count = struct.unpack('<i', f.read(4))[0]

            for _ in range(frame_count):
                self.timestamps.append(struct.unpack('<i', f.read(4))[0])

            for _ in range(frame_count):
                size = struct.unpack('<i', f.read(4))[0]
                img = Image.open(io.BytesIO(f.read(size)))
                if target_size and img.size != target_size:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                self.frames.append(img)

        # Calculate delays from timestamps
        for i in range(len(self.timestamps)):
            if i < len(self.timestamps) - 1:
                delay = self.timestamps[i + 1] - self.timestamps[i]
            else:
                delay = self.delays[-1] if self.delays else 42  # ~24fps default
            self.delays.append(max(1, delay))

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def fps(self) -> float:
        """Average fps derived from delays."""
        if not self.delays:
            return 24.0
        avg_delay = sum(self.delays) / len(self.delays)
        return 1000.0 / avg_delay if avg_delay > 0 else 24.0

    def close(self) -> None:
        for frame in self.frames:
            if hasattr(frame, 'close'):
                frame.close()
        self.frames = []


# Backward-compat aliases
VideoPlayer = VideoDecoder
ThemeZtPlayer = ThemeZtDecoder
GIFAnimator = VideoDecoder
GIFThemeLoader = VideoDecoder
