"""Font resolution infrastructure — name → file path → PIL font.

Pure infrastructure: subprocess (fc-match) + filesystem scanning.
No business logic. Used by OverlayService for text rendering.
"""
from __future__ import annotations

import logging
import os
import subprocess

from PIL import ImageFont

from .data_repository import FONT_SEARCH_DIRS

log = logging.getLogger(__name__)


class FontResolver:
    """Resolve font names to PIL font objects with caching.

    Resolution order:
    1. Cache hit → return immediately
    2. fc-match (fontconfig) → system font by family name
    3. Manual scan of FONT_SEARCH_DIRS → bundled/user/system fonts
    4. PIL default font → ultimate fallback
    """

    def __init__(self) -> None:
        self.cache: dict[tuple, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def get(self, size: int, bold: bool = False,
            font_name: str | None = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Get font by name with fallback chain.

        If font_name is given, resolves it via fc-match. Otherwise uses
        the default fallback chain (bundled → user → system).
        """
        key = (size, bold, font_name)
        if key in self.cache:
            return self.cache[key]

        # Try resolving by name first (user-picked fonts)
        if font_name and font_name != 'Microsoft YaHei':
            path = self.resolve_path(font_name, bold)
            if path:
                self.cache[key] = ImageFont.truetype(path, size)
                return self.cache[key]

        # Build font search list from centralized FONT_SEARCH_DIRS
        bold_suffix = '-Bold' if bold else ''
        bold_style = 'Bold' if bold else 'Regular'
        msyh_name = 'MSYHBD.TTC' if bold else 'MSYH.TTC'
        msyh_lower = msyh_name.lower()

        font_filenames = [
            msyh_name, msyh_lower,
            'NotoSansCJK-VF.ttc', 'NotoSansCJK-Regular.ttc',
            'NotoSans[wght].ttf', f'NotoSans-{bold_style}.ttf',
            f'DejaVuSans{bold_suffix}.ttf',
        ]

        paths: list[str] = []
        for font_dir in FONT_SEARCH_DIRS:
            for fname in font_filenames:
                paths.append(os.path.join(font_dir, fname))

        for p in paths:
            if os.path.exists(p):
                self.cache[key] = ImageFont.truetype(p, size)
                return self.cache[key]

        # Ultimate fallback
        self.cache[key] = ImageFont.load_default()
        return self.cache[key]

    def resolve_path(self, font_name: str, bold: bool = False) -> str | None:
        """Resolve font family name to file path.

        Tries fc-match first, falls back to manual directory scanning.
        """
        try:
            style = 'Bold' if bold else 'Regular'
            result = subprocess.run(
                ['fc-match', f'{font_name}:style={style}', '--format=%{file}'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout and os.path.exists(result.stdout):
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Manual scan using centralized cross-distro font search dirs
        name_lower = font_name.lower().replace(' ', '')
        for font_dir in FONT_SEARCH_DIRS:
            if not os.path.isdir(font_dir):
                continue
            for fname in os.listdir(font_dir):
                if name_lower in fname.lower().replace(' ', ''):
                    return os.path.join(font_dir, fname)

        return None

    def clear_cache(self) -> None:
        """Clear the font cache (e.g. after resolution change)."""
        self.cache.clear()
