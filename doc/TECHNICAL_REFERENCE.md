# TRCC Linux - Technical Reference

## Overview

Linux port of the Thermalright TRCC application for controlling LCD displays on CPU coolers.

## Supported Devices

| VID    | PID    | Vendor      | Product           |
|--------|--------|-------------|-------------------|
| 0x87CD | 0x70DB | Thermalright| LCD Display       |
| 0x0416 | 0x5406 | ALi Corp    | LCD Display       |
| 0x0402 | 0x3922 | ALi Corp    | USB PRC System    |

Devices appear as SCSI Generic (`/dev/sgX`) with vendor "USBLCD".

## Display Resolutions

### FBL (Feature Byte Length) Detection

The Windows app uses FBL values to identify display resolution. FBL mapping:

| FBL | Resolution | Notes |
|-----|------------|-------|
| 36, 37 | 240x240 | Small |
| 54 | 360x360 | Medium |
| 64 | 640x480 | VGA |
| 72 | 480x480 | Large square |
| 100-102 | 320x320 | Standard (default) |
| 114 | 1600x720 | Ultrawide |
| 128 | 1280x480 | Wide |
| 192 | 1920x462 | Ultrawide |
| 224 | 854x480/960x540/800x480 | Depends on pm |

### Theme Directories

Pre-rendered themes organized by resolution in `data/`:
- `Theme320320/` - 320x320 displays (5 themes)
- `Theme480480/` - 480x480 displays
- `Theme240240/` - 240x240 displays
- etc.

Each theme contains:
- `00.png` - Display state 0
- `01.png` - Display state 1
- `config1.dc` - Theme configuration
- `Theme.png` - Preview image

## Protocol

### SCSI Commands

All communication via `sg_raw` to `/dev/sgX`.

**Header format (20 bytes):**
```
cmd(4) + zeros(8) + size(4) + crc32(4)
```

### Initialization Sequence

```
1. Poll:  0xF5   READ  57,600 bytes (check device ready)
2. Init:  0x1F5  WRITE 57,600 bytes (initialize display)
```

### Frame Transfer (320x320 = 204,800 bytes)

```
Chunk 1: 0x101F5    WRITE 65,536 bytes
Chunk 2: 0x10101F5  WRITE 65,536 bytes
Chunk 3: 0x20101F5  WRITE 65,536 bytes
Chunk 4: 0x30101F5  WRITE  8,192 bytes
```

**Important:** Initialize ONCE, then stream frames without re-init.

### Pixel Format

RGB565 big-endian (2 bytes/pixel):
```python
pixel = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
```

## Architecture

### Windows TRCC Architecture (Reference)

The original Windows application is organized into these namespaces:

| Namespace | Purpose | Key Files |
|-----------|---------|-----------|
| **TRCC** | Main application shell | `Form1.cs` (main window 1454×800), `FormStart.cs` (splash), `Program.cs`, `UCDevice.cs` (sidebar), `UCAbout.cs` |
| **TRCC.CZTV** | LCD/Color Screen Controller | `FormCZTV.cs` (per-device controller), `FormGetColor.cs` (screen color picker), `FormScreenImage.cs`, `FormScreenshot.cs` |
| **TRCC.DCUserControl** | Reusable UI Components | 50+ `UC*.cs` files for all UI widgets |
| **TRCC.LED** | LED Strip Controller | `FormLED.cs` |
| **TRCC.KVMALED6** | KVM + ARGB LED (6-port) | `FormKVMALED6.cs` |
| **TRCC.Properties** | Resources & Settings | `Resources.cs` (670 embedded bitmaps), `Settings.cs` |

**CZTV** = **C**olor **Z**hong (彩屏) **T**ube/**V**ideo - "Color Screen Display"

### Windows UI Specifications

| Component | Size | Layout |
|-----------|------|--------|
| Main Window | 1454×800 | Borderless, RGB(35,34,39) = `#232227` |
| UCDevice (sidebar) | 180×800 | Left side at (0,0) |
| Content area | 1274×800 | Right side at (180,0) |
| Theme grid | 732×652 | 5 cols, 120×120 thumbnails, 135×150 spacing |
| Overlay grid | ~490×430 | 7×6 fixed grid (42 max), 60×60 elements, 67×66 spacing |
| Color panel | 230×374 | 11 preset colors + font settings |

### Windows Hardware Category Colors

From `UCSystemInfoOptionsOne.cs`:

| Category | Color | RGB |
|----------|-------|-----|
| CPU | `#32C5FF` | RGB(50, 197, 255) cyan |
| GPU | `#44D7B6` | RGB(68, 215, 182) teal |
| MEM | `#6DD401` | RGB(109, 212, 1) lime |
| HDD | `#F7B501` | RGB(247, 181, 1) amber |
| NET | `#FA6401` | RGB(250, 100, 1) orange |
| FAN | `#E02020` | RGB(224, 32, 32) red |

### Windows Resource Naming

670 embedded bitmap resources with localization suffixes:
- (none) = Chinese
- `d` = German, `e` = Spanish, `en` = English, `f` = French
- `p` = Portuguese, `r` = Russian, `tc` = Traditional Chinese, `x` = Japanese

Prefixes: `A0` (startup), `A1` (device images), `A2` (dropdowns), `D0` (device panels), `P` (UI buttons/panels)

### Linux Port Files

```
src/trcc/
├── device_detector.py    # USB/SCSI device detection
├── device_implementations.py  # Device-specific protocols
├── fbl_detector.py       # FBL resolution detection
├── lcd_driver.py         # Unified LCD driver
├── trcc_handshake_v2.py  # Low-level SCSI commands
├── dc_parser.py          # Theme config parser
├── gif_animator.py       # GIF/video playback
├── gui.py                # Main GUI application
└── components/           # Modular UI components (matches Windows)
    ├── base.py           # UCBase with delegate support
    ├── trcc_app.py       # TRCCApp main shell
    ├── form_cztv.py      # FormCZTV LCD controller
    ├── uc_device.py      # UCDevice sidebar
    ├── uc_theme_local.py # UCThemeLocal (5-col grid)
    ├── uc_theme_web.py   # UCThemeWeb cloud themes
    ├── uc_xitong_xianshi.py      # Overlay element manager (7×6 grid)
    ├── uc_xitong_xianshi_sub.py  # Individual overlay element
    ├── uc_xitong_xianshi_color.py # Color/font settings panel
    └── ...
```

### Device Detection Flow

```
1. lsusb → find known VID:PID
2. lsscsi → map USB to /dev/sgX
3. sysfs → verify USBLCD vendor
4. FBL query → detect resolution (or use default 320x320)
```

## Video Playback

### Windows TRCC Video Implementation

Windows TRCC uses ffmpeg directly via subprocess for video frame extraction (from `FormCZTV.cs` lines 1975-1993):

```csharp
string value = $"ffmpeg -i \"{name}\" -y -r 24 -f image2 \"{ucVideoCut1.allPicAddr}%04d.bmp\"";
Process.Start(new ProcessStartInfo {
    FileName = "cmd.exe",
    Arguments = "/c \"" + value + "\"",
    WindowStyle = ProcessWindowStyle.Hidden,
    CreateNoWindow = true
});
```

**Key parameters:**
- `-r 24` - Extract at 24 frames per second
- `-f image2` - Output as image sequence
- `%04d.bmp` - Sequential numbered BMP files

### Linux Implementation

The Linux port matches Windows behavior by using ffmpeg via subprocess. This is the **recommended** approach.

**Alternative:** OpenCV (`opencv-python`) can be used as a fallback if ffmpeg is not available.

| Method | Pros | Cons |
|--------|------|------|
| ffmpeg (recommended) | Matches Windows, better codec support, lighter | Requires system package |
| opencv-python | Pure Python, no system deps | Large package (~50MB), fewer codecs |

## Configuration

Settings stored in `data/settings.json`:

```json
{
  "screen": {
    "resolution": "320x320",
    "brightness": 100,
    "refresh_rate": 60
  }
}
```

## Quick Commands

```bash
# Detect device
lsscsi | grep USBLCD

# Test display (red screen)
python3 src/trcc/trcc_handshake_v2.py --device /dev/sg0 --color ff0000

# Display image
python3 src/trcc/trcc_handshake_v2.py --device /dev/sg0 --image photo.png

# Run GUI
python3 -m trcc.gui
```

## Troubleshooting

### Permission denied
```bash
sudo usermod -aG trcc $USER
# or use udev rules in 99-trcc.rules
```

### Device not found
```bash
# Check USB connection
lsusb | grep -i "0402\|0416\|87cd"

# Check SCSI mapping
lsscsi -t

# Load sg driver
sudo modprobe sg
```

### Display shows garbage
- Verify resolution matches your LCD (default: 320x320)
- Check pixel format (RGB565 big-endian)
- Ensure full frame is sent (204,800 bytes for 320x320)
