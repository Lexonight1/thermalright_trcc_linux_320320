# Architecture

## Project Layout

```
src/trcc/
├── cli.py                       # CLI entry point
├── lcd_driver.py                # SCSI RGB565 frame send
├── device_detector.py           # USB device scan + KNOWN_DEVICES registry
├── device_implementations.py    # Per-device protocol variants
├── scsi_device.py               # Low-level SCSI commands
├── dc_parser.py                 # Parse config1.dc overlay configs
├── dc_writer.py                 # Write config1.dc files
├── overlay_renderer.py          # PIL-based text/sensor overlay rendering
├── gif_animator.py              # FFmpeg video frame extraction
├── sensor_enumerator.py         # Hardware sensor discovery (hwmon, pynvml, psutil, RAPL)
├── sysinfo_config.py            # Dashboard panel config persistence
├── system_info.py               # CPU/GPU/RAM/disk sensor collection
├── cloud_downloader.py          # Cloud theme HTTP fetch
├── theme_downloader.py          # Theme pack download manager
├── theme_io.py                  # Theme export/import (.tr format)
├── paths.py                     # XDG data/config, per-device config, .7z extraction
├── __version__.py               # Version info
├── core/
│   ├── models.py                # ThemeInfo, DeviceInfo, VideoState, OverlayElement
│   └── controllers.py           # GUI-independent MVC controllers
└── qt_components/
    ├── qt_app_mvc.py            # Main window (1454x800)
    ├── base.py                  # BasePanel, ImageLabel, pil_to_pixmap
    ├── constants.py             # Layout coords, sizes, colors, styles
    ├── assets.py                # Asset loader with lru_cache
    ├── eyedropper.py            # Fullscreen color picker
    ├── screen_capture.py        # X11/Wayland screen grab
    ├── pipewire_capture.py      # PipeWire/Portal Wayland capture
    ├── uc_device.py             # Device sidebar
    ├── uc_preview.py            # Live preview frame
    ├── uc_theme_local.py        # Local theme browser
    ├── uc_theme_web.py          # Cloud theme browser
    ├── uc_theme_mask.py         # Mask browser
    ├── uc_theme_setting.py      # Overlay editor / display mode panels
    ├── uc_image_cut.py          # Image cropper
    ├── uc_video_cut.py          # Video trimmer
    ├── uc_system_info.py        # Sensor dashboard
    ├── uc_sensor_picker.py      # Sensor selection dialog
    ├── uc_info_module.py        # Live system info display
    ├── uc_activity_sidebar.py   # Sensor element picker
    └── uc_about.py              # Settings / about panel
```

## Design Patterns

### MVC

Controllers in `core/` are GUI-independent. Views subscribe via callbacks, making it possible to swap frontends.

### Per-Device Configuration

Each connected LCD is identified by `"{index}:{vid:04x}_{pid:04x}"` (e.g. `"0:87cd_70db"`). Settings are stored in `~/.config/trcc/config.json` under a `"devices"` key. Each device independently persists:

- **Theme** — last selected local/cloud theme path
- **Brightness** — 3-level brightness (25%, 50%, 100%)
- **Rotation** — 0°/90°/180°/270°
- **Carousel** — enabled, interval, and theme list
- **Overlay** — element config and enabled state

### Asset System

726 GUI assets extracted from the Windows application, applied via QPalette (not stylesheets) to match the original dark theme exactly.

### Theme Archives

Starter themes and mask overlays ship as `.7z` archives, extracted on first use to `~/.local/share/trcc/`. This keeps the git repo and package size small.
