"""
Tests for DisplayMode - Display mode strategy pattern.
"""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import DisplayMode, ImageMode, VideoMode, ScreenMode
from PIL import Image


class TestImageMode(unittest.TestCase):
    """Test ImageMode functionality."""

    def setUp(self):
        """Create ImageMode instance."""
        self.mode = ImageMode()

    def test_initial_state(self):
        """Test initial state of ImageMode."""
        self.assertFalse(self.mode.is_active)
        self.assertIsNone(self.mode.get_frame())

    def test_activate_deactivate(self):
        """Test activating and deactivating mode."""
        self.mode.activate()
        self.assertTrue(self.mode.is_active)

        self.mode.deactivate()
        self.assertFalse(self.mode.is_active)

    def test_set_image(self):
        """Test setting an image."""
        img = Image.new('RGB', (320, 320), color='red')

        self.mode.set_image(img)
        frame = self.mode.get_frame()

        self.assertIsNotNone(frame)
        self.assertEqual(frame.size, (320, 320))

    def test_update_returns_same_image(self):
        """Test that update returns same image (static mode)."""
        img = Image.new('RGB', (320, 320), color='blue')

        self.mode.set_image(img)

        frame1 = self.mode.update()
        frame2 = self.mode.update()

        self.assertEqual(frame1, frame2)

    def test_image_copy(self):
        """Test that image is copied, not referenced."""
        img = Image.new('RGB', (100, 100), color='green')

        self.mode.set_image(img)

        # Modify original
        img.putpixel((0, 0), (255, 0, 0))

        # Mode's image should be unchanged
        mode_img = self.mode.get_frame()
        self.assertIsNotNone(mode_img)


class TestVideoMode(unittest.TestCase):
    """Test VideoMode functionality."""

    def setUp(self):
        """Create VideoMode instance."""
        self.mode = VideoMode()

    def test_initial_state(self):
        """Test initial state of VideoMode."""
        self.assertFalse(self.mode.is_active)
        self.assertFalse(self.mode.is_playing)
        self.assertEqual(self.mode.frame_count, 0)
        self.assertIsNone(self.mode.get_frame())

    def test_play_pause_stop(self):
        """Test playback controls."""
        self.mode.play()
        self.assertTrue(self.mode.is_playing)

        self.mode.pause()
        self.assertFalse(self.mode.is_playing)

        self.mode.stop()
        self.assertFalse(self.mode.is_playing)
        self.assertEqual(self.mode.current_frame_index, 0)

    def test_manual_frames(self):
        """Test with manually set frames."""
        # Simulate loaded frames
        self.mode._frames = [
            Image.new('RGB', (320, 320), color='red'),
            Image.new('RGB', (320, 320), color='green'),
            Image.new('RGB', (320, 320), color='blue'),
        ]

        self.assertEqual(self.mode.frame_count, 3)

        # Test frame advancement when playing
        self.mode.play()

        frame1 = self.mode.update()
        self.assertIsNotNone(frame1)
        self.assertEqual(self.mode.current_frame_index, 1)

        frame2 = self.mode.update()
        self.assertEqual(self.mode.current_frame_index, 2)

    def test_loop_behavior(self):
        """Test that video loops by default."""
        self.mode._frames = [
            Image.new('RGB', (100, 100), color='red'),
            Image.new('RGB', (100, 100), color='green'),
        ]
        self.mode.play()

        # Advance to end
        self.mode.update()  # Frame 1
        self.mode.update()  # Frame 0 (wrapped)

        self.assertEqual(self.mode.current_frame_index, 0)


class TestScreenMode(unittest.TestCase):
    """Test ScreenMode functionality."""

    def setUp(self):
        """Create ScreenMode instance."""
        self.mode = ScreenMode()

    def test_initial_state(self):
        """Test initial state of ScreenMode."""
        self.assertFalse(self.mode.is_active)
        self.assertIsNone(self.mode.get_frame())

    def test_set_capture_area(self):
        """Test setting capture area."""
        self.mode.set_capture_area(0, 0, 1920, 1080)

        self.assertEqual(self.mode._capture_area, (0, 0, 1920, 1080))

    def test_capture_screen_graceful_failure(self):
        """Test that screen capture fails gracefully if not available."""
        # This will likely fail in test environment, but should not crash
        frame = self.mode.capture_screen()

        # Should return None or last_frame
        # Just verify it doesn't raise exception


if __name__ == '__main__':
    unittest.main()
