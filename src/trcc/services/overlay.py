"""Overlay configuration, rendering, and mask management service.

Pure Python (PIL), no Qt dependencies.
Absorbed from OverlayController + OverlayModel in controllers.py/models.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


class OverlayService:
    """Overlay rendering: config, mask, metrics → composited image."""

    def __init__(self, width: int = 320, height: int = 320) -> None:
        self._width = width
        self._height = height
        self._enabled = False
        self._background: Any = None
        self._renderer: Any = None
        self._metrics: dict[str, Any] = {}
        self._dc_data: dict[str, Any] | None = None

    # ── Resolution ───────────────────────────────────────────────────

    def set_resolution(self, w: int, h: int) -> None:
        """Set target render size."""
        self._width = w
        self._height = h
        # Force renderer recreation at new size
        self._renderer = None

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
        """Set background image for rendering."""
        self._background = image
        if self._renderer:
            self._renderer.set_background(image)

    @property
    def background(self) -> Any:
        return self._background

    # ── Config ───────────────────────────────────────────────────────

    def configure(self, config: dict) -> None:
        """Set overlay config dict directly (from DC parsing)."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_config(config)

    def set_config_resolution(self, w: int, h: int) -> None:
        """Set the resolution the config was designed for (dynamic scaling)."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_config_resolution(w, h)

    def set_scale_enabled(self, enabled: bool) -> None:
        """Enable or disable dynamic font/coordinate scaling."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_scale_enabled(enabled)

    def load_from_dc(self, dc_path: Path) -> dict:
        """Load overlay config, preferring config.json over config1.dc.

        Tries config.json first (human-editable), falls back to config1.dc.

        Returns:
            display_options dict (may contain 'animation_file', etc.).
        """
        from ..paths import ThemeDir

        json_path = ThemeDir(dc_path.parent).json if dc_path else None
        if json_path and json_path.exists():
            try:
                from ..dc_parser import load_config_json

                result = load_config_json(str(json_path))
                if result is not None:
                    overlay_config, display_options = result
                    self.configure(overlay_config)
                    self.set_config_resolution(self._width, self._height)
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
            self.set_config_resolution(self._width, self._height)
            self.set_dc_data(dc.to_dict())
            return dc.display_options
        except Exception as e:
            log.error("Failed to parse DC file: %s", e)
            return {}

    # ── Mask ─────────────────────────────────────────────────────────

    def set_mask(self, image: Any, position: tuple[int, int] | None = None) -> None:
        """Set theme mask overlay image."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_theme_mask(image, position)

    def get_mask(self) -> tuple[Any, tuple[int, int] | None]:
        """Get current theme mask image and position."""
        renderer = self._ensure_renderer()
        if renderer:
            return renderer.theme_mask, renderer.theme_mask_position
        return None, None

    def set_mask_visible(self, visible: bool) -> None:
        """Toggle mask visibility without clearing it."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_mask_visible(visible)

    # ── Temp unit ────────────────────────────────────────────────────

    def set_temp_unit(self, unit: int) -> None:
        """Set temperature display unit (0=Celsius, 1=Fahrenheit)."""
        renderer = self._ensure_renderer()
        if renderer:
            renderer.set_temp_unit(unit)

    # ── Metrics ──────────────────────────────────────────────────────

    def update_metrics(self, metrics: dict) -> None:
        """Update system metrics for hardware overlay elements."""
        self._metrics = metrics

    # ── Render ───────────────────────────────────────────────────────

    def render(self, background: Any = None, metrics: dict | None = None,
               *, force: bool = False) -> Any:
        """Render overlay onto background.

        Args:
            background: Optional PIL Image (uses stored background if None).
            metrics: System metrics dict (uses stored metrics if None).
            force: Render even when disabled (for live editing preview).

        Returns:
            PIL Image with overlay rendered.
        """
        if background:
            self.set_background(background)
        m = metrics if metrics is not None else self._metrics

        if force:
            renderer = self._ensure_renderer()
            if renderer:
                return renderer.render(m)
            return self._background

        if not self._enabled or not self._renderer:
            return self._background

        return self._renderer.render(m)

    # ── DC data (lossless round-trip) ────────────────────────────────

    def set_dc_data(self, data: dict[str, Any] | None) -> None:
        """Store parsed DC data for lossless save round-trip."""
        self._dc_data = data

    def get_dc_data(self) -> dict[str, Any] | None:
        return self._dc_data

    def clear_dc_data(self) -> None:
        self._dc_data = None

    # ── Internal ─────────────────────────────────────────────────────

    def _ensure_renderer(self) -> Optional[Any]:
        """Ensure the internal renderer is initialized."""
        if not self._renderer:
            try:
                from ..overlay_renderer import OverlayRenderer

                self._renderer = OverlayRenderer(self._width, self._height)
                if self._background:
                    self._renderer.set_background(self._background)
            except ImportError:
                return None
        return self._renderer
