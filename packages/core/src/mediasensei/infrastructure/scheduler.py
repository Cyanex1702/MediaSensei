from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mediasensei.domain.jobs import ResourceHints, ResourceLevel, RuntimeProfile

_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    cpu_threads: int
    total_memory_bytes: int | None
    available_memory_bytes: int | None
    free_disk_bytes: int
    gpu_available: bool = False
    gpu_vram_bytes: int | None = None

    @classmethod
    def detect(cls, workspace: str | Path) -> HardwareProfile:
        total_memory, available_memory = _memory_status()
        return cls(
            cpu_threads=max(1, os.cpu_count() or 1),
            total_memory_bytes=total_memory,
            available_memory_bytes=available_memory,
            free_disk_bytes=shutil.disk_usage(Path(workspace).resolve()).free,
        )


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    profile: RuntimeProfile
    max_concurrency: int
    paused_for_pressure: bool
    warnings: tuple[str, ...]


class AdaptiveScheduler:
    """Conservative concurrency planner with memory and disk backpressure."""

    def decide(
        self,
        hardware: HardwareProfile,
        profile: RuntimeProfile,
        hints: ResourceHints,
        *,
        custom_concurrency: int | None = None,
    ) -> ScheduleDecision:
        warnings: list[str] = []
        paused = False

        if hardware.free_disk_bytes < 2 * _GIB:
            paused = True
            warnings.append("Less than 2 GiB of disk space remains; new work is paused.")
        elif hardware.free_disk_bytes < 10 * _GIB:
            warnings.append("Disk headroom is below 10 GiB; concurrency is reduced.")

        if hardware.available_memory_bytes is not None:
            if hardware.available_memory_bytes < 512 * 1024**2:
                paused = True
                warnings.append("Available memory is below 512 MiB; new work is paused.")
            elif hardware.available_memory_bytes < 2 * _GIB:
                warnings.append("Available memory is below 2 GiB; concurrency is reduced.")

        cpu_threads = hardware.cpu_threads
        if profile is RuntimeProfile.ECO:
            concurrency = 1
        elif profile is RuntimeProfile.MAXIMUM:
            concurrency = max(1, min(16, cpu_threads - 1 if cpu_threads > 1 else 1))
        elif profile is RuntimeProfile.CUSTOM:
            concurrency = max(1, min(32, custom_concurrency or 1))
        else:
            concurrency = max(1, min(8, cpu_threads // 2 or 1))

        level_caps = {
            ResourceLevel.NONE: 32,
            ResourceLevel.LOW: 12,
            ResourceLevel.MEDIUM: 6,
            ResourceLevel.HIGH: 2,
            ResourceLevel.VERY_HIGH: 1,
        }
        concurrency = min(concurrency, level_caps[hints.cpu], level_caps[hints.memory])

        if (
            hints.gpu in {ResourceLevel.HIGH, ResourceLevel.VERY_HIGH}
            and not hardware.gpu_available
        ):
            paused = True
            warnings.append("This node requires a GPU, but no compatible GPU was detected.")
        if hardware.free_disk_bytes < 10 * _GIB:
            concurrency = 1
        if (
            hardware.available_memory_bytes is not None
            and hardware.available_memory_bytes < 2 * _GIB
        ):
            concurrency = 1
        if paused:
            concurrency = 0

        return ScheduleDecision(profile, concurrency, paused, tuple(warnings))


def _memory_status() -> tuple[int | None, int | None]:
    """Return total and available memory without adding a mandatory psutil dependency."""
    try:
        if os.name == "posix":
            sysconf = getattr(os, "sysconf")  # noqa: B009 - absent from Windows stubs
            page_size = sysconf("SC_PAGE_SIZE")
            total = sysconf("SC_PHYS_PAGES") * page_size
            available = sysconf("SC_AVPHYS_PAGES") * page_size
            return int(total), int(available)
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical), int(status.available_physical)
    except (AttributeError, OSError, ValueError):
        pass
    return None, None
