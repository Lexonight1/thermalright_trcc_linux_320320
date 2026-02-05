"""
PyQt6 UCThemeLocal - Local themes browser panel.

Matches Windows TRCC.DCUserControl.UCThemeLocal (732x652)
Shows theme thumbnails in a 5-column scrollable grid.
"""

from PyQt6.QtWidgets import QPushButton, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon

from .base import BaseThemeBrowser, BaseThumbnail, create_image_button
from .assets import load_pixmap
from .constants import Sizes, Layout, Styles
from pathlib import Path


class ThemeThumbnail(BaseThumbnail):
    """Local theme thumbnail. Uses default BaseThumbnail behavior."""
    pass


class UCThemeLocal(BaseThemeBrowser):
    """
    Local themes browser panel.

    Windows size: 732x652
    Background image provides header. Filter buttons are transparent overlays.
    """

    MODE_ALL = 0
    MODE_DEFAULT = 1
    MODE_USER = 2

    CMD_THEME_SELECTED = 16
    CMD_FILTER_CHANGED = 3
    CMD_SLIDESHOW = 48

    slideshow_changed = pyqtSignal(bool, int, list)  # enabled, interval, theme_indices

    def __init__(self, parent=None):
        self.filter_mode = self.MODE_ALL
        self.theme_directory = None
        self._slideshow = False
        self._slideshow_interval = 3
        super().__init__(parent)

    def _create_filter_buttons(self):
        """Three filter buttons: All, Default, User."""
        btn_normal, btn_active = self._load_filter_assets()
        self._filter_buttons = []
        self._btn_refs = [btn_normal, btn_active]

        configs = [
            (Layout.LOCAL_BTN_ALL, self.MODE_ALL),
            (Layout.LOCAL_BTN_DEFAULT, self.MODE_DEFAULT),
            (Layout.LOCAL_BTN_USER, self.MODE_USER),
        ]
        for (x, y, w, h), mode in configs:
            btn = self._make_filter_button(x, y, w, h, btn_normal, btn_active,
                lambda checked, m=mode: self._set_filter(m))
            self._filter_buttons.append(btn)

        self._filter_buttons[0].setChecked(True)

        # Slideshow toggle — Windows: buttonLunbo (531, 28) 40x17
        self._lunbo_off = load_pixmap('P主题轮播.png', 40, 17)
        self._lunbo_on = load_pixmap('P主题轮播a.png', 40, 17)
        self.slideshow_btn = QPushButton(self)
        self.slideshow_btn.setGeometry(531, 28, 40, 17)
        self.slideshow_btn.setFlat(True)
        self.slideshow_btn.setStyleSheet(Styles.FLAT_BUTTON)
        self.slideshow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if not self._lunbo_off.isNull():
            self.slideshow_btn.setIcon(QIcon(self._lunbo_off))
            self.slideshow_btn.setIconSize(self.slideshow_btn.size())
        self.slideshow_btn.clicked.connect(self._on_slideshow_clicked)

        # Slideshow interval input — Windows: textBoxTimer (602, 29) 24x16
        self.timer_input = QLineEdit(self)
        self.timer_input.setGeometry(602, 29, 24, 16)
        self.timer_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.timer_input.setMaxLength(3)
        self.timer_input.setText("3")
        self.timer_input.setStyleSheet(
            "QLineEdit { background: #232227; color: white; border: none; "
            "font-family: 'Microsoft YaHei'; font-size: 9pt; }"
        )
        self.timer_input.editingFinished.connect(self._on_timer_changed)

        # Export button — Windows: buttonThemeOut (651, 27) 60x18 (empty handler)
        export_px = load_pixmap('P导出所有主题.png', 60, 18)
        self.export_btn = QPushButton(self)
        self.export_btn.setGeometry(651, 27, 60, 18)
        self.export_btn.setFlat(True)
        self.export_btn.setStyleSheet(Styles.FLAT_BUTTON)
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if not export_px.isNull():
            self.export_btn.setIcon(QIcon(export_px))
            self.export_btn.setIconSize(self.export_btn.size())
            self.export_btn._img_ref = export_px

    def _create_thumbnail(self, item_info: dict) -> ThemeThumbnail:
        return ThemeThumbnail(item_info)

    def _no_items_message(self) -> str:
        return "No themes found"

    def set_theme_directory(self, path):
        self.theme_directory = Path(path) if path else None
        self.load_themes()

    def _set_filter(self, mode):
        self.filter_mode = mode
        for i, btn in enumerate(self._filter_buttons):
            btn.setChecked(i == mode)
        self.load_themes()
        self.invoke_delegate(self.CMD_FILTER_CHANGED, mode)

    def load_themes(self):
        self._clear_grid()

        if not self.theme_directory or not self.theme_directory.exists():
            self._show_empty_message()
            return

        theme_dirs = []
        for item in sorted(self.theme_directory.iterdir()):
            if item.is_dir():
                thumb = item / 'Theme.png'
                bg = item / '00.png'
                if thumb.exists() or bg.exists():
                    theme_dirs.append({
                        'name': item.name,
                        'path': str(item),
                        'thumbnail': str(thumb if thumb.exists() else bg),
                        'is_user': item.name.startswith('User') or item.name.startswith('Custom'),
                    })

        if self.filter_mode == self.MODE_DEFAULT:
            theme_dirs = [t for t in theme_dirs if not t.get('is_user')]
        elif self.filter_mode == self.MODE_USER:
            theme_dirs = [t for t in theme_dirs if t.get('is_user')]

        self._populate_grid(theme_dirs)

    def _on_item_clicked(self, item_info: dict):
        """Extend base to also invoke delegate."""
        super()._on_item_clicked(item_info)
        self.invoke_delegate(self.CMD_THEME_SELECTED, item_info)

    def _on_slideshow_clicked(self):
        """Toggle slideshow mode (Windows: buttonLunbo_Click)."""
        self._slideshow = not self._slideshow
        px = self._lunbo_on if self._slideshow else self._lunbo_off
        if not px.isNull():
            self.slideshow_btn.setIcon(QIcon(px))
            self.slideshow_btn.setIconSize(self.slideshow_btn.size())
        self.invoke_delegate(self.CMD_SLIDESHOW)

    def _on_timer_changed(self):
        """Validate and apply slideshow interval (Windows: min 3 seconds)."""
        text = self.timer_input.text().strip()
        try:
            val = int(text)
        except ValueError:
            val = 3
        val = max(3, val)
        self.timer_input.setText(str(val))
        self._slideshow_interval = val
        self.invoke_delegate(self.CMD_SLIDESHOW)

    def is_slideshow(self):
        return self._slideshow

    def get_slideshow_interval(self):
        return self._slideshow_interval

    def get_selected_theme(self):
        return self.selected_item
