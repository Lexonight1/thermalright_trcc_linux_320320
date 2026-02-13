"""Tests verifying OOP design patterns from CLAUDE.md.

Validates that the hexagonal architecture patterns are correctly implemented:
- Dependency Injection
- Observer Pattern (Callbacks)
- Factory Pattern
- Strategy Pattern
- Data Transfer Objects (DTOs)
- Service isolation (no Qt dependencies)
"""
from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from trcc.core.controllers import (
    DeviceController,
    LCDDeviceController,
    LEDController,
    OverlayController,
    ThemeController,
    VideoController,
    create_controller,
)
from trcc.core.models import (
    DeviceInfo,
    ThemeData,
    ThemeInfo,
    VideoState,
)
from trcc.services.device import DeviceService
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.media import MediaService
from trcc.services.overlay import OverlayService
from trcc.services.theme import ThemeService

SERVICES_DIR = Path(__file__).resolve().parent.parent / 'src' / 'trcc' / 'services'


# =============================================================================
# Dependency Injection — services are injectable, not hardcoded
# =============================================================================


class TestDependencyInjection(unittest.TestCase):
    """Controllers accept injected services — never create their own."""

    def test_theme_controller_accepts_injected_service(self):
        """ThemeController uses the injected ThemeService, not a new one."""
        svc = ThemeService()
        ctrl = ThemeController(svc)
        self.assertIs(ctrl.svc, svc)

    def test_device_controller_accepts_injected_service(self):
        svc = DeviceService()
        ctrl = DeviceController(svc)
        self.assertIs(ctrl.svc, svc)

    def test_video_controller_accepts_injected_service(self):
        svc = MediaService()
        ctrl = VideoController(svc)
        self.assertIs(ctrl.svc, svc)

    def test_overlay_controller_accepts_injected_service(self):
        svc = OverlayService()
        ctrl = OverlayController(svc)
        self.assertIs(ctrl.svc, svc)

    def test_display_service_accepts_injected_sub_services(self):
        """DisplayService receives DeviceService, OverlayService, MediaService."""
        dev = DeviceService()
        ovl = OverlayService()
        med = MediaService()
        svc = DisplayService(dev, ovl, med)
        self.assertIs(svc.devices, dev)
        self.assertIs(svc.overlay, ovl)
        self.assertIs(svc.media, med)

    def test_controllers_default_to_fresh_service(self):
        """When no service injected, controllers create their own."""
        self.assertIsInstance(ThemeController().svc, ThemeService)
        self.assertIsInstance(DeviceController().svc, DeviceService)
        self.assertIsInstance(VideoController().svc, MediaService)
        self.assertIsInstance(OverlayController().svc, OverlayService)

    @patch('trcc.services.display.ensure_all_data')
    def test_shared_services_across_controllers(self, _):
        """LCDDeviceController shares service instances with sub-controllers."""
        ctrl = LCDDeviceController()
        # Sub-controllers reference the same service objects as DisplayService
        self.assertIs(ctrl.devices.svc, ctrl._display.devices)
        self.assertIs(ctrl.overlay.svc, ctrl._display.overlay)
        self.assertIs(ctrl.video.svc, ctrl._display.media)


# =============================================================================
# Observer Pattern — callbacks fire on state changes
# =============================================================================


class TestObserverPattern(unittest.TestCase):
    """Controllers broadcast state changes via callbacks (Observer pattern)."""

    def test_theme_controller_fires_on_theme_selected(self):
        ctrl = ThemeController()
        fired = []
        ctrl.on_theme_selected = lambda t: fired.append(t)
        theme = ThemeInfo(name='test')
        ctrl.select_theme(theme)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].name, 'test')

    def test_theme_controller_fires_on_filter_changed(self):
        ctrl = ThemeController()
        fired = []
        ctrl.on_filter_changed = lambda m: fired.append(m)
        ctrl.set_filter('user')
        self.assertEqual(fired, ['user'])

    def test_device_controller_fires_on_devices_changed(self):
        svc = DeviceService()
        ctrl = DeviceController(svc)
        fired = []
        ctrl.on_devices_changed = lambda devs: fired.append(devs)
        with patch.object(svc, 'detect', return_value=[]):
            ctrl.detect_devices()
        self.assertEqual(len(fired), 1)

    def test_device_controller_fires_on_device_selected(self):
        ctrl = DeviceController()
        fired = []
        ctrl.on_device_selected = lambda d: fired.append(d)
        dev = DeviceInfo(name='test', path='/dev/sg0')
        ctrl.select_device(dev)
        self.assertEqual(len(fired), 1)

    def test_overlay_controller_fires_on_config_changed(self):
        ctrl = OverlayController()
        fired = []
        ctrl.on_config_changed = lambda: fired.append(True)
        ctrl.set_config({'elements': []})
        self.assertEqual(len(fired), 1)

    def test_no_callback_no_crash(self):
        """When no callback registered, operations don't raise."""
        ctrl = ThemeController()
        ctrl.select_theme(ThemeInfo(name='test'))  # no on_theme_selected set
        ctrl.set_filter('all')                     # no on_filter_changed set

    def test_led_controller_observer_wiring(self):
        """LEDController wires model callbacks to its own."""
        ctrl = LEDController()
        fired = []
        ctrl.on_state_changed = lambda s: fired.append(s)
        # Trigger model state change
        ctrl.set_color(255, 0, 0)
        self.assertTrue(len(fired) > 0)


# =============================================================================
# Factory Pattern — centralized instantiation
# =============================================================================


class TestFactoryPattern(unittest.TestCase):
    """Factory methods create fully wired object graphs."""

    @patch('trcc.services.display.ensure_all_data')
    def test_create_controller_returns_wired_graph(self, _):
        """create_controller() builds the complete controller tree."""
        ctrl = create_controller()
        self.assertIsInstance(ctrl, LCDDeviceController)
        self.assertIsInstance(ctrl.themes, ThemeController)
        self.assertIsInstance(ctrl.devices, DeviceController)
        self.assertIsInstance(ctrl.video, VideoController)
        self.assertIsInstance(ctrl.overlay, OverlayController)

    @patch('trcc.services.display.ensure_all_data')
    def test_create_controller_callbacks_wired(self, _):
        """Factory wires internal callbacks between sub-controllers."""
        ctrl = create_controller()
        # _on_theme_selected, _on_video_frame, _on_device_selected
        self.assertIsNotNone(ctrl.themes.on_theme_selected)
        self.assertIsNotNone(ctrl.video.on_frame_ready)
        self.assertIsNotNone(ctrl.devices.on_device_selected)


# =============================================================================
# Strategy Pattern — swappable behavior based on context
# =============================================================================


class TestStrategyPattern(unittest.TestCase):
    """Algorithms swap dynamically based on device/resolution context."""

    def test_byte_order_strategy_scsi_320(self):
        """SCSI 320x320 uses big-endian (Windows ImageTo565 compat)."""
        self.assertEqual(ImageService.byte_order_for('scsi', (320, 320)), '>')

    def test_byte_order_strategy_scsi_480(self):
        """SCSI non-320 uses little-endian."""
        self.assertEqual(ImageService.byte_order_for('scsi', (480, 480)), '<')

    def test_byte_order_strategy_hid(self):
        """HID always uses big-endian regardless of resolution."""
        self.assertEqual(ImageService.byte_order_for('hid', (480, 480)), '>')
        self.assertEqual(ImageService.byte_order_for('hid', (320, 320)), '>')

    def test_rotation_strategy_0(self):
        img = Image.new('RGB', (4, 8))
        result = ImageService.apply_rotation(img, 0)
        self.assertEqual(result.size, (4, 8))

    def test_rotation_strategy_90(self):
        img = Image.new('RGB', (4, 8))
        result = ImageService.apply_rotation(img, 90)
        self.assertEqual(result.size, (8, 4))

    def test_rotation_strategy_180(self):
        img = Image.new('RGB', (4, 8))
        result = ImageService.apply_rotation(img, 180)
        self.assertEqual(result.size, (4, 8))

    def test_rotation_strategy_270(self):
        img = Image.new('RGB', (4, 8))
        result = ImageService.apply_rotation(img, 270)
        self.assertEqual(result.size, (8, 4))

    def test_brightness_strategy_100_noop(self):
        """100% brightness returns the same object (no processing)."""
        img = Image.new('RGB', (2, 2), (200, 100, 50))
        result = ImageService.apply_brightness(img, 100)
        self.assertIs(result, img)

    def test_brightness_strategy_50_darkens(self):
        img = Image.new('RGB', (1, 1), (200, 100, 50))
        result = ImageService.apply_brightness(img, 50)
        self.assertLess(result.getpixel((0, 0))[0], 200)

    def test_theme_filter_strategy_all(self):
        """'all' filter passes everything."""
        theme = ThemeInfo(name='anything')
        self.assertTrue(ThemeService._passes_filter(theme, 'all'))

    def test_theme_filter_strategy_user(self):
        """'user' filter passes Custom_ prefix."""
        theme = ThemeInfo(name='Custom_foo')
        self.assertTrue(ThemeService._passes_filter(theme, 'user'))

    def test_theme_filter_strategy_default_excludes_custom(self):
        """'default' filter excludes Custom_ prefix."""
        theme = ThemeInfo(name='Custom_foo')
        self.assertFalse(ThemeService._passes_filter(theme, 'default'))


# =============================================================================
# Data Transfer Objects — pure dataclasses, no logic
# =============================================================================


class TestDTOs(unittest.TestCase):
    """DTOs are strictly defined structures for cross-boundary data."""

    def test_theme_data_is_dataclass(self):
        """ThemeData is a dataclass with known fields."""
        field_names = {f.name for f in fields(ThemeData)}
        expected = {'background', 'animation_path', 'is_animated',
                    'mask', 'mask_position', 'mask_source_dir'}
        self.assertEqual(field_names, expected)

    def test_theme_data_defaults(self):
        """ThemeData defaults are all None/False — no surprise state."""
        data = ThemeData()
        self.assertIsNone(data.background)
        self.assertIsNone(data.animation_path)
        self.assertFalse(data.is_animated)
        self.assertIsNone(data.mask)
        self.assertIsNone(data.mask_position)
        self.assertIsNone(data.mask_source_dir)

    def test_theme_info_is_dataclass(self):
        field_names = {f.name for f in fields(ThemeInfo)}
        self.assertIn('name', field_names)
        self.assertIn('path', field_names)

    def test_device_info_is_dataclass(self):
        field_names = {f.name for f in fields(DeviceInfo)}
        self.assertIn('name', field_names)
        self.assertIn('path', field_names)
        self.assertIn('protocol', field_names)

    def test_video_state_is_dataclass(self):
        field_names = {f.name for f in fields(VideoState)}
        self.assertIn('current_frame', field_names)
        self.assertIn('total_frames', field_names)
        self.assertIn('fps', field_names)

    def test_theme_data_lives_in_models(self):
        """ThemeData is in core.models, not in services."""
        from trcc.core import models
        self.assertTrue(hasattr(models, 'ThemeData'))

    def test_device_info_lives_in_models(self):
        from trcc.core import models
        self.assertTrue(hasattr(models, 'DeviceInfo'))


# =============================================================================
# Service Isolation — no Qt/GUI dependencies in services
# =============================================================================


class TestServiceIsolation(unittest.TestCase):
    """Services are pure Python — no Qt/PySide6/PyQt6 imports."""

    def _get_imports(self, filepath: Path) -> set[str]:
        """Parse a Python file and return all imported module names."""
        source = filepath.read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        return imports

    def test_no_qt_in_services(self):
        """No service file imports PySide6 or PyQt6."""
        qt_modules = {'PySide6', 'PyQt6', 'PyQt5'}
        for py_file in SERVICES_DIR.glob('*.py'):
            imports = self._get_imports(py_file)
            offenders = imports & qt_modules
            self.assertEqual(
                offenders, set(),
                f"{py_file.name} imports Qt: {offenders}")

    def test_no_qt_in_models(self):
        """Models are pure dataclasses — no Qt."""
        models_path = SERVICES_DIR.parent / 'core' / 'models.py'
        qt_modules = {'PySide6', 'PyQt6', 'PyQt5'}
        imports = self._get_imports(models_path)
        offenders = imports & qt_modules
        self.assertEqual(offenders, set(),
                         f"models.py imports Qt: {offenders}")

    def test_services_init_exports(self):
        """services/__init__.py exports all 6 services."""
        from trcc import services
        expected = {'DeviceService', 'DisplayService', 'ImageService',
                    'MediaService', 'OverlayService', 'ThemeService'}
        for name in expected:
            self.assertTrue(
                hasattr(services, name),
                f"services missing export: {name}")


# =============================================================================
# Controller Thinness — controllers delegate, don't compute
# =============================================================================


class TestControllerThinness(unittest.TestCase):
    """Controllers are thin waiters — call service, fire callback."""

    def test_theme_controller_delegates_filter(self):
        svc = MagicMock(spec=ThemeService)
        ctrl = ThemeController(svc)
        ctrl.set_filter('user')
        svc.set_filter.assert_called_once_with('user')

    def test_theme_controller_delegates_select(self):
        svc = MagicMock(spec=ThemeService)
        ctrl = ThemeController(svc)
        theme = ThemeInfo(name='test')
        ctrl.select_theme(theme)
        svc.select.assert_called_once_with(theme)

    def test_device_controller_delegates_detect(self):
        svc = MagicMock(spec=DeviceService)
        svc.devices = []
        svc.selected = None
        ctrl = DeviceController(svc)
        ctrl.detect_devices()
        svc.detect.assert_called_once()

    def test_video_controller_delegates_play(self):
        svc = MagicMock(spec=MediaService)
        ctrl = VideoController(svc)
        ctrl.play()
        svc.play.assert_called_once()

    def test_video_controller_delegates_pause(self):
        svc = MagicMock(spec=MediaService)
        ctrl = VideoController(svc)
        ctrl.pause()
        svc.pause.assert_called_once()

    def test_video_controller_delegates_stop(self):
        svc = MagicMock(spec=MediaService)
        ctrl = VideoController(svc)
        ctrl.stop()
        svc.stop.assert_called_once()

    def test_overlay_controller_delegates_enable(self):
        svc = OverlayService()
        ctrl = OverlayController(svc)
        ctrl.enable(True)
        self.assertTrue(svc.enabled)

    def test_overlay_controller_delegates_render(self):
        svc = MagicMock(spec=OverlayService)
        ctrl = OverlayController(svc)
        ctrl.render(force=True)
        svc.render.assert_called_once()


# =============================================================================
# Service Statelessness — stateless services have only static methods
# =============================================================================


class TestServiceStatelessness(unittest.TestCase):
    """Stateless services (ImageService) use only static methods."""

    def test_image_service_all_static(self):
        """Every public method on ImageService is @staticmethod."""
        for name, method in inspect.getmembers(ImageService, predicate=inspect.isfunction):
            if not name.startswith('_'):
                self.assertTrue(
                    isinstance(inspect.getattr_static(ImageService, name), staticmethod),
                    f"ImageService.{name} should be @staticmethod")

    def test_image_service_no_init_state(self):
        """ImageService has no __init__ — fully stateless."""
        # ImageService inherits object.__init__, has no custom state
        svc = ImageService()
        self.assertEqual(len(svc.__dict__), 0)


if __name__ == '__main__':
    unittest.main()
