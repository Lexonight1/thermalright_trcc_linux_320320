# CLI Reference

Complete reference for the `trcc` command-line interface.

## Usage

```
trcc [--version] [-v] <command> [options]
```

### Global Options

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `-v` | Increase verbosity (`-v` info, `-vv` debug) |
| `--last-one` | Start minimized to system tray, send last-used theme (for autostart) |

---

## Commands

### `trcc gui`

Launch the graphical interface.

```bash
trcc gui
trcc gui --decorated
trcc gui -vv          # debug logging
```

| Option | Description |
|--------|-------------|
| `--decorated`, `-d` | Show window with titlebar (can minimize/resize) |

The default window is frameless (matching the Windows TRCC layout). Use `--decorated` for debugging or if your window manager has trouble with frameless windows.

---

### `trcc detect`

Detect connected LCD devices.

```bash
trcc detect            # show active device
trcc detect --all      # list all detected devices
```

| Option | Description |
|--------|-------------|
| `--all`, `-a` | List all devices (not just the active one) |

**Example output:**

```
* [1] /dev/sg2 — Thermalright LCD Display [87cd:70db] (SCSI)
  [2] /dev/sg3 — ALi Corp LCD Display [0416:5406] (SCSI)
```

The `*` marks the currently active device.

---

### `trcc select`

Switch the active device (when multiple LCDs are connected).

```bash
trcc select 2          # select device number 2
```

Device numbers correspond to the `[N]` shown in `trcc detect --all`.

---

### `trcc send`

Send an image to the LCD.

```bash
trcc send image.png
trcc send photo.jpg --device /dev/sg2
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

The image is automatically resized and cropped to fit the LCD resolution.

---

### `trcc color`

Display a solid color on the LCD.

```bash
trcc color ff0000      # red
trcc color 00ff00      # green
trcc color '#0000ff'   # blue (quote the # in shell)
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

---

### `trcc test`

Test the display with a color cycle (red, green, blue, yellow, magenta, cyan, white).

```bash
trcc test
trcc test --loop       # cycle continuously until Ctrl+C
trcc test --device /dev/sg2
```

| Option | Description |
|--------|-------------|
| `--loop`, `-l` | Loop colors continuously (Ctrl+C to stop) |
| `--device`, `-d` | Device path (default: auto-detect) |

---

### `trcc reset`

Reset/reinitialize the LCD device. Sends a red test frame with force-init.

```bash
trcc reset
trcc reset --device /dev/sg2
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

---

### `trcc info`

Show live system metrics (CPU, GPU, memory, date/time).

```bash
trcc info
```

**Example output:**

```
System Information
========================================

CPU:
  cpu_temp: 52°C
  cpu_percent: 12%
  cpu_freq: 3.6 GHz

GPU:
  gpu_temp: 45°C

Memory:
  mem_percent: 34%
  mem_used: 5.4 GB
  mem_total: 16.0 GB

Date/Time:
  date: 2026-02-07
  time: 14:30:00
  weekday: Saturday
```

---

### `trcc setup-udev`

Install udev rules and USB storage quirks (required once after first install).

```bash
# Preview what will be written
trcc setup-udev --dry-run

# Install (auto-prompts for sudo)
trcc setup-udev
```

| Option | Description |
|--------|-------------|
| `--dry-run` | Print rules without installing (no root needed) |

**What this does:**

1. Creates `/etc/udev/rules.d/99-trcc-lcd.rules` — grants your user permission to access the LCD
2. Creates `/etc/modprobe.d/trcc-lcd.conf` — USB quirk that forces bulk-only transport (required for device detection)
3. Reloads udev rules

After running, **unplug and replug the USB cable** (or reboot).

---

### `trcc install-desktop`

Install the application menu entry (`.desktop` file) and icon so TRCC appears in your app launcher.

```bash
trcc install-desktop
```

Creates:
- `~/.local/share/applications/trcc.desktop`
- Copies the TRCC icon to the appropriate location

---

### `trcc resume`

Send the last-used theme to each detected device, then exit. Designed for headless use (autostart, cron, scripts).

```bash
trcc resume
```

This is what `~/.config/autostart/trcc.desktop` calls on login with `trcc --last-one` (which launches the GUI minimized to tray and sends the last theme).

---

### `trcc report`

Generate a full diagnostic report for bug reports. Collects everything needed to diagnose device issues in one command — users can copy-paste the entire output into a GitHub issue.

```bash
trcc report
```

**What it collects:**

- TRCC version, Python version, OS/kernel info
- `lsusb` output (all USB devices)
- `trcc detect --all` (detected TRCC devices with protocol info)
- HID handshake results (PM byte, resolution, serial)
- Udev rules status
- USB descriptor details for relevant devices

---

### `trcc hid-debug`

HID handshake diagnostic — prints hex dump and resolved device info for bug reports.

```bash
trcc hid-debug
```

**Example output:**

```
HID Debug — Handshake Diagnostic
============================================================

Device: ALi Corp LCD Display
  VID:PID = 0416:52e2
  Type = 2
  Implementation = hid_lcd

  Attempting handshake...
  Handshake OK!
  PM byte  = 100 (0x64)
  SUB byte = 0 (0x00)
  FBL      = 100 (0x64)
  Serial   = ABCDEF0123456789
  Resolution = 320x320
  Button image = A1FROZEN WARFRAME PRO
  FBL 100 = known resolution

  Raw handshake response (first 64 bytes):
  0000: da db dc dd 64 00 00 00 ...
```

---

### `trcc led-debug`

Diagnose an LED device — performs handshake and reports PM byte, style, and segment count.

```bash
trcc led-debug             # handshake only
trcc led-debug --test      # handshake + send test colors
```

| Option | Description |
|--------|-------------|
| `--test` | Send test colors to the device after handshake |

---

### `trcc hr10-tempd`

Display NVMe drive temperature on the HR10 2280 PRO Digital 7-segment display. Runs as a daemon — reads sysfs temperature and sends it to the device continuously with a breathe animation and thermal color gradient.

```bash
trcc hr10-tempd                          # default: 100% brightness, "9100" drive, Celsius
trcc hr10-tempd --brightness 50          # 50% brightness
trcc hr10-tempd --drive "Samsung 990"    # match a specific drive model
trcc hr10-tempd --unit F                 # Fahrenheit
```

| Option | Description |
|--------|-------------|
| `--brightness` | LED brightness 0-100 (default: 100) |
| `--drive` | Drive model substring to match (default: "9100") |
| `--unit` | Temperature unit: C or F (default: C) |

---

### `trcc doctor`

Check dependencies, libraries, and permissions. Useful for diagnosing installation issues.

```bash
trcc doctor
```

Reports status of: Python version, PySide6, PIL/Pillow, numpy, pyusb, sg_raw, udev rules, and device access permissions.

---

### `trcc serve`

Start a REST API server for remote LCD control (requires `trcc-linux[api]` extras).

```bash
trcc serve                              # localhost:8080
trcc serve --host 0.0.0.0 --port 9090  # LAN-accessible
trcc serve --token mysecret             # require auth token
```

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`, use `0.0.0.0` for LAN) |
| `--port` | Listen port (default: `8080`) |
| `--token` | API bearer token for authentication |

---

### `trcc brightness`

Set display brightness level.

```bash
trcc brightness 1       # 25%
trcc brightness 2       # 50%
trcc brightness 3       # 100%
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

Persists to per-device config.

---

### `trcc rotation`

Set display rotation.

```bash
trcc rotation 0         # no rotation
trcc rotation 90        # 90° clockwise
trcc rotation 180       # 180°
trcc rotation 270       # 270° clockwise
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

Persists to per-device config.

---

### `trcc video`

Play a video, GIF, or ZT file on the LCD.

```bash
trcc video clip.mp4
trcc video animation.gif --no-loop
trcc video clip.mp4 --duration 30
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |
| `--no-loop` | Play once instead of looping |
| `--duration` | Stop after N seconds (default: 0 = forever) |

---

### `trcc screencast`

Stream a screen region to the LCD.

```bash
trcc screencast                           # full screen
trcc screencast --x 100 --y 100 --w 320 --h 320
trcc screencast --fps 15
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |
| `--x`, `--y` | Top-left corner of capture region |
| `--w`, `--h` | Width/height of capture region (0 = full screen) |
| `--fps` | Frames per second (default: 10) |

---

### `trcc mask`

Load a mask overlay and send to LCD.

```bash
trcc mask /path/to/mask.png
trcc mask /path/to/theme/dir
trcc mask --clear                 # remove mask (send solid black)
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |
| `--clear` | Clear mask (send solid black) |

---

### `trcc overlay`

Render overlay from a DC config file.

```bash
trcc overlay /path/to/config1.dc
trcc overlay /path/to/theme/dir --send
trcc overlay /path/to/theme/dir --output rendered.png
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |
| `--send`, `-s` | Send rendered result to LCD |
| `--output`, `-o` | Save rendered image to file |

---

### `trcc theme-list`

List available themes for the current device resolution.

```bash
trcc theme-list                   # local themes
trcc theme-list --cloud           # cloud themes
trcc theme-list --cloud --category a   # gallery category only
```

| Option | Description |
|--------|-------------|
| `--cloud`, `-c` | List cloud themes instead of local |
| `--category` | Filter by category (a=Gallery, b=Tech, c=HUD, d=Light, e=Nature, y=Aesthetic) |

---

### `trcc theme-load`

Load a theme by name and send to LCD.

```bash
trcc theme-load 003a              # exact name
trcc theme-load "Custom_MyTheme"  # custom theme
trcc theme-load warframe          # partial match
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |

Applies saved brightness/rotation, saves as last-used theme.

---

### `trcc theme-save`

Save current display state as a custom theme.

```bash
trcc theme-save MyTheme
trcc theme-save AnimTheme --video /path/to/clip.mp4
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (default: auto-detect) |
| `--video`, `-v` | Video path for animated theme |

Saves to `~/.trcc/data/theme{W}{H}/Custom_{name}/`.

---

### `trcc theme-export`

Export a theme as a `.tr` file.

```bash
trcc theme-export 003a /tmp/mytheme.tr
trcc theme-export Custom_MyTheme ~/backup.tr
```

---

### `trcc theme-import`

Import a theme from a `.tr` file.

```bash
trcc theme-import /tmp/mytheme.tr
```

| Option | Description |
|--------|-------------|
| `--device`, `-d` | Device path (determines resolution for import target) |

---

### `trcc led-color`

Set LED static color.

```bash
trcc led-color ff0000      # red
trcc led-color 00ff00      # green
```

---

### `trcc led-mode`

Set LED effect mode.

```bash
trcc led-mode static       # solid color
trcc led-mode breathing    # fade in/out (Ctrl+C to stop)
trcc led-mode colorful     # cycle colors (Ctrl+C to stop)
trcc led-mode rainbow      # rotating hue (Ctrl+C to stop)
```

Animated modes run until Ctrl+C.

---

### `trcc led-brightness`

Set LED brightness.

```bash
trcc led-brightness 50     # 50%
trcc led-brightness 100    # full
```

Range: 0-100.

---

### `trcc led-off`

Turn LEDs off.

```bash
trcc led-off
```

---

### `trcc led-sensor`

Set sensor source for temperature/load linked LED modes.

```bash
trcc led-sensor cpu        # CPU temp/load drives LED color
trcc led-sensor gpu        # GPU temp/load drives LED color
```

---

### `trcc download`

Download theme packs for all supported LCD resolutions.

```bash
trcc download                        # list available packs
trcc download --list                 # same as above
trcc download themes-320x320        # download 320x320 theme pack
trcc download themes-320             # shorthand for 320x320 (square)
trcc download themes-240x320        # non-square resolution
trcc download themes-320x320 --force # re-download even if exists
trcc download themes-320x320 --info  # show pack details
```

Pack names follow the format `themes-{W}x{H}`. Square resolutions have a shorthand alias (e.g., `themes-320` → `themes-320x320`).

| Option | Description |
|--------|-------------|
| `--list`, `-l` | List available theme packs |
| `--force`, `-f` | Force re-download |
| `--info`, `-i` | Show pack info without downloading |

---

### `trcc uninstall`

Remove all TRCC configuration, udev rules, and autostart files.

```bash
trcc uninstall             # remove user config files

# Also remove udev rules (requires root — run from the repo directory)
sudo PYTHONPATH=src python3 -m trcc.cli uninstall
```

**Removes:**

| Item | Path |
|------|------|
| Config directory | `~/.config/trcc/` |
| Legacy config | `~/.trcc/` |
| Autostart entry | `~/.config/autostart/trcc.desktop` |
| Desktop shortcut | `~/.local/share/applications/trcc.desktop` |
| Udev rules (root) | `/etc/udev/rules.d/99-trcc-lcd.rules` |
| USB quirks (root) | `/etc/modprobe.d/trcc-lcd.conf` |

To fully uninstall the Python package as well:

```bash
trcc uninstall
sudo PYTHONPATH=src python3 -m trcc.cli uninstall
pip uninstall trcc-linux
```

---

## Troubleshooting

### `trcc: command not found`

pip installs to `~/.local/bin/` which may not be on your PATH. Either:

- **Open a new terminal** (Fedora/Ubuntu add `~/.local/bin` to PATH on shell startup if the directory exists)
- Run directly: `PYTHONPATH=src python3 -m trcc.cli gui`
- Add to PATH permanently: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc`

### `sudo trcc: command not found` / `No module named 'trcc'` with sudo

This was fixed in v1.2.0 — `trcc setup-udev` now automatically re-invokes itself with sudo and the correct PYTHONPATH. Just run:

```bash
trcc setup-udev
```
