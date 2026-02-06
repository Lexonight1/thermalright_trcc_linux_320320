"""Tests for gif_animator – GIF/video animation and Theme.zt playback."""

import io
import os
import struct
import tempfile
import unittest

from PIL import Image

from trcc.gif_animator import GIFAnimator, GIFThemeLoader, ThemeZtPlayer


def _make_gif(frames=3, size=(4, 4), durations=None):
    """Create a minimal GIF in a temp file. Returns path."""
    if durations is None:
        durations = [100] * frames

    imgs = []
    for i in range(frames):
        # Each frame gets a distinct color so we can tell them apart
        img = Image.new('RGB', size, color=(i * 80, 0, 0))
        imgs.append(img)

    path = tempfile.mktemp(suffix='.gif')
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=durations, loop=0)
    return path


def _make_theme_zt(frames=4, size=(8, 8), quality=50):
    """Create a minimal Theme.zt binary file. Returns path."""
    path = tempfile.mktemp(suffix='.zt')

    jpeg_blobs = []
    for i in range(frames):
        img = Image.new('RGB', size, color=(0, i * 60, 0))
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        jpeg_blobs.append(buf.getvalue())

    # Timestamps: 0, 42, 84, ...
    timestamps = [i * 42 for i in range(frames)]

    with open(path, 'wb') as f:
        f.write(struct.pack('B', 0xDC))           # magic
        f.write(struct.pack('<i', frames))          # frame_count
        for ts in timestamps:
            f.write(struct.pack('<i', ts))          # timestamps
        for blob in jpeg_blobs:
            f.write(struct.pack('<i', len(blob)))   # size
            f.write(blob)                           # JPEG data

    return path


# ── GIFAnimator ──────────────────────────────────────────────────────────────

class TestGIFAnimator(unittest.TestCase):
    """Core GIF playback logic."""

    def setUp(self):
        self.path = _make_gif(frames=3, durations=[100, 200, 150])
        self.anim = GIFAnimator(self.path)

    def tearDown(self):
        self.anim.close()
        os.unlink(self.path)

    def test_frame_count(self):
        self.assertEqual(self.anim.frame_count, 3)

    def test_frames_are_rgb(self):
        for i in range(self.anim.frame_count):
            self.assertEqual(self.anim.get_frame(i).mode, 'RGB')

    def test_delays_extracted(self):
        self.assertEqual(len(self.anim.delays), 3)
        self.assertEqual(self.anim.delays, [100, 200, 150])

    def test_get_frame_default_is_current(self):
        """get_frame() with no arg returns current_frame."""
        self.anim.current_frame = 1
        frame = self.anim.get_frame()
        self.assertEqual(frame, self.anim.frames[1])

    def test_get_frame_out_of_range(self):
        """Out-of-range index returns frame 0."""
        self.assertIsNotNone(self.anim.get_frame(999))

    def test_next_frame_advances(self):
        self.assertEqual(self.anim.current_frame, 0)
        self.anim.next_frame()
        self.assertEqual(self.anim.current_frame, 1)

    def test_next_frame_loops(self):
        self.anim.loop = True
        for _ in range(3):
            self.anim.next_frame()
        self.assertEqual(self.anim.current_frame, 0)

    def test_next_frame_stops_when_no_loop(self):
        self.anim.loop = False
        for _ in range(10):
            self.anim.next_frame()
        self.assertEqual(self.anim.current_frame, 2)
        self.assertFalse(self.anim.playing)

    def test_reset(self):
        self.anim.current_frame = 2
        self.anim.reset()
        self.assertEqual(self.anim.current_frame, 0)

    def test_play_pause(self):
        self.anim.play()
        self.assertTrue(self.anim.is_playing())
        self.anim.pause()
        self.assertFalse(self.anim.is_playing())

    def test_set_speed_clamps(self):
        self.anim.set_speed(0.01)
        self.assertAlmostEqual(self.anim.speed_multiplier, 0.1)
        self.anim.set_speed(99)
        self.assertAlmostEqual(self.anim.speed_multiplier, 10.0)

    def test_get_delay_respects_speed(self):
        self.anim.speed_multiplier = 2.0
        delay = self.anim.get_delay(0)
        self.assertEqual(delay, 50)  # 100 / 2.0

    def test_is_last_frame(self):
        self.assertFalse(self.anim.is_last_frame())
        self.anim.current_frame = 2
        self.assertTrue(self.anim.is_last_frame())


# ── GIFThemeLoader ───────────────────────────────────────────────────────────

class TestGIFThemeLoader(unittest.TestCase):
    """Static helpers for GIF→theme conversion."""

    def setUp(self):
        self.gif_path = _make_gif(frames=2, size=(8, 8))

    def tearDown(self):
        os.unlink(self.gif_path)

    def test_load_gif_theme_returns_animator(self):
        anim = GIFThemeLoader.load_gif_theme(self.gif_path)
        self.assertIsInstance(anim, GIFAnimator)
        self.assertEqual(anim.frame_count, 2)
        anim.close()

    def test_gif_to_frames_extracts_files(self):
        with tempfile.TemporaryDirectory() as out_dir:
            count = GIFThemeLoader.gif_to_frames(
                self.gif_path, out_dir, target_size=(8, 8))
            self.assertEqual(count, 2)
            # Check frame files exist
            self.assertTrue(os.path.exists(os.path.join(out_dir, 'frame_0000.png')))
            self.assertTrue(os.path.exists(os.path.join(out_dir, 'frame_0001.png')))
            # Delay txt files
            self.assertTrue(os.path.exists(os.path.join(out_dir, 'frame_0000.txt')))
            # Background frame
            self.assertTrue(os.path.exists(os.path.join(out_dir, '00.png')))


# ── ThemeZtPlayer ────────────────────────────────────────────────────────────

class TestThemeZtPlayer(unittest.TestCase):
    """Theme.zt binary animation player."""

    def setUp(self):
        self.path = _make_theme_zt(frames=4, size=(8, 8))
        self.player = ThemeZtPlayer(self.path)

    def tearDown(self):
        self.player.close()
        os.unlink(self.path)

    def test_frame_count(self):
        self.assertEqual(self.player.frame_count, 4)

    def test_timestamps(self):
        self.assertEqual(self.player.timestamps, [0, 42, 84, 126])

    def test_delays_computed(self):
        # [42, 42, 42, 42] — last frame reuses previous delay
        self.assertEqual(self.player.delays, [42, 42, 42, 42])

    def test_frames_are_rgb(self):
        for frame in self.player.frames:
            self.assertEqual(frame.mode, 'RGB')

    def test_play_pause_stop(self):
        self.assertFalse(self.player.is_playing())
        self.player.play()
        self.assertTrue(self.player.is_playing())
        self.player.pause()
        self.assertFalse(self.player.is_playing())
        self.player.stop()
        self.assertEqual(self.player.current_frame, 0)

    def test_next_frame_loops(self):
        for _ in range(4):
            self.player.next_frame()
        self.assertEqual(self.player.current_frame, 0)

    def test_next_frame_stops_no_loop(self):
        self.player.loop = False
        for _ in range(10):
            self.player.next_frame()
        self.assertEqual(self.player.current_frame, 3)
        self.assertFalse(self.player.playing)

    def test_seek_clamps(self):
        self.player.seek(-1)
        self.assertEqual(self.player.current_frame, 0)
        self.player.seek(0.5)
        self.assertEqual(self.player.current_frame, 1)
        self.player.seek(5.0)
        self.assertEqual(self.player.current_frame, 3)

    def test_get_progress(self):
        self.assertEqual(self.player.get_progress(), 0)
        self.player.current_frame = 3
        self.assertEqual(self.player.get_progress(), 100)

    def test_get_current_frame_returns_copy(self):
        f1 = self.player.get_current_frame()
        f2 = self.player.get_current_frame()
        self.assertIsNot(f1, f2)  # .copy() each time

    def test_get_delay(self):
        self.assertEqual(self.player.get_delay(), 42)

    def test_invalid_magic_raises(self):
        path = tempfile.mktemp(suffix='.zt')
        with open(path, 'wb') as f:
            f.write(b'\x00\x00\x00\x00\x00')
        with self.assertRaises(ValueError):
            ThemeZtPlayer(path)
        os.unlink(path)

    def test_resize_on_load(self):
        player = ThemeZtPlayer(self.path, target_size=(4, 4))
        self.assertEqual(player.frames[0].size, (4, 4))
        player.close()


if __name__ == '__main__':
    unittest.main()
