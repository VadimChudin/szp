"""
hw_profile.py — Что за компьютер у пользователя и что он потянет.

Профиль показывается ДО оплаты ключа и до скачивания модели. Формулировка в
интерфейсе: «RTX 4070, 12 ГБ → Qwen3 14B, качать 8.4 ГБ, полный разбор».
Иначе неизбежны обращения «купил ключ, а ИИ не работает».

Ни один способ определения не открывает окно консоли: видеопамять читаем через
NVML (nvidia-smi.exe вызывается только как запасной вариант и через proc_util),
память и диск — стандартными средствами Python.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass, field

import proc_util
from ai import model_catalog

GIB = 1024 ** 3


@dataclass
class Profile:
    gpu_name: str = ""
    vram_gib: float = 0.0
    ram_gib: float = 0.0
    free_disk_gib: float = 0.0
    cpu_name: str = ""
    cpu_cores: int = 0
    model: model_catalog.ModelSpec | None = field(default=None)
    reason: str = ""

    @property
    def has_gpu(self) -> bool:
        return self.vram_gib > 0

    @property
    def supported(self) -> bool:
        return self.model is not None

    def summary(self) -> str:
        """Короткая строка про железо для интерфейса."""
        if self.has_gpu:
            return f"{self.gpu_name}, {self.vram_gib:.0f} ГБ видеопамяти"
        cores = f", {self.cpu_cores} ядер" if self.cpu_cores else ""
        return f"{self.cpu_name or 'процессор'}{cores}, " \
               f"{self.ram_gib:.0f} ГБ памяти"

    def verdict(self) -> str:
        """Что пользователь получит — или почему не получит."""
        if not self.model:
            return self.reason or "Компьютер не тянет локальную модель"
        where = "на видеокарте" if self.has_gpu else "на процессоре"
        return (f"{self.model.title} {where} — скачать "
                f"{self.model.download_gib:.1f} ГБ. "
                f"{self.model.capability_text}")

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "verdict": self.verdict(),
            "supported": self.supported,
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "vram_gib": round(self.vram_gib, 1),
            "ram_gib": round(self.ram_gib, 1),
            "free_disk_gib": round(self.free_disk_gib, 1),
            "model": self.model.to_dict() if self.model else None,
        }


# ── Видеопамять ─────────────────────────────────────────────────────────────
def _vram_via_nvml() -> tuple[str, float]:
    """Предпочтительный путь: без процессов и без окон."""
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", "ignore")
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return str(name), info.total / GIB
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return "", 0.0


def _vram_via_smi() -> tuple[str, float]:
    """Запасной вариант. Через proc_util, поэтому окно не появляется."""
    try:
        result = proc_util.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"], timeout=10)
        if result.returncode != 0 or not result.stdout:
            return "", 0.0
        first = result.stdout.strip().splitlines()[0]
        name, _, total = first.partition(",")
        return name.strip(), float(total.strip()) / 1024.0
    except Exception:
        return "", 0.0


def detect_gpu() -> tuple[str, float]:
    name, vram = _vram_via_nvml()
    if vram > 0:
        return name, vram
    return _vram_via_smi()


# ── Память, диск, процессор ─────────────────────────────────────────────────
def detect_ram_gib() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / GIB
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return status.ullTotalPhys / GIB
        except Exception:
            pass
    try:
        return (os.sysconf("SC_PAGE_SIZE")
                * os.sysconf("SC_PHYS_PAGES")) / GIB
    except (ValueError, OSError, AttributeError):
        return 0.0


def detect_free_disk_gib(path: str | None = None) -> float:
    target = path or os.environ.get("APPDATA") or os.path.expanduser("~")
    try:
        return shutil.disk_usage(target).free / GIB
    except OSError:
        return 0.0


def detect_cpu() -> tuple[str, int]:
    name = platform.processor() or platform.machine() or ""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            with key:
                name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except Exception:
            pass
    else:
        try:
            from pathlib import Path
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith("model name"):
                    name = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    return re.sub(r"\s+", " ", str(name)).strip(), os.cpu_count() or 0


# ── Сборка профиля ──────────────────────────────────────────────────────────
def build_profile() -> Profile:
    gpu_name, vram = detect_gpu()
    ram = detect_ram_gib()
    free_disk = detect_free_disk_gib()
    cpu_name, cores = detect_cpu()

    profile = Profile(gpu_name=gpu_name, vram_gib=vram, ram_gib=ram,
                      free_disk_gib=free_disk, cpu_name=cpu_name,
                      cpu_cores=cores)

    profile.model = model_catalog.select(vram, ram, free_disk)
    if profile.model is None:
        wanted = model_catalog.select(vram, ram)
        if wanted is not None:
            need = wanted.download_gib * model_catalog.DISK_HEADROOM
            profile.reason = (f"Не хватает места на диске: нужно "
                              f"{need:.1f} ГБ, свободно {free_disk:.1f} ГБ")
        elif ram < 8:
            profile.reason = (f"Мало оперативной памяти: {ram:.0f} ГБ. "
                              f"Локальной модели нужно минимум 8 ГБ")
        else:
            profile.reason = "Конфигурация не подходит для локальной модели"
    return profile
