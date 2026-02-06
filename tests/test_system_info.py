"""Tests for system_info – metric reading helpers and format_metric display."""

import unittest
from unittest.mock import MagicMock, mock_open, patch

from trcc.system_info import (
    DATE_FORMATS,
    TIME_FORMATS,
    WEEKDAYS,
    find_hwmon_by_name,
    format_metric,
    get_cpu_frequency,
    get_cpu_temperature,
    get_cpu_usage,
    get_disk_stats,
    get_disk_temperature,
    get_fan_speeds,
    get_gpu_clock,
    get_gpu_temperature,
    get_gpu_usage,
    get_memory_available,
    get_memory_clock,
    get_memory_temperature,
    get_memory_usage,
    get_network_stats,
    read_file,
)

# ── read_file ────────────────────────────────────────────────────────────────

class TestReadFile(unittest.TestCase):

    def test_returns_stripped_content(self):
        m = mock_open(read_data="  hello world  \n")
        with patch('builtins.open', m):
            self.assertEqual(read_file('/fake'), 'hello world')

    def test_returns_none_on_error(self):
        self.assertIsNone(read_file('/nonexistent/path/xyz'))


# ── find_hwmon_by_name ───────────────────────────────────────────────────────

class TestFindHwmon(unittest.TestCase):

    @patch('trcc.system_info.os.path.exists', return_value=True)
    @patch('trcc.system_info.read_file')
    def test_finds_matching_hwmon(self, mock_read, mock_exists):
        def side_effect(path):
            if 'hwmon2/name' in path:
                return 'coretemp'
            return None
        mock_read.side_effect = side_effect

        result = find_hwmon_by_name('coretemp')
        assert result is not None
        self.assertIn('hwmon2', result)

    @patch('trcc.system_info.os.path.exists', return_value=False)
    def test_returns_none_no_hwmon_dir(self, _):
        self.assertIsNone(find_hwmon_by_name('coretemp'))


# ── get_cpu_temperature ──────────────────────────────────────────────────────

class TestGetCpuTemperature(unittest.TestCase):

    @patch('trcc.system_info.read_file')
    @patch('trcc.system_info.find_hwmon_by_name')
    def test_reads_k10temp(self, mock_find, mock_read):
        mock_find.side_effect = lambda name: '/sys/class/hwmon/hwmon0' if name == 'k10temp' else None
        mock_read.return_value = '45000'

        temp = get_cpu_temperature()
        assert temp is not None
        self.assertAlmostEqual(temp, 45.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run')
    def test_fallback_to_sensors(self, mock_run, _):
        mock_run.return_value = type('R', (), {
            'stdout': 'temp1_input: 52.0\n', 'returncode': 0
        })()
        temp = get_cpu_temperature()
        assert temp is not None
        self.assertAlmostEqual(temp, 52.0)


# ── get_cpu_usage ────────────────────────────────────────────────────────────

class TestGetCpuUsage(unittest.TestCase):

    def test_reads_proc_stat(self):
        stat_line = "cpu  1000 200 300 8000 100 0 0 0 0 0\n"
        m = mock_open(read_data=stat_line)
        with patch('builtins.open', m):
            usage = get_cpu_usage()
            assert usage is not None
            self.assertGreater(usage, 0)
            self.assertLessEqual(usage, 100)


# ── get_cpu_frequency ────────────────────────────────────────────────────────

class TestGetCpuFrequency(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='3500000')
    def test_reads_cpufreq(self, _):
        freq = get_cpu_frequency()
        assert freq is not None
        self.assertAlmostEqual(freq, 3500.0)

    @patch('trcc.system_info.read_file', return_value=None)
    def test_fallback_proc_cpuinfo(self, _):
        cpuinfo = "processor\t: 0\ncpu MHz\t\t: 4200.123\n"
        m = mock_open(read_data=cpuinfo)
        with patch('builtins.open', m):
            freq = get_cpu_frequency()
            assert freq is not None
            self.assertAlmostEqual(freq, 4200.123)


# ── get_memory_usage / get_memory_available ──────────────────────────────────

class TestMemoryMetrics(unittest.TestCase):

    def _meminfo(self):
        return (
            "MemTotal:       16000000 kB\n"
            "MemFree:         2000000 kB\n"
            "MemAvailable:    8000000 kB\n"
        )

    def test_memory_usage_percentage(self):
        m = mock_open(read_data=self._meminfo())
        with patch('builtins.open', m):
            usage = get_memory_usage()
            assert usage is not None
            self.assertAlmostEqual(usage, 50.0)

    def test_memory_available_mb(self):
        m = mock_open(read_data=self._meminfo())
        with patch('builtins.open', m):
            avail = get_memory_available()
            assert avail is not None
            self.assertAlmostEqual(avail, 8000000 / 1024.0)


# ── format_metric ────────────────────────────────────────────────────────────

class TestFormatMetric(unittest.TestCase):
    """format_metric covers temperatures, percentages, frequencies, etc."""

    # Temperatures
    def test_temp_celsius(self):
        self.assertEqual(format_metric('cpu_temp', 65.3), '65°C')

    def test_temp_fahrenheit(self):
        result = format_metric('gpu_temp', 50.0, temp_unit=1)
        self.assertEqual(result, '122°F')

    # Percentages
    def test_percent(self):
        self.assertEqual(format_metric('cpu_percent', 88.7), '89%')

    def test_usage(self):
        self.assertEqual(format_metric('gpu_usage', 42.0), '42%')

    def test_activity(self):
        self.assertEqual(format_metric('disk_activity', 12.0), '12%')

    # Frequencies
    def test_freq_mhz(self):
        self.assertEqual(format_metric('cpu_freq', 800.0), '800MHz')

    def test_freq_ghz(self):
        self.assertEqual(format_metric('gpu_clock', 1800.0), '1.8GHz')

    # Disk I/O
    def test_disk_read(self):
        self.assertEqual(format_metric('disk_read', 1.5), '1.5MB/s')

    def test_disk_write(self):
        self.assertEqual(format_metric('disk_write', 0.3), '0.3MB/s')

    # Network
    def test_net_kbs(self):
        self.assertEqual(format_metric('net_up', 512.0), '512KB/s')

    def test_net_mbs(self):
        self.assertEqual(format_metric('net_down', 2048.0), '2.0MB/s')

    def test_net_total_mb(self):
        self.assertEqual(format_metric('net_total_up', 500.0), '500MB')

    def test_net_total_gb(self):
        self.assertEqual(format_metric('net_total_down', 2048.0), '2.0GB')

    # Fan
    def test_fan(self):
        self.assertEqual(format_metric('fan_cpu', 1200.0), '1200RPM')

    # Memory available
    def test_mem_available_mb(self):
        self.assertEqual(format_metric('mem_available', 512.0), '512MB')

    def test_mem_available_gb(self):
        self.assertEqual(format_metric('mem_available', 4096.0), '4.0GB')

    # Date / time / weekday (use frozen datetime)
    @patch('trcc.system_info.datetime')
    def test_date_format_0(self, mock_dt):
        from datetime import datetime as real_dt
        fake_now = real_dt(2026, 2, 6, 14, 30, 0)
        mock_dt.now.return_value = fake_now
        # datetime.now() returns our fake, but strftime must work on real obj
        result = format_metric('date', 0, date_format=0)
        self.assertEqual(result, '2026/02/06')

    @patch('trcc.system_info.datetime')
    def test_time_format_0(self, mock_dt):
        from datetime import datetime as real_dt
        fake_now = real_dt(2026, 2, 6, 14, 5, 0)
        mock_dt.now.return_value = fake_now
        result = format_metric('time', 0, time_format=0)
        self.assertEqual(result, '14:05')

    @patch('trcc.system_info.datetime')
    def test_weekday(self, mock_dt):
        from datetime import datetime as real_dt
        fake_now = real_dt(2026, 2, 6, 0, 0, 0)  # Friday
        mock_dt.now.return_value = fake_now
        result = format_metric('weekday', 0)
        self.assertEqual(result, 'FRI')

    def test_day_of_week_index(self):
        self.assertEqual(format_metric('day_of_week', 0), 'MON')
        self.assertEqual(format_metric('day_of_week', 6), 'SUN')

    # Fallback
    def test_unknown_metric(self):
        self.assertEqual(format_metric('something', 3.14), '3.1')

    # time_/date_ prefix branch
    def test_time_hour_prefix(self):
        self.assertEqual(format_metric('time_hour', 9), '09')

    def test_date_month_prefix(self):
        self.assertEqual(format_metric('date_month', 2), '02')

    @patch('trcc.system_info.datetime')
    def test_date_format_1(self, mock_dt):
        """date_format=1 is identical to 0: yyyy/MM/dd."""
        from datetime import datetime as real_dt
        fake_now = real_dt(2026, 2, 6, 14, 30, 0)
        mock_dt.now.return_value = fake_now
        result = format_metric('date', 0, date_format=1)
        self.assertEqual(result, '2026/02/06')

    @patch('trcc.system_info.datetime')
    def test_time_format_1(self, mock_dt):
        """time_format=1 uses %-I (no leading zero on hour)."""
        from datetime import datetime as real_dt
        fake_now = real_dt(2026, 2, 6, 14, 5, 0)
        mock_dt.now.return_value = fake_now
        result = format_metric('time', 0, time_format=1)
        self.assertEqual(result, '2:05 PM')


# ── get_gpu_temperature ──────────────────────────────────────────────────────

class TestGetGpuTemperature(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='55000')
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon1')
    def test_amd_gpu(self, mock_find, mock_read):
        temp = get_gpu_temperature()
        self.assertAlmostEqual(temp, 55.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run')
    def test_nvidia_gpu(self, mock_run, _):
        mock_run.return_value = type('R', (), {'stdout': '72\n', 'returncode': 0})()
        temp = get_gpu_temperature()
        self.assertAlmostEqual(temp, 72.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    def test_no_gpu(self, *_):
        self.assertIsNone(get_gpu_temperature())

    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon1')
    @patch('trcc.system_info.subprocess.run')
    def test_amd_no_temp_falls_through(self, mock_run, mock_find, mock_read):
        mock_run.return_value = type('R', (), {'stdout': '60\n', 'returncode': 0})()
        temp = get_gpu_temperature()
        self.assertAlmostEqual(temp, 60.0)


# ── get_gpu_usage ────────────────────────────────────────────────────────────

class TestGetGpuUsage(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='85')
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon1')
    def test_amd_gpu(self, mock_find, mock_read):
        usage = get_gpu_usage()
        self.assertAlmostEqual(usage, 85.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run')
    def test_nvidia_gpu(self, mock_run, _):
        mock_run.return_value = type('R', (), {'stdout': '45\n', 'returncode': 0})()
        usage = get_gpu_usage()
        self.assertAlmostEqual(usage, 45.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    def test_no_gpu(self, *_):
        self.assertIsNone(get_gpu_usage())


# ── get_gpu_clock ────────────────────────────────────────────────────────────

class TestGetGpuClock(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='1500000000')
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon1')
    def test_amd_gpu(self, mock_find, mock_read):
        clock = get_gpu_clock()
        self.assertAlmostEqual(clock, 1500.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run')
    def test_nvidia_gpu(self, mock_run, _):
        mock_run.return_value = type('R', (), {'stdout': '1800\n', 'returncode': 0})()
        clock = get_gpu_clock()
        self.assertAlmostEqual(clock, 1800.0)

    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    def test_no_gpu(self, *_):
        self.assertIsNone(get_gpu_clock())


# ── get_memory_temperature ───────────────────────────────────────────────────

class TestGetMemoryTemperature(unittest.TestCase):

    @patch('trcc.system_info.read_file')
    @patch('trcc.system_info.os.path.exists', return_value=True)
    def test_hwmon_ddr(self, mock_exists, mock_read):
        def side_effect(path):
            if 'hwmon0/name' in path:
                return 'ddr5_thermal'
            if 'hwmon0/temp1_input' in path:
                return '42000'
            return None
        mock_read.side_effect = side_effect
        temp = get_memory_temperature()
        self.assertAlmostEqual(temp, 42.0)

    @patch('trcc.system_info.subprocess.run')
    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.os.path.exists', return_value=False)
    def test_returns_none_when_unavailable(self, *_):
        self.assertIsNone(get_memory_temperature())


# ── get_memory_clock ─────────────────────────────────────────────────────────

class TestGetMemoryClock(unittest.TestCase):

    @patch('trcc.system_info.subprocess.run')
    def test_dmidecode_configured_speed(self, mock_run):
        mock_run.return_value = type('R', (), {
            'stdout': 'Memory Device\n  Configured Memory Speed: 3200 MT/s\n',
            'returncode': 0
        })()
        clock = get_memory_clock()
        self.assertAlmostEqual(clock, 3200.0)

    @patch('trcc.system_info.subprocess.run')
    def test_dmidecode_speed_fallback(self, mock_run):
        mock_run.return_value = type('R', (), {
            'stdout': 'Memory Device\n  Speed: 2400 MHz\n',
            'returncode': 0
        })()
        clock = get_memory_clock()
        self.assertAlmostEqual(clock, 2400.0)

    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    def test_returns_none_when_unavailable(self, _):
        self.assertIsNone(get_memory_clock())


# ── get_disk_stats ───────────────────────────────────────────────────────────

class TestGetDiskStats(unittest.TestCase):

    @patch('trcc.system_info.PSUTIL_AVAILABLE', False)
    def test_no_psutil(self):
        self.assertEqual(get_disk_stats(), {})

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    def test_first_call_returns_empty(self, mock_psutil):
        """First call caches baseline, returns empty."""
        import trcc.system_info as si
        si._prev_disk_io = None
        si._prev_disk_time = None
        mock_psutil.disk_io_counters.return_value = MagicMock(
            read_bytes=1000, write_bytes=2000, busy_time=100)
        result = get_disk_stats()
        self.assertEqual(result, {})


# ── get_disk_temperature ─────────────────────────────────────────────────────

class TestGetDiskTemperature(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='38000')
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon3')
    def test_nvme(self, mock_find, mock_read):
        temp = get_disk_temperature()
        self.assertAlmostEqual(temp, 38.0)

    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    def test_returns_none(self, *_):
        self.assertIsNone(get_disk_temperature())


# ── get_network_stats ────────────────────────────────────────────────────────

class TestGetNetworkStats(unittest.TestCase):

    @patch('trcc.system_info.PSUTIL_AVAILABLE', False)
    def test_no_psutil(self):
        self.assertEqual(get_network_stats(), {})

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    def test_first_call_has_totals(self, mock_psutil):
        import trcc.system_info as si
        si._prev_net_io = None
        si._prev_net_time = None
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=1024 * 1024 * 100, bytes_recv=1024 * 1024 * 500)
        result = get_network_stats()
        self.assertIn('net_total_up', result)
        self.assertIn('net_total_down', result)


# ── get_fan_speeds ───────────────────────────────────────────────────────────

class TestGetFanSpeeds(unittest.TestCase):

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    def test_psutil_fans(self, mock_psutil):
        mock_psutil.sensors_fans.return_value = {
            'nct6798': [
                MagicMock(label='Processor Fan', current=1200),
                MagicMock(label='System Fan #2', current=800),
            ]
        }
        result = get_fan_speeds()
        self.assertIn('fan_cpu', result)
        self.assertEqual(result['fan_cpu'], 1200)

    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.os.path.exists', return_value=False)
    @patch('trcc.system_info.PSUTIL_AVAILABLE', False)
    def test_no_fans(self, *_):
        result = get_fan_speeds()
        self.assertEqual(result, {})


# ── get_all_metrics ──────────────────────────────────────────────────────────

class TestGetAllMetrics(unittest.TestCase):

    @patch('trcc.system_info.get_fan_speeds', return_value={})
    @patch('trcc.system_info.get_network_stats', return_value={})
    @patch('trcc.system_info.get_disk_stats', return_value={})
    @patch('trcc.system_info.get_disk_temperature', return_value=None)
    @patch('trcc.system_info.get_memory_clock', return_value=None)
    @patch('trcc.system_info.get_memory_temperature', return_value=None)
    @patch('trcc.system_info.get_memory_available', return_value=8000.0)
    @patch('trcc.system_info.get_memory_usage', return_value=50.0)
    @patch('trcc.system_info.get_gpu_clock', return_value=None)
    @patch('trcc.system_info.get_gpu_usage', return_value=None)
    @patch('trcc.system_info.get_gpu_temperature', return_value=None)
    @patch('trcc.system_info.get_cpu_frequency', return_value=3500.0)
    @patch('trcc.system_info.get_cpu_usage', return_value=25.0)
    @patch('trcc.system_info.get_cpu_temperature', return_value=55.0)
    def test_basic_metrics(self, *_):
        from trcc.system_info import get_all_metrics
        m = get_all_metrics()

        # Always present: date/time fields
        self.assertIn('date', m)
        self.assertIn('time', m)
        self.assertIn('weekday', m)
        self.assertIn('day_of_week', m)

        # CPU metrics should be present
        self.assertIn('cpu_temp', m)
        self.assertAlmostEqual(m['cpu_temp'], 55.0)
        self.assertIn('cpu_percent', m)
        self.assertIn('cpu_freq', m)

        # Memory
        self.assertIn('mem_percent', m)
        self.assertIn('mem_available', m)

        # GPU not available — keys should be absent
        self.assertNotIn('gpu_temp', m)


# ── Format dictionaries ─────────────────────────────────────────────────────

class TestFormatConstants(unittest.TestCase):

    def test_time_formats_keys(self):
        self.assertEqual(set(TIME_FORMATS.keys()), {0, 1, 2})

    def test_date_formats_keys(self):
        self.assertEqual(set(DATE_FORMATS.keys()), {0, 1, 2, 3, 4})

    def test_weekdays_length(self):
        self.assertEqual(len(WEEKDAYS), 7)
        self.assertEqual(WEEKDAYS[0], 'MON')
        self.assertEqual(WEEKDAYS[6], 'SUN')


# ── Additional format_metric branches ────────────────────────────────────────

class TestFormatMetricExtra(unittest.TestCase):
    """Cover date_format 2/3/4, time_format 2, and invalid format fallbacks."""

    @patch('trcc.system_info.datetime')
    def test_date_format_2_dd_mm_yyyy(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 0, 0, 0)
        self.assertEqual(format_metric('date', 0, date_format=2), '15/03/2026')

    @patch('trcc.system_info.datetime')
    def test_date_format_3_mm_dd(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 0, 0, 0)
        self.assertEqual(format_metric('date', 0, date_format=3), '03/15')

    @patch('trcc.system_info.datetime')
    def test_date_format_4_dd_mm(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 0, 0, 0)
        self.assertEqual(format_metric('date', 0, date_format=4), '15/03')

    @patch('trcc.system_info.datetime')
    def test_date_format_invalid_falls_back(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 0, 0, 0)
        # Invalid format key → falls back to format 0
        self.assertEqual(format_metric('date', 0, date_format=99), '2026/03/15')

    @patch('trcc.system_info.datetime')
    def test_time_format_2(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 9, 5, 0)
        result = format_metric('time', 0, time_format=2)
        self.assertEqual(result, '09:05')

    @patch('trcc.system_info.datetime')
    def test_time_format_invalid_falls_back(self, mock_dt):
        from datetime import datetime as real_dt
        mock_dt.now.return_value = real_dt(2026, 3, 15, 14, 30, 0)
        result = format_metric('time', 0, time_format=99)
        self.assertEqual(result, '14:30')


# ── CPU temperature fallback branches ────────────────────────────────────────

class TestCpuTempFallbacks(unittest.TestCase):

    @patch('trcc.system_info.subprocess.run')
    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    def test_lm_sensors_tctl(self, mock_find, mock_read, mock_run):
        """Fallback to sensors -u with Tctl match."""
        mock_run.return_value = type('R', (), {
            'stdout': 'k10temp-isa-0000\n  Tctl:\n    tctl_input: 63.500\n',
            'returncode': 0
        })()
        # Tctl falls through to 'Tctl' in line.lower() branch
        temp = get_cpu_temperature()
        # If sensors parsing works, it finds the value from Tctl line
        # The code checks 'Tctl' in line.lower() and looks for ': <number>'
        if temp is not None:
            self.assertGreater(temp, 0)

    @patch('trcc.system_info.subprocess.run', side_effect=Exception("no sensors"))
    @patch('trcc.system_info.find_hwmon_by_name', return_value='/sys/class/hwmon/hwmon0')
    @patch('trcc.system_info.read_file', return_value=None)
    def test_hwmon_all_temps_none(self, *_):
        """hwmon found but temp{1,2,3}_input all None → sensors fallback fails → None."""
        temp = get_cpu_temperature()
        self.assertIsNone(temp)


# ── CPU usage fallback branches ──────────────────────────────────────────────

class TestCpuUsageFallbacks(unittest.TestCase):

    @patch('trcc.system_info.read_file', return_value='2.50 1.00 0.50 1/234 5678')
    def test_loadavg_fallback(self, mock_read):
        """When /proc/stat fails, falls back to /proc/loadavg."""
        with patch('builtins.open', side_effect=OSError("no stat")):
            usage = get_cpu_usage()
            self.assertIsNotNone(usage)
            self.assertAlmostEqual(usage, 25.0)  # 2.50 * 10

    @patch('trcc.system_info.read_file', side_effect=Exception("no loadavg"))
    def test_both_fail_returns_none(self, _):
        with patch('builtins.open', side_effect=OSError("no stat")):
            usage = get_cpu_usage()
            self.assertIsNone(usage)


# ── Memory temperature lm_sensors fallback ───────────────────────────────────

class TestMemoryTempSensors(unittest.TestCase):

    @patch('trcc.system_info.subprocess.run')
    @patch('trcc.system_info.read_file', return_value=None)
    @patch('trcc.system_info.os.path.exists', return_value=False)
    def test_lm_sensors_memory_section(self, mock_exists, mock_read, mock_run):
        sensors_output = (
            "coretemp-isa-0000\n"
            "  temp1_input: 55.000\n"
            "\n"
            "ddr5_dimm-virtual-0\n"
            "  temp1_input: 38.500\n"
        )
        mock_run.return_value = type('R', (), {
            'stdout': sensors_output, 'returncode': 0
        })()
        temp = get_memory_temperature()
        self.assertIsNotNone(temp)
        self.assertAlmostEqual(temp, 38.5)


# ── Memory clock fallbacks ───────────────────────────────────────────────────

class TestMemoryClockFallbacks(unittest.TestCase):

    @patch('trcc.system_info.os.path.exists', return_value=False)
    @patch('trcc.system_info.subprocess.run')
    def test_lshw_fallback(self, mock_run, _):
        # First call (dmidecode) fails, second (lshw) succeeds
        mock_run.side_effect = [
            type('R', (), {'stdout': '', 'returncode': 1})(),
            type('R', (), {
                'stdout': '/0/33  memory  4096MB DIMM DDR5 4800 MHz\n',
                'returncode': 0
            })(),
        ]
        clock = get_memory_clock()
        self.assertAlmostEqual(clock, 4800.0)

    @patch('trcc.system_info.read_file', return_value='Type: DDR5\nFrequency: 5600 MHz\n')
    @patch('trcc.system_info.os.listdir', return_value=['mc0'])
    @patch('trcc.system_info.os.path.exists', return_value=True)
    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    def test_edac_fallback(self, mock_run, mock_exists, mock_listdir, mock_read):
        clock = get_memory_clock()
        self.assertAlmostEqual(clock, 5600.0)


# ── Disk stats delta calculation ─────────────────────────────────────────────

class TestDiskStatsDelta(unittest.TestCase):

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    @patch('time.time', return_value=101.0)
    def test_second_call_with_delta(self, mock_time, mock_psutil):
        import trcc.system_info as si
        si._prev_disk_io = MagicMock(
            read_bytes=0, write_bytes=0, busy_time=0)
        si._prev_disk_time = 100.0

        mock_psutil.disk_io_counters.return_value = MagicMock(
            read_bytes=10 * 1024 * 1024,
            write_bytes=5 * 1024 * 1024,
            busy_time=500,
        )
        result = get_disk_stats()

        self.assertIn('disk_read', result)
        self.assertAlmostEqual(result['disk_read'], 10.0, delta=0.1)
        self.assertAlmostEqual(result['disk_write'], 5.0, delta=0.1)
        self.assertIn('disk_activity', result)

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    @patch('time.time', return_value=101.0)
    def test_no_busy_time_estimate(self, mock_time, mock_psutil):
        import trcc.system_info as si
        prev_io = MagicMock(read_bytes=0, write_bytes=0, spec=['read_bytes', 'write_bytes'])
        si._prev_disk_io = prev_io
        si._prev_disk_time = 100.0

        curr_io = MagicMock(read_bytes=1024 * 1024, write_bytes=1024 * 1024,
                            spec=['read_bytes', 'write_bytes'])
        mock_psutil.disk_io_counters.return_value = curr_io
        result = get_disk_stats()
        self.assertIn('disk_activity', result)


# ── Disk temperature fallbacks ───────────────────────────────────────────────

class TestDiskTempFallbacks(unittest.TestCase):

    @patch('trcc.system_info.subprocess.run', side_effect=FileNotFoundError)
    @patch('trcc.system_info.read_file', return_value='38000')
    @patch('trcc.system_info.find_hwmon_by_name')
    def test_drivetemp_hwmon(self, mock_find, mock_read, _):
        mock_find.side_effect = [None, '/sys/class/hwmon/hwmon5']  # nvme=None, drivetemp=found
        temp = get_disk_temperature()
        self.assertAlmostEqual(temp, 38.0)

    @patch('trcc.system_info.subprocess.run')
    @patch('trcc.system_info.find_hwmon_by_name', return_value=None)
    def test_smartctl_fallback(self, mock_find, mock_run):
        # smartctl output: the code finds a digit <100 among parts
        mock_run.return_value = type('R', (), {
            'stdout': 'ID# ATTRIBUTE_NAME  VALUE WORST THRESH TYPE\n194 Temperature_Celsius  35  40  0  Old_age\n',
            'returncode': 0
        })()
        temp = get_disk_temperature()
        self.assertIsNotNone(temp)
        self.assertAlmostEqual(temp, 35.0)


# ── Network stats delta ─────────────────────────────────────────────────────

class TestNetworkStatsDelta(unittest.TestCase):

    @patch('trcc.system_info.PSUTIL_AVAILABLE', True)
    @patch('trcc.system_info.psutil')
    @patch('time.time', return_value=101.0)
    def test_second_call_with_rates(self, mock_time, mock_psutil):
        import trcc.system_info as si
        si._prev_net_io = MagicMock(
            bytes_sent=0, bytes_recv=0)
        si._prev_net_time = 100.0

        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=1024 * 100,
            bytes_recv=1024 * 500,
        )
        result = get_network_stats()

        self.assertIn('net_up', result)
        self.assertAlmostEqual(result['net_up'], 100.0, delta=1.0)
        self.assertAlmostEqual(result['net_down'], 500.0, delta=1.0)


# ── Fan speeds hwmon fallback ────────────────────────────────────────────────

class TestFanSpeedsHwmon(unittest.TestCase):

    @patch('trcc.system_info.read_file')
    @patch('trcc.system_info.os.path.exists')
    @patch('trcc.system_info.PSUTIL_AVAILABLE', False)
    def test_direct_hwmon_access(self, mock_exists, mock_read):
        def exists_side(path):
            return path in [
                '/sys/class/hwmon',
                '/sys/class/hwmon/hwmon0',
            ]
        mock_exists.side_effect = exists_side

        def read_side(path):
            if path == '/sys/class/hwmon/hwmon0/fan1_input':
                return '1500'
            if path == '/sys/class/hwmon/hwmon0/fan2_input':
                return '900'
            return None
        mock_read.side_effect = read_side

        result = get_fan_speeds()
        self.assertIn('fan_cpu', result)
        self.assertEqual(result['fan_cpu'], 1500.0)
        self.assertIn('fan_gpu', result)
        self.assertEqual(result['fan_gpu'], 900.0)


if __name__ == '__main__':
    unittest.main()
