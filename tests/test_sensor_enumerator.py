"""Tests for sensor_enumerator – hardware sensor discovery and reading."""

import unittest
from unittest.mock import MagicMock, patch

from trcc.sensor_enumerator import (
    _HWMON_DIVISORS,
    _HWMON_TYPES,
    SensorEnumerator,
    SensorInfo,
    _read_sysfs,
)

# ── _read_sysfs ─────────────────────────────────────────────────────────────

class TestReadSysfs(unittest.TestCase):

    @patch('trcc.sensor_enumerator.Path')
    def test_reads_and_strips(self, mock_path_cls):
        mock_path_cls.return_value.read_text.return_value = '  42000  \n'
        self.assertEqual(_read_sysfs('/fake/path'), '42000')

    @patch('trcc.sensor_enumerator.Path')
    def test_returns_none_on_error(self, mock_path_cls):
        mock_path_cls.return_value.read_text.side_effect = FileNotFoundError
        self.assertIsNone(_read_sysfs('/no/such/file'))


# ── SensorInfo ───────────────────────────────────────────────────────────────

class TestSensorInfo(unittest.TestCase):

    def test_fields(self):
        s = SensorInfo(
            id='hwmon:coretemp:temp1', name='CPU Package',
            category='temperature', unit='°C', source='hwmon'
        )
        self.assertEqual(s.id, 'hwmon:coretemp:temp1')
        self.assertEqual(s.source, 'hwmon')


# ── HWMON constants ──────────────────────────────────────────────────────────

class TestHwmonConstants(unittest.TestCase):

    def test_types_cover_expected(self):
        for key in ('temp', 'fan', 'in', 'power', 'freq'):
            self.assertIn(key, _HWMON_TYPES)

    def test_divisors_match_types(self):
        for key in _HWMON_TYPES:
            self.assertIn(key, _HWMON_DIVISORS)


# ── SensorEnumerator ────────────────────────────────────────────────────────

class TestSensorEnumeratorDiscover(unittest.TestCase):
    """Discovery methods with mocked sysfs."""

    def _make_enumerator(self):
        return SensorEnumerator()

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', False)
    @patch('trcc.sensor_enumerator.NVML_AVAILABLE', False)
    @patch('trcc.sensor_enumerator.Path')
    def test_discover_hwmon_basic(self, mock_path_cls):
        """Verify hwmon discovery parses driver name and inputs."""

        # Build a fake hwmon directory tree
        hwmon_base = MagicMock()
        hwmon_base.exists.return_value = True

        hwmon0 = MagicMock()
        hwmon0.name = 'hwmon0'
        hwmon0.__truediv__ = lambda self, key: MagicMock(
            # name file
            name=key
        )

        # Create fake input file
        temp1_input = MagicMock()
        temp1_input.name = 'temp1_input'

        hwmon0.glob.return_value = [temp1_input]
        hwmon_base.iterdir.return_value = [hwmon0]

        def path_side_effect(p):
            if p == '/sys/class/hwmon':
                return hwmon_base
            return MagicMock(read_text=MagicMock(return_value='coretemp'))

        mock_path_cls.side_effect = path_side_effect

        # The hwmon discovery is tightly coupled to Path — test via integration below
        # Here just verify the enumerator initializes cleanly
        enum = self._make_enumerator()
        self.assertEqual(enum.get_sensors(), [])

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', True)
    @patch('trcc.sensor_enumerator.NVML_AVAILABLE', False)
    def test_discover_psutil(self):
        """psutil sensors are always added when available."""
        enum = self._make_enumerator()
        # Manually call psutil discovery
        enum._discover_psutil()
        ids = [s.id for s in enum.get_sensors()]
        self.assertIn('psutil:cpu_percent', ids)
        self.assertIn('psutil:cpu_freq', ids)
        self.assertIn('psutil:mem_percent', ids)
        self.assertIn('psutil:mem_available', ids)

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', False)
    @patch('trcc.sensor_enumerator.NVML_AVAILABLE', False)
    def test_discover_psutil_unavailable(self):
        enum = self._make_enumerator()
        enum._discover_psutil()
        self.assertEqual(enum.get_sensors(), [])

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', True)
    @patch('trcc.sensor_enumerator.NVML_AVAILABLE', False)
    def test_discover_computed(self):
        enum = self._make_enumerator()
        enum._discover_computed()
        ids = [s.id for s in enum.get_sensors()]
        self.assertIn('computed:disk_read', ids)
        self.assertIn('computed:net_up', ids)
        self.assertIn('computed:net_down', ids)

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', False)
    @patch('trcc.sensor_enumerator.NVML_AVAILABLE', False)
    def test_discover_computed_no_psutil(self):
        enum = self._make_enumerator()
        enum._discover_computed()
        self.assertEqual(enum.get_sensors(), [])


class TestSensorEnumeratorGetters(unittest.TestCase):

    def test_get_by_category(self):
        enum = SensorEnumerator()
        enum._sensors = [
            SensorInfo('a', 'A', 'temperature', '°C', 'hwmon'),
            SensorInfo('b', 'B', 'fan', 'RPM', 'hwmon'),
            SensorInfo('c', 'C', 'temperature', '°C', 'nvidia'),
        ]
        temps = enum.get_by_category('temperature')
        self.assertEqual(len(temps), 2)
        fans = enum.get_by_category('fan')
        self.assertEqual(len(fans), 1)


class TestSensorEnumeratorReadHwmon(unittest.TestCase):

    @patch('trcc.sensor_enumerator._read_sysfs')
    def test_read_all_hwmon(self, mock_read):
        mock_read.return_value = '65000'

        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:coretemp:temp1': '/sys/class/hwmon/hwmon0/temp1_input'}
        enum._sensors = [
            SensorInfo('hwmon:coretemp:temp1', 'CPU', 'temperature', '°C', 'hwmon')
        ]

        readings = enum.read_all()
        self.assertAlmostEqual(readings['hwmon:coretemp:temp1'], 65.0)

    @patch('trcc.sensor_enumerator._read_sysfs', return_value='1500')
    def test_read_all_fan(self, _):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:it8688:fan1': '/sys/class/hwmon/hwmon3/fan1_input'}
        enum._sensors = [
            SensorInfo('hwmon:it8688:fan1', 'Fan', 'fan', 'RPM', 'hwmon')
        ]

        readings = enum.read_all()
        self.assertAlmostEqual(readings['hwmon:it8688:fan1'], 1500.0)

    @patch('trcc.sensor_enumerator._read_sysfs', return_value=None)
    def test_read_all_missing_value(self, _):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:x:temp1': '/fake'}
        readings = enum.read_all()
        self.assertNotIn('hwmon:x:temp1', readings)


class TestSensorEnumeratorReadOne(unittest.TestCase):

    @patch('trcc.sensor_enumerator._read_sysfs', return_value='72500')
    def test_read_one_hwmon(self, _):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:k10temp:temp1': '/fake'}
        val = enum.read_one('hwmon:k10temp:temp1')
        assert val is not None
        self.assertAlmostEqual(val, 72.5)

    @patch('trcc.sensor_enumerator._read_sysfs', return_value=None)
    def test_read_one_missing(self, _):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:k10temp:temp1': '/fake'}
        self.assertIsNone(enum.read_one('hwmon:k10temp:temp1'))


# ── RAPL reading ─────────────────────────────────────────────────────────────

class TestSensorEnumeratorReadRapl(unittest.TestCase):

    @patch('trcc.sensor_enumerator._read_sysfs')
    @patch('trcc.sensor_enumerator.time')
    def test_rapl_power_calculation(self, mock_time, mock_read):
        enum = SensorEnumerator()
        enum._rapl_paths = {'rapl:package-0': '/sys/class/powercap/intel-rapl:0/energy_uj'}

        # First call: seed the cache
        mock_time.monotonic.return_value = 1000.0
        mock_read.return_value = '10000000'  # 10 J in µJ
        readings1 = {}
        enum._read_rapl(readings1)
        self.assertNotIn('rapl:package-0', readings1)  # No delta yet

        # Second call: 1 second later, 15 J
        mock_time.monotonic.return_value = 1001.0
        mock_read.return_value = '15000000'  # 15 J in µJ
        readings2 = {}
        enum._read_rapl(readings2)
        # Delta = 5J / 1s = 5W
        self.assertAlmostEqual(readings2['rapl:package-0'], 5.0)


# ── psutil reading ───────────────────────────────────────────────────────────

class TestSensorEnumeratorReadPsutil(unittest.TestCase):

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', True)
    @patch('trcc.sensor_enumerator.psutil')
    def test_reads_cpu_and_memory(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 42.0
        mock_psutil.cpu_freq.return_value = MagicMock(current=3600.0)
        mock_psutil.virtual_memory.return_value = MagicMock(
            percent=55.0, available=8 * 1024 * 1024 * 1024
        )

        enum = SensorEnumerator()
        readings = {}
        enum._read_psutil(readings)

        self.assertAlmostEqual(readings['psutil:cpu_percent'], 42.0)
        self.assertAlmostEqual(readings['psutil:cpu_freq'], 3600.0)
        self.assertAlmostEqual(readings['psutil:mem_percent'], 55.0)

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', False)
    def test_noop_without_psutil(self):
        enum = SensorEnumerator()
        readings = {}
        enum._read_psutil(readings)
        self.assertEqual(readings, {})


# ── map_defaults ─────────────────────────────────────────────────────────────

class TestMapDefaults(unittest.TestCase):

    def test_returns_dict(self):
        # Reset global cache for clean test
        import trcc.sensor_enumerator as mod
        from trcc.sensor_enumerator import map_defaults
        mod._DEFAULT_MAP = None

        enum = SensorEnumerator()
        # Add some psutil sensors
        enum._sensors = [
            SensorInfo('psutil:cpu_percent', 'CPU Usage', 'usage', '%', 'psutil'),
            SensorInfo('psutil:cpu_freq', 'CPU Freq', 'clock', 'MHz', 'psutil'),
            SensorInfo('psutil:mem_percent', 'Mem Usage', 'usage', '%', 'psutil'),
            SensorInfo('psutil:mem_available', 'Mem Avail', 'other', 'MB', 'psutil'),
            SensorInfo('computed:disk_read', 'Disk Read', 'other', 'MB/s', 'computed'),
        ]

        mapping = map_defaults(enum)
        self.assertIsInstance(mapping, dict)
        self.assertEqual(mapping.get('cpu_percent'), 'psutil:cpu_percent')
        self.assertEqual(mapping.get('disk_read'), 'computed:disk_read')

        # Clean up global
        mod._DEFAULT_MAP = None


# ── discover() end-to-end ────────────────────────────────────────────────────

class TestDiscoverEndToEnd(unittest.TestCase):

    @patch.object(SensorEnumerator, '_discover_computed')
    @patch.object(SensorEnumerator, '_discover_rapl')
    @patch.object(SensorEnumerator, '_discover_psutil')
    @patch.object(SensorEnumerator, '_discover_nvidia')
    @patch.object(SensorEnumerator, '_discover_hwmon')
    def test_discover_calls_all_sub_discoveries(self, hw, nv, ps, rapl, comp):
        enum = SensorEnumerator()
        result = enum.discover()
        hw.assert_called_once()
        nv.assert_called_once()
        ps.assert_called_once()
        rapl.assert_called_once()
        comp.assert_called_once()
        self.assertEqual(result, [])

    @patch.object(SensorEnumerator, '_discover_computed')
    @patch.object(SensorEnumerator, '_discover_rapl')
    @patch.object(SensorEnumerator, '_discover_psutil')
    @patch.object(SensorEnumerator, '_discover_nvidia')
    @patch.object(SensorEnumerator, '_discover_hwmon')
    def test_discover_resets_state(self, *_):
        enum = SensorEnumerator()
        enum._sensors = [SensorInfo('old', 'Old', 'temp', '°C', 'hwmon')]
        enum._hwmon_paths = {'old': '/fake'}
        enum.discover()
        self.assertEqual(len(enum._sensors), 0)
        self.assertEqual(len(enum._hwmon_paths), 0)


# ── _discover_hwmon ──────────────────────────────────────────────────────────

class TestDiscoverHwmon(unittest.TestCase):

    @patch('trcc.sensor_enumerator._read_sysfs')
    @patch('trcc.sensor_enumerator.Path')
    def test_discovers_temp_and_fan(self, mock_path_cls, mock_sysfs):
        from pathlib import PurePosixPath

        hwmon_base = MagicMock()
        hwmon_base.exists.return_value = True

        hwmon0 = MagicMock()
        hwmon0.name = 'hwmon0'

        # Use PurePosixPath so sorted() works (has __lt__)
        temp_file = PurePosixPath('/sys/class/hwmon/hwmon0/temp1_input')
        fan_file = PurePosixPath('/sys/class/hwmon/hwmon0/fan1_input')
        hwmon0.glob.return_value = [temp_file, fan_file]
        hwmon0.__truediv__ = lambda self, x: MagicMock(
            __str__=lambda s: f'/sys/class/hwmon/hwmon0/{x}')

        hwmon_base.iterdir.return_value = [hwmon0]

        def path_side(arg):
            if arg == '/sys/class/hwmon':
                return hwmon_base
            return MagicMock()
        mock_path_cls.side_effect = path_side

        def sysfs_side(path):
            if 'name' in str(path):
                return 'k10temp'
            if 'label' in str(path):
                return None
            return '55000'
        mock_sysfs.side_effect = sysfs_side

        enum = SensorEnumerator()
        enum._discover_hwmon()
        self.assertGreaterEqual(len(enum._sensors), 2)
        ids = [s.id for s in enum._sensors]
        self.assertTrue(any('temp1' in sid for sid in ids))
        self.assertTrue(any('fan1' in sid for sid in ids))


# ── _discover_rapl ───────────────────────────────────────────────────────────

class TestDiscoverRapl(unittest.TestCase):

    @patch('trcc.sensor_enumerator._read_sysfs')
    @patch('trcc.sensor_enumerator.Path')
    def test_discovers_rapl_domain(self, mock_path_cls, mock_sysfs):
        rapl_base = MagicMock()
        rapl_base.exists.return_value = True

        rapl_dir = MagicMock()
        rapl_dir.name = 'intel-rapl:0'
        energy_uj = MagicMock()
        energy_uj.exists.return_value = True
        name_file = MagicMock()

        rapl_dir.__truediv__ = lambda self, x: (
            energy_uj if x == 'energy_uj' else name_file)
        rapl_base.glob.return_value = [rapl_dir]

        def path_side(arg):
            if 'powercap' in str(arg):
                return rapl_base
            return MagicMock()
        mock_path_cls.side_effect = path_side
        mock_sysfs.return_value = 'package-0'

        enum = SensorEnumerator()
        enum._discover_rapl()
        self.assertEqual(len(enum._sensors), 1)
        self.assertEqual(enum._sensors[0].source, 'rapl')
        self.assertIn('package-0', enum._sensors[0].id)

    @patch('trcc.sensor_enumerator._read_sysfs')
    @patch('trcc.sensor_enumerator.Path')
    def test_skips_sub_zones(self, mock_path_cls, mock_sysfs):
        rapl_base = MagicMock()
        rapl_base.exists.return_value = True

        sub_zone = MagicMock()
        sub_zone.name = 'intel-rapl:0:0'  # Sub-zone (has extra colon)
        rapl_base.glob.return_value = [sub_zone]

        mock_path_cls.return_value = rapl_base

        enum = SensorEnumerator()
        enum._discover_rapl()
        self.assertEqual(len(enum._sensors), 0)


# ── read_all hwmon edge cases ────────────────────────────────────────────────

class TestReadAllEdgeCases(unittest.TestCase):

    def test_unknown_prefix_returns_raw(self):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:test:custom1': '/fake/custom1_input'}
        with patch('trcc.sensor_enumerator._read_sysfs', return_value='123'):
            readings = enum.read_all()
        # 'custom1' doesn't start with temp/fan/in/power/freq → raw value
        self.assertEqual(readings['hwmon:test:custom1'], 123.0)

    def test_hwmon_value_error(self):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:test:temp1': '/fake/temp1_input'}
        with patch('trcc.sensor_enumerator._read_sysfs', return_value='not-a-number'):
            readings = enum.read_all()
        self.assertNotIn('hwmon:test:temp1', readings)


# ── read_one edge cases ──────────────────────────────────────────────────────

class TestReadOneEdgeCases(unittest.TestCase):

    def test_falls_through_to_read_all(self):
        enum = SensorEnumerator()
        # Sensor not in _hwmon_paths → falls through to read_all
        with patch.object(enum, 'read_all', return_value={'psutil:cpu_percent': 42.0}):
            result = enum.read_one('psutil:cpu_percent')
        self.assertEqual(result, 42.0)

    def test_hwmon_value_error_returns_none(self):
        enum = SensorEnumerator()
        enum._hwmon_paths = {'hwmon:test:temp1': '/fake/path'}
        with patch('trcc.sensor_enumerator._read_sysfs', return_value='bad'):
            result = enum.read_one('hwmon:test:temp1')
        self.assertIsNone(result)


# ── _read_computed ───────────────────────────────────────────────────────────

class TestReadComputed(unittest.TestCase):

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', True)
    @patch('trcc.sensor_enumerator.psutil')
    @patch('trcc.sensor_enumerator.time')
    def test_disk_delta(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 101.0
        mock_psutil.disk_io_counters.return_value = MagicMock(
            read_bytes=10 * 1024 * 1024,
            write_bytes=5 * 1024 * 1024,
            busy_time=500,
        )
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=1024, bytes_recv=2048)

        enum = SensorEnumerator()
        enum._disk_prev = (MagicMock(
            read_bytes=0, write_bytes=0, busy_time=0), 100.0)

        readings = {}
        enum._read_computed(readings)
        self.assertIn('computed:disk_read', readings)
        self.assertAlmostEqual(readings['computed:disk_read'], 10.0, delta=0.1)
        self.assertIn('computed:disk_activity', readings)

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', True)
    @patch('trcc.sensor_enumerator.psutil')
    @patch('trcc.sensor_enumerator.time')
    def test_network_delta(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 101.0
        mock_psutil.disk_io_counters.return_value = None
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=1024 * 100, bytes_recv=1024 * 500)

        enum = SensorEnumerator()
        enum._net_prev = (MagicMock(
            bytes_sent=0, bytes_recv=0), 100.0)

        readings = {}
        enum._read_computed(readings)
        self.assertIn('computed:net_up', readings)
        self.assertAlmostEqual(readings['computed:net_up'], 100.0, delta=1.0)

    @patch('trcc.sensor_enumerator.PSUTIL_AVAILABLE', False)
    def test_no_psutil_returns_nothing(self):
        enum = SensorEnumerator()
        readings = {}
        enum._read_computed(readings)
        self.assertEqual(readings, {})


# ── map_defaults with fans and GPU ───────────────────────────────────────────

class TestMapDefaultsFull(unittest.TestCase):

    def test_fan_sensor_mapping(self):
        import trcc.sensor_enumerator as mod
        from trcc.sensor_enumerator import map_defaults
        mod._DEFAULT_MAP = None

        enum = SensorEnumerator()
        enum._sensors = [
            SensorInfo('hwmon:nct:fan1', 'NCT Fan1', 'fan', 'RPM', 'hwmon'),
            SensorInfo('hwmon:nct:fan2', 'NCT Fan2', 'fan', 'RPM', 'hwmon'),
        ]
        mapping = map_defaults(enum)
        self.assertEqual(mapping.get('fan_cpu'), 'hwmon:nct:fan1')
        self.assertEqual(mapping.get('fan_gpu'), 'hwmon:nct:fan2')
        mod._DEFAULT_MAP = None

    def test_cached_second_call(self):
        import trcc.sensor_enumerator as mod
        from trcc.sensor_enumerator import map_defaults
        mod._DEFAULT_MAP = None

        enum = SensorEnumerator()
        enum._sensors = []
        first = map_defaults(enum)
        second = map_defaults(enum)
        self.assertIs(first, second)
        mod._DEFAULT_MAP = None


if __name__ == '__main__':
    unittest.main()
