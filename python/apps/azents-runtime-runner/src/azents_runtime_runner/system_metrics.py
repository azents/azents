"""Linux system-metrics collection for the Runtime Runner."""

import dataclasses
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path

from azents_runtime_control.system_metrics import (
    CollectedRunnerSystemMetrics,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsScope,
)

_PROC_STAT = Path("/proc/stat")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_ONE_CGROUP = Path("/proc/1/cgroup")
_CGROUP_V2_CPU_STAT = Path("/sys/fs/cgroup/cpu.stat")
_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V2_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_CPU_USAGE = Path("/sys/fs/cgroup/cpuacct/cpuacct.usage")
_CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
_CGROUP_V1_MEMORY_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
_CGROUP_V1_MEMORY_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_DOCKER_ENV = Path("/.dockerenv")
_HYPERVISOR_TYPE = Path("/sys/hypervisor/type")
_DMI_PRODUCT_NAME = Path("/sys/class/dmi/id/product_name")
_DMI_SYS_VENDOR = Path("/sys/class/dmi/id/sys_vendor")
_CONTAINER_CGROUP_MARKERS = (
    "/docker/",
    "/kubepods/",
    "/containerd/",
    "/libpod/",
    "/lxc/",
)
_VM_MARKERS = (
    "amazon ec2",
    "bhyve",
    "bochs",
    "google compute engine",
    "hyper-v",
    "kvm",
    "openstack",
    "parallels",
    "qemu",
    "virtualbox",
    "vmware",
    "xen",
)
_UNLIMITED_MEMORY_THRESHOLD_BYTES = 1 << 60

type ReadText = Callable[[Path], str]
type PathExists = Callable[[Path], bool]
type StatVfs = Callable[[str], os.statvfs_result]
type CpuCount = Callable[[], int | None]
type Monotonic = Callable[[], float]


@dataclasses.dataclass(frozen=True)
class _CpuReading:
    """One cumulative CPU counter set."""

    source: str
    cumulative_used_ns: int | None
    total_ticks: int | None
    idle_ticks: int | None
    capacity_millicores: int | None


@dataclasses.dataclass(frozen=True)
class _CpuBaseline:
    """Previous cumulative CPU counters and monotonic observation time."""

    reading: _CpuReading
    observed_at: float


class LinuxSystemMetricsCollector:
    """Collect Runner-visible CPU, memory, and root-filesystem usage."""

    def __init__(
        self,
        *,
        read_text: ReadText,
        path_exists: PathExists,
        statvfs: StatVfs,
        cpu_count: CpuCount,
        monotonic: Monotonic,
        platform_name: str,
    ) -> None:
        """Initialize an injected collector."""
        self._read_text = read_text
        self._path_exists = path_exists
        self._statvfs = statvfs
        self._cpu_count = cpu_count
        self._monotonic = monotonic
        self._platform_name = platform_name
        self._scope = self._detect_scope()
        self._cpu_baseline: _CpuBaseline | None = None

    def collect(self) -> CollectedRunnerSystemMetrics:
        """Collect one independent CPU, memory, and disk sample."""
        if self._platform_name != "Linux":
            unsupported = _missing(RunnerSystemMetricAvailability.UNSUPPORTED)
            return CollectedRunnerSystemMetrics(
                scope=RunnerSystemMetricsScope.HOST,
                cpu=unsupported,
                memory=unsupported,
                disk=unsupported,
            )
        return CollectedRunnerSystemMetrics(
            scope=self._scope,
            cpu=self._collect_cpu(),
            memory=self._collect_memory(),
            disk=self._collect_disk(),
        )

    def _detect_scope(self) -> RunnerSystemMetricsScope:
        if self._platform_name != "Linux":
            return RunnerSystemMetricsScope.HOST
        if self._path_exists(_DOCKER_ENV):
            return RunnerSystemMetricsScope.CONTAINER
        cgroup = self._read_optional(_PROC_ONE_CGROUP)
        if cgroup is not None and any(
            marker in cgroup.lower() for marker in _CONTAINER_CGROUP_MARKERS
        ):
            return RunnerSystemMetricsScope.CONTAINER
        hypervisor = self._read_optional(_HYPERVISOR_TYPE)
        if hypervisor is not None and hypervisor.strip():
            return RunnerSystemMetricsScope.VM
        dmi = " ".join(
            value
            for path in (_DMI_PRODUCT_NAME, _DMI_SYS_VENDOR)
            if (value := self._read_optional(path)) is not None
        ).lower()
        if any(marker in dmi for marker in _VM_MARKERS):
            return RunnerSystemMetricsScope.VM
        return RunnerSystemMetricsScope.HOST

    def _collect_cpu(self) -> RunnerSystemMetricObservation:
        try:
            reading = (
                self._read_container_cpu()
                if self._scope is RunnerSystemMetricsScope.CONTAINER
                else self._read_host_cpu()
            )
        except OSError, ValueError:
            return _missing(RunnerSystemMetricAvailability.UNAVAILABLE)
        observed_at = self._monotonic()
        baseline = self._cpu_baseline
        self._cpu_baseline = _CpuBaseline(
            reading=reading,
            observed_at=observed_at,
        )
        if baseline is None or baseline.reading.source != reading.source:
            return _missing(RunnerSystemMetricAvailability.UNAVAILABLE)
        used_millicores = _cpu_used_millicores(
            baseline,
            reading,
            observed_at=observed_at,
        )
        if used_millicores is None:
            return _missing(RunnerSystemMetricAvailability.UNAVAILABLE)
        return _available(
            used=used_millicores,
            total=reading.capacity_millicores,
        )

    def _read_container_cpu(self) -> _CpuReading:
        try:
            fields = _key_value_lines(self._read_text(_CGROUP_V2_CPU_STAT))
            usage_usec = _required_nonnegative_int(fields, "usage_usec")
            return _CpuReading(
                source="cgroup-v2",
                cumulative_used_ns=usage_usec * 1000,
                total_ticks=None,
                idle_ticks=None,
                capacity_millicores=_cgroup_v2_cpu_capacity(
                    self._read_text(_CGROUP_V2_CPU_MAX)
                ),
            )
        except OSError:
            usage_ns = _parse_nonnegative_int(self._read_text(_CGROUP_V1_CPU_USAGE))
            quota = int(self._read_text(_CGROUP_V1_CPU_QUOTA).strip())
            period = _parse_positive_int(self._read_text(_CGROUP_V1_CPU_PERIOD))
            return _CpuReading(
                source="cgroup-v1",
                cumulative_used_ns=usage_ns,
                total_ticks=None,
                idle_ticks=None,
                capacity_millicores=(
                    None if quota < 0 else max(round(quota / period * 1000), 1)
                ),
            )

    def _read_host_cpu(self) -> _CpuReading:
        first_line = self._read_text(_PROC_STAT).splitlines()[0].split()
        if not first_line or first_line[0] != "cpu" or len(first_line) < 5:
            raise ValueError("Aggregate CPU counters are unavailable")
        counters = [_parse_nonnegative_int(value) for value in first_line[1:]]
        total_ticks = sum(counters)
        idle_ticks = counters[3] + (counters[4] if len(counters) > 4 else 0)
        count = self._cpu_count()
        return _CpuReading(
            source="host",
            cumulative_used_ns=None,
            total_ticks=total_ticks,
            idle_ticks=idle_ticks,
            capacity_millicores=(
                count * 1000 if count is not None and count > 0 else None
            ),
        )

    def _collect_memory(self) -> RunnerSystemMetricObservation:
        try:
            if self._scope is RunnerSystemMetricsScope.CONTAINER:
                used, total = self._read_container_memory()
            else:
                used, total = self._read_host_memory()
        except OSError, ValueError:
            return _missing(RunnerSystemMetricAvailability.UNAVAILABLE)
        return _available(used=used, total=total)

    def _read_container_memory(self) -> tuple[int, int | None]:
        try:
            used = _parse_nonnegative_int(self._read_text(_CGROUP_V2_MEMORY_CURRENT))
            raw_total = self._read_text(_CGROUP_V2_MEMORY_MAX).strip()
            total = None if raw_total == "max" else _parse_positive_int(raw_total)
        except OSError:
            used = _parse_nonnegative_int(self._read_text(_CGROUP_V1_MEMORY_USAGE))
            parsed_total = _parse_positive_int(self._read_text(_CGROUP_V1_MEMORY_LIMIT))
            total = (
                None
                if parsed_total >= _UNLIMITED_MEMORY_THRESHOLD_BYTES
                else parsed_total
            )
        return used, total

    def _read_host_memory(self) -> tuple[int, int]:
        fields = _memory_info(self._read_text(_PROC_MEMINFO))
        total = _required_nonnegative_int(fields, "MemTotal") * 1024
        available = _required_nonnegative_int(fields, "MemAvailable") * 1024
        if total <= 0 or available > total:
            raise ValueError("Host memory counters are invalid")
        return total - available, total

    def _collect_disk(self) -> RunnerSystemMetricObservation:
        try:
            stat = self._statvfs("/")
            total = stat.f_frsize * stat.f_blocks
            available = stat.f_frsize * stat.f_bavail
            if total <= 0 or available < 0 or available > total:
                raise ValueError("Root filesystem counters are invalid")
        except OSError, ValueError:
            return _missing(RunnerSystemMetricAvailability.UNAVAILABLE)
        return _available(used=total - available, total=total)

    def _read_optional(self, path: Path) -> str | None:
        try:
            return self._read_text(path)
        except OSError:
            return None


def create_system_metrics_collector() -> LinuxSystemMetricsCollector:
    """Create the production Linux collector."""
    return LinuxSystemMetricsCollector(
        read_text=lambda path: path.read_text(),
        path_exists=lambda path: path.exists(),
        statvfs=os.statvfs,
        cpu_count=os.cpu_count,
        monotonic=time.monotonic,
        platform_name=platform.system(),
    )


def _cpu_used_millicores(
    baseline: _CpuBaseline,
    reading: _CpuReading,
    *,
    observed_at: float,
) -> int | None:
    if reading.source == "host":
        previous_total = baseline.reading.total_ticks
        previous_idle = baseline.reading.idle_ticks
        if (
            previous_total is None
            or previous_idle is None
            or reading.total_ticks is None
            or reading.idle_ticks is None
            or reading.capacity_millicores is None
        ):
            return None
        total_delta = reading.total_ticks - previous_total
        idle_delta = reading.idle_ticks - previous_idle
        if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
            return None
        return max(
            round(
                (total_delta - idle_delta) / total_delta * reading.capacity_millicores
            ),
            0,
        )
    previous_used = baseline.reading.cumulative_used_ns
    current_used = reading.cumulative_used_ns
    elapsed = observed_at - baseline.observed_at
    if (
        previous_used is None
        or current_used is None
        or elapsed <= 0
        or current_used < previous_used
    ):
        return None
    return max(round((current_used - previous_used) / (elapsed * 1_000_000)), 0)


def _cgroup_v2_cpu_capacity(raw: str) -> int | None:
    values = raw.split()
    if len(values) != 2:
        raise ValueError("cgroup v2 CPU capacity is invalid")
    if values[0] == "max":
        _parse_positive_int(values[1])
        return None
    quota = _parse_positive_int(values[0])
    period = _parse_positive_int(values[1])
    return max(round(quota / period * 1000), 1)


def _key_value_lines(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        values = line.split()
        if len(values) == 2:
            result[values[0]] = values[1]
    return result


def _memory_info(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, remainder = line.partition(":")
        if not separator:
            continue
        value = remainder.strip().split()
        if value:
            result[key] = value[0]
    return result


def _required_nonnegative_int(values: dict[str, str], key: str) -> int:
    try:
        raw = values[key]
    except KeyError as exc:
        raise ValueError(f"{key} is required") from exc
    return _parse_nonnegative_int(raw)


def _parse_nonnegative_int(raw: str) -> int:
    value = int(raw.strip())
    if value < 0:
        raise ValueError("Metric counter must be non-negative")
    return value


def _parse_positive_int(raw: str) -> int:
    value = _parse_nonnegative_int(raw)
    if value == 0:
        raise ValueError("Metric total must be positive")
    return value


def _available(*, used: int, total: int | None) -> RunnerSystemMetricObservation:
    return RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.AVAILABLE,
        used=used,
        total=total,
    )


def _missing(
    availability: RunnerSystemMetricAvailability,
) -> RunnerSystemMetricObservation:
    return RunnerSystemMetricObservation(
        availability=availability,
        used=None,
        total=None,
    )
