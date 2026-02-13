"""
TRCC Core - Services + Controllers Architecture

Services: Pure Python business logic (no GUI dependencies)
Controllers: Driving adapters that wrap services for GUI
Models: Data classes only (ThemeInfo, DeviceInfo, VideoState, etc.)

Note: Controllers are NOT re-exported here to avoid circular imports
(services → core.models → core.__init__ → controllers → services).
Import controllers directly: `from trcc.core.controllers import ...`
"""

from .models import (
    DeviceInfo,
    PlaybackState,
    ThemeInfo,
    ThemeType,
    VideoState,
)

__all__ = [
    'ThemeType',
    'PlaybackState',
    'ThemeInfo',
    'DeviceInfo',
    'VideoState',
]
