"""
PyQt6 UCThemeWeb - Cloud themes browser panel.

Matches Windows TRCC.DCUserControl.UCThemeWeb (732x652)
Shows cloud theme thumbnails with category filtering.
"""

from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon

from .base import BaseThemeBrowser, BaseThumbnail
from .assets import load_pixmap
from .constants import Sizes, Layout, Styles
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class CloudThemeThumbnail(BaseThumbnail):
    """Cloud theme thumbnail. Overrides keys for cloud theme dict."""

    def _get_display_name(self, info: dict) -> str:
        return info.get('id', info.get('name', 'Unknown'))

    def _get_image_path(self, info: dict) -> str | None:
        return info.get('preview')


class UCThemeWeb(BaseThemeBrowser):
    """
    Cloud themes browser panel.

    Windows size: 732x652
    Background image provides header. Category buttons are transparent overlays.
    """

    CMD_THEME_SELECTED = 16
    CMD_CATEGORY_CHANGED = 4

    def __init__(self, parent=None):
        self.current_category = 'all'
        self.videos_directory = None
        super().__init__(parent)

    def _create_filter_buttons(self):
        """Seven category buttons matching Windows positions."""
        btn_normal, btn_active = self._load_filter_assets()
        self.cat_buttons = {}
        self._btn_refs = [btn_normal, btn_active]

        for cat_id, x, y, w, h in Layout.WEB_CATEGORIES:
            btn = self._make_filter_button(x, y, w, h, btn_normal, btn_active,
                lambda checked, c=cat_id: self._set_category(c))
            self.cat_buttons[cat_id] = btn

        self.cat_buttons['all'].setChecked(True)

    def _create_thumbnail(self, item_info: dict) -> CloudThemeThumbnail:
        return CloudThemeThumbnail(item_info)

    def _no_items_message(self) -> str:
        return "No cloud themes found\n\nDownload with: trcc download themes-320"

    def set_videos_directory(self, path):
        """Set the videos directory and load themes."""
        self.videos_directory = Path(path) if path else None
        self.load_themes()

    def _set_category(self, category):
        self.current_category = category
        for cat_id, btn in self.cat_buttons.items():
            btn.setChecked(cat_id == category)
        self.load_themes()
        self.invoke_delegate(self.CMD_CATEGORY_CHANGED, category)

    def load_themes(self):
        """Load cloud themes from videos directory."""
        self._clear_grid()

        if not self.videos_directory or not self.videos_directory.exists():
            self._show_empty_message()
            return

        themes = []
        for video_file in sorted(self.videos_directory.glob('*.mp4')):
            theme_id = video_file.stem
            preview_path = self.videos_directory / f"{theme_id}.png"

            if self.current_category != 'all':
                if not theme_id.startswith(self.current_category):
                    continue

            themes.append({
                'id': theme_id,
                'name': theme_id,
                'video': str(video_file),
                'preview': str(preview_path) if preview_path.exists() else None,
            })

        self._populate_grid(themes)

    def _on_item_clicked(self, item_info: dict):
        """Extend base to also invoke delegate."""
        super()._on_item_clicked(item_info)
        self.invoke_delegate(self.CMD_THEME_SELECTED, item_info)

    def get_selected_theme(self):
        return self.selected_item
