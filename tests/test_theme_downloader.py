"""
Tests for theme_downloader — pack registry, download, list, info, and removal.

Tests cover:
- THEME_REGISTRY built from FBL_TO_RESOLUTION
- PackInfo dataclass
- Short alias resolution (themes-320 → themes-320x320)
- list_available() / show_info() display output
- download_pack() delegation to DataManager.ensure_themes()
- remove_pack() uninstall flow
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from trcc.theme_downloader import (
    _SHORT_ALIASES,
    THEME_REGISTRY,
    PackInfo,
    ThemeDownloader,
    _resolve_pack_name,
    download_pack,
    list_available,
    remove_pack,
    show_info,
)

# ── Registry ─────────────────────────────────────────────────────────────


class TestThemeRegistry(unittest.TestCase):
    """Validate the dynamically built THEME_REGISTRY."""

    def test_registry_not_empty(self):
        self.assertGreater(len(THEME_REGISTRY), 0)

    def test_all_entries_are_pack_info(self):
        for pack_id, info in THEME_REGISTRY.items():
            with self.subTest(pack=pack_id):
                self.assertIsInstance(info, PackInfo)

    def test_resolution_format(self):
        """Resolution must be WxH format (e.g., '320x320')."""
        for pack_id, info in THEME_REGISTRY.items():
            with self.subTest(pack=pack_id):
                self.assertRegex(info.resolution, r'^\d+x\d+$')

    def test_pack_id_matches_resolution(self):
        """Pack ID format is themes-{w}x{h}."""
        for pack_id, info in THEME_REGISTRY.items():
            with self.subTest(pack=pack_id):
                self.assertEqual(pack_id, f"themes-{info.width}x{info.height}")

    def test_archive_name(self):
        """Archive name matches Theme{w}{h}.7z."""
        for pack_id, info in THEME_REGISTRY.items():
            with self.subTest(pack=pack_id):
                self.assertEqual(info.archive, f"theme{info.width}{info.height}.7z")

    def test_url_property(self):
        """URL should point to GitHub raw content."""
        info = list(THEME_REGISTRY.values())[0]
        self.assertIn("raw.githubusercontent.com", info.url)
        self.assertTrue(info.url.endswith(info.archive))

    def test_known_resolutions_present(self):
        """Key resolutions from FBL_TO_RESOLUTION must be in registry."""
        self.assertIn('themes-320x320', THEME_REGISTRY)
        self.assertIn('themes-240x240', THEME_REGISTRY)
        self.assertIn('themes-480x480', THEME_REGISTRY)
        self.assertIn('themes-320x240', THEME_REGISTRY)
        self.assertIn('themes-1280x480', THEME_REGISTRY)


# ── Short aliases ────────────────────────────────────────────────────────


class TestShortAliases(unittest.TestCase):
    """Test short alias resolution (themes-320 → themes-320x320)."""

    def test_square_aliases_exist(self):
        """Square resolutions get short aliases."""
        self.assertIn('themes-320', _SHORT_ALIASES)
        self.assertIn('themes-240', _SHORT_ALIASES)
        self.assertIn('themes-480', _SHORT_ALIASES)

    def test_alias_resolves_correctly(self):
        self.assertEqual(_resolve_pack_name('themes-320'), 'themes-320x320')
        self.assertEqual(_resolve_pack_name('themes-480'), 'themes-480x480')

    def test_canonical_name_passes_through(self):
        self.assertEqual(_resolve_pack_name('themes-320x320'), 'themes-320x320')
        self.assertEqual(_resolve_pack_name('themes-240x320'), 'themes-240x320')

    def test_unknown_name_passes_through(self):
        self.assertEqual(_resolve_pack_name('nonexistent'), 'nonexistent')


# ── list_available ───────────────────────────────────────────────────────


class TestListAvailable(unittest.TestCase):

    def test_runs_without_error(self):
        """list_available() should print without error."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            list_available()
        output = buf.getvalue()
        self.assertIn('Available theme packs', output)
        self.assertIn('themes-', output)

    @patch.object(ThemeDownloader, '_is_installed', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    def test_shows_installed_status(self, _count, _inst):
        buf = io.StringIO()
        with redirect_stdout(buf):
            list_available()
        self.assertIn('[installed', buf.getvalue())

    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_shows_not_installed(self, _inst):
        buf = io.StringIO()
        with redirect_stdout(buf):
            list_available()
        self.assertNotIn('[installed', buf.getvalue())


# ── show_info ────────────────────────────────────────────────────────────


class TestShowInfo(unittest.TestCase):

    def test_known_pack(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_info('themes-320x320')
        output = buf.getvalue()
        self.assertIn('320x320', output)
        self.assertIn('Pack ID', output)

    def test_short_alias(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_info('themes-320')
        self.assertIn('320x320', buf.getvalue())

    def test_unknown_pack(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_info('nonexistent')
        self.assertIn('Unknown', buf.getvalue())

    @patch.object(ThemeDownloader, '_is_installed', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=10)
    def test_shows_installed_yes(self, _count, _inst):
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_info('themes-320x320')
        self.assertIn('Installed:   Yes', buf.getvalue())

    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_shows_installed_no(self, _inst):
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_info('themes-320x320')
        self.assertIn('Installed:   No', buf.getvalue())


# ── download_pack ────────────────────────────────────────────────────────


class TestDownloadPack(unittest.TestCase):

    def test_unknown_pack_returns_1(self):
        self.assertEqual(download_pack('nonexistent'), 1)

    @patch.object(ThemeDownloader, '_is_installed', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    def test_already_installed_returns_0(self, _count, _inst):
        self.assertEqual(download_pack('themes-320x320'), 0)

    @patch.object(ThemeDownloader, '_is_installed', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    def test_already_installed_with_alias(self, _count, _inst):
        self.assertEqual(download_pack('themes-320'), 0)

    @patch('trcc.theme_downloader.DataManager.ensure_themes', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_successful_download(self, _inst, _count, mock_ensure):
        result = download_pack('themes-320x320')
        self.assertEqual(result, 0)
        mock_ensure.assert_called_once_with(320, 320)

    @patch('trcc.theme_downloader.DataManager.ensure_themes', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_download_with_alias(self, _inst, _count, mock_ensure):
        result = download_pack('themes-480')
        self.assertEqual(result, 0)
        mock_ensure.assert_called_once_with(480, 480)

    @patch('trcc.theme_downloader.DataManager.ensure_themes', return_value=False)
    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_download_failure_returns_1(self, _inst, mock_ensure):
        result = download_pack('themes-320x320')
        self.assertEqual(result, 1)

    @patch('trcc.theme_downloader.DataManager.ensure_themes', return_value=True)
    @patch('trcc.theme_downloader.shutil.rmtree')
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    @patch.object(ThemeDownloader, '_is_installed', return_value=True)
    def test_force_reinstall(self, _inst, _count, mock_rmtree, mock_ensure):
        """force=True removes existing and re-downloads."""
        result = download_pack('themes-320x320', force=True)
        self.assertEqual(result, 0)
        mock_ensure.assert_called_once_with(320, 320)

    @patch('trcc.theme_downloader.DataManager.ensure_themes', return_value=True)
    @patch.object(ThemeDownloader, '_theme_count', return_value=5)
    @patch.object(ThemeDownloader, '_is_installed', return_value=False)
    def test_non_square_resolution(self, _inst, _count, mock_ensure):
        result = download_pack('themes-240x320')
        self.assertEqual(result, 0)
        mock_ensure.assert_called_once_with(240, 320)


# ── remove_pack ──────────────────────────────────────────────────────────


class TestRemovePack(unittest.TestCase):

    def test_unknown_pack_returns_1(self):
        self.assertEqual(remove_pack('nonexistent'), 1)

    def test_not_installed_returns_1(self):
        with patch('trcc.theme_downloader.USER_DATA_DIR', '/nonexistent'):
            self.assertEqual(remove_pack('themes-320x320'), 1)

    def test_removes_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'theme320320'
            theme_dir.mkdir()
            (theme_dir / 'Theme1').mkdir()

            with patch('trcc.theme_downloader.USER_DATA_DIR', tmp):
                result = remove_pack('themes-320x320')

            self.assertEqual(result, 0)
            self.assertFalse(theme_dir.exists())

    def test_remove_with_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'theme320320'
            theme_dir.mkdir()
            (theme_dir / 'Theme1').mkdir()

            with patch('trcc.theme_downloader.USER_DATA_DIR', tmp):
                result = remove_pack('themes-320')

            self.assertEqual(result, 0)
            self.assertFalse(theme_dir.exists())


# ── _theme_dir / _is_installed / _theme_count ────────────────────────────


class TestHelpers(unittest.TestCase):

    def test_theme_dir_prefers_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_dir = Path(tmp) / 'user' / 'theme320320'
            user_dir.mkdir(parents=True)
            pkg_dir = Path(tmp) / 'pkg' / 'theme320320'
            pkg_dir.mkdir(parents=True)

            with patch('trcc.theme_downloader.USER_DATA_DIR', str(Path(tmp) / 'user')), \
                 patch('trcc.theme_downloader.DATA_DIR', str(Path(tmp) / 'pkg')):
                result = ThemeDownloader._theme_dir(320, 320)
            self.assertEqual(result, user_dir)

    def test_theme_dir_falls_back_to_pkg(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg_dir = Path(tmp) / 'pkg' / 'theme320320'
            pkg_dir.mkdir(parents=True)

            with patch('trcc.theme_downloader.USER_DATA_DIR', str(Path(tmp) / 'user')), \
                 patch('trcc.theme_downloader.DATA_DIR', str(Path(tmp) / 'pkg')):
                result = ThemeDownloader._theme_dir(320, 320)
            self.assertEqual(result, pkg_dir)

    def test_is_installed_false_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'theme320320'
            d.mkdir()
            with patch('trcc.theme_downloader.USER_DATA_DIR', tmp), \
                 patch('trcc.theme_downloader.DATA_DIR', '/nonexistent'):
                self.assertFalse(ThemeDownloader._is_installed(320, 320))

    def test_is_installed_true_with_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'theme320320'
            d.mkdir()
            (d / 'Theme1').mkdir()
            with patch('trcc.theme_downloader.USER_DATA_DIR', tmp), \
                 patch('trcc.theme_downloader.DATA_DIR', '/nonexistent'):
                self.assertTrue(ThemeDownloader._is_installed(320, 320))

    def test_theme_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'theme320320'
            d.mkdir()
            (d / 'Theme1').mkdir()
            (d / 'Theme2').mkdir()
            (d / 'readme.txt').write_text('hi')  # file, not dir
            with patch('trcc.theme_downloader.USER_DATA_DIR', tmp), \
                 patch('trcc.theme_downloader.DATA_DIR', '/nonexistent'):
                self.assertEqual(ThemeDownloader._theme_count(320, 320), 2)

    def test_theme_count_nonexistent(self):
        with patch('trcc.theme_downloader.USER_DATA_DIR', '/nonexistent'), \
             patch('trcc.theme_downloader.DATA_DIR', '/nonexistent'):
            self.assertEqual(ThemeDownloader._theme_count(999, 999), 0)


if __name__ == '__main__':
    unittest.main()
