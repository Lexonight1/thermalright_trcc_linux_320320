"""
TRCC Core - MVC Architecture

Models and Controllers that are GUI-framework independent.
Views (Tkinter, PyQt6, etc.) import from here.

Architecture:
- Models: Pure data classes, no GUI dependencies
- Controllers: Business logic, coordinates models and views
- Views: GUI-specific widgets (in components/ or qt_components/)
"""

from .models import (
    # Enums
    ThemeType,
    PlaybackState,
    OverlayElementType,
    # Data classes
    ThemeInfo,
    ThemeModel,
    DeviceInfo,
    DeviceModel,
    VideoState,
    VideoModel,
    OverlayElement,
    OverlayModel,
)

from .controllers import (
    ThemeController,
    DeviceController,
    VideoController,
    OverlayController,
    FormCZTVController,
    create_controller,
)

__all__ = [
    # Enums
    'ThemeType',
    'PlaybackState',
    'OverlayElementType',
    # Models
    'ThemeInfo',
    'ThemeModel',
    'DeviceInfo',
    'DeviceModel',
    'VideoState',
    'VideoModel',
    'OverlayElement',
    'OverlayModel',
    # Controllers
    'ThemeController',
    'DeviceController',
    'VideoController',
    'OverlayController',
    'FormCZTVController',
    'create_controller',
]
