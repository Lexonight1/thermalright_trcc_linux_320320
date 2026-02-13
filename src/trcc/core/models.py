"""
TRCC Models - Pure data classes with no GUI dependencies.

These models can be used by any GUI framework (Tkinter, PyQt6, etc.)
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..data_repository import ThemeDir

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


@dataclass
class HandshakeResult:
    """Common output from any device handshake.

    Every protocol (SCSI, HID, LED, Bulk) produces at least these fields.
    Protocol-specific subclasses (HidHandshakeInfo, LedHandshakeInfo) add extras.
    """

    resolution: Optional[Tuple[int, int]] = None
    model_id: int = 0
    serial: str = ""
    raw_response: bytes = field(default=b"", repr=False)


# Implementation key → display name (SCSI LCD devices)
IMPL_NAMES: dict[str, str] = {
    "thermalright_lcd_v1": "Thermalright LCD v1 (USBLCD)",
    "ali_corp_lcd_v1": "ALi Corp LCD v1 (USBLCD)",
    "generic": "Generic LCD",
}


@dataclass
class LCDDeviceConfig:
    """SCSI LCD device config — resolution, pixel format, protocol constants.

    Pure data: no I/O, no business logic. Business logic lives in
    ImageService (rgb_to_bytes, byte_order) and DeviceService (detect_resolution).
    """
    name: str = "Generic LCD"
    width: int = 320
    height: int = 320
    pixel_format: str = "RGB565"
    fbl: Optional[int] = None
    resolution_detected: bool = False
    poll_command: Tuple[int, int] = (0xF5, 0xE100)
    init_command: Tuple[int, int] = (0x1F5, 0xE100)
    init_per_frame: bool = False
    init_delay: float = 0.0
    frame_delay: float = 0.0

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @staticmethod
    def from_key(impl_key: str) -> 'LCDDeviceConfig':
        """Factory: create config from implementation key."""
        name = IMPL_NAMES.get(impl_key, "Generic LCD")
        return LCDDeviceConfig(name=name)

    @staticmethod
    def list_all() -> list[dict[str, str]]:
        """List all available implementations."""
        return [{"name": key, "class": dn} for key, dn in IMPL_NAMES.items()]


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


# =============================================================================
# DC File Format DTOs (config1.dc overlay configuration)
# =============================================================================

@dataclass
class FontConfig:
    """Font configuration from .dc file."""
    name: str
    size: float
    style: int      # 0=Regular, 1=Bold, 2=Italic
    unit: int       # GraphicsUnit
    charset: int
    color_argb: tuple  # (alpha, red, green, blue)


@dataclass
class ElementConfig:
    """Element position and font config."""
    x: int
    y: int
    font: Optional[FontConfig] = None
    enabled: bool = True


@dataclass
class DisplayElement:
    """
    Display element from UCXiTongXianShiSub (time, date, weekday, hardware info, custom text).

    myMode values:
        0 = Hardware info (CPU/GPU metrics)
        1 = Time
        2 = Weekday (SUN, MON, TUE, etc.)
        3 = Date
        4 = Custom text

    myModeSub values (format variants):
        For mode 1 (Time):
            0 = HH:mm (24-hour)
            1 = hh:mm AM/PM (12-hour)
            2 = HH:mm (same as 0)
        For mode 3 (Date):
            0 = yyyy/MM/dd
            1 = yyyy/MM/dd (same as 0)
            2 = dd/MM/yyyy
            3 = MM/dd
            4 = dd/MM
    """
    mode: int           # Display type (0=hardware, 1=time, 2=weekday, 3=date, 4=custom)
    mode_sub: int       # Format variant
    x: int              # X position
    y: int              # Y position
    main_count: int = 0     # For hardware info - sensor category
    sub_count: int = 0      # For hardware info - specific sensor
    font_name: str = "Microsoft YaHei"
    font_size: float = 24.0
    font_style: int = 0  # 0=Regular, 1=Bold, 2=Italic
    font_unit: int = 3   # GraphicsUnit.Point
    font_charset: int = 134  # GB2312 (Windows default: new Font("微软雅黑", 36f, 0, 3, 134))
    color_argb: tuple = (255, 255, 255, 255)  # ARGB
    text: str = ""      # Custom text content

    @property
    def mode_name(self) -> str:
        """Get human-readable mode name."""
        names = {0: 'hardware', 1: 'time', 2: 'weekday', 3: 'date', 4: 'custom'}
        return names.get(self.mode, f'unknown_{self.mode}')

    @property
    def color_hex(self) -> str:
        """Get color as hex string."""
        _, r, g, b = self.color_argb
        return f"#{r:02x}{g:02x}{b:02x}"


# Hardware sensor ↔ metric name mapping (single source of truth).
# Used by dc_parser, dc_writer, dc_config, uc_sensor_picker.
HARDWARE_METRICS: Dict[Tuple[int, int], str] = {
    (0, 1): 'cpu_temp',
    (0, 2): 'cpu_percent',
    (0, 3): 'cpu_freq',
    (0, 4): 'cpu_power',
    (1, 1): 'gpu_temp',
    (1, 2): 'gpu_usage',
    (1, 3): 'gpu_clock',
    (1, 4): 'gpu_power',
    (2, 1): 'mem_percent',
    (2, 2): 'mem_clock',
    (3, 1): 'disk_activity',
}

METRIC_TO_IDS: Dict[str, Tuple[int, int]] = {v: k for k, v in HARDWARE_METRICS.items()}


# =============================================================================
# Theme Config DTOs (dc_writer save/export format)
# =============================================================================

@dataclass
class ThemeConfig:
    """Complete theme configuration for saving."""
    # Display elements (UCXiTongXianShiSubArray)
    elements: List[DisplayElement] = field(default_factory=list)

    # System info global enable
    system_info_enabled: bool = True

    # Display options
    background_display: bool = True    # myBjxs
    transparent_display: bool = False  # myTpxs
    rotation: int = 0                  # directionB (0/90/180/270)
    ui_mode: int = 0                   # myUIMode
    display_mode: int = 0              # myMode

    # Overlay settings
    overlay_enabled: bool = True       # myYcbk
    overlay_x: int = 0                 # JpX
    overlay_y: int = 0                 # JpY
    overlay_w: int = 320               # JpW
    overlay_h: int = 320               # JpH

    # Mask settings
    mask_enabled: bool = False         # myMbxs
    mask_x: int = 0                    # XvalMB
    mask_y: int = 0                    # YvalMB


@dataclass
class CarouselConfig:
    """Carousel/slideshow configuration."""
    current_theme: int = 0             # myTheme - index of current theme
    enabled: bool = False              # isLunbo
    interval_seconds: int = 3          # myLunBoTimer (minimum 3)
    count: int = 0                     # lunBoCount
    theme_indices: List[int] = field(default_factory=lambda: [-1, -1, -1, -1, -1, -1])
    lcd_rotation: int = 1              # myLddVal (1-4)


# =============================================================================
# Sensor DTOs
# =============================================================================

@dataclass
class SensorInfo:
    """Describes a single hardware sensor."""
    id: str             # Unique ID: "hwmon:coretemp:temp1"
    name: str           # Human-readable: "CPU Package"
    category: str       # "temperature", "fan", "clock", "usage", "power", "voltage", "other"
    unit: str           # "°C", "RPM", "MHz", "%", "W", "V", "MB/s", "KB/s", "MB"
    source: str         # "hwmon", "nvidia", "psutil", "rapl", "computed"


# =============================================================================
# Domain Constants (FBL/resolution mapping, display formats)
# =============================================================================

# Time formats matching Windows TRCC (UCXiTongXianShiSub.cs)
TIME_FORMATS: Dict[int, str] = {
    0: "%H:%M",       # 24-hour (14:58)
    1: "%-I:%M %p",   # 12-hour with AM/PM, no leading zero (2:58 PM)
    2: "%H:%M",       # 24-hour (same as mode 0 in Windows)
}

# Date formats matching Windows TRCC
DATE_FORMATS: Dict[int, str] = {
    0: "%Y/%m/%d",    # 2026/01/30
    1: "%Y/%m/%d",    # 2026/01/30 (same as mode 0 in Windows)
    2: "%d/%m/%Y",    # 30/01/2026
    3: "%m/%d",       # 01/30
    4: "%d/%m",       # 30/01
}

# Weekday names matching Windows TRCC (English)
# Python weekday(): Monday=0, Sunday=6
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Chinese weekday names (for Language == 1)
WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# FBL → Resolution mapping (from FormCZTV.cs lines 811-821)
# FBL (Frame Buffer Layout) byte determines LCD resolution.
FBL_TO_RESOLUTION: dict[int, tuple[int, int]] = {
    36:  (240, 240),
    37:  (240, 240),
    50:  (240, 320),
    51:  (320, 240),
    54:  (360, 360),
    64:  (640, 480),
    72:  (480, 480),
    100: (320, 320),
    101: (320, 320),
    102: (320, 320),
    114: (1600, 720),
    128: (1280, 480),
    192: (1920, 462),
    224: (854, 480),
}

# Reverse lookup: resolution → PM/FBL (first match wins)
RESOLUTION_TO_PM: dict[tuple[int, int], int] = {
    res: fbl for fbl, res in FBL_TO_RESOLUTION.items()
    if fbl not in (37, 101, 102, 224)
}

# PM byte → FBL byte for Type 2 devices where PM ≠ FBL.
# (FormCZTV.cs lines 682-821)
# For all other PM values, PM=FBL (same convention as SCSI poll bytes).
_PM_TO_FBL_OVERRIDES: dict[int, int] = {
    5:   50,    # 240x320
    7:   64,    # 640x480
    9:   224,   # 854x480
    10:  224,   # 960x540 (special: actual res depends on PM)
    11:  224,   # 854x480
    12:  224,   # 800x480 (special)
    32:  100,   # 320x320
    64:  114,   # 1600x720
    65:  192,   # 1920x462
}


def fbl_to_resolution(fbl: int, pm: int = 0) -> tuple[int, int]:
    """Map FBL byte to (width, height).

    Used by all protocols: SCSI (poll byte[0] = FBL directly),
    HID (PM → pm_to_fbl → FBL), and Bulk (PM → pm_to_fbl → FBL).

    For FBL 224, the PM byte disambiguates the actual resolution.
    Returns (320, 320) as default if FBL is unknown.
    """
    if fbl == 224:
        if pm == 10:
            return (960, 540)
        elif pm == 12:
            return (800, 480)
        return (854, 480)
    return FBL_TO_RESOLUTION.get(fbl, (320, 320))


def pm_to_fbl(pm: int, sub: int = 0) -> int:
    """Map PM byte to FBL byte.

    Default: PM=FBL (same convention as SCSI poll bytes).
    Only overrides for the few PM values where PM ≠ FBL.
    Special case: PM=1 + SUB=48 → FBL=114, PM=1 + SUB=49 → FBL=192.
    """
    if pm == 1 and sub == 48:
        return 114
    if pm == 1 and sub == 49:
        return 192
    return _PM_TO_FBL_OVERRIDES.get(pm, pm)

