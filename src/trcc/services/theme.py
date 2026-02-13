"""Theme discovery, loading, saving, export/import service.

Pure Python (PIL + filesystem), no Qt dependencies.
Absorbed from ThemeController + ThemeModel + LCDDeviceController theme ops.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..core.models import ThemeData, ThemeInfo, ThemeType
from ..data_repository import ThemeDir

log = logging.getLogger(__name__)


class ThemeService:
    """Theme lifecycle: discover, load, save, export, import.

    Holds theme list, selection, filter state, and directory paths.
    """

    # Category mappings (Windows prefix → display name)
    CATEGORIES = {
        'all': 'All',
        'a': 'Gallery',
        'b': 'Tech',
        'c': 'HUD',
        'd': 'Light',
        'e': 'Nature',
        'y': 'Aesthetic',
    }

    def __init__(self) -> None:
        self._themes: list[ThemeInfo] = []
        self._selected: ThemeInfo | None = None
        self._filter_mode: str = 'all'
        self._category: str | None = None
        self._local_dir: Path | None = None
        self._web_dir: Path | None = None
        self._masks_dir: Path | None = None

    # ── State ─────────────────────────────────────────────────────────

    @property
    def themes(self) -> list[ThemeInfo]:
        return self._themes

    @property
    def selected(self) -> ThemeInfo | None:
        return self._selected

    def select(self, theme: ThemeInfo) -> None:
        self._selected = theme

    def set_filter(self, mode: str) -> None:
        self._filter_mode = mode

    def set_category(self, category: str) -> None:
        self._category = category if category != 'all' else None

    def set_directories(self,
                        local_dir: Path | None = None,
                        web_dir: Path | None = None,
                        masks_dir: Path | None = None) -> None:
        if local_dir is not None:
            self._local_dir = local_dir
        if web_dir is not None:
            self._web_dir = web_dir
        if masks_dir is not None:
            self._masks_dir = masks_dir

    @property
    def local_dir(self) -> Path | None:
        return self._local_dir

    @property
    def web_dir(self) -> Path | None:
        return self._web_dir

    @property
    def masks_dir(self) -> Path | None:
        return self._masks_dir

    # ── Directory setup ──────────────────────────────────────────────

    @staticmethod
    def setup_dirs(width: int, height: int) -> None:
        """Extract all .7z archives for a resolution if needed."""
        from ..data_repository import DataManager

        DataManager.ensure_all(width, height)

    # ── Discovery ────────────────────────────────────────────────────

    def load_local_themes(self, resolution: tuple[int, int] = (320, 320)) -> list[ThemeInfo]:
        """Discover local themes and store them. Returns the list."""
        if self._local_dir:
            self._themes = ThemeService.discover_local(
                self._local_dir, resolution, self._filter_mode)
        else:
            self._themes = []
        return self._themes

    def load_cloud_themes(self) -> list[ThemeInfo]:
        """Discover cloud themes and store them. Returns the list."""
        if self._web_dir:
            self._themes = ThemeService.discover_cloud(
                self._web_dir, self._category)
        else:
            self._themes = []
        return self._themes

    @staticmethod
    def discover_local(
        theme_dir: Path,
        resolution: tuple[int, int] = (320, 320),
        filter_mode: str = 'all',
    ) -> list[ThemeInfo]:
        """Load themes from a local directory.

        Args:
            theme_dir: Path to Theme{W}{H}/ directory.
            resolution: LCD resolution tuple.
            filter_mode: 'all', 'default', or 'user'.

        Returns:
            List of ThemeInfo objects.
        """
        themes: list[ThemeInfo] = []
        if not theme_dir or not theme_dir.exists():
            return themes

        for item in sorted(theme_dir.iterdir()):
            if item.is_dir() and ThemeDir(item).is_valid():
                theme = ThemeInfo.from_directory(item, resolution)
                if ThemeService._passes_filter(theme, filter_mode):
                    themes.append(theme)

        return themes

    @staticmethod
    def discover_cloud(
        web_dir: Path,
        category: str | None = None,
    ) -> list[ThemeInfo]:
        """Load cloud video themes from web directory.

        Args:
            web_dir: Path to Web/{W}{H}/ directory.
            category: Category filter ('a', 'b', etc.) or None for all.
        """
        themes: list[ThemeInfo] = []
        if not web_dir or not web_dir.exists():
            return themes

        for video_file in sorted(web_dir.glob('*.mp4')):
            preview_path = web_dir / f"{video_file.stem}.png"
            theme = ThemeInfo.from_video(
                video_file,
                preview_path if preview_path.exists() else None,
            )
            if category and category != 'all':
                if theme.category != category:
                    continue
            themes.append(theme)

        return themes

    # ── Load ─────────────────────────────────────────────────────────

    @staticmethod
    def load(
        theme: ThemeInfo,
        working_dir: Path,
        lcd_size: tuple[int, int],
    ) -> ThemeData:
        """Load a theme and return all data needed to display it.

        Handles both reference-based (config.json) and copy-based themes.

        Args:
            theme: ThemeInfo to load.
            working_dir: Temporary working directory.
            lcd_size: (width, height) of the LCD.

        Returns:
            ThemeData bundle with background, mask, overlay config, etc.
        """
        assert theme.path is not None
        td = ThemeDir(theme.path)
        w, h = lcd_size
        data = ThemeData()

        # Reference-based theme (config.json exists)
        if td.json.exists():
            opts = ThemeService._load_dc_display_options(td.dc, w, h)

            mask_ref = opts.get('mask_path')
            if mask_ref:
                ThemeService._load_mask_into(data, ThemeDir(mask_ref), w, h)

            bg_ref = opts.get('background_path')
            if bg_ref:
                bg_path = Path(bg_ref)
                if bg_path.exists():
                    if bg_path.suffix in ('.mp4', '.avi', '.mkv', '.webm', '.zt'):
                        data.animation_path = bg_path
                        data.is_animated = True
                    else:
                        data.background = ThemeService._open_image(
                            bg_path, w, h)

            return data

        # Copy-based theme (original behavior)
        ThemeService._copy_dir(theme.path, working_dir)
        wd = ThemeDir(working_dir)

        opts = ThemeService._load_dc_display_options(wd.dc, w, h)

        # Determine background / animation
        anim_file = opts.get('animation_file')
        if anim_file:
            anim_path = working_dir / anim_file
            if anim_path.exists():
                data.animation_path = anim_path
                data.is_animated = True
            elif theme.is_animated and theme.animation_path:
                data.animation_path = theme.animation_path
                data.is_animated = True
        elif theme.is_animated and theme.animation_path:
            wd_copy = working_dir / Path(theme.animation_path).name
            data.animation_path = wd_copy if wd_copy.exists() else theme.animation_path
            data.is_animated = True
        elif wd.zt.exists():
            data.animation_path = wd.zt
            data.is_animated = True
        elif wd.bg.exists():
            mp4_files = list(working_dir.glob('*.mp4'))
            if mp4_files:
                data.animation_path = mp4_files[0]
                data.is_animated = True
            else:
                data.background = ThemeService._open_image(wd.bg, w, h)
        elif theme.is_mask_only:
            data.background = ThemeService._black_image(w, h)

        # Mask from working dir
        if wd.mask.exists():
            data.mask_source_dir = theme.path
            ThemeService._load_mask_into(
                data, wd, w, h, dc_path=wd.dc if wd.dc.exists() else None)

        return data

    # ── Save ─────────────────────────────────────────────────────────

    @staticmethod
    def save(
        name: str,
        data_dir: Path,
        lcd_size: tuple[int, int],
        *,
        background: Any,
        overlay_config: dict,
        mask: Any | None = None,
        mask_source: Path | None = None,
        mask_position: tuple[int, int] | None = None,
        video_path: Path | None = None,
        current_theme_path: Path | None = None,
    ) -> tuple[bool, str]:
        """Save current config as a custom theme with path references.

        Returns (success, message).
        """
        if not background:
            return False, "No image to save"

        w, h = lcd_size
        safe_name = f'Custom_{name}' if not name.startswith('Custom_') else name
        theme_path = data_dir / f'theme{w}{h}' / safe_name

        try:
            theme_path.mkdir(parents=True, exist_ok=True)
            td = ThemeDir(theme_path)

            # Thumbnail from rendered preview
            thumb = background.copy()
            thumb.thumbnail((120, 120))
            thumb.save(str(td.preview))

            # Save current frame as 00.png
            background.save(str(td.bg))

            # Determine background source path
            background_path = None
            if video_path:
                background_path = str(video_path)
            elif current_theme_path:
                orig_bg = ThemeDir(current_theme_path).bg
                if orig_bg.exists():
                    background_path = str(orig_bg)

            # Determine mask source path
            mask_path_str = None
            if mask and mask_source:
                mask_file = ThemeDir(mask_source).mask
                if mask_file.exists():
                    mask_path_str = str(mask_source)

            config_json = {
                'background': background_path,
                'mask': mask_path_str,
                'dc': overlay_config or {},
            }
            if mask_path_str and mask_position:
                config_json['mask_position'] = list(mask_position)

            with open(str(td.json), 'w') as f:
                json.dump(config_json, f, indent=2)

            return True, f"Saved: {safe_name}"
        except Exception as e:
            return False, f"Save failed: {e}"

    # ── Export / Import ──────────────────────────────────────────────

    @staticmethod
    def export_tr(theme_path: Path, export_path: Path) -> tuple[bool, str]:
        """Export theme as .tr file."""
        try:
            from ..dc_writer import export_theme

            export_theme(str(theme_path), str(export_path))
            return True, f"Exported: {export_path.name}"
        except Exception as e:
            return False, f"Export failed: {e}"

    @staticmethod
    def import_tr(
        import_path: Path,
        data_dir: Path,
        lcd_size: tuple[int, int],
    ) -> tuple[bool, str | ThemeInfo]:
        """Import theme from .tr file.

        Returns (success, message_or_theme_info).
        On success, second element is a ThemeInfo that can be loaded.
        """
        try:
            from ..dc_writer import import_theme

            w, h = lcd_size
            name = import_path.stem
            theme_path = data_dir / f'theme{w}{h}' / name
            import_theme(str(import_path), str(theme_path))
            theme = ThemeInfo.from_directory(theme_path)
            return True, theme
        except Exception as e:
            return False, f"Import failed: {e}"

    # ── Private helpers ──────────────────────────────────────────────

    @staticmethod
    def _passes_filter(theme: ThemeInfo, filter_mode: str) -> bool:
        if filter_mode == 'all':
            return True
        elif filter_mode == 'default':
            return (theme.theme_type == ThemeType.LOCAL
                    and not theme.name.startswith(('User', 'Custom')))
        elif filter_mode == 'user':
            return (theme.theme_type == ThemeType.USER
                    or theme.name.startswith(('User', 'Custom')))
        return True

    @staticmethod
    def _copy_dir(src: Path, dest: Path) -> None:
        """Copy theme files to working dir (Windows CopyDireToDire)."""
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(str(f), str(dest / f.name))

    @staticmethod
    def _open_image(path: Path, w: int, h: int) -> Any:
        """Open and resize an image to LCD dimensions."""
        from PIL import Image

        img = Image.open(path)
        img = img.resize((w, h), Image.Resampling.LANCZOS)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img

    @staticmethod
    def _black_image(w: int, h: int) -> Any:
        """Create a black background image."""
        from PIL import Image

        return Image.new('RGB', (w, h), (0, 0, 0))

    @staticmethod
    def _load_dc_display_options(dc_path: Path, w: int, h: int) -> dict:
        """Load DC config and return display_options dict."""
        json_path = ThemeDir(dc_path.parent).json if dc_path else None
        if json_path and json_path.exists():
            try:
                from ..dc_parser import load_config_json

                result = load_config_json(str(json_path))
                if result is not None:
                    _, display_options = result
                    return display_options
            except Exception as e:
                log.warning("Failed to load config.json: %s", e)

        if not dc_path or not dc_path.exists():
            return {}
        try:
            from ..dc_config import DcConfig

            dc = DcConfig(dc_path)
            return dc.display_options
        except Exception as e:
            log.error("Failed to parse DC file: %s", e)
            return {}

    @staticmethod
    def _parse_mask_position(
        dc_path: Path | None,
        mask_img: Any,
        lcd_w: int,
        lcd_h: int,
    ) -> tuple[int, int] | None:
        """Parse mask position from DC file.

        DC files store mask_position as center coordinates.
        Full-size masks go at (0, 0).
        """
        if mask_img.width >= lcd_w and mask_img.height >= lcd_h:
            return (0, 0)

        if not dc_path or not Path(dc_path).exists():
            return None

        try:
            from ..dc_config import DcConfig

            dc = DcConfig(dc_path)
            if dc.mask_enabled:
                center_pos = dc.mask_settings.get('mask_position')
                if center_pos:
                    return (
                        center_pos[0] - mask_img.width // 2,
                        center_pos[1] - mask_img.height // 2,
                    )
        except Exception:
            pass
        return None

    @staticmethod
    def _load_mask_into(
        data: ThemeData,
        td: ThemeDir,
        w: int,
        h: int,
        dc_path: Path | None = None,
    ) -> None:
        """Load mask image and position into ThemeData."""
        mask_file = td.mask
        if not mask_file.exists():
            return
        try:
            from PIL import Image

            mask_img = Image.open(mask_file)
            position = ThemeService._parse_mask_position(
                dc_path or (td.dc if td.dc.exists() else None),
                mask_img, w, h)
            data.mask = mask_img
            data.mask_position = position
            data.mask_source_dir = td.path
        except Exception as e:
            log.error("Failed to load mask: %s", e)
