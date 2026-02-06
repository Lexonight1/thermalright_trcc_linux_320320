"""Tests for cloud_downloader – cloud theme catalogue and download logic."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from trcc.cloud_downloader import (
    CATEGORIES,
    CATEGORY_NAMES,
    RESOLUTION_URLS,
    CloudThemeDownloader,
    get_known_themes,
    get_themes_by_category,
)

# ── Catalogue helpers ────────────────────────────────────────────────────────

class TestCatalogue(unittest.TestCase):

    def test_categories_has_all(self):
        prefixes = [c[0] for c in CATEGORIES]
        self.assertEqual(prefixes[0], 'all')

    def test_category_names_populated(self):
        self.assertIn('a', CATEGORY_NAMES)
        self.assertEqual(CATEGORY_NAMES['a'], 'Gallery')

    def test_get_known_themes_non_empty(self):
        themes = get_known_themes()
        self.assertGreater(len(themes), 50)
        self.assertTrue(themes[0].startswith('a'))

    def test_get_known_themes_format(self):
        for tid in get_known_themes():
            self.assertRegex(tid, r'^[a-z]\d{3}$')

    def test_get_themes_by_category_a(self):
        a_themes = get_themes_by_category('a')
        self.assertTrue(all(t.startswith('a') for t in a_themes))

    def test_get_themes_by_category_all(self):
        all_themes = get_themes_by_category('all')
        self.assertEqual(all_themes, get_known_themes())

    def test_get_themes_by_category_unknown(self):
        self.assertEqual(get_themes_by_category('z'), [])


# ── Resolution URLs ──────────────────────────────────────────────────────────

class TestResolutionURLs(unittest.TestCase):

    def test_common_resolutions_present(self):
        for res in ['240x240', '320x320', '480x480', '640x480']:
            self.assertIn(res, RESOLUTION_URLS)

    def test_url_format(self):
        self.assertEqual(RESOLUTION_URLS['320x320'], 'bj320320')


# ── CloudThemeDownloader init ────────────────────────────────────────────────

class TestDownloaderInit(unittest.TestCase):

    def test_default_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, 'home', return_value=Path(tmp)):
                dl = CloudThemeDownloader(resolution='320x320')
                self.assertIn('320320', str(dl.cache_dir))

    def test_custom_cache_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            self.assertEqual(dl.cache_dir, Path(tmp))

    def test_base_url_contains_resolution(self):
        dl = CloudThemeDownloader(resolution='480x480', cache_dir='/tmp/test_trcc')
        self.assertIn('480480', dl.base_url)


# ── URL generation ───────────────────────────────────────────────────────────

class TestDownloaderURLs(unittest.TestCase):

    def setUp(self):
        self.dl = CloudThemeDownloader(resolution='320x320', cache_dir='/tmp/test_trcc')

    def test_get_theme_url(self):
        url = self.dl.get_theme_url('a001')
        self.assertTrue(url.endswith('a001.mp4'))

    def test_get_theme_url_strips_extension(self):
        url = self.dl.get_theme_url('a001.mp4')
        self.assertTrue(url.endswith('a001.mp4'))
        self.assertNotIn('.mp4.mp4', url)

    def test_get_preview_url(self):
        url = self.dl.get_preview_url('b005')
        self.assertTrue(url.endswith('b005.mp4'))


# ── Resolution / server switching ────────────────────────────────────────────

class TestDownloaderSwitching(unittest.TestCase):

    def test_set_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, 'home', return_value=Path(tmp)):
                dl = CloudThemeDownloader(resolution='320x320')
                dl.set_resolution('480x480')
                self.assertIn('480480', dl.base_url)
                self.assertIn('480480', str(dl.cache_dir))

    def test_set_server(self):
        dl = CloudThemeDownloader(resolution='320x320', cache_dir='/tmp/test_trcc')
        dl.set_server('china')
        self.assertIn('czhorde.com', dl.base_url)


# ── Cache operations ─────────────────────────────────────────────────────────

class TestDownloaderCache(unittest.TestCase):

    def test_is_cached_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            self.assertFalse(dl.is_cached('a001'))

    def test_is_cached_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            (Path(tmp) / 'a001.mp4').write_bytes(b'\x00')
            self.assertTrue(dl.is_cached('a001'))

    def test_get_cached_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            (Path(tmp) / 'b002.mp4').write_bytes(b'\x00')
            self.assertEqual(dl.get_cached_path('b002'), Path(tmp) / 'b002.mp4')

    def test_get_cached_themes(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            (Path(tmp) / 'a001.mp4').write_bytes(b'\x00')
            (Path(tmp) / 'c010.mp4').write_bytes(b'\x00')
            cached = dl.get_cached_themes()
            self.assertEqual(cached, ['a001', 'c010'])

    def test_get_all_theme_ids(self):
        dl = CloudThemeDownloader(cache_dir='/tmp/test_trcc')
        self.assertEqual(dl.get_all_theme_ids(), get_known_themes())


# ── Download with mock network ───────────────────────────────────────────────

class TestDownloaderDownload(unittest.TestCase):

    def _mock_urlopen(self, data=b'\x00\x00\x01\x00'):
        """Build a mock urlopen context manager."""
        response = MagicMock()
        response.headers = {'content-length': str(len(data))}
        response.read.side_effect = [data, b'']
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        return response

    @patch('trcc.cloud_downloader.urlopen')
    def test_download_theme_success(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen()

        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            result = dl.download_theme('a001')
            assert result is not None
            self.assertTrue(Path(result).exists())

    @patch('trcc.cloud_downloader.urlopen')
    def test_download_theme_returns_cached(self, mock_urlopen):
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            # Pre-create cached file
            cached = Path(tmp) / 'a001.mp4'
            cached.write_bytes(b'\xFF')

            result = dl.download_theme('a001')
            self.assertEqual(result, str(cached))
            mock_urlopen.assert_not_called()

    @patch('trcc.cloud_downloader.urlopen')
    def test_download_preview_png(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen(b'\x89PNG')

        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            result = dl.download_preview_png('a001')
            self.assertIsNotNone(result)

    def test_download_theme_force_redownloads(self):
        """force=True should re-download even when cached."""
        with tempfile.TemporaryDirectory() as tmp:
            dl = CloudThemeDownloader(cache_dir=tmp)
            cached = Path(tmp) / 'a001.mp4'
            cached.write_bytes(b'\xFF')

            with patch('trcc.cloud_downloader.urlopen') as mock_urlopen:
                mock_urlopen.return_value = self._mock_urlopen()
                dl.download_theme('a001', force=True)
                mock_urlopen.assert_called_once()


# ── Cancel ───────────────────────────────────────────────────────────────────

class TestDownloaderCancel(unittest.TestCase):

    def test_cancel_sets_flag(self):
        dl = CloudThemeDownloader(cache_dir='/tmp/test_trcc')
        dl.cancel()
        self.assertTrue(dl._cancelled)


if __name__ == '__main__':
    unittest.main()
