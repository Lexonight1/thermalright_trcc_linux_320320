#!/usr/bin/env python3
"""
Tests for GIF and Video animation support.
"""

import unittest
import sys
import os
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

# Import modules under test
try:
    from gif_animator import GIFAnimator, GIFThemeLoader, VideoPlayer, OPENCV_AVAILABLE
except ImportError as e:
    print(f"Import error: {e}")
    OPENCV_AVAILABLE = False


class TestGIFAnimator(unittest.TestCase):
    """Test GIF animation functionality."""

    @classmethod
    def setUpClass(cls):
        """Create a test GIF file."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_gif_path = os.path.join(cls.temp_dir, "test.gif")

        # Create a simple animated GIF with 4 frames
        frames = []
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        for color in colors:
            img = Image.new('RGB', (100, 100), color)
            frames.append(img)

        # Save as animated GIF
        frames[0].save(
            cls.test_gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=100,  # 100ms per frame
            loop=0
        )

    @classmethod
    def tearDownClass(cls):
        """Clean up temp directory."""
        shutil.rmtree(cls.temp_dir)

    def test_load_gif(self):
        """Test loading a GIF file."""
        animator = GIFAnimator(self.test_gif_path)
        self.assertEqual(animator.frame_count, 4)

    def test_get_frame(self):
        """Test getting individual frames."""
        animator = GIFAnimator(self.test_gif_path)

        frame = animator.get_frame(0)
        self.assertIsInstance(frame, Image.Image)
        self.assertEqual(frame.size, (100, 100))

    def test_frame_navigation(self):
        """Test advancing through frames."""
        animator = GIFAnimator(self.test_gif_path)

        self.assertEqual(animator.current_frame, 0)
        animator.next_frame()
        self.assertEqual(animator.current_frame, 1)
        animator.next_frame()
        self.assertEqual(animator.current_frame, 2)

    def test_loop_behavior(self):
        """Test that animation loops correctly."""
        animator = GIFAnimator(self.test_gif_path)
        animator.loop = True

        # Advance to last frame
        for _ in range(3):
            animator.next_frame()
        self.assertEqual(animator.current_frame, 3)

        # Should loop back to 0
        animator.next_frame()
        self.assertEqual(animator.current_frame, 0)

    def test_no_loop_behavior(self):
        """Test animation without looping."""
        animator = GIFAnimator(self.test_gif_path)
        animator.loop = False

        # Advance beyond last frame
        for _ in range(5):
            animator.next_frame()

        # Should stay at last frame
        self.assertEqual(animator.current_frame, 3)

    def test_play_pause(self):
        """Test play/pause state."""
        animator = GIFAnimator(self.test_gif_path)

        self.assertFalse(animator.is_playing())
        animator.play()
        self.assertTrue(animator.is_playing())
        animator.pause()
        self.assertFalse(animator.is_playing())

    def test_reset(self):
        """Test reset to first frame."""
        animator = GIFAnimator(self.test_gif_path)

        animator.next_frame()
        animator.next_frame()
        self.assertEqual(animator.current_frame, 2)

        animator.reset()
        self.assertEqual(animator.current_frame, 0)

    def test_get_delay(self):
        """Test frame delay retrieval."""
        animator = GIFAnimator(self.test_gif_path)

        delay = animator.get_delay()
        self.assertIsInstance(delay, int)
        self.assertGreater(delay, 0)

    def test_speed_multiplier(self):
        """Test speed adjustment."""
        animator = GIFAnimator(self.test_gif_path)
        normal_delay = animator.get_delay()

        animator.set_speed(2.0)  # Double speed
        fast_delay = animator.get_delay()

        self.assertEqual(fast_delay, normal_delay // 2)


class TestGIFThemeLoader(unittest.TestCase):
    """Test GIF theme loading utilities."""

    @classmethod
    def setUpClass(cls):
        """Create test resources."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_gif_path = os.path.join(cls.temp_dir, "test.gif")

        # Create test GIF
        frames = [Image.new('RGB', (100, 100), (i * 50, 0, 0)) for i in range(3)]
        frames[0].save(
            cls.test_gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir)

    def test_load_gif_theme(self):
        """Test loading GIF as theme."""
        animator = GIFThemeLoader.load_gif_theme(self.test_gif_path)
        self.assertIsInstance(animator, GIFAnimator)
        self.assertEqual(animator.frame_count, 3)

    def test_extract_frames(self):
        """Test extracting GIF frames to directory."""
        output_dir = os.path.join(self.temp_dir, "extracted")

        count = GIFThemeLoader.gif_to_frames(
            self.test_gif_path,
            output_dir,
            target_size=(320, 320)
        )

        self.assertEqual(count, 3)
        self.assertTrue(os.path.exists(os.path.join(output_dir, "frame_0000.png")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "00.png")))


@unittest.skipUnless(OPENCV_AVAILABLE, "OpenCV not installed")
class TestVideoPlayer(unittest.TestCase):
    """Test video playback functionality."""

    @classmethod
    def setUpClass(cls):
        """Create a test video file using OpenCV."""
        import cv2
        import numpy as np

        cls.temp_dir = tempfile.mkdtemp()
        cls.test_video_path = os.path.join(cls.temp_dir, "test.mp4")

        # Create a simple test video (10 frames, 100x100)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(cls.test_video_path, fourcc, 10, (100, 100))

        for i in range(10):
            # Create frame with gradient
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[:, :, 0] = i * 25  # Blue channel varies
            frame[:, :, 1] = 100     # Green constant
            frame[:, :, 2] = 200     # Red constant
            writer.write(frame)

        writer.release()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir)

    def test_load_video(self):
        """Test loading a video file."""
        player = VideoPlayer(self.test_video_path)
        self.assertEqual(player.frame_count, 10)
        player.close()

    def test_get_frame(self):
        """Test getting video frames as PIL Images."""
        player = VideoPlayer(self.test_video_path)

        frame = player.get_frame(0)
        self.assertIsInstance(frame, Image.Image)

        player.close()

    def test_target_size(self):
        """Test frame resizing to target size."""
        player = VideoPlayer(self.test_video_path, target_size=(320, 320))

        frame = player.get_frame(0)
        self.assertEqual(frame.size, (320, 320))

        player.close()

    def test_frame_navigation(self):
        """Test navigating through video frames."""
        player = VideoPlayer(self.test_video_path)

        self.assertEqual(player.current_frame, 0)
        player.next_frame()
        self.assertEqual(player.current_frame, 1)

        player.close()

    def test_seek(self):
        """Test seeking to specific frame."""
        player = VideoPlayer(self.test_video_path)

        player.seek(5)
        self.assertEqual(player.current_frame, 5)

        player.close()

    def test_seek_percent(self):
        """Test seeking by percentage."""
        player = VideoPlayer(self.test_video_path)

        player.seek_percent(50)
        self.assertEqual(player.current_frame, 5)  # 50% of 10 frames

        player.close()

    def test_get_progress(self):
        """Test progress calculation."""
        player = VideoPlayer(self.test_video_path)

        player.seek(5)
        progress = player.get_progress()
        self.assertEqual(progress, 50.0)

        player.close()

    def test_play_pause_stop(self):
        """Test playback controls."""
        player = VideoPlayer(self.test_video_path)

        self.assertFalse(player.is_playing())
        player.play()
        self.assertTrue(player.is_playing())
        player.pause()
        self.assertFalse(player.is_playing())
        
        player.seek(5)
        player.stop()
        self.assertFalse(player.is_playing())
        self.assertEqual(player.current_frame, 0)

        player.close()

    def test_get_delay(self):
        """Test frame delay calculation from FPS."""
        player = VideoPlayer(self.test_video_path)

        delay = player.get_delay()
        self.assertIsInstance(delay, int)
        self.assertGreater(delay, 0)
        # 10 FPS = 100ms delay
        self.assertAlmostEqual(delay, 100, delta=10)

        player.close()

    def test_speed_multiplier(self):
        """Test speed adjustment."""
        player = VideoPlayer(self.test_video_path)

        normal_delay = player.get_delay()
        player.set_speed(2.0)
        fast_delay = player.get_delay()

        self.assertEqual(fast_delay, normal_delay // 2)

        player.close()

    def test_loop_behavior(self):
        """Test video looping."""
        player = VideoPlayer(self.test_video_path)
        player.loop = True

        # Go to last frame
        player.seek(9)
        player.next_frame()

        # Should loop to 0
        self.assertEqual(player.current_frame, 0)

        player.close()

    def test_extract_frames_static(self):
        """Test static frame extraction method."""
        output_dir = os.path.join(self.temp_dir, "extracted")

        count = VideoPlayer.extract_frames(
            self.test_video_path,
            output_dir,
            target_size=(320, 320),
            max_frames=5
        )

        self.assertEqual(count, 5)
        self.assertTrue(os.path.exists(os.path.join(output_dir, "frame_0000.png")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "video_info.txt")))


class TestAnimatorIntegration(unittest.TestCase):
    """Integration tests for animation system."""

    def test_gif_and_video_share_interface(self):
        """Test that GIF and Video players have compatible interfaces."""
        # Common methods both should have
        common_methods = [
            'get_frame',
            'get_current_frame',
            'get_delay',
            'next_frame',
            'reset',
            'play',
            'pause',
            'set_speed',
            'is_playing',
        ]

        for method in common_methods:
            self.assertTrue(hasattr(GIFAnimator, method),
                          f"GIFAnimator missing method: {method}")
            if OPENCV_AVAILABLE:
                self.assertTrue(hasattr(VideoPlayer, method),
                              f"VideoPlayer missing method: {method}")


if __name__ == '__main__':
    unittest.main()
