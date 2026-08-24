"""Runtime Runner system-metrics collector tests."""

import os
from collections.abc import Callable
from pathlib import Path

from azents_runtime_control.system_metrics import (
    RunnerSystemMetricAvailability,
    RunnerSystemMetricsScope,
)

from azents_runtime_runner.system_metrics import LinuxSystemMetricsCollector


class FakeFiles:
    """Injected text filesystem with per-path read sequences."""

    def __init__(
        self,
        values: dict[str, str | list[str]],
        *,
        existing: set[str] | None = None,
    ) -> None:
        self.values = values
        self.existing = existing or set()
        self.read_counts: dict[str, int] = {}

    def read_text(self, path: Path) -> str:
        """Read one static or sequenced value."""
        key = str(path)
        value = self.values.get(key)
        if value is None:
            raise FileNotFoundError(key)
        if isinstance(value, str):
            return value
        index = self.read_counts.get(key, 0)
        self.read_counts[key] = index + 1
        return value[min(index, len(value) - 1)]

    def path_exists(self, path: Path) -> bool:
        """Return injected path existence."""
        return str(path) in self.existing


def test_collects_cgroup_v2_with_immediate_cpu_baseline() -> None:
    """Container CPU starts unavailable, then reports the one-minute average."""
    files = FakeFiles(
        {
            "/proc/1/cgroup": "0::/kubepods/runtime-1",
            "/sys/fs/cgroup/cpu.stat": [
                "usage_usec 1000000\n",
                "usage_usec 31000000\n",
            ],
            "/sys/fs/cgroup/cpu.max": "100000 100000",
            "/sys/fs/cgroup/memory.current": "512",
            "/sys/fs/cgroup/memory.max": "1024",
        }
    )
    monotonic_values = iter((100.0, 160.0))
    collector = _collector(
        files,
        monotonic=lambda: next(monotonic_values),
        statvfs=lambda _path: _statvfs(total_blocks=100, available_blocks=25),
    )

    first = collector.collect()
    second = collector.collect()

    assert first.scope is RunnerSystemMetricsScope.CONTAINER
    assert first.cpu.availability is RunnerSystemMetricAvailability.UNAVAILABLE
    assert first.memory.used == 512
    assert first.memory.total == 1024
    assert first.disk.used == 75 * 4096
    assert first.disk.total == 100 * 4096
    assert second.cpu.availability is RunnerSystemMetricAvailability.AVAILABLE
    assert second.cpu.used == 500
    assert second.cpu.total == 1000


def test_collects_host_cpu_memory_and_vm_scope() -> None:
    """Explicit virtualization evidence keeps host counters scoped to the VM."""
    files = FakeFiles(
        {
            "/sys/class/dmi/id/product_name": "KVM Virtual Machine",
            "/proc/stat": [
                "cpu 100 0 100 800 0 0 0 0\n",
                "cpu 200 0 200 1000 0 0 0 0\n",
            ],
            "/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 250 kB\n",
        }
    )
    collector = _collector(
        files,
        monotonic=lambda: 100.0,
        statvfs=lambda _path: _statvfs(total_blocks=10, available_blocks=4),
        cpu_count=lambda: 2,
    )

    first = collector.collect()
    second = collector.collect()

    assert first.scope is RunnerSystemMetricsScope.VM
    assert first.cpu.availability is RunnerSystemMetricAvailability.UNAVAILABLE
    assert second.cpu.used == 1000
    assert second.cpu.total == 2000
    assert second.memory.used == 750 * 1024
    assert second.memory.total == 1000 * 1024


def test_cgroup_v1_unlimited_memory_omits_total() -> None:
    """A cgroup v1 unlimited sentinel does not fabricate a denominator."""
    files = FakeFiles(
        {
            "/proc/1/cgroup": "2:memory:/docker/runtime-1",
            "/sys/fs/cgroup/cpuacct/cpuacct.usage": "1000000000",
            "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1",
            "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
            "/sys/fs/cgroup/memory/memory.usage_in_bytes": "2048",
            "/sys/fs/cgroup/memory/memory.limit_in_bytes": str(1 << 62),
        }
    )
    collector = _collector(files)

    sample = collector.collect()

    assert sample.scope is RunnerSystemMetricsScope.CONTAINER
    assert sample.memory.availability is RunnerSystemMetricAvailability.AVAILABLE
    assert sample.memory.used == 2048
    assert sample.memory.total is None


def test_metric_failures_are_independent() -> None:
    """Malformed CPU and disk reads do not discard available memory."""
    files = FakeFiles(
        {
            "/proc/stat": "invalid",
            "/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
        }
    )

    def fail_statvfs(_path: str) -> os.statvfs_result:
        raise OSError("filesystem unavailable")

    collector = _collector(files, statvfs=fail_statvfs)

    sample = collector.collect()

    assert sample.cpu.availability is RunnerSystemMetricAvailability.UNAVAILABLE
    assert sample.memory.availability is RunnerSystemMetricAvailability.AVAILABLE
    assert sample.disk.availability is RunnerSystemMetricAvailability.UNAVAILABLE


def test_host_cpu_counter_reset_is_unavailable_then_recovers() -> None:
    """Counter regression resets the baseline before a later valid interval."""
    files = FakeFiles(
        {
            "/proc/stat": [
                "cpu 100 0 100 800\n",
                "cpu 50 0 50 400\n",
                "cpu 60 0 60 480\n",
            ],
            "/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 500 kB\n",
        }
    )
    monotonic_values = iter((100.0, 160.0, 220.0))
    collector = _collector(
        files,
        monotonic=lambda: next(monotonic_values),
    )

    assert collector.collect().cpu.availability is (
        RunnerSystemMetricAvailability.UNAVAILABLE
    )
    assert collector.collect().cpu.availability is (
        RunnerSystemMetricAvailability.UNAVAILABLE
    )
    assert collector.collect().cpu.availability is (
        RunnerSystemMetricAvailability.AVAILABLE
    )


def test_cgroup_cpu_zero_elapsed_is_unavailable() -> None:
    """A cgroup counter delta without elapsed time cannot become a CPU rate."""
    files = FakeFiles(
        {
            "/proc/1/cgroup": "0::/docker/runtime-1",
            "/sys/fs/cgroup/cpu.stat": [
                "usage_usec 1000000\n",
                "usage_usec 2000000\n",
            ],
            "/sys/fs/cgroup/cpu.max": "max 100000",
            "/sys/fs/cgroup/memory.current": "512",
            "/sys/fs/cgroup/memory.max": "max",
        }
    )
    collector = _collector(files, monotonic=lambda: 100.0)

    assert collector.collect().cpu.availability is (
        RunnerSystemMetricAvailability.UNAVAILABLE
    )
    assert collector.collect().cpu.availability is (
        RunnerSystemMetricAvailability.UNAVAILABLE
    )


def test_non_linux_environment_is_explicitly_unsupported() -> None:
    """Non-Linux future backends use the same contract without fake values."""
    collector = _collector(FakeFiles({}), platform_name="Darwin")

    sample = collector.collect()

    assert sample.scope is RunnerSystemMetricsScope.HOST
    assert {
        sample.cpu.availability,
        sample.memory.availability,
        sample.disk.availability,
    } == {RunnerSystemMetricAvailability.UNSUPPORTED}


def _collector(
    files: FakeFiles,
    *,
    monotonic: Callable[[], float] = lambda: 100.0,
    statvfs: Callable[[str], os.statvfs_result] = (
        lambda _path: _statvfs(total_blocks=10, available_blocks=5)
    ),
    cpu_count: Callable[[], int | None] = lambda: 1,
    platform_name: str = "Linux",
) -> LinuxSystemMetricsCollector:
    return LinuxSystemMetricsCollector(
        read_text=files.read_text,
        path_exists=files.path_exists,
        statvfs=statvfs,
        cpu_count=cpu_count,
        monotonic=monotonic,
        platform_name=platform_name,
    )


def _statvfs(
    *,
    total_blocks: int,
    available_blocks: int,
) -> os.statvfs_result:
    return os.statvfs_result(
        (
            4096,
            4096,
            total_blocks,
            available_blocks,
            available_blocks,
            0,
            0,
            0,
            255,
            255,
        )
    )
