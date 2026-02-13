#!/usr/bin/env python3
"""
TRCC Linux — Command Line Interface.

Entry points for the trcc-linux package (Typer CLI).
Organized into four command classes:
  DeviceCommands  — detection, selection, probing
  DisplayCommands — LCD frame operations (test, send, color, resume)
  DiagCommands    — HID/LED diagnostics
  SystemCommands  — setup, install, admin, info, download
"""

import os
import subprocess
import sys
from typing import Annotated, Optional

import typer

# =========================================================================
# Typer app
# =========================================================================

app = typer.Typer(
    help="Thermalright LCD Control Center for Linux",
    add_completion=False,
    pretty_exceptions_enable=False,
)

_verbose = 0


def _version_callback(value: bool) -> None:
    if value:
        from trcc.__version__ import __version__
        typer.echo(f"trcc {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    verbose: Annotated[int, typer.Option(
        "--verbose", "-v", count=True,
        help="Increase verbosity (-v, -vv, -vvv)",
    )] = 0,
    last_one: Annotated[bool, typer.Option(
        "--last-one",
        help="Start minimized to system tray with last-used theme (autostart)",
    )] = False,
    testing_hid: Annotated[bool, typer.Option(
        "--testing-hid", hidden=True,
        help="No-op (HID devices are now auto-detected)",
    )] = False,
    version: Annotated[Optional[bool], typer.Option(
        "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit",
    )] = None,
) -> None:
    global _verbose
    _verbose = verbose
    if last_one:
        result = gui(verbose=verbose, start_hidden=True)
        raise typer.Exit(result or 0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# =========================================================================
# Typer command functions (thin wrappers → class methods)
# =========================================================================

@app.command("gui")
def _cmd_gui(
    decorated: Annotated[bool, typer.Option(
        "--decorated", "-d",
        help="Use decorated window (normal window with titlebar, can minimize)",
    )] = False,
) -> int:
    """Launch graphical interface."""
    return gui(verbose=_verbose, decorated=decorated)


@app.command("detect")
def _cmd_detect(
    all_devices: Annotated[bool, typer.Option(
        "--all", "-a", help="Show all devices",
    )] = False,
) -> int:
    """Detect LCD device."""
    return DeviceCommands.detect(show_all=all_devices)


@app.command("select")
def _cmd_select(
    number: Annotated[int, typer.Argument(help="Device number from 'trcc detect --all'")],
) -> int:
    """Select device to control."""
    return DeviceCommands.select(number)


@app.command("test")
def _cmd_test(
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path (e.g., /dev/sg0)",
    )] = None,
    loop: Annotated[bool, typer.Option(
        "--loop", "-l", help="Loop colors continuously",
    )] = False,
) -> int:
    """Test display with color cycle."""
    return DisplayCommands.test(device=device, loop=loop)


@app.command("send")
def _cmd_send(
    image: Annotated[str, typer.Argument(help="Image file to send")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Send image to LCD."""
    return DisplayCommands.send_image(image, device=device)


@app.command("color")
def _cmd_color(
    hex_color: Annotated[str, typer.Argument(
        metavar="HEX", help="Hex color code (e.g., ff0000 for red)",
    )],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Display solid color."""
    return DisplayCommands.send_color(hex_color, device=device)


@app.command("info")
def _cmd_info() -> int:
    """Show system metrics."""
    return SystemCommands.show_info()


@app.command("reset")
def _cmd_reset(
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path (e.g., /dev/sg0)",
    )] = None,
) -> int:
    """Reset/reinitialize LCD device."""
    return DisplayCommands.reset(device=device)


@app.command("setup-udev")
def _cmd_setup_udev(
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Print rules without installing",
    )] = False,
) -> int:
    """Install udev rules for LCD device access."""
    return SystemCommands.setup_udev(dry_run=dry_run)


@app.command("install-desktop")
def _cmd_install_desktop() -> int:
    """Install application menu entry and icon."""
    return SystemCommands.install_desktop()


@app.command("resume")
def _cmd_resume() -> int:
    """Send last-used theme to each detected device (headless)."""
    return DisplayCommands.resume()


@app.command("uninstall")
def _cmd_uninstall() -> int:
    """Remove all TRCC config, udev rules, and autostart files."""
    return SystemCommands.uninstall()


@app.command("hid-debug")
def _cmd_hid_debug() -> int:
    """HID handshake diagnostic (hex dump for bug reports)."""
    return DiagCommands.hid_debug()


@app.command("led-debug")
def _cmd_led_debug(
    test_colors: Annotated[bool, typer.Option(
        "--test", help="Send test colors after handshake",
    )] = False,
) -> int:
    """Diagnose LED device (handshake, PM byte)."""
    return DiagCommands.led_debug(test=test_colors)


@app.command("hr10-tempd")
def _cmd_hr10_tempd(
    brightness: Annotated[int, typer.Option(help="LED brightness 0-100")] = 100,
    drive: Annotated[str, typer.Option(help="NVMe model substring to match")] = "9100",
    unit: Annotated[str, typer.Option(help="Temperature unit: C or F")] = "C",
) -> int:
    """Display NVMe temperature on HR10 (daemon)."""
    return DiagCommands.hr10_tempd(
        brightness=brightness, drive=drive, unit=unit, verbose=_verbose)


@app.command("report")
def _cmd_report() -> int:
    """Generate full diagnostic report for bug reports."""
    return SystemCommands.report()


@app.command("doctor")
def _cmd_doctor() -> int:
    """Check dependencies, libraries, and permissions."""
    from trcc.doctor import run_doctor
    return run_doctor()


@app.command("download")
def _cmd_download(
    pack: Annotated[Optional[str], typer.Argument(help="Theme pack name (e.g., themes-320x320 or themes-480)")] = None,
    show_list: Annotated[bool, typer.Option("--list", "-l", help="List available packs")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Force reinstall")] = False,
    show_info: Annotated[bool, typer.Option("--info", "-i", help="Show pack info")] = False,
) -> int:
    """Download theme packs."""
    return SystemCommands.download_themes(
        pack=pack, show_list=show_list, force=force, show_info=show_info)


@app.command("serve")
def _cmd_serve(
    host: Annotated[str, typer.Option(help="Bind address (use 0.0.0.0 for LAN)")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Listen port")] = 8080,
    token: Annotated[Optional[str], typer.Option(help="API token for auth")] = None,
) -> int:
    """Start REST API server (requires trcc-linux[api])."""
    try:
        import uvicorn  # noqa: I001

        from trcc.api import app as api_app, configure_auth
        configure_auth(token)
        uvicorn.run(api_app, host=host, port=port)
        return 0
    except ImportError:
        print("REST API requires: pip install trcc-linux[api]")
        return 1


# =========================================================================
# Main entry point
# =========================================================================

def main():
    """Main CLI entry point (pyproject.toml console_scripts)."""
    try:
        result = app(standalone_mode=False)
        return result if isinstance(result, int) else 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0


# =========================================================================
# Sudo helpers (module-level — used by SystemCommands)
# =========================================================================

def _sudo_reexec(subcommand):
    """Re-exec `trcc <subcommand>` as root via sudo with correct PYTHONPATH."""
    trcc_pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Include user site-packages so third-party deps (typer etc.) are available
    # under sudo, which strips ~/.local/lib from sys.path.
    import site
    user_site = site.getusersitepackages()
    pythonpath = f"{trcc_pkg}:{user_site}" if isinstance(user_site, str) else trcc_pkg
    cmd = [
        "sudo", "env", f"PYTHONPATH={pythonpath}",
        sys.executable, "-m", "trcc.cli", subcommand,
    ]
    print("Root required — requesting sudo...")
    result = subprocess.run(cmd)
    return result.returncode


def _sudo_run(cmd):
    """Run a command with sudo prepended. Returns subprocess.CompletedProcess."""
    return subprocess.run(["sudo"] + cmd)


# =========================================================================
# GUI launcher
# =========================================================================

def gui(verbose=0, decorated=False, start_hidden=False):
    """Launch the GUI application.

    Args:
        verbose: Logging verbosity (0=warning, 1=info, 2=debug).
        decorated: Use decorated window with titlebar.
        start_hidden: Start minimized to system tray (used by --last-one autostart).
    """
    import logging

    # Set up logging based on verbosity (filter out noisy PIL)
    if verbose >= 2:
        logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(name)s: %(message)s')
        logging.getLogger('PIL').setLevel(logging.WARNING)
    elif verbose == 1:
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        from trcc.qt_components.qt_app_mvc import run_mvc_app
        print("[TRCC] Starting LCD Control Center...")
        return run_mvc_app(decorated=decorated, start_hidden=start_hidden)
    except ImportError as e:
        print(f"Error: PySide6 not available: {e}")
        print("Install with: pip install PySide6")
        return 1
    except Exception as e:
        print(f"Error launching GUI: {e}")
        import traceback
        traceback.print_exc()
        return 1


# =========================================================================
# DeviceCommands — detection, selection, probing
# =========================================================================

class DeviceCommands:
    """Device detection, selection, and probing commands."""

    @staticmethod
    def _get_service(device_path: Optional[str] = None):
        """Create a DeviceService, detect devices, and select by path.

        Args:
            device_path: SCSI path (/dev/sgX) or None to use saved selection.

        Returns:
            DeviceService with a selected device.
        """
        from trcc.services import DeviceService

        svc = DeviceService()
        svc.detect()

        if device_path:
            # Select by explicit path
            match = next((d for d in svc.devices if d.path == device_path), None)
            if match:
                svc.select(match)
            elif svc.devices:
                svc.select(svc.devices[0])
        elif not svc.selected:
            # Fall back to saved selection
            from trcc.conf import get_selected_device
            saved = get_selected_device()
            if saved:
                match = next((d for d in svc.devices if d.path == saved), None)
                if match:
                    svc.select(match)

        return svc

    @staticmethod
    def _ensure_extracted(driver):
        """Extract theme/mask archives for the driver's detected resolution (one-time)."""
        try:
            if driver.implementation:
                w, h = driver.implementation.resolution
                from trcc.data_repository import DataManager
                DataManager.ensure_all(w, h)
        except Exception:
            pass  # Non-fatal — themes are optional for CLI commands

    @staticmethod
    def _get_driver(device=None):
        """Create an LCDDriver, resolving selected device and extracting archives."""
        from trcc.conf import get_selected_device
        from trcc.device_lcd import LCDDriver
        if device is None:
            device = get_selected_device()
        driver = LCDDriver(device_path=device)
        DeviceCommands._ensure_extracted(driver)
        return driver

    @staticmethod
    def _probe(dev):
        """Try to resolve device details via HID handshake/cache.

        Returns a dict with resolved fields, or empty dict if no probe available.
        """
        result = {}

        # LED devices: probe via led_device cache/handshake
        if dev.implementation == 'hid_led':
            try:
                from trcc.device_led import probe_led_model
                info = probe_led_model(dev.vid, dev.pid, usb_path=dev.usb_path)
                if info and info.model_name:
                    result['model'] = info.model_name
                    result['pm'] = info.pm
                    result['style'] = info.style
            except Exception:
                pass

        # HID LCD devices: probe via hid_device handshake
        elif dev.implementation in ('hid_type2', 'hid_type3'):
            try:
                from trcc.device_factory import DeviceProtocolFactory
                from trcc.device_hid import HidHandshakeInfo
                device_info = {
                    'vid': dev.vid, 'pid': dev.pid,
                    'protocol': dev.protocol, 'device_type': dev.device_type,
                    'implementation': dev.implementation,
                    'path': f"hid:{dev.vid:04x}:{dev.pid:04x}",
                }
                protocol = DeviceProtocolFactory.get_protocol(device_info)
                raw_info = protocol.handshake()
                if isinstance(raw_info, HidHandshakeInfo):
                    result['pm'] = raw_info.mode_byte_1
                    result['resolution'] = raw_info.resolution
                    if raw_info.serial:
                        result['serial'] = raw_info.serial
            except Exception:
                pass

        # Bulk USB devices: probe via BulkProtocol
        elif dev.implementation == 'bulk_usblcdnew':
            try:
                from trcc.device_factory import BulkProtocol
                bp = BulkProtocol(dev.vid, dev.pid)
                hs = bp.handshake()
                if hs and hs.resolution:
                    result['resolution'] = hs.resolution
                    result['pm'] = hs.model_id
                bp.close()
            except Exception:
                pass

        return result

    @staticmethod
    def _format(dev, probe=False):
        """Format a detected device for display."""
        vid_pid = f"[{dev.vid:04x}:{dev.pid:04x}]"
        proto = dev.protocol.upper()
        if dev.scsi_device:
            path = dev.scsi_device
        elif dev.protocol in ("hid", "bulk"):
            path = f"{dev.vid:04x}:{dev.pid:04x}"
        else:
            path = "No device path found"
        line = f"{path} — {dev.product_name} {vid_pid} ({proto})"

        if not probe:
            return line

        info = DeviceCommands._probe(dev)
        if not info:
            return line

        details = []
        if 'model' in info:
            details.append(f"model: {info['model']}")
        if 'resolution' in info:
            w, h = info['resolution']
            details.append(f"resolution: {w}x{h}")
        if 'pm' in info:
            details.append(f"PM={info['pm']}")
        if 'serial' in info:
            details.append(f"serial: {info['serial'][:16]}")

        if details:
            line += f" ({', '.join(details)})"
        return line

    @staticmethod
    def detect(show_all=False):
        """Detect LCD device."""
        try:
            from trcc.conf import get_selected_device
            from trcc.device_detector import check_udev_rules, detect_devices

            devices = detect_devices()
            if not devices:
                print("No compatible TRCC LCD device detected.")
                return 1

            if show_all:
                selected = get_selected_device()
                for i, dev in enumerate(devices, 1):
                    marker = "*" if dev.scsi_device == selected else " "
                    print(f"{marker} [{i}] {DeviceCommands._format(dev, probe=True)}")
                if len(devices) > 1:
                    print("\nUse 'trcc select N' to switch devices")
            else:
                selected = get_selected_device()
                dev = None
                if selected:
                    dev = next((d for d in devices if d.scsi_device == selected), None)
                if not dev:
                    dev = devices[0]
                print(f"Active: {DeviceCommands._format(dev, probe=True)}")

            # Check for stale/missing udev rules on any device
            for dev in devices:
                if not check_udev_rules(dev):
                    msg = f"\nDevice {dev.vid:04x}:{dev.pid:04x} needs updated udev rules.\n"
                    msg += "Run:  sudo trcc setup-udev"
                    if dev.protocol == "scsi":
                        msg += "\nThen reboot for the USB storage quirk to take effect."
                    print(msg)
                    break

            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1

    @staticmethod
    def select(number):
        """Select a device by number."""
        try:
            from trcc.conf import save_selected_device
            from trcc.device_detector import detect_devices

            devices = detect_devices()
            if not devices:
                print("No devices found.")
                return 1

            if number < 1 or number > len(devices):
                print(f"Invalid device number. Use 1-{len(devices)}")
                return 1

            device = devices[number - 1]
            save_selected_device(device.scsi_device)
            print(f"Selected: {device.scsi_device} ({device.product_name})")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1


# =========================================================================
# DisplayCommands — LCD frame operations
# =========================================================================

class DisplayCommands:
    """LCD display frame sending commands."""

    @staticmethod
    def test(device=None, loop=False):
        """Test display with color cycle."""
        try:
            import time

            from trcc.services import ImageService

            svc = DeviceCommands._get_service(device)
            if not svc.selected:
                print("No device found.")
                return 1

            dev = svc.selected
            w, h = dev.resolution

            colors = [
                ((255, 0, 0), "Red"),
                ((0, 255, 0), "Green"),
                ((0, 0, 255), "Blue"),
                ((255, 255, 0), "Yellow"),
                ((255, 0, 255), "Magenta"),
                ((0, 255, 255), "Cyan"),
                ((255, 255, 255), "White"),
            ]

            print(f"Testing display on {dev.path}...")

            while True:
                for (r, g, b), name in colors:
                    print(f"  Displaying: {name}")
                    img = ImageService.solid_color(r, g, b, w, h)
                    svc.send_pil(img, w, h)
                    time.sleep(1)

                if not loop:
                    break

            print("Test complete!")
            return 0
        except KeyboardInterrupt:
            print("\nTest interrupted.")
            return 0
        except Exception as e:
            print(f"Error testing display: {e}")
            return 1

    @staticmethod
    def send_image(image_path, device=None):
        """Send image to LCD."""
        try:
            if not os.path.exists(image_path):
                print(f"Error: File not found: {image_path}")
                return 1

            from PIL import Image

            from trcc.services import ImageService

            svc = DeviceCommands._get_service(device)
            if not svc.selected:
                print("No device found.")
                return 1

            dev = svc.selected
            w, h = dev.resolution
            img = Image.open(image_path).convert('RGB')
            img = ImageService.resize(img, w, h)
            svc.send_pil(img, w, h)
            print(f"Sent {image_path} to {dev.path}")
            return 0
        except Exception as e:
            print(f"Error sending image: {e}")
            return 1

    @staticmethod
    def send_color(hex_color, device=None):
        """Send solid color to LCD."""
        try:
            hex_color = hex_color.lstrip('#')
            if len(hex_color) != 6:
                print("Error: Invalid hex color. Use format: ff0000")
                return 1

            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)

            from trcc.services import ImageService

            svc = DeviceCommands._get_service(device)
            if not svc.selected:
                print("No device found.")
                return 1

            dev = svc.selected
            w, h = dev.resolution
            img = ImageService.solid_color(r, g, b, w, h)
            svc.send_pil(img, w, h)
            print(f"Sent color #{hex_color} to {dev.path}")
            return 0
        except Exception as e:
            print(f"Error sending color: {e}")
            return 1

    @staticmethod
    def reset(device=None):
        """Reset/reinitialize the LCD device."""
        try:
            from trcc.services import ImageService

            print("Resetting LCD device...")
            svc = DeviceCommands._get_service(device)
            if not svc.selected:
                print("No device found.")
                return 1

            dev = svc.selected
            w, h = dev.resolution
            print(f"  Device: {dev.path}")

            img = ImageService.solid_color(255, 0, 0, w, h)
            svc.send_pil(img, w, h)
            print("[OK] Device reset - displaying RED")
            return 0
        except Exception as e:
            print(f"Error resetting device: {e}")
            return 1

    @staticmethod
    def resume():
        """Send last-used theme to each detected device (headless, no GUI)."""
        try:
            import time

            from trcc.conf import device_config_key, get_device_config
            from trcc.services import DeviceService, ImageService

            svc = DeviceService()

            # Wait for USB devices to appear (they may not be ready at boot)
            devices: list = []
            for attempt in range(10):
                devices = svc.detect()
                if devices:
                    break
                print(f"Waiting for device... ({attempt + 1}/10)")
                time.sleep(2)

            if not devices:
                print("No compatible TRCC device detected.")
                return 1

            sent = 0
            for dev in devices:
                if dev.protocol != "scsi":
                    continue

                key = device_config_key(dev.device_index, dev.vid, dev.pid)
                cfg = get_device_config(key)
                theme_path = cfg.get("theme_path")

                if not theme_path:
                    print(f"  [{dev.product}] No saved theme, skipping")
                    continue

                # Find the image to send (00.png in theme dir, or direct file)
                image_path = None
                if os.path.isdir(theme_path):
                    candidate = os.path.join(theme_path, "00.png")
                    if os.path.exists(candidate):
                        image_path = candidate
                elif os.path.isfile(theme_path):
                    image_path = theme_path

                if not image_path:
                    print(f"  [{dev.product}] Theme not found: {theme_path}")
                    continue

                try:
                    from PIL import Image

                    img = Image.open(image_path).convert("RGB")
                    w, h = dev.resolution
                    img = ImageService.resize(img, w, h)

                    # Apply brightness
                    brightness_level = cfg.get("brightness_level", 3)
                    brightness_pct = {1: 25, 2: 50, 3: 100}.get(brightness_level, 100)
                    img = ImageService.apply_brightness(img, brightness_pct)

                    # Apply rotation
                    rotation = cfg.get("rotation", 0)
                    img = ImageService.apply_rotation(img, rotation)

                    # Send via service (auto byte-order)
                    svc.select(dev)
                    svc.send_pil(img, w, h)
                    print(f"  [{dev.product}] Sent: {os.path.basename(theme_path)}")
                    sent += 1
                except Exception as e:
                    print(f"  [{dev.product}] Error: {e}")

            if sent == 0:
                print("No themes were sent. Use the GUI to set a theme first.")
                return 1

            print(f"Resumed {sent} device(s).")
            return 0

        except Exception as e:
            print(f"Error: {e}")
            return 1


# =========================================================================
# DiagCommands — HID/LED diagnostics
# =========================================================================

class DiagCommands:
    """HID/LED diagnostic commands."""

    @staticmethod
    def _hex_dump(data: bytes, max_bytes: int = 64) -> None:
        """Print a hex dump of data (for hid-debug diagnostics)."""
        for row in range(0, min(len(data), max_bytes), 16):
            hex_str = ' '.join(f'{b:02x}' for b in data[row:row + 16])
            ascii_str = ''.join(
                chr(b) if 32 <= b < 127 else '.'
                for b in data[row:row + 16]
            )
            print(f"  {row:04x}: {hex_str:<48s} {ascii_str}")

    @staticmethod
    def _hid_debug_lcd(dev) -> None:
        """HID handshake diagnostic for LCD devices (Type 2/3)."""
        from trcc.device_factory import HidProtocol
        from trcc.device_hid import (
            FBL_TO_RESOLUTION,
            HidHandshakeInfo,
            fbl_to_resolution,
            get_button_image,
            pm_to_fbl,
        )

        protocol = HidProtocol(
            vid=dev.vid, pid=dev.pid,
            device_type=dev.device_type,
        )
        info = protocol.handshake()

        if info is None:
            error = protocol.last_error
            if error:
                print(f"  Handshake FAILED: {error}")
            else:
                print("  Handshake returned None (no response from device)")
            protocol.close()
            return

        assert isinstance(info, HidHandshakeInfo)
        pm = info.mode_byte_1
        sub = info.mode_byte_2
        fbl = info.fbl if info.fbl is not None else pm_to_fbl(pm, sub)
        resolution = info.resolution or fbl_to_resolution(fbl, pm)

        print("  Handshake OK!")
        print(f"  PM byte  = {pm} (0x{pm:02x})")
        print(f"  SUB byte = {sub} (0x{sub:02x})")
        print(f"  FBL      = {fbl} (0x{fbl:02x})")
        print(f"  Serial   = {info.serial}")
        print(f"  Resolution = {resolution[0]}x{resolution[1]}")

        # Button image from PM + SUB
        button = get_button_image(pm, sub)
        if button:
            print(f"  Button image = {button}")
        else:
            print(f"  Button image = unknown PM={pm} SUB={sub} (defaulting to CZTV)")

        # Known FBL?
        if fbl in FBL_TO_RESOLUTION:
            print(f"  FBL {fbl} = known resolution")
        else:
            print(f"  FBL {fbl} = UNKNOWN (not in mapping table)")

        # Raw response hex dump
        if info.raw_response:
            print("\n  Raw handshake response (first 64 bytes):")
            DiagCommands._hex_dump(info.raw_response)

        protocol.close()

    @staticmethod
    def _hid_debug_led(dev) -> None:
        """HID handshake diagnostic for LED devices (Type 1)."""
        from trcc.device_factory import LedProtocol
        from trcc.device_led import PM_TO_STYLE, LedHandshakeInfo

        protocol = LedProtocol(vid=dev.vid, pid=dev.pid)
        info = protocol.handshake()

        if info is None:
            error = protocol.last_error
            if error:
                print(f"  Handshake FAILED: {error}")
            else:
                print("  Handshake returned None (no response from device)")
            protocol.close()
            return

        assert isinstance(info, LedHandshakeInfo)
        print("  Handshake OK!")
        print(f"  PM byte    = {info.pm} (0x{info.pm:02x})")
        print(f"  Sub-type   = {info.sub_type} (0x{info.sub_type:02x})")
        print(f"  Model      = {info.model_name}")

        style = info.style
        if style:
            print(f"  Style ID   = {style.style_id}")
            print(f"  LED count  = {style.led_count}")
            print(f"  Segments   = {style.segment_count}")
            print(f"  Zones      = {style.zone_count}")

        if info.pm in PM_TO_STYLE:
            print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
        else:
            print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
            print("  This device falls back to AX120 defaults.")
            print(f"  Please report PM {info.pm} in your GitHub issue.")

        # Raw response hex dump
        if info.raw_response:
            print("\n  Raw handshake response (first 64 bytes):")
            DiagCommands._hex_dump(info.raw_response)

        protocol.close()

    @staticmethod
    def hid_debug():
        """HID handshake diagnostic — prints hex dump and resolved device info.

        Users can share this output in bug reports to help debug HID device issues.
        Routes LED devices (Type 1) through LedProtocol, LCD devices through HidProtocol.
        """
        try:
            from trcc.device_detector import detect_devices

            print("HID Debug — Handshake Diagnostic")
            print("=" * 60)

            devices = detect_devices()
            hid_devices = [d for d in devices if d.protocol == 'hid']

            if not hid_devices:
                print("\nNo HID devices found.")
                print("Make sure the device is plugged in and try:")
                print("  trcc setup-udev   (then unplug/replug USB cable)")
                return 0

            for dev in hid_devices:
                is_led = dev.implementation == 'hid_led'
                dev_kind = "LED" if is_led else f"LCD (Type {dev.device_type})"

                print(f"\nDevice: {dev.vendor_name} {dev.product_name}")
                print(f"  VID:PID = {dev.vid:04x}:{dev.pid:04x}")
                print(f"  Kind = {dev_kind}")
                print(f"  Implementation = {dev.implementation}")

                print("\n  Attempting handshake...")
                try:
                    if is_led:
                        DiagCommands._hid_debug_led(dev)
                    else:
                        DiagCommands._hid_debug_lcd(dev)
                except ImportError as e:
                    print(f"  Missing dependency: {e}")
                    print("  Install: pip install pyusb  (or pip install hidapi)")
                except Exception as e:
                    print(f"  Handshake FAILED: {e}")
                    import traceback
                    traceback.print_exc()

            print(f"\n{'=' * 60}")
            print("Copy the output above and paste it in your GitHub issue.")
            return 0

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    @staticmethod
    def led_debug(test=False):
        """Diagnose LED device — handshake, PM byte discovery, optional test colors."""
        try:
            import time

            from trcc.device_factory import LedProtocol
            from trcc.device_led import (
                LED_PID,
                LED_VID,
                PM_TO_STYLE,
                LedHandshakeInfo,
            )

            print("LED Device Diagnostic")
            print("=" * 50)
            print(f"  Target: VID=0x{LED_VID:04x} PID=0x{LED_PID:04x}")

            protocol = LedProtocol(vid=LED_VID, pid=LED_PID)
            info = protocol.handshake()

            if info is None:
                error = protocol.last_error
                print(f"\nHandshake failed: {error or 'no response'}")
                protocol.close()
                return 1

            assert isinstance(info, LedHandshakeInfo)
            print(f"\n  PM byte:    {info.pm}")
            print(f"  Sub-type:   {info.sub_type}")
            print(f"  Model:      {info.model_name}")
            style = info.style
            if style is None:
                print("  Style:      (unknown — handshake returned no style)")
                protocol.close()
                return 1
            print(f"  Style ID:   {style.style_id}")
            print(f"  LED count:  {style.led_count}")
            print(f"  Segments:   {style.segment_count}")
            print(f"  Zones:      {style.zone_count}")

            if info.pm in PM_TO_STYLE:
                print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
            else:
                print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
                print("  This device falls back to AX120 defaults.")
                print(f"  Add PM {info.pm} to led_device.py _PM_REGISTRY.")

            if test:
                print("\n  Sending test colors...")
                led_count = style.led_count
                for name, color in [("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)),
                                    ("BLUE", (0, 0, 255)), ("WHITE", (255, 255, 255))]:
                    protocol.send_led_data([color] * led_count, brightness=100)
                    print(f"    {name}")
                    time.sleep(1.5)
                protocol.send_led_data(
                    [(0, 0, 0)] * led_count, global_on=False, brightness=0)
                print("    OFF")

            protocol.close()
            print("\nDone.")
            return 0

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return 1

    @staticmethod
    def hr10_tempd(brightness=100, drive="9100", unit="C", verbose=0):
        """Run the HR10 NVMe temperature display daemon."""
        try:
            from trcc.device_led_hr10 import run_hr10_daemon
            return run_hr10_daemon(
                brightness=brightness,
                model_substr=drive,
                unit=unit,
                verbose=verbose > 0,
            )
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return 1


# =========================================================================
# SystemCommands — setup, install, admin
# =========================================================================

class SystemCommands:
    """System setup and administration commands."""

    @staticmethod
    def show_info():
        """Show system metrics."""
        try:
            from trcc.system_info import format_metric, get_all_metrics

            metrics = get_all_metrics()

            print("System Information")
            print("=" * 40)

            groups = [
                ("CPU", ['cpu_temp', 'cpu_percent', 'cpu_freq']),
                ("GPU", ['gpu_temp', 'gpu_usage', 'gpu_clock']),
                ("Memory", ['mem_percent', 'mem_used', 'mem_total']),
                ("Date/Time", ['date', 'time', 'weekday']),
            ]
            for label, keys in groups:
                print(f"\n{label}:")
                for key in keys:
                    if key in metrics:
                        print(f"  {key}: {format_metric(key, metrics[key])}")

            return 0
        except Exception as e:
            print(f"Error getting metrics: {e}")
            return 1

    @staticmethod
    def setup_udev(dry_run=False):
        """Generate and install udev rules + USB storage quirks from KNOWN_DEVICES.

        Without quirks, UAS claims these LCD devices and the kernel ignores them
        (no /dev/sgX created). The :u quirk forces usb-storage bulk-only transport.
        """
        try:
            from trcc.device_detector import (
                _BULK_DEVICES,
                _HID_LCD_DEVICES,
                _LED_DEVICES,
                KNOWN_DEVICES,
            )

            # Always include ALL devices in udev rules (so hardware is ready
            # when users plug in HID/bulk devices, even without --testing-hid)
            all_devices = {**KNOWN_DEVICES, **_HID_LCD_DEVICES, **_LED_DEVICES, **_BULK_DEVICES}

            # --- 1. udev rules (permissions) ---
            rules_path = "/etc/udev/rules.d/99-trcc-lcd.rules"
            rules_lines = ["# Thermalright LCD/LED cooler devices — auto-generated by trcc setup-udev"]

            for (vid, pid), info in sorted(all_devices.items()):
                vendor = info.vendor
                product = info.product
                protocol = info.protocol
                if protocol == "hid":
                    rules_lines.append(
                        f'# {vendor} {product}\n'
                        f'SUBSYSTEM=="hidraw", '
                        f'ATTRS{{idVendor}}=="{vid:04x}", '
                        f'ATTRS{{idProduct}}=="{pid:04x}", '
                        f'MODE="0666"\n'
                        f'SUBSYSTEM=="usb", '
                        f'ATTR{{idVendor}}=="{vid:04x}", '
                        f'ATTR{{idProduct}}=="{pid:04x}", '
                        f'MODE="0666"'
                    )
                elif protocol == "bulk":
                    rules_lines.append(
                        f'# {vendor} {product}\n'
                        f'SUBSYSTEM=="usb", '
                        f'ATTR{{idVendor}}=="{vid:04x}", '
                        f'ATTR{{idProduct}}=="{pid:04x}", '
                        f'MODE="0666"'
                    )
                else:
                    rules_lines.append(
                        f'# {vendor} {product}\n'
                        f'SUBSYSTEM=="scsi_generic", '
                        f'ATTRS{{idVendor}}=="{vid:04x}", '
                        f'ATTRS{{idProduct}}=="{pid:04x}", '
                        f'MODE="0666"'
                    )

            rules_content = "\n\n".join(rules_lines) + "\n"

            # --- 2. usb-storage quirks (UAS bypass) ---
            quirk_entries = [f"{vid:04x}:{pid:04x}:u" for vid, pid in sorted(KNOWN_DEVICES)]
            quirks_param = ",".join(quirk_entries)

            # modprobe config (persistent across reboots)
            modprobe_path = "/etc/modprobe.d/trcc-lcd.conf"
            modprobe_content = (
                "# Thermalright LCD — force usb-storage bulk-only (bypass UAS)\n"
                "# Without this, devices are ignored and /dev/sgX is never created\n"
                "# Auto-generated by trcc setup-udev\n"
                f"options usb-storage quirks={quirks_param}\n"
            )

            if dry_run:
                print("=== udev rules ===")
                print(rules_content)
                print(f"# Would write to {rules_path}\n")
                print("=== usb-storage quirks ===")
                print(modprobe_content)
                print(f"# Would write to {modprobe_path}")
                return 0

            # Need root — re-exec with sudo automatically
            if os.geteuid() != 0:
                return _sudo_reexec("setup-udev")

            # Write udev rules
            with open(rules_path, "w") as f:
                f.write(rules_content)
            print(f"Wrote {rules_path}")

            # Write modprobe config
            with open(modprobe_path, "w") as f:
                f.write(modprobe_content)
            print(f"Wrote {modprobe_path}")

            # Apply quirks immediately (without reboot)
            quirks_sysfs = "/sys/module/usb_storage/parameters/quirks"
            if os.path.exists(quirks_sysfs):
                with open(quirks_sysfs, "w") as f:
                    f.write(quirks_param)
                print(f"Applied quirks: {quirks_param}")

            # Reload udev
            subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
            subprocess.run(["udevadm", "trigger"], check=False)
            print("\nDone. Unplug and replug the USB cable (or reboot if it's not easily accessible).")
            return 0

        except Exception as e:
            print(f"Error: {e}")
            return 1

    @staticmethod
    def install_desktop():
        """Install .desktop menu entry and icon for app launchers.

        Works from both pip install and git clone — generates .desktop inline
        and resolves icons from the package tree (src/trcc/assets/icons/).
        """
        import shutil
        from pathlib import Path

        home = Path.home()
        app_dir = home / ".local" / "share" / "applications"

        # Icons live inside the package (works for both pip install and git clone)
        icon_pkg_dir = Path(__file__).parent / "assets" / "icons"

        # Generate .desktop content inline (no dependency on repo root)
        desktop_content = """\
[Desktop Entry]
Name=TRCC Linux
Comment=Thermalright LCD Control Center
Exec=trcc gui
Icon=trcc
Terminal=false
Type=Application
Categories=Utility;System;
Keywords=thermalright;lcd;cooler;aio;cpu;
StartupWMClass=trcc-linux
"""

        # Install .desktop file
        app_dir.mkdir(parents=True, exist_ok=True)
        desktop_dst = app_dir / "trcc-linux.desktop"
        desktop_dst.write_text(desktop_content)
        print(f"Installed {desktop_dst}")

        # Install icons to XDG hicolor theme
        installed_icon = False
        for size in [256, 128, 64, 48]:
            icon_src = icon_pkg_dir / f"trcc_{size}x{size}.png"
            if icon_src.exists():
                icon_dir = home / ".local" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
                icon_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(icon_src, icon_dir / "trcc.png")
                installed_icon = True

        if installed_icon:
            # Update icon cache
            subprocess.run(
                ["gtk-update-icon-cache", str(home / ".local" / "share" / "icons" / "hicolor")],
                check=False, capture_output=True
            )
        else:
            print("Warning: icons not found, menu entry will use a generic icon")

        print("\nTRCC should now appear in your application menu.")
        print("If it doesn't show up immediately, log out and back in.")
        return 0

    @staticmethod
    def uninstall():
        """Remove all TRCC config, udev rules, autostart, and desktop files."""
        import shutil
        from pathlib import Path

        from trcc.conf import clear_installed_resolutions

        # Clear resolution markers before wiping config dir
        clear_installed_resolutions()

        home = Path.home()

        # Files that require root to remove
        root_files = [
            "/etc/udev/rules.d/99-trcc-lcd.rules",
            "/etc/modprobe.d/trcc-lcd.conf",
        ]

        # User files/dirs to remove
        user_items = [
            home / ".config" / "trcc",                          # config dir
            home / ".trcc",                                      # downloaded themes/web data
            home / ".config" / "autostart" / "trcc-linux.desktop",     # autostart
            home / ".local" / "share" / "applications" / "trcc-linux.desktop",  # desktop shortcut
            # Legacy filenames (pre-v2.0.2)
            home / ".config" / "autostart" / "trcc.desktop",
            home / ".local" / "share" / "applications" / "trcc.desktop",
        ]

        removed = []

        # Handle root files — auto-elevate with sudo if needed
        root_exists = [p for p in root_files if os.path.exists(p)]
        if root_exists and os.geteuid() != 0:
            print("Root files found — requesting sudo to remove...")
            result = _sudo_run(["rm", "-f"] + root_exists)
            if result.returncode == 0:
                removed.extend(root_exists)
                _sudo_run(["udevadm", "control", "--reload-rules"])
                _sudo_run(["udevadm", "trigger"])
        else:
            for path_str in root_exists:
                os.remove(path_str)
                removed.append(path_str)

        # Handle user files/dirs
        for path in user_items:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed.append(str(path))

        if removed:
            print("Removed:")
            for item in removed:
                print(f"  {item}")
        else:
            print("Nothing to remove — TRCC is already clean.")

        # Reload udev if we removed rules (and we're root — non-root already did it above)
        if os.geteuid() == 0 and any("udev" in r for r in removed):
            subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
            subprocess.run(["udevadm", "trigger"], check=False)

        # Uninstall the pip package itself
        print("\nUninstalling trcc-linux pip package...")
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "trcc-linux"],
            check=False,
        )

        return 0

    @staticmethod
    def report():
        """Generate a full diagnostic report for bug reports."""
        from trcc.debug_report import DebugReport

        rpt = DebugReport()
        rpt.collect()
        print(rpt)
        return 0

    @staticmethod
    def download_themes(pack=None, show_list=False, force=False, show_info=False):
        """Download theme packs (like spacy download)."""
        try:
            from trcc.theme_downloader import download_pack, list_available
            from trcc.theme_downloader import show_info as pack_info

            if show_list or pack is None:
                list_available()
                return 0

            if show_info:
                pack_info(pack)
                return 0

            if force:
                from trcc.conf import clear_installed_resolutions
                clear_installed_resolutions()

            return download_pack(pack, force=force)

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return 1


# =========================================================================
# Backward-compat aliases (pyproject.toml entry points + tests)
# =========================================================================

# Entry points (pyproject.toml console_scripts)
detect = DeviceCommands.detect
test_display = DisplayCommands.test
select_device = DeviceCommands.select

# Backward-compat for tests and external consumers
_probe_device = DeviceCommands._probe
_format_device = DeviceCommands._format
_ensure_extracted = DeviceCommands._ensure_extracted
_get_driver = DeviceCommands._get_driver
_get_service = DeviceCommands._get_service
send_image = DisplayCommands.send_image
send_color = DisplayCommands.send_color
reset_device = DisplayCommands.reset
resume = DisplayCommands.resume
show_info = SystemCommands.show_info
hid_debug = DiagCommands.hid_debug
led_debug = DiagCommands.led_debug
hr10_tempd = DiagCommands.hr10_tempd
setup_udev = SystemCommands.setup_udev
install_desktop = SystemCommands.install_desktop
uninstall = SystemCommands.uninstall
report = SystemCommands.report
download_themes = SystemCommands.download_themes
_hex_dump = DiagCommands._hex_dump
_hid_debug_lcd = DiagCommands._hid_debug_lcd
_hid_debug_led = DiagCommands._hid_debug_led




if __name__ == "__main__":
    sys.exit(main())
