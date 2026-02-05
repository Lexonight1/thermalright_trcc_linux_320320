"""
Tests for GUI components and layout fixes.

Tests the following fixes:
1. Duplicate bottom controls removed (setup_bottom_toolbar not called)
2. Logo overlap fixed (TRCC text removed since background has it)
3. Initial theme loading on startup
4. Preview frame sizing and pack_propagate
"""

import pytest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestOverlayRenderer:
    """Test the OverlayRenderer class."""

    def test_renderer_initialization(self):
        """Test OverlayRenderer initializes with None background."""
        from trcc.gui import OverlayRenderer
        renderer = OverlayRenderer()

        assert renderer.background is None
        assert renderer.theme_mask is None
        assert renderer.config == {}

    def test_renderer_set_background(self):
        """Test setting a background image."""
        from trcc.gui import OverlayRenderer
        from PIL import Image

        renderer = OverlayRenderer()
        test_img = Image.new('RGB', (100, 100), color='red')
        renderer.set_background(test_img)

        assert renderer.background is not None
        # Should be resized to WIDTH x HEIGHT (320x320)
        assert renderer.background.size == (320, 320)

    def test_renderer_set_none_background(self):
        """Test setting background to None."""
        from trcc.gui import OverlayRenderer
        from PIL import Image

        renderer = OverlayRenderer()
        test_img = Image.new('RGB', (100, 100), color='red')
        renderer.set_background(test_img)
        renderer.set_background(None)

        assert renderer.background is None

    def test_renderer_render_no_background(self):
        """Test rendering with no background produces transparent image."""
        from trcc.gui import OverlayRenderer

        renderer = OverlayRenderer()
        result = renderer.render({})

        assert result is not None
        assert result.mode == 'RGBA'
        assert result.size == (320, 320)

    def test_renderer_render_with_background(self):
        """Test rendering with a background."""
        from trcc.gui import OverlayRenderer
        from PIL import Image

        renderer = OverlayRenderer()
        test_img = Image.new('RGB', (320, 320), color='blue')
        renderer.set_background(test_img)

        result = renderer.render({})

        assert result is not None
        # Should preserve background color
        pixel = result.getpixel((160, 160))
        # Blue pixel (0, 0, 255, 255) in RGBA
        assert pixel[2] == 255  # Blue channel


class TestGuiSetup:
    """Test GUI setup and initialization."""

    def test_data_dir_exists(self):
        """Test that DATA_DIR constant is defined."""
        from trcc.gui import DATA_DIR
        # DATA_DIR should be a string path
        assert isinstance(DATA_DIR, str)

    def test_width_height_constants(self):
        """Test WIDTH and HEIGHT constants."""
        from trcc.gui import WIDTH, HEIGHT
        assert WIDTH == 320
        assert HEIGHT == 320

    def test_format_metric_time(self):
        """Test time formatting."""
        from trcc.gui import format_metric
        from datetime import datetime

        # Test 24-hour format (format 0)
        now = datetime.now()
        result = format_metric('time', now, time_format=0)
        assert ':' in result
        # Should be HH:mm format
        assert len(result) == 5

    def test_format_metric_date(self):
        """Test date formatting."""
        from trcc.gui import format_metric
        from datetime import datetime

        now = datetime.now()
        result = format_metric('date', now, date_format=0)
        assert '/' in result

    def test_format_metric_weekday(self):
        """Test weekday formatting."""
        from trcc.gui import format_metric
        from datetime import datetime

        now = datetime.now()
        result = format_metric('weekday', now)
        # Should be a day name like "MON", "TUE", etc.
        assert len(result) >= 2


class TestGuiLayoutFixes:
    """Test the layout fixes made to the GUI."""

    def test_no_duplicate_toolbar_call(self):
        """Verify setup_bottom_toolbar is not called in setup_ui.

        The bottom toolbar was removed because the control_bar inside
        preview_frame already provides these controls.
        """
        import inspect
        from trcc.gui import FormCZTV

        # Get the source code of setup_ui method
        source = inspect.getsource(FormCZTV.setup_ui)

        # Should NOT contain a call to setup_bottom_toolbar()
        # (it's commented out now)
        assert 'self.setup_bottom_toolbar()' not in source

    def test_title_bar_no_duplicate_text(self):
        """Verify _create_title_bar doesn't add duplicate TRCC text.

        The TRCC text is in the background image, so we don't create
        a text label anymore.
        """
        import inspect
        from trcc.gui import FormCZTV

        # Get the source code of _create_title_bar method
        source = inspect.getsource(FormCZTV._create_title_bar)

        # Should NOT create a "TRCC" text label
        assert 'text="TRCC"' not in source

    def test_initial_theme_loading_scheduled(self):
        """Verify _load_initial_theme is scheduled on startup."""
        import inspect
        from trcc.gui import FormCZTV

        # Check setup_ui schedules _load_initial_theme
        source = inspect.getsource(FormCZTV.setup_ui)
        assert '_load_initial_theme' in source

    def test_load_initial_theme_method_exists(self):
        """Verify _load_initial_theme method exists."""
        from trcc.gui import FormCZTV
        assert hasattr(FormCZTV, '_load_initial_theme')
        assert callable(getattr(FormCZTV, '_load_initial_theme'))


class TestSystemTray:
    """Test system tray functionality."""

    def test_systray_module_importable(self):
        """Test that systray module can be imported."""
        try:
            from trcc.systray import TRCCSystray, PYSTRAY_AVAILABLE
            assert True
        except ImportError:
            # pystray might not be installed - that's OK
            pytest.skip("pystray not installed")

    def test_systray_signal_patch(self):
        """Test that systray has signal patching for thread safety."""
        try:
            from trcc.systray import TRCCSystray
            import inspect

            # Get the start method source
            source = inspect.getsource(TRCCSystray.start)

            # Should contain signal patching code
            assert 'patched_signal' in source or 'signal.signal' in source
        except ImportError:
            pytest.skip("pystray not installed")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
