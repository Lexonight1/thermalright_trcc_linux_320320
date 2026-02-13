"""
TRCC Models - Pure data classes with no GUI dependencies.

These models can be used by any GUI framework (Tkinter, PyQt6, etc.)
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..paths import ThemeDir

# =============================================================================
# Browser Item Dataclasses (replace raw dicts in theme/mask panels)
# =============================================================================


@dataclass
class ThemeItem:
    """Base for all theme browser items."""
    name: str
    is_local: bool = True


@dataclass
class LocalThemeItem(ThemeItem):
    """Item in the local themes browser (UCThemeLocal)."""
    path: str = ""
    thumbnail: str = ""
    is_user: bool = False
    index: int = 0  # position in unfiltered list


@dataclass
class CloudThemeItem(ThemeItem):
    """Item in the cloud themes browser (UCThemeWeb)."""
    id: str = ""
    video: Optional[str] = None
    preview: Optional[str] = None


@dataclass
class MaskItem(ThemeItem):
    """Item in the cloud masks browser (UCThemeMask)."""
    path: Optional[str] = None
    preview: Optional[str] = None


# =============================================================================
# Theme Model
# =============================================================================

@dataclass
class ThemeData:
    """Bundle returned after loading a theme — everything needed to display it."""
    background: Any = None               # PIL Image
    animation_path: Optional[Path] = None  # video/zt path
    is_animated: bool = False
    mask: Any = None                     # PIL Image
    mask_position: Optional[Tuple[int, int]] = None
    mask_source_dir: Optional[Path] = None


class ThemeType(Enum):
    """Type of theme."""
    LOCAL = auto()      # Local theme from Theme{resolution}/ directory
    CLOUD = auto()      # Cloud theme (video) from Web/{W}{H}/ directory
    MASK = auto()       # Mask overlay from Web/zt{W}{H}/ directory
    USER = auto()       # User-created theme


@dataclass
class ThemeInfo:
    """
    Information about a single theme.

    Matches Windows FormCZTV theme data structure.
    """
    name: str
    path: Optional[Path] = None
    theme_type: ThemeType = ThemeType.LOCAL

    # Files within theme directory
    background_path: Optional[Path] = None      # 00.png
    mask_path: Optional[Path] = None            # 01.png
    thumbnail_path: Optional[Path] = None       # Theme.png
    animation_path: Optional[Path] = None       # Theme.zt or video file
    config_path: Optional[Path] = None          # config1.dc

    # Metadata
    resolution: Tuple[int, int] = (320, 320)
    is_animated: bool = False
    is_mask_only: bool = False

    # Cloud theme specific
    video_url: Optional[str] = None
    preview_url: Optional[str] = None
    category: Optional[str] = None  # a=Gallery, b=Tech, c=HUD, etc.

    @classmethod
    def from_directory(cls, path: Path, resolution: Tuple[int, int] = (320, 320)) -> 'ThemeInfo':
        """Create ThemeInfo from a theme directory."""
        td = ThemeDir(path)

        # Determine if animated — check Theme.zt first, then .mp4 files
        if td.zt.exists():
            is_animated = True
            animation_path = td.zt
        else:
            mp4_files = list(path.glob('*.mp4'))
            if mp4_files:
                is_animated = True
                animation_path = mp4_files[0]
            else:
                is_animated = False
                animation_path = None

        return cls(
            name=path.name,
            path=path,
            theme_type=ThemeType.LOCAL,
            background_path=td.bg if td.bg.exists() else None,
            mask_path=td.mask if td.mask.exists() else None,
            thumbnail_path=td.preview if td.preview.exists() else (td.bg if td.bg.exists() else None),
            animation_path=animation_path,
            config_path=td.dc if td.dc.exists() else None,
            resolution=resolution,
            is_animated=is_animated,
            is_mask_only=not td.bg.exists() and td.mask.exists(),
        )

    @classmethod
    def from_video(cls, video_path: Path, preview_path: Optional[Path] = None) -> 'ThemeInfo':
        """Create ThemeInfo from a cloud video file."""
        name = video_path.stem
        category = name[0] if name else None

        return cls(
            name=name,
            path=video_path.parent,
            theme_type=ThemeType.CLOUD,
            animation_path=video_path,
            thumbnail_path=preview_path,
            is_animated=True,
            category=category,
        )


@dataclass
class DeviceInfo:
    """
    Information about a connected LCD device.

    Matches Windows FormCZTV device data.
    """
    name: str
    path: str  # /dev/sgX
    resolution: Tuple[int, int] = (320, 320)

    # Device properties (from detection)
    vendor: Optional[str] = None
    product: Optional[str] = None
    model: Optional[str] = None
    vid: int = 0
    pid: int = 0
    device_index: int = 0  # 0-based ordinal among detected devices
    fbl_code: Optional[int] = None  # Resolution identifier
    protocol: str = "scsi"  # "scsi" or "hid"
    device_type: int = 1  # 1=SCSI, 2=HID Type 2 ("H"), 3=HID Type 3 ("ALi")
    implementation: str = "generic"  # e.g. "thermalright_lcd_v1", "hid_type2", "hid_led"

    # State
    connected: bool = True
    brightness: int = 100  # 0-100%
    rotation: int = 0  # 0, 90, 180, 270

    @property
    def resolution_str(self) -> str:
        """Get resolution as string (e.g., '320x320')."""
        return f"{self.resolution[0]}x{self.resolution[1]}"


class PlaybackState(Enum):
    """Video playback state."""
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass
class VideoState:
    """
    State of video/animation playback.
    """
    state: PlaybackState = PlaybackState.STOPPED
    current_frame: int = 0
    total_frames: int = 0
    fps: float = 16.0
    loop: bool = True

    @property
    def progress(self) -> float:
        """Get playback progress (0-100)."""
        if self.total_frames <= 0:
            return 0.0
        return (self.current_frame / self.total_frames) * 100

    @property
    def current_time_str(self) -> str:
        """Get current time as MM:SS string."""
        if self.fps <= 0:
            return "00:00"
        secs = self.current_frame / self.fps
        return f"{int(secs // 60):02d}:{int(secs % 60):02d}"

    @property
    def total_time_str(self) -> str:
        """Get total time as MM:SS string."""
        if self.fps <= 0:
            return "00:00"
        secs = self.total_frames / self.fps
        return f"{int(secs // 60):02d}:{int(secs % 60):02d}"

    @property
    def frame_interval_ms(self) -> int:
        """Get frame interval in milliseconds."""
        if self.fps <= 0:
            return 62  # Default ~16fps (Windows: 62.5ms per frame)
        return int(1000 / self.fps)


class OverlayElementType(Enum):
    """Type of overlay element."""
    HARDWARE = 0    # CPU temp, GPU usage, etc.
    TIME = 1        # Current time
    WEEKDAY = 2     # Day of week
    DATE = 3        # Current date
    TEXT = 4        # Custom text


@dataclass
class OverlayElement:
    """
    Single overlay element configuration.

    Matches Windows UCXiTongXianShi element data.
    """
    element_type: OverlayElementType = OverlayElementType.TEXT
    enabled: bool = True
    x: int = 10
    y: int = 10
    color: Tuple[int, int, int] = (255, 255, 255)
    font_size: int = 16
    font_name: str = "Microsoft YaHei"

    # Hardware element specific
    metric_key: Optional[str] = None  # e.g., 'cpu_temp', 'gpu_usage'
    format_string: str = "{value}"    # e.g., "CPU: {value}°C"

    # Text element specific
    text: str = ""


# =============================================================================
# LED Model (FormLED equivalent)
# =============================================================================

class LEDMode(Enum):
    """LED effect modes from FormLED.cs timer functions."""
    STATIC = 0       # DSCL_Timer: solid color
    BREATHING = 1    # DSHX_Timer: fade in/out, period=66 ticks
    COLORFUL = 2     # QCJB_Timer: 6-phase gradient, period=168 ticks
    RAINBOW = 3      # CHMS_Timer: 768-entry table shift
    TEMP_LINKED = 4  # WDLD_Timer: color from CPU/GPU temperature
    LOAD_LINKED = 5  # FZLD_Timer: color from CPU/GPU load %


@dataclass
class LEDZoneState:
    """Per-zone state for multi-zone LED devices.

    Multi-zone devices (styles 2,3,5,6,7,8,11) have 2-4 independent zones,
    each with its own mode, color, brightness, and on/off state.
    From FormLED.cs: myLedMode1-4, rgbR1_1-4, myBrightness1-4, myOnOff1-4.
    """
    mode: LEDMode = LEDMode.STATIC
    color: Tuple[int, int, int] = (255, 0, 0)
    brightness: int = 100  # 0-100 (from FormLED.cs myBrightness, default 65)
    on: bool = True


@dataclass
class LEDState:
    """Complete LED device state matching FormLED.cs globals.

    This is the serializable state that gets persisted and restored.
    Animation counters are transient (not saved).
    """
    # Device configuration (from handshake pm → LedDeviceStyle)
    style: int = 1              # nowLedStyle
    led_count: int = 30         # from LedDeviceStyle.led_count
    segment_count: int = 10     # from LedDeviceStyle.segment_count
    zone_count: int = 1         # from LedDeviceStyle.zone_count

    # Global state
    mode: LEDMode = LEDMode.STATIC    # myLedMode
    color: Tuple[int, int, int] = (255, 0, 0)  # rgbR1, rgbG1, rgbB1
    brightness: int = 100       # myBrightness (0-100)
    global_on: bool = True      # myOnOff

    # Per-segment on/off (ucScreenLED1.isOn[] per logical segment)
    segment_on: List[bool] = field(default_factory=list)

    # Multi-zone states (styles with zone_count > 1)
    zones: List[LEDZoneState] = field(default_factory=list)

    # Animation counters (transient, not persisted)
    rgb_timer: int = 0          # rgbTimer for breathing/gradient/rainbow

    # Sensor linkage (for TEMP_LINKED and LOAD_LINKED modes)
    temp_source: str = "cpu"    # "cpu" or "gpu"
    load_source: str = "cpu"    # "cpu" or "gpu"

    # LC2 clock settings (style 9)
    is_timer_24h: bool = True
    is_week_sunday: bool = False

    def __post_init__(self):
        if not self.segment_on:
            self.segment_on = [True] * self.segment_count
        if not self.zones and self.zone_count > 1:
            self.zones = [LEDZoneState() for _ in range(self.zone_count)]

