"""
Theme pack download manager for TRCC Linux.

Thin CLI adapter wrapping DataManager (paths.py) for theme pack operations.
All downloading and extraction is delegated to DataManager.

Usage:
    trcc download                          # list available packs
    trcc download themes-320x320           # download 320x320 themes
    trcc download themes-480               # shorthand for 480x480
    trcc download themes-320x320 --force   # re-download even if exists
    trcc download themes-320x320 --info    # show pack details
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .constants import FBL_TO_RESOLUTION
from .paths import DATA_DIR, USER_DATA_DIR, DataManager

log = logging.getLogger(__name__)


# =========================================================================
# Pack registry — built dynamically from known resolutions
# =========================================================================

@dataclass(frozen=True)
class PackInfo:
    """Metadata for a downloadable theme pack."""

    name: str
    resolution: str
    width: int
    height: int
    archive: str
    size_kb: int

    @property
    def url(self) -> str:
        return f"{DataManager.GITHUB_BASE_URL}{self.archive}"



# HID sub-variant resolutions not in FBL_TO_RESOLUTION (FBL 224 overloads).
# These depend on PM sub-bytes in device_hid.py but have their own theme archives.
_EXTRA_RESOLUTIONS: set[tuple[int, int]] = {
    (480, 800), (480, 854), (540, 960), (800, 480), (960, 540),
}


def _all_resolutions() -> list[tuple[int, int]]:
    """All supported resolutions: FBL table + HID sub-variants."""
    return sorted(set(FBL_TO_RESOLUTION.values()) | _EXTRA_RESOLUTIONS)


def _build_registry() -> Dict[str, PackInfo]:
    """Build theme pack registry from all known resolutions."""
    registry: Dict[str, PackInfo] = {}
    for w, h in _all_resolutions():
        pack_id = f"themes-{w}x{h}"
        archive = f"theme{w}{h}.7z"
        archive_path = os.path.join(DATA_DIR, archive)
        size_kb = os.path.getsize(archive_path) // 1024 if os.path.isfile(archive_path) else 0
        registry[pack_id] = PackInfo(
            name=f"TRCC Themes {w}x{h}",
            resolution=f"{w}x{h}",
            width=w,
            height=h,
            archive=archive,
            size_kb=size_kb,
        )
    return registry


def _build_short_aliases(registry: Dict[str, PackInfo]) -> Dict[str, str]:
    """Build short aliases for square resolutions (themes-320 → themes-320x320)."""
    aliases: Dict[str, str] = {}
    for pack_id, info in registry.items():
        if info.width == info.height:
            aliases[f"themes-{info.width}"] = pack_id
    return aliases


THEME_REGISTRY = _build_registry()
_SHORT_ALIASES = _build_short_aliases(THEME_REGISTRY)


def _resolve_pack_name(name: str) -> str:
    """Resolve short aliases to canonical pack names."""
    return _SHORT_ALIASES.get(name, name)


# =========================================================================
# ThemeDownloader — CLI adapter for DataManager
# =========================================================================

class ThemeDownloader:
    """Download and manage TRCC theme packs via DataManager."""

    @staticmethod
    def _theme_dir(w: int, h: int) -> Path:
        """Path to extracted theme directory (prefers user dir)."""
        user = Path(USER_DATA_DIR) / f"theme{w}{h}"
        if user.exists():
            return user
        pkg = Path(DATA_DIR) / f"theme{w}{h}"
        if pkg.exists():
            return pkg
        return user  # default to user dir for installs

    @staticmethod
    def _is_installed(w: int, h: int) -> bool:
        """Check if themes are extracted for a resolution."""
        d = ThemeDownloader._theme_dir(w, h)
        return d.exists() and any(d.iterdir())

    @staticmethod
    def _theme_count(w: int, h: int) -> int:
        """Count theme subdirectories for a resolution."""
        d = ThemeDownloader._theme_dir(w, h)
        if not d.exists():
            return 0
        return sum(1 for item in d.iterdir() if item.is_dir())

    # ── Public API ────────────────────────────────────────────────────

    @staticmethod
    def list_available() -> None:
        """List available theme packs with install status."""
        print("Available theme packs:")
        print("=" * 60)

        for pack_id, info in THEME_REGISTRY.items():
            installed = ThemeDownloader._is_installed(info.width, info.height)
            status = ""
            if installed:
                count = ThemeDownloader._theme_count(info.width, info.height)
                status = f" [installed, {count} themes]"

            alias = f" (or: themes-{info.width})" if info.width == info.height else ""
            size = f"{info.size_kb}KB" if info.size_kb > 0 else "on-demand"

            print(f"\n  {pack_id}{alias}{status}")
            print(f"    {info.name}, Size: ~{size}")

        print("\n" + "=" * 60)
        print("Install with: trcc download <pack-name>")
        print("Example: trcc download themes-320x320")
        print("         trcc download themes-480  (shorthand for 480x480)")

    @staticmethod
    def show_info(pack_name: str) -> None:
        """Show detailed info about a theme pack."""
        pack_name = _resolve_pack_name(pack_name)
        if pack_name not in THEME_REGISTRY:
            print(f"Unknown theme pack: {pack_name}")
            print("Use 'trcc download --list' to see available packs")
            return

        info = THEME_REGISTRY[pack_name]
        theme_dir = ThemeDownloader._theme_dir(info.width, info.height)

        print(f"\n{info.name}")
        print("=" * 40)
        print(f"Pack ID:     {pack_name}")
        print(f"Resolution:  {info.resolution}")
        print(f"Archive:     {info.archive}")
        print(f"Size:        ~{info.size_kb}KB")

        if ThemeDownloader._is_installed(info.width, info.height):
            count = ThemeDownloader._theme_count(info.width, info.height)
            print(f"\nInstalled:   Yes ({count} themes)")
            print(f"  Location:  {theme_dir}")
        else:
            print("\nInstalled:   No")

        print(f"\nSource:      {info.url}")

    @staticmethod
    def download_pack(pack_name: str, force: bool = False) -> int:
        """Download and install a theme pack via DataManager.

        Returns:
            0 on success, non-zero on failure.
        """
        pack_name = _resolve_pack_name(pack_name)
        if pack_name not in THEME_REGISTRY:
            print(f"Unknown theme pack: {pack_name}")
            print("Use 'trcc download --list' to see available packs")
            return 1

        info = THEME_REGISTRY[pack_name]
        w, h = info.width, info.height

        # Already installed?
        if not force and ThemeDownloader._is_installed(w, h):
            count = ThemeDownloader._theme_count(w, h)
            print(f"{pack_name} already installed ({count} themes)")
            print("Use --force to reinstall")
            return 0

        # Force: remove existing first
        if force:
            for d in (Path(USER_DATA_DIR) / f"theme{w}{h}",
                      Path(DATA_DIR) / f"theme{w}{h}"):
                if d.exists():
                    log.info("Removing %s for reinstall", d)
                    shutil.rmtree(d)

        print(f"Downloading {info.name} ({info.resolution})...")

        ok = DataManager.ensure_themes(w, h)
        if not ok:
            print(f"Failed to download/extract {info.archive}")
            return 1

        count = ThemeDownloader._theme_count(w, h)
        print(f"\n[OK] Installed {count} themes to {ThemeDownloader._theme_dir(w, h)}")
        return 0

    @staticmethod
    def remove_pack(pack_name: str) -> int:
        """Remove an installed theme pack from user data directory."""
        pack_name = _resolve_pack_name(pack_name)
        if pack_name not in THEME_REGISTRY:
            print(f"Unknown theme pack: {pack_name}")
            return 1

        info = THEME_REGISTRY[pack_name]
        user_dir = Path(USER_DATA_DIR) / f"theme{info.width}{info.height}"

        if not user_dir.exists():
            print(f"Theme pack '{pack_name}' is not installed in user directory")
            return 1

        print(f"Removing {pack_name} from {user_dir}...")
        shutil.rmtree(user_dir)
        print(f"[OK] Removed {pack_name}")
        return 0


# =========================================================================
# Backward-compat aliases (used by cli.py and tests)
# =========================================================================
list_available = ThemeDownloader.list_available
show_info = ThemeDownloader.show_info
download_pack = ThemeDownloader.download_pack
remove_pack = ThemeDownloader.remove_pack
