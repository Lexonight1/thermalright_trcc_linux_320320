"""Backward-compat shim — delegates to SystemService.

All business logic now lives in services/system.py (SystemService).
This module re-exports the public API so existing imports keep working.
"""
from __future__ import annotations

from trcc.services.system import SystemService

# Re-export the class under its old name
SystemInfo = SystemService

# Module-level singleton
_instance = SystemService()

# Legacy function aliases
get_cpu_temperature = lambda: _instance.cpu_temperature  # noqa: E731
get_cpu_usage = lambda: _instance.cpu_usage  # noqa: E731
get_cpu_frequency = lambda: _instance.cpu_frequency  # noqa: E731
get_gpu_temperature = lambda: _instance.gpu_temperature  # noqa: E731
get_gpu_usage = lambda: _instance.gpu_usage  # noqa: E731
get_gpu_clock = lambda: _instance.gpu_clock  # noqa: E731
get_memory_usage = lambda: _instance.memory_usage  # noqa: E731
get_memory_available = lambda: _instance.memory_available  # noqa: E731
get_memory_temperature = lambda: _instance.memory_temperature  # noqa: E731
get_memory_clock = lambda: _instance.memory_clock  # noqa: E731
get_disk_stats = lambda: _instance.disk_stats  # noqa: E731
get_disk_temperature = lambda: _instance.disk_temperature  # noqa: E731
get_network_stats = lambda: _instance.network_stats  # noqa: E731
get_fan_speeds = lambda: _instance.fan_speeds  # noqa: E731
get_all_metrics = lambda: _instance.all_metrics  # noqa: E731
format_metric = SystemService.format_metric
find_hwmon_by_name = SystemService.find_hwmon_by_name
