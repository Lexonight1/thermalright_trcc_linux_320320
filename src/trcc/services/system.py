"""System monitoring service — sensors, panels, and metrics.

Business logic for hardware monitoring: sensor discovery, metric reading,
formatting, and dashboard panel configuration. Pure Python, no Qt dependencies.

Absorbs system_info.py (SystemInfo) logic. Uses system_sensors.py
(SensorEnumerator) and system_config.py (SysInfoConfig) as infrastructure.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

from ..core.models import DATE_FORMATS, TIME_FORMATS, WEEKDAYS
from ..data_repository import SysUtils

if TYPE_CHECKING:
    from ..core.models import SensorInfo
    from ..system_config import PanelConfig

log = logging.getLogger(__name__)


class SystemService:
    """Unified system monitoring: sensor discovery, metrics, panel config."""

    def __init__(self) -> None:
        from ..system_sensors import SensorEnumerator

        self._enumerator = SensorEnumerator()
        self._discovered = False
        self._defaults: Optional[Dict[str, str]] = None

    # ── Sensor discovery ──────────────────────────────────────────────

    def discover(self) -> list[SensorInfo]:
        """Scan hardware for available sensors. Call once at startup."""
        sensors = self._enumerator.discover()
        self._discovered = True
        self._defaults = None  # Reset cached defaults
        return sensors

    def _ensure_discovered(self) -> None:
        """Lazy-discover sensors on first use."""
        if not self._discovered:
            self.discover()

    @property
    def sensors(self) -> list[SensorInfo]:
        """All discovered sensors."""
        self._ensure_discovered()
        return self._enumerator.get_sensors()

    def sensors_by_category(self, category: str) -> list[SensorInfo]:
        """Filter sensors by category (temperature, fan, clock, etc.)."""
        self._ensure_discovered()
        return self._enumerator.get_by_category(category)

    @property
    def enumerator(self):
        """Direct access to SensorEnumerator (for GUI sensor picker)."""
        self._ensure_discovered()
        return self._enumerator

    # ── Readings ──────────────────────────────────────────────────────

    def read_all(self) -> dict[str, float]:
        """Read current values for all discovered sensors."""
        self._ensure_discovered()
        return self._enumerator.read_all()

    def read_one(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor by ID."""
        self._ensure_discovered()
        return self._enumerator.read_one(sensor_id)

    # ── Legacy key mapping ────────────────────────────────────────────

    def _ensure_defaults(self) -> Dict[str, str]:
        """Get legacy metric key → sensor_id mapping (cached)."""
        self._ensure_discovered()
        if self._defaults is None:
            self._defaults = self._enumerator.map_defaults()
        return self._defaults

    def _read_metric(self, legacy_key: str) -> Optional[float]:
        """Read a single metric by legacy key via the enumerator."""
        defaults = self._ensure_defaults()
        sensor_id = defaults.get(legacy_key)
        if sensor_id:
            return self._enumerator.read_one(sensor_id)
        return None

    # ── Metric properties ─────────────────────────────────────────────

    @property
    def cpu_temperature(self) -> Optional[float]:
        """CPU temperature (enumerator hwmon, fallback: lm_sensors)."""
        return self._read_metric('cpu_temp') or self._fallback_cpu_temp()

    @property
    def cpu_usage(self) -> Optional[float]:
        """CPU usage percentage."""
        return self._read_metric('cpu_percent') or self._fallback_cpu_usage()

    @property
    def cpu_frequency(self) -> Optional[float]:
        """CPU frequency in MHz."""
        return self._read_metric('cpu_freq') or self._fallback_cpu_freq()

    @property
    def gpu_temperature(self) -> Optional[float]:
        return self._read_metric('gpu_temp')

    @property
    def gpu_usage(self) -> Optional[float]:
        return self._read_metric('gpu_usage')

    @property
    def gpu_clock(self) -> Optional[float]:
        return self._read_metric('gpu_clock')

    @property
    def memory_usage(self) -> Optional[float]:
        return self._read_metric('mem_percent')

    @property
    def memory_available(self) -> Optional[float]:
        return self._read_metric('mem_available')

    @property
    def memory_temperature(self) -> Optional[float]:
        return self._read_metric('mem_temp') or self._fallback_mem_temp()

    @property
    def memory_clock(self) -> Optional[float]:
        return self._fallback_mem_clock()

    @property
    def disk_stats(self) -> Dict[str, float]:
        readings = self.read_all()
        stats: Dict[str, float] = {}
        for legacy, sensor in [
            ('disk_read', 'computed:disk_read'),
            ('disk_write', 'computed:disk_write'),
            ('disk_activity', 'computed:disk_activity'),
        ]:
            if sensor in readings:
                stats[legacy] = readings[sensor]
        return stats

    @property
    def disk_temperature(self) -> Optional[float]:
        return self._read_metric('disk_temp') or self._fallback_disk_temp()

    @property
    def network_stats(self) -> Dict[str, float]:
        readings = self.read_all()
        stats: Dict[str, float] = {}
        for legacy, sensor in [
            ('net_up', 'computed:net_up'),
            ('net_down', 'computed:net_down'),
            ('net_total_up', 'computed:net_total_up'),
            ('net_total_down', 'computed:net_total_down'),
        ]:
            if sensor in readings:
                stats[legacy] = readings[sensor]
        return stats

    @property
    def fan_speeds(self) -> Dict[str, float]:
        defaults = self._ensure_defaults()
        readings = self.read_all()
        fans: Dict[str, float] = {}
        for fan_key in ('fan_cpu', 'fan_gpu', 'fan_ssd', 'fan_sys2'):
            sensor_id = defaults.get(fan_key)
            if sensor_id and sensor_id in readings:
                fans[fan_key] = readings[sensor_id]
        return fans

    # ── Aggregate metrics ─────────────────────────────────────────────

    @property
    def all_metrics(self) -> Dict[str, float]:
        """All system metrics as a flat dict."""
        metrics: Dict[str, float] = {}

        # Date and time
        now = datetime.now()
        metrics['date_year'] = now.year
        metrics['date_month'] = now.month
        metrics['date_day'] = now.day
        metrics['time_hour'] = now.hour
        metrics['time_minute'] = now.minute
        metrics['time_second'] = now.second
        metrics['day_of_week'] = now.weekday()
        metrics['date'] = 0
        metrics['time'] = 0
        metrics['weekday'] = 0

        # Batch read ALL sensors once
        defaults = self._ensure_defaults()
        readings = self._enumerator.read_all()
        for legacy_key, sensor_id in defaults.items():
            if sensor_id in readings:
                metrics[legacy_key] = readings[sensor_id]

        # Fallbacks for metrics the enumerator couldn't provide
        _fallbacks = [
            ('cpu_temp', self._fallback_cpu_temp),
            ('cpu_percent', self._fallback_cpu_usage),
            ('cpu_freq', self._fallback_cpu_freq),
            ('mem_temp', self._fallback_mem_temp),
            ('mem_clock', self._fallback_mem_clock),
            ('disk_temp', self._fallback_disk_temp),
        ]
        for key, fallback in _fallbacks:
            if key not in metrics:
                if (v := fallback()) is not None:
                    metrics[key] = v

        return metrics

    # ── Formatting ────────────────────────────────────────────────────

    @staticmethod
    def format_metric(metric: str, value: float, time_format: int = 0,
                      date_format: int = 0, temp_unit: int = 0) -> str:
        """Format a metric value for display (matches Windows TRCC)."""
        if metric == 'date':
            now = datetime.now()
            fmt = DATE_FORMATS.get(date_format, DATE_FORMATS[0])
            return now.strftime(fmt)
        elif metric == 'time':
            now = datetime.now()
            fmt = TIME_FORMATS.get(time_format, TIME_FORMATS[0])
            return now.strftime(fmt)
        elif metric == 'weekday':
            now = datetime.now()
            return WEEKDAYS[now.weekday()]
        elif metric == 'day_of_week':
            return WEEKDAYS[int(value)]
        elif metric.startswith('time_') or metric.startswith('date_'):
            return f"{int(value):02d}"
        elif 'temp' in metric:
            if temp_unit == 1:  # Fahrenheit
                fahrenheit = value * 9 / 5 + 32
                return f"{fahrenheit:.0f}°F"
            else:
                return f"{value:.0f}°C"
        elif 'percent' in metric or 'usage' in metric or 'activity' in metric:
            return f"{value:.0f}%"
        elif 'freq' in metric or 'clock' in metric:
            if value >= 1000:
                return f"{value/1000:.1f}GHz"
            return f"{value:.0f}MHz"
        elif metric in ('disk_read', 'disk_write'):
            return f"{value:.1f}MB/s"
        elif metric in ('net_up', 'net_down'):
            if value >= 1024:
                return f"{value/1024:.1f}MB/s"
            return f"{value:.0f}KB/s"
        elif metric in ('net_total_up', 'net_total_down'):
            if value >= 1024:
                return f"{value/1024:.1f}GB"
            return f"{value:.0f}MB"
        elif metric.startswith('fan_'):
            return f"{value:.0f}RPM"
        elif metric == 'mem_available':
            if value >= 1024:
                return f"{value/1024:.1f}GB"
            return f"{value:.0f}MB"
        return f"{value:.1f}"

    # ── Utilities ─────────────────────────────────────────────────────

    @staticmethod
    def find_hwmon_by_name(name: str) -> Optional[str]:
        """Find hwmon path by sensor name (k10temp, coretemp, amdgpu, etc.)."""
        hwmon_base = "/sys/class/hwmon"
        if not os.path.exists(hwmon_base):
            return None
        for i in range(20):
            hwmon_path = f"{hwmon_base}/hwmon{i}"
            sensor_name = SysUtils.read_sysfs(f"{hwmon_path}/name")
            if sensor_name and name.lower() in sensor_name.lower():
                return hwmon_path
        return None

    # ── Subprocess fallbacks ──────────────────────────────────────────

    def _fallback_cpu_temp(self) -> Optional[float]:
        """CPU temp via lm_sensors subprocess."""
        try:
            result = subprocess.run(
                ['sensors', '-u'], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split('\n'):
                if 'temp1_input' in line or 'Tctl' in line.lower():
                    match = re.search(r':\s*([0-9.]+)', line)
                    if match:
                        return float(match.group(1))
        except Exception:
            pass
        return None

    @staticmethod
    def _fallback_cpu_usage() -> Optional[float]:
        """CPU usage via /proc/loadavg."""
        try:
            loadavg = SysUtils.read_sysfs('/proc/loadavg')
            if loadavg:
                load = float(loadavg.split()[0])
                return min(100.0, load * 10)
        except Exception:
            pass
        return None

    @staticmethod
    def _fallback_cpu_freq() -> Optional[float]:
        """CPU frequency via /proc/cpuinfo."""
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if 'cpu MHz' in line:
                        match = re.search(r':\s*([0-9.]+)', line)
                        if match:
                            return float(match.group(1))
        except Exception:
            pass
        return None

    def _fallback_mem_temp(self) -> Optional[float]:
        """Memory temp via lm_sensors subprocess."""
        try:
            result = subprocess.run(
                ['sensors', '-u'], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                in_memory_section = False
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    if any(x in line_lower for x in ['ddr', 'dimm', 'memory']):
                        in_memory_section = True
                    elif line and not line.startswith(' ') and ':' not in line:
                        in_memory_section = False
                    if in_memory_section and 'temp' in line_lower and '_input' in line_lower:
                        match = re.search(r':\s*([0-9.]+)', line)
                        if match:
                            return float(match.group(1))
        except Exception:
            pass
        return None

    @staticmethod
    def _fallback_mem_clock() -> Optional[float]:
        """Memory clock via dmidecode / lshw / EDAC."""
        try:
            result = subprocess.run(
                ['dmidecode', '-t', 'memory'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Configured Memory Speed' in line:
                        match = re.search(r'(\d+)\s*(?:MT/s|MHz)', line)
                        if match:
                            return float(match.group(1))
                for line in result.stdout.split('\n'):
                    if 'Speed:' in line and 'Unknown' not in line:
                        match = re.search(r'(\d+)\s*(?:MT/s|MHz)', line)
                        if match:
                            return float(match.group(1))
        except Exception:
            pass

        try:
            result = subprocess.run(
                ['lshw', '-class', 'memory', '-short'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                match = re.search(r'(\d+)\s*(?:MT/s|MHz)', result.stdout)
                if match:
                    return float(match.group(1))
        except Exception:
            pass

        mc_path = "/sys/devices/system/edac/mc"
        if os.path.exists(mc_path):
            try:
                for mc in os.listdir(mc_path):
                    content = SysUtils.read_sysfs(f"{mc_path}/{mc}/dimm_info")
                    if content:
                        match = re.search(r'(\d+)\s*MHz', content)
                        if match:
                            return float(match.group(1))
            except Exception:
                pass

        return None

    @staticmethod
    def _fallback_disk_temp() -> Optional[float]:
        """Disk temperature via smartctl."""
        try:
            result = subprocess.run(
                ['smartctl', '-A', '/dev/sda'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'Temperature' in line or 'Airflow_Temperature' in line:
                        parts = line.split()
                        for part in parts:
                            if part.isdigit() and int(part) < 100:
                                return float(part)
        except Exception:
            pass
        return None

    # ── Panel configuration ──────────────────────────────────────────

    def load_panels(self) -> list[PanelConfig]:
        """Load dashboard panel config from disk (or defaults)."""
        from ..system_config import SysInfoConfig
        return SysInfoConfig().load()

    def save_panels(self, panels: list[PanelConfig]) -> None:
        """Save dashboard panel config to disk."""
        from ..system_config import SysInfoConfig
        cfg = SysInfoConfig()
        cfg.panels = panels
        cfg.save()

    def auto_map_panels(self, panels: list[PanelConfig]) -> None:
        """Fill empty sensor_ids in panels with best-guess defaults."""
        from ..system_config import SysInfoConfig
        self._ensure_discovered()
        cfg = SysInfoConfig()
        cfg.panels = panels
        cfg.auto_map(self._enumerator)

    @staticmethod
    def default_panels() -> list[PanelConfig]:
        """Return 6 default panels with empty sensor_ids."""
        from ..system_config import SysInfoConfig
        return SysInfoConfig.defaults()
