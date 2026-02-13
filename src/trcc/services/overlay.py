"""Overlay rendering service — config, mask, metrics → composited image.

Pure Python (PIL), no Qt dependencies.
Orchestrates background, mask compositing, text overlays, and dynamic scaling.
Font resolution delegated to FontResolver infrastructure.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..font_resolver import FontResolver
from .system import SystemService

log = logging.getLogger(__name__)


class OverlayService:
    """Overlay rendering: config, mask, metrics → composited image.

    Supports:
    - Background images from themes
    - Theme masks (partial overlays)
    - Text overlays with customizable position, color, font
    - Time/date with multiple format options
    - Hardware metrics (CPU, GPU, etc.)
    - Dynamic font/coordinate scaling across resolutions
    """

    # Base resolution for scaling (most common device)
    BASE_RESOLUTION = 320

    def __init__(self, width: int = 320, height: int = 320) -> None:
        # Rendering state (public — tests + callers access these directly)
        self.width = width
        self.height = height
        self.config: dict = {}
        self.background: Any = None
        self.theme_mask: Any = None
        self.theme_mask_position: tuple[int, int] = (0, 0)
        self.theme_mask_visible: bool = True  # Windows: isDrawMbImage
        self._fonts = FontResolver()
        self.flash_skip_index: int = -1  # Windows shanPingCount

        # Format settings (matching Windows TRCC UCXiTongXianShiSub.cs)
        # Time: 0=HH:mm, 1=hh:mm AM/PM, 2=HH:mm (same as 0)
        # Date: 0=yyyy/MM/dd, 1=yyyy/MM/dd, 2=dd/MM/yyyy, 3=MM/dd, 4=dd/MM
        # Temp: 0=Celsius (°C), 1=Fahrenheit (°F)
        self.time_format: int = 0
        self.date_format: int = 0
        self.temp_unit: int = 0

        # Dynamic font/coordinate scaling
        self._config_resolution: tuple[int, int] = (width, height)
        self._scale_enabled: bool = True

        # Service-only state
        self._enabled: bool = False
        self._metrics: dict[str, Any] = {}
        self._dc_data: dict[str, Any] | None = None

    # ── Resolution ───────────────────────────────────────────────────

    def set_resolution(self, w: int, h: int) -> None:
        """Update LCD resolution. Clears font cache and background."""
        self.width = w
        self.height = h
        self._fonts.clear_cache()
        self.background = None

    # ── Enable / disable ─────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        log.debug("Overlay %s", "enabled" if value else "disabled")
        self._enabled = value

    # ── Background ───────────────────────────────────────────────────

    def set_background(self, image: Any) -> None:
        """Set background image.

        Optimized for video playback — skips copy/resize if image is
        already the correct size (VideoPlayer pre-resizes frames).
        """
        if image is None:
            self.background = None
            return
        if not self.width or not self.height:
            self.background = image
            return
        # Skip resize if already correct size (video frames are pre-sized)
        if image.size == (self.width, self.height):
            self.background = image
        else:
            self.background = image.copy().resize(
                (self.width, self.height), Image.Resampling.LANCZOS
            )

    # ── Config ───────────────────────────────────────────────────────

    def set_config(self, config: dict) -> None:
        """Set overlay config dict directly."""
        self.config = config

    def configure(self, config: dict) -> None:
        """Alias for set_config (used by controllers/display)."""
        self.config = config

    def set_config_resolution(self, w: int, h: int) -> None:
        """Set the resolution the current config was designed for.

        Used for dynamic font/coordinate scaling when displaying a config
        designed for one resolution on a device with a different resolution.
        """
        self._config_resolution = (w, h)

    def set_scale_enabled(self, enabled: bool) -> None:
        """Enable or disable dynamic font/coordinate scaling."""
        self._scale_enabled = enabled
        self._fonts.clear_cache()

    def _get_scale_factor(self) -> float:
        """Calculate scale factor from config resolution to display resolution.

        Uses the smaller dimension (usually the same for square LCDs) to
        calculate a uniform scale factor.

        Returns:
            Float scale factor (1.0 = no scaling)
        """
        if not self._scale_enabled:
            return 1.0

        cfg_w, cfg_h = self._config_resolution
        cfg_size = min(cfg_w, cfg_h)
        disp_size = min(self.width, self.height)

        if cfg_size <= 0:
            return 1.0

        return disp_size / cfg_size

    def load_from_dc(self, dc_path: Path) -> dict:
        """Load overlay config, preferring config.json over config1.dc.

        Tries config.json first (human-editable), falls back to config1.dc.

        Returns:
            display_options dict (may contain 'animation_file', etc.).
        """
        from ..data_repository import ThemeDir

        json_path = ThemeDir(dc_path.parent).json if dc_path else None
        if json_path and json_path.exists():
            try:
                from ..dc_parser import load_config_json

                result = load_config_json(str(json_path))
                if result is not None:
                    overlay_config, display_options = result
                    self.configure(overlay_config)
                    self.set_config_resolution(self.width, self.height)
                    self.set_dc_data({'display_options': display_options})
                    return display_options
            except Exception as e:
                log.warning("Failed to load config.json, falling back to DC: %s", e)

        if not dc_path or not dc_path.exists():
            return {}
        try:
            from ..dc_config import DcConfig

            dc = DcConfig(dc_path)
            overlay_config = dc.to_overlay_config()
            self.configure(overlay_config)
            self.set_config_resolution(self.width, self.height)
            self.set_dc_data(dc.to_dict())
            return dc.display_options
        except Exception as e:
            log.error("Failed to parse DC file: %s", e)
            return {}

    # ── Mask ─────────────────────────────────────────────────────────

    def set_mask(self, image: Any, position: tuple[int, int] | None = None) -> None:
        """Set theme mask overlay image."""
        self.set_theme_mask(image, position)

    def set_theme_mask(self, image: Any, position: tuple[int, int] | None = None) -> None:
        """Set theme mask overlay.

        Masks are kept at original size (not stretched) and positioned
        at the bottom by default for partial overlays.
        """
        if image is None:
            self.theme_mask = None
            self.theme_mask_position = (0, 0)
            return

        if image.mode != 'RGBA':
            image = image.convert('RGBA')

        self.theme_mask = image

        if position is not None:
            self.theme_mask_position = position
        elif image.height < self.height:
            self.theme_mask_position = (0, self.height - image.height)
        else:
            self.theme_mask_position = (0, 0)

    def get_mask(self) -> tuple[Any, tuple[int, int] | None]:
        """Get current theme mask image and position."""
        return self.theme_mask, self.theme_mask_position

    def set_mask_visible(self, visible: bool) -> None:
        """Toggle mask visibility without destroying it (Windows SetDrawMengBan)."""
        self.theme_mask_visible = visible

    # ── Temp unit ────────────────────────────────────────────────────

    def set_temp_unit(self, unit: int) -> None:
        """Set temperature display unit (0=Celsius, 1=Fahrenheit)."""
        self.temp_unit = unit

    # ── Metrics ──────────────────────────────────────────────────────

    def update_metrics(self, metrics: dict) -> None:
        """Update system metrics for hardware overlay elements."""
        self._metrics = metrics

    # ── Font resolution (delegated to FontResolver) ─────────────────

    @property
    def font_cache(self) -> dict:
        """Font cache (delegates to FontResolver)."""
        return self._fonts.cache

    @font_cache.setter
    def font_cache(self, value: dict) -> None:
        self._fonts.cache = value

    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        """Get font by name with fallback chain."""
        return self._fonts.get(size, bold, font_name)

    def _resolve_font_path(self, font_name: str, bold: bool = False) -> str | None:
        """Resolve font family name to file path."""
        return self._fonts.resolve_path(font_name, bold)

    # ── Render ───────────────────────────────────────────────────────

    def render(self, background: Any = None, metrics: dict | None = None,
               **_kw: Any) -> Any:
        """Render overlay onto background.

        Callers gate on `.enabled` before calling — this method always renders.

        Args:
            background: Optional PIL Image (uses stored background if None).
            metrics: System metrics dict (uses stored metrics if None).

        Returns:
            PIL Image with overlay rendered.
        """
        if background:
            self.set_background(background)
        m = metrics if metrics is not None else self._metrics
        return self._render_overlay(m)

    def _render_overlay(self, metrics: dict | None = None) -> Any:
        """Core PIL compositing — background + mask + text overlays.

        Optimized for video playback — returns background directly when
        there's nothing to overlay (no mask, no config).
        """
        metrics = metrics or {}

        # Fast path: no overlays, just return background as-is
        has_overlays = (
            (self.theme_mask and self.theme_mask_visible)
            or (self.config and isinstance(self.config, dict))
        )
        if not has_overlays and self.background:
            return self.background

        # Create base image
        if self.background is None:
            img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        else:
            img = self.background.copy()
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

        # Apply theme mask (Windows: isDrawMbImage check)
        if self.theme_mask and self.theme_mask_visible:
            scale = self._get_scale_factor()
            if abs(scale - 1.0) > 0.01:
                mask_w = int(self.theme_mask.width * scale)
                mask_h = int(self.theme_mask.height * scale)
                scaled_mask = self.theme_mask.resize(
                    (mask_w, mask_h), Image.Resampling.LANCZOS)
                pos_x = int(self.theme_mask_position[0] * scale)
                pos_y = int(self.theme_mask_position[1] * scale)
                img.paste(scaled_mask, (pos_x, pos_y), scaled_mask)
            else:
                img.paste(self.theme_mask, self.theme_mask_position, self.theme_mask)

        # Convert to RGB before drawing text (matches Windows GenerateImage).
        # Drawing on RGBA causes PIL to replace alpha at anti-aliased edges;
        # compositing RGBA onto black creates dark fringes.
        if img.mode == 'RGBA':
            img = img.convert('RGB')

        # Draw text overlays
        draw = ImageDraw.Draw(img)

        if not self.config or not isinstance(self.config, dict):
            return img

        scale = self._get_scale_factor()

        for elem_idx, (key, cfg) in enumerate(self.config.items()):
            if not isinstance(cfg, dict) or not cfg.get('enabled', True):
                continue
            if elem_idx == self.flash_skip_index:
                continue

            base_x = cfg.get('x', 10)
            base_y = cfg.get('y', 10)
            font_cfg = cfg.get('font', {})
            base_font_size = font_cfg.get('size', 24) if isinstance(font_cfg, dict) else 24
            color = cfg.get('color', '#FFFFFF')

            x = int(base_x * scale)
            y = int(base_y * scale)
            font_size = max(8, int(base_font_size * scale))

            # Get text to render
            if 'text' in cfg:
                text = str(cfg['text'])
            elif 'metric' in cfg:
                metric_name = cfg['metric']
                if metric_name in metrics:
                    time_fmt = cfg.get('time_format', self.time_format)
                    date_fmt = cfg.get('date_format', self.date_format)
                    text = SystemService.format_metric(
                        metric_name, metrics[metric_name],
                        time_fmt, date_fmt, self.temp_unit)
                else:
                    text = "N/A"
            else:
                continue

            bold = font_cfg.get('style') == 'bold' if isinstance(font_cfg, dict) else False
            font_name = font_cfg.get('name') if isinstance(font_cfg, dict) else None
            font = self.get_font(font_size, bold=bold, font_name=font_name)
            draw.text((x, y), text, fill=color, font=font, anchor='mm')

        return img

    # ── DC data (lossless round-trip) ────────────────────────────────

    def set_dc_data(self, data: dict[str, Any] | None) -> None:
        """Store parsed DC data for lossless save round-trip."""
        self._dc_data = data

    def get_dc_data(self) -> dict[str, Any] | None:
        return self._dc_data

    def clear_dc_data(self) -> None:
        self._dc_data = None

    # ── Clear ────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear rendering state (preserves resolution and format options)."""
        self.config = {}
        self.background = None
        self.theme_mask = None
        self.theme_mask_position = (0, 0)
        self.theme_mask_visible = True
