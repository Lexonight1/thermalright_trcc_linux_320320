"""
Tests for ThemeManager - Theme management component.
"""

import unittest
import sys
import os
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ThemeManager, Theme


class TestThemeManager(unittest.TestCase):
    """Test ThemeManager singleton and theme operations."""

    def setUp(self):
        """Create temp directories for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.themes_dir = Path(self.temp_dir) / 'themes'
        self.themes_dir.mkdir()

        # Get fresh ThemeManager instance
        # Reset singleton for testing
        ThemeManager._instance = None
        self.manager = ThemeManager()

    def test_singleton(self):
        """Test that ThemeManager is a singleton."""
        manager1 = ThemeManager()
        manager2 = ThemeManager()

        self.assertIs(manager1, manager2)

    def test_theme_dataclass(self):
        """Test Theme dataclass creation."""
        theme = Theme(
            name='Test Theme',
            path='/test/path',
            theme_type='local',
            preview_image='/test/preview.png'
        )

        self.assertEqual(theme.name, 'Test Theme')
        self.assertEqual(theme.theme_type, 'local')
        self.assertIsNotNone(theme.background_images)
        self.assertEqual(len(theme.background_images), 0)

    def test_scan_local_themes_empty(self):
        """Test scanning empty themes directory."""
        themes = self.manager.scan_local_themes(str(self.themes_dir))

        self.assertEqual(len(themes), 0)

    def test_scan_local_themes_with_theme(self):
        """Test scanning directory with valid theme."""
        # Create theme directory
        theme_dir = self.themes_dir / 'Theme1'
        theme_dir.mkdir()

        # Create theme files
        (theme_dir / '00.png').touch()
        (theme_dir / '01.png').touch()
        (theme_dir / 'Theme.png').touch()
        (theme_dir / 'config1.dc').touch()

        themes = self.manager.scan_local_themes(str(self.themes_dir))

        self.assertEqual(len(themes), 1)
        self.assertEqual(themes[0].name, 'Theme1')
        self.assertEqual(themes[0].theme_type, 'local')
        self.assertEqual(len(themes[0].background_images), 2)

    def test_load_theme(self):
        """Test loading theme by name."""
        # Create and add theme
        theme = Theme(
            name='TestTheme',
            path='/test',
            theme_type='local'
        )
        self.manager.themes['TestTheme'] = theme

        loaded = self.manager.load_theme('TestTheme')

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.name, 'TestTheme')
        self.assertEqual(self.manager.current_theme, theme)

    def test_load_nonexistent_theme(self):
        """Test loading theme that doesn't exist."""
        loaded = self.manager.load_theme('NonExistent')

        self.assertIsNone(loaded)

    def test_get_all_themes(self):
        """Test getting all themes."""
        theme1 = Theme(name='Theme1', path='/1', theme_type='local')
        theme2 = Theme(name='Theme2', path='/2', theme_type='cloud')

        self.manager.themes['Theme1'] = theme1
        self.manager.themes['Theme2'] = theme2

        all_themes = self.manager.get_all_themes()
        self.assertEqual(len(all_themes), 2)

    def test_get_themes_by_type(self):
        """Test filtering themes by type."""
        theme1 = Theme(name='Theme1', path='/1', theme_type='local')
        theme2 = Theme(name='Theme2', path='/2', theme_type='cloud')
        theme3 = Theme(name='Theme3', path='/3', theme_type='local')

        self.manager.themes['Theme1'] = theme1
        self.manager.themes['Theme2'] = theme2
        self.manager.themes['Theme3'] = theme3

        local_themes = self.manager.get_all_themes(theme_type='local')

        self.assertEqual(len(local_themes), 2)
        self.assertTrue(all(t.theme_type == 'local' for t in local_themes))

    def test_clear_cache(self):
        """Test clearing image cache."""
        self.manager._cache['test'] = "cached_data"

        self.manager.clear_cache()

        self.assertEqual(len(self.manager._cache), 0)

    def tearDown(self):
        """Clean up temp directories."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
