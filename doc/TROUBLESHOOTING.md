# Troubleshooting

Quick reference for common TRCC Linux issues. For full installation instructions, see the [Install Guide](INSTALL_GUIDE.md).

---

## Table of Contents

1. [Command Not Found](#trcc-command-not-found)
2. [No Device Detected](#no-compatible-trcc-lcd-device-detected)
3. [Permission Denied](#permission-denied-when-accessing-the-device)
4. [SELinux / Immutable Distros](#selinux--immutable-distros)
5. [PyQt6 Issues](#pyqt6-issues)
6. [HID Device Issues](#hid-device-issues)
7. [Display Issues](#display-issues)
8. [Video / Media Issues](#video--media-issues)
9. [NixOS-Specific](#nixos-specific)

---

## `trcc: command not found`

**Cause:** `pip install` puts the `trcc` script in `~/.local/bin/`, which isn't in your shell's `PATH` on many distros.

**Fix:** Open a **new terminal**, or add `~/.local/bin` to your PATH permanently:

```bash
# Bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc

# Zsh (Arch, Garuda, some Manjaro)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc

# Fish
fish_add_path ~/.local/bin
```

| Distro | `~/.local/bin` in PATH by default? |
|--------|-----------------------------------|
| Fedora | Yes |
| Ubuntu / Debian | Conditionally (only if dir exists at login) |
| Arch / Manjaro / EndeavourOS | No |
| openSUSE | No |
| Void / Alpine | No |

---

## No compatible TRCC LCD device detected

**Cause:** The LCD isn't showing up as a SCSI device.

**Fix:**
1. Make sure the USB cable is plugged in (both ends)
2. Run udev setup: `trcc setup-udev`
3. **Unplug and replug the USB cable** (or reboot)
4. Check if the device appears: `ls /dev/sg*`
5. Check kernel messages: `dmesg | tail -20` right after plugging in

> **HID devices** (0416:5302, 0418:5303, 0418:5304, 0416:8001) don't use `/dev/sg*`. Use `trcc detect --all` instead.

---

## Permission denied when accessing the device

**Cause:** Udev rules not set up, or stale rules from an older version.

**Fix:**
```bash
# Upgrade to latest version first
pip install --upgrade trcc-linux

# Re-generate udev rules
trcc setup-udev

# Unplug/replug USB cable, or reboot
```

### SELinux / Immutable Distros

**Affects:** Bazzite, Fedora Silverblue, Fedora Kinoite, Aurora, Bluefin, and any SELinux-enforcing distro.

Versions before v1.2.16 used `TAG+="uaccess"` in udev rules, which relies on systemd-logind ACLs. **SELinux blocks these ACLs**, so the device stays root-only even after `setup-udev`.

**Symptoms:**
- `ls -la /dev/sgX` shows `crw-rw----. 1 root root` (no ACL `+` marker)
- `getenforce` returns `Enforcing`
- Device works with `sudo` but not as regular user

**Fix:** Upgrade to v1.2.16+ which uses `MODE="0666"`:
```bash
pip install --upgrade trcc-linux
sudo trcc setup-udev
# Unplug/replug USB cable
```

**Verify:** After replug, check permissions:
```bash
ls -la /dev/sg*
# Should show: crw-rw-rw- (world-readable/writable)
```

---

## PyQt6 Issues

### "Error: PyQt6 not available"

**Fix:** Install for your distro:
```bash
# Fedora
sudo dnf install python3-pyqt6

# Ubuntu / Debian
sudo apt install python3-pyqt6

# Arch
sudo pacman -S python-pyqt6

# Or via pip as fallback
pip install PyQt6
```

### Segmentation fault (core dumped)

**Cause:** Most commonly, a missing Qt6 xcb dependency. On Ubuntu/Mint, `libxcb-cursor0` is not installed by default but Qt6 requires it — without it, Qt segfaults silently on startup.

**Fix 1 — Install missing library** (try this first):
```bash
sudo apt install libxcb-cursor0
```

**Fix 2 — Use a virtual environment** (if Fix 1 doesn't help):
```bash
python3 -m venv ~/.local/share/trcc-venv
~/.local/share/trcc-venv/bin/pip install trcc-linux PyQt6 pyusb
~/.local/share/trcc-venv/bin/trcc gui
```

**Diagnostic:** If neither fix works:
```bash
# Show Qt plugin loading errors
QT_DEBUG_PLUGINS=1 trcc gui 2>&1 | head -30
```

### "Qt_6_PRIVATE_API not found"

**Cause:** pip-installed PyQt6 bundles its own Qt6 libraries, but your system's Qt6 is loaded first. Version mismatch causes symbol errors.

**Fix (recommended):** Use the system PyQt6 package:
```bash
# Fedora
sudo dnf install python3-pyqt6
pip uninstall PyQt6 PyQt6-Qt6 PyQt6-sip

# Ubuntu / Debian
sudo apt install python3-pyqt6
pip uninstall PyQt6 PyQt6-Qt6 PyQt6-sip

# Arch
sudo pacman -S python-pyqt6
pip uninstall PyQt6 PyQt6-Qt6 PyQt6-sip
```

**Fix (alternative):** Force pip PyQt6 to use its own bundled Qt6:
```bash
LD_LIBRARY_PATH=$(python3 -c "import PyQt6; print(PyQt6.__path__[0])")/Qt6/lib trcc gui
```

---

## HID Device Issues

### "No HID devices found"

1. Verify USB connection: `lsusb | grep -i "0416\|0418\|87"`
2. Run `trcc setup-udev` and unplug/replug
3. Check if another process holds the USB device (VM, Windows TRCC in dual-boot)

### "Handshake returned None (protocol error)"

The device was detected but didn't respond to the handshake query. Common causes:

1. **Old version** — v1.2.9 rewrote the HID handshake with retry logic, 5s timeout, and endpoint auto-detect. Upgrade first:
   ```bash
   pip install --upgrade trcc-linux
   ```
2. **Firmware consumed the handshake** — some devices only respond once per USB power cycle. Unplug the USB header, wait 5 seconds, replug, then immediately run `trcc hid-debug`
3. **Unknown device** — if the device model isn't in our mapping table, [open an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues) with the `trcc hid-debug` output

### "No USB backend available"

**Fix:** Install pyusb:
```bash
pip install pyusb

# Also need the system library:
sudo apt install libusb-1.0-0-dev    # Debian/Ubuntu
sudo dnf install libusb1-devel       # Fedora
sudo pacman -S libusb                # Arch
```

### HID "Permission denied"

See [Permission denied](#permission-denied-when-accessing-the-device) above — same fix applies. Make sure you're on v1.2.16+ for SELinux compatibility.

### GUI shows empty themes with HID device

Themes are resolution-specific. If the handshake failed, the app doesn't know your screen resolution, so it can't load the right theme pack. Fix the handshake first — themes will populate automatically once the resolution is detected.

---

## Display Issues

### LCD stays blank or shows old image

```bash
trcc reset
```

### GUI looks wrong / elements overlapping

**Cause:** HiDPI scaling interfering with the fixed-size layout.

```bash
QT_AUTO_SCREEN_SCALE_FACTOR=0 trcc gui
```

### Colors are wrong (red/blue swapped)

**Cause:** Some SCSI devices use different RGB565 byte ordering. This was fixed in v1.2.1. Upgrade:

```bash
pip install --upgrade trcc-linux
```

If the issue persists, [open an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues) with `trcc report` output.

### Device detected but nothing displays / sg_raw errors

**Cause:** UAS (USB Attached SCSI) kernel driver interferes with LCD devices.

**Fix:** Verify the USB quirk file exists:
```bash
cat /etc/modprobe.d/trcc-lcd.conf
```

If missing, recreate:
```bash
trcc setup-udev
# Unplug/replug or reboot
```

If the problem persists, manually blacklist UAS:
```bash
echo "options usb-storage quirks=87cd:70db:u,87ad:70db:u,0416:5406:u,0402:3922:u" | sudo tee /etc/modprobe.d/trcc-lcd.conf
sudo dracut --force       # Fedora/RHEL
# or
sudo update-initramfs -u  # Debian/Ubuntu
```

---

## Video / Media Issues

### Video/GIF playback not working

**Cause:** FFmpeg not installed.

```bash
# Fedora / Nobara
sudo dnf install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Arch / CachyOS / Garuda
sudo pacman -S ffmpeg
```

### Screen cast shows black on Wayland

**Cause:** GNOME/KDE Wayland require PipeWire portal for screen capture.

```bash
# Fedora
sudo dnf install python3-gobject python3-dbus pipewire-devel

# Ubuntu / Debian
sudo apt install python3-gi python3-dbus python3-gst-1.0

# Arch
sudo pacman -S python-gobject python-dbus python-gst
```

> Screen cast works automatically on X11 and wlroots-based compositors (Sway, Hyprland). PipeWire portal is only needed for GNOME and KDE Wayland.

---

## NixOS-Specific

### `trcc setup-udev` doesn't work

NixOS manages udev rules declaratively. Add rules to `/etc/nixos/configuration.nix`:

```nix
services.udev.extraRules = ''
  # SCSI LCD devices
  SUBSYSTEM=="scsi_generic", ATTRS{idVendor}=="87cd", ATTRS{idProduct}=="70db", MODE="0666"
  SUBSYSTEM=="scsi_generic", ATTRS{idVendor}=="87ad", ATTRS{idProduct}=="70db", MODE="0666"
  SUBSYSTEM=="scsi_generic", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="5406", MODE="0666"
  SUBSYSTEM=="scsi_generic", ATTRS{idVendor}=="0402", ATTRS{idProduct}=="3922", MODE="0666"
  # HID LCD/LED devices
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="5302", MODE="0666"
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0418", ATTRS{idProduct}=="5303", MODE="0666"
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0418", ATTRS{idProduct}=="5304", MODE="0666"
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="8001", MODE="0666"
'';
```

Then rebuild: `sudo nixos-rebuild switch`

---

## Still Stuck?

1. Run `trcc report` and copy the full output
2. [Open an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues) with the report
3. Include your distro, kernel version (`uname -r`), and what you've tried
