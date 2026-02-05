# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**TRCC Linux** - Native Linux port of Thermalright LCD Control Center (Windows TRCC 2.0.3) for controlling LCD displays on CPU coolers.

- Python/Tkinter GUI matching Windows layout exactly
- SCSI protocol via sg_raw, RGB565 pixel format
- Modular component architecture mirroring Windows UC* classes

## Commands

```bash
# Run GUI
PYTHONPATH=src python3 -m trcc.cli gui

# Run with window decorations (for debugging)
PYTHONPATH=src python3 -m trcc.cli gui --decorated

# Device detection
trcc detect

# Send image to LCD
trcc send image.png

# Run tests
pytest tests/

# Download cloud themes
trcc download themes-320
```

## Source Locations

| What | Path |
|------|------|
| **Windows decompiled C#** | `/home/ignorant/Downloads/TRCCCAPEN/TRCC_decompiled/` |
| **Extracted resources** | `assets/extracted_resx/TRCC.Properties.Resources/` |
| **Linux Python sources** | `src/trcc/` |
| **Session memory** | `~/.claude/.../memory/MEMORY.md` |

## Architecture

### Windows→Linux Component Mapping

| Windows Class | Linux File | Size | Purpose |
|---------------|------------|------|---------|
| Form1 | `trcc_app.py` | 1454x800 | Main shell |
| FormCZTV | `form_cztv.py` | 1274x800 | LCD controller per device |
| UCDevice | `uc_device.py` | 180x800 | Sidebar with device buttons |
| UCThemeLocal | `uc_theme_local.py` | 732x652 | Local themes browser |
| UCThemeWeb | `uc_theme_web.py` | 732x652 | Cloud themes browser |
| UCThemeMask | `uc_theme_mask.py` | 732x652 | Cloud masks browser |
| UCThemeSetting | `uc_theme_setting.py` | 732x661 | Settings container |
| UCXiTongXianShi | `uc_xitong_xianshi.py` | 472x430 | Overlay editor (7x6 grid) |
| UCPreview | `uc_preview.py` | 500x500 | Preview frame |
| UCVideoCut | `uc_video_cut.py` | 500x702 | Video trimmer |
| UCImageCut | `uc_image_cut.py` | 500x702 | Image cropper |

### Key Patterns

**Delegate Pattern**: Components communicate via `invoke_delegate(cmd, info, data)`. Parent handles commands.

**Background Images**: Three patterns exist:
1. Component sets own default in `__init__()`
2. Parent's .resx may override
3. `FormCZTV.set_panel_images()` applies language-specific images at runtime

**Theme Directory Structure**:
```
src/data/Theme320320/
├── Theme1/
│   ├── 00.png         # Background (sent to LCD)
│   ├── 01.png         # Mask overlay
│   ├── config1.dc     # Overlay configuration
│   └── Theme.png      # Preview thumbnail only
```

## Critical Rule: Reference Windows C# First

**ALWAYS read the decompiled Windows C# code before implementing or debugging.** The Windows code is the source of truth.

### Process for New Features

1. **Find the Windows class**: `TRCC.DCUserControl/{ClassName}.cs` or `TRCC.CZTV/FormCZTV.cs`

2. **Get coordinates from .resx**: `TRCC.{Namespace}.{ClassName}.resx` contains `Point(x, y)` and `Size(w, h)`

3. **Get images**: `assets/extracted_resx/TRCC.Properties.Resources/{ResourceName}.png`

4. **Check delegate commands**: Search for `delegate*.Invoke(cmd, ...)` to find command values

### Reading Large C# Files

FormCZTV.cs is ~6800 lines. Read in chunks:

```bash
# Find methods
Grep pattern="private void \w+\(" path="FormCZTV.cs"

# Read specific method
Read file_path="FormCZTV.cs" offset=3582 limit=100
```

### Key FormCZTV.cs Methods

| Method | Line | Purpose |
|--------|------|---------|
| `ThemeLocal` | 3582 | Local theme delegate (cmd: 0/1/2=filter, 16=select, 32=delete) |
| `ThemeWeb` | 3991 | Cloud theme delegate (cmd: 0-6=filter, 16=download) |
| `ThemeMask` | 4374 | Mask delegate (cmd: 16=apply) |
| `ThemeSetting` | 4422 | Settings panel commands |
| `buttonBCZT_Click` | 5497 | Save theme (writes config1.dc) |

## Common Pitfalls

- `UCPreview.set_preview_image(img)` - NOT `update_preview()`
- Check `VIDEO_AVAILABLE` not `OPENCV_AVAILABLE` for video support
- Tkinter canvas z-order: use `tag_lower("background")` so thumbnails render on top
- RGB565 conversion must use numpy for performance (not pixel-by-pixel loop)
- SCSI send must be threaded to prevent GUI freeze

## Coding Standards

- **OOP** - Favor inheritance, base classes, and composition for code reuse
- **No magic numbers** - Extract coordinates, sizes, and thresholds into named constants or config
- **DRY** - Extract common logic into base classes or shared utilities; single source of truth
- **KISS** - Simplest solution that works; don't over-abstract
- Follow PEP 8, use type hints
- Match Windows behavior exactly unless improving

## Video Playback Architecture

FFmpeg is the default (matches Windows). Key settings:
- Frame skipping: `_lcd_send_interval = 4` (send every 4th frame to LCD)
- Preload frames into memory (matches Windows Theme.zt pattern)
- Threaded SCSI send with busy flag

## DC File Formats

**0xDC (Local themes)**: Background, mask, overlay element configs
**0xDD (Cloud themes)**: Theme ID, preview URLs, video URL, config
**Theme.zt**: Pre-rendered JPEG frames with timing (UCVideoCut export)

## Cloud Theme Servers

- International: `http://www.czhorde.cc/tr/bj{resolution}/`
- China: `http://www.czhorde.com/tr/bj{resolution}/`

Categories by filename prefix: a=Gallery, b=Tech, c=HUD, d=Light, e=Nature, y=Aesthetic

## Active TODOs

- [ ] Add integration test for GUI rendering (screenshot compare)
- [ ] Add font case-sensitivity tests (MSYH.TTC)
- [ ] Polish UCComboBox styling to match Windows

## See Also

- `docs/TECHNICAL_REFERENCE.md` - Protocol details, FBL codes
- `docs/WINDOWS_CS_REFERENCE.md` - Detailed C# code analysis
- `~/.claude/.../memory/MEMORY.md` - Session learnings
