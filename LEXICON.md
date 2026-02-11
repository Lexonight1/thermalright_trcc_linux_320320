# TRCC Linux — Lexicon

Shared terminology so everyone uses the same names.

## Devices & Protocols
| Term | Meaning |
|------|---------|
| **SCSI** | USB mass-storage protocol used to send LCD frames (RGB565) |
| **HID** | USB Human Interface Device protocol — handshake, resolution detection |
| **LED** | RGB LED control protocol via HID (effects, colors, zones) |
| **PM** | Product Model byte from HID handshake — identifies device variant |
| **FBL** | Firmware Byte Layout — maps PM to screen resolution |
| **PID** | USB Product ID (e.g., `0x5011`, `0x8001`) |
| **VID** | USB Vendor ID — Thermalright is `0x0416` |

## Theme System
| Term | Meaning |
|------|---------|
| **Local theme** | User-saved theme on disk (tab 1) — directory with `00.png`, `config1.dc` |
| **Cloud theme** | Downloadable MP4 video from czhorde.cc servers (tab 2) |
| **Mask** | Overlay layout template downloaded from cloud (tab 3) — `zt{resolution}/` |
| **config1.dc** | Binary overlay config file — text positions, fonts, sensor bindings |
| **Reference theme** | Read-only theme in `Custom_*/` dirs shipped with archives |
| **.tr file** | Theme export/import archive format |

## GUI Components
| Term | Meaning |
|------|---------|
| **UCPreview** | Main preview panel (500x500) showing current LCD frame |
| **UCThemeLocal** | Local themes browser (tab 1) |
| **UCThemeWeb** | Cloud themes browser (tab 2) |
| **UCThemeMask** | Cloud masks browser (tab 3) |
| **UCOverlay** | Overlay grid editor for sensor text placement |
| **UCDevice** | Device sidebar with detection and selection |
| **FormLED** | LED RGB control panel (effects, colors, zones) |
| **Carousel** | Auto-rotating theme slideshow |
| **Screencast** | Live screen capture sent to LCD |

## Data Flow
| Term | Meaning |
|------|---------|
| **On-demand download** | Archives fetched from GitHub raw at runtime when not found locally |
| **Theme archive** | `Theme{W}{H}.7z` — bundled theme images per resolution |
| **Web archive** | `{W}{H}.7z` — cloud theme preview PNGs |
| **Mask archive** | `zt{W}{H}.7z` — cloud mask overlay templates |
| **RGB565** | 16-bit pixel format (5R/6G/5B) sent to LCD via SCSI |

## Settings Tab
| Term | Meaning |
|------|---------|
| **`_update_selected(**fields)`** | Single handler for all overlay config changes — updates selected element and propagates |
| **`require_mode`** | Optional guard in `_update_selected` — only applies update if element's `mode` matches |
| **`mode_sub`** | Sub-format selector within a mode (e.g., 0=24H, 1=12H for time) |

## Directories
| Term | Meaning |
|------|---------|
| **DATA_DIR** | Package data dir (`src/trcc/data/` or site-packages equivalent) |
| **USER_DATA_DIR** | User writable data (`~/.trcc/data/`) — primary data location, survives pip upgrades |
| **Config dir** | Per-device config (`~/.trcc/config/{pid}/`) |
