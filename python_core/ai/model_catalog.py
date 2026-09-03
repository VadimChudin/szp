"""
model_catalog.py — Какую модель Qwen тянет конкретный компьютер.

Все размеры и имена файлов сверены с официальными GGUF-репозиториями Qwen
на Hugging Face (Apache 2.0, скачивание без токена). Квантование Q4_K_M —
штатный компромисс: сохраняет около 95% качества при вчетверо меньшем весе.

Важно про скорость: индикатор обращается к модели 6-10 раз в сутки, по одному
разу на закрытую свечу H4. Ждать ответ минуту никто не заметит. Поэтому
выбираем не самую быструю модель, а самую крупную из доступных железу.

Уровни возможностей показываются пользователю ДО оплаты ключа, чтобы он знал,
что именно получит на своём компьютере.
"""
from __future__ import annotations

from dataclasses import dataclass

GIB = 1024 ** 3

# Уровни глубины анализа — то, что видно в интерфейсе.
FULL = "full"
STANDARD = "standard"
BASIC = "basic"
LIMITED = "limited"

CAPABILITY_TEXT = {
    FULL: "Полный разбор: ранжирование зон, цепочки инструментов, "
          "исторические аналоги уровней",
    STANDARD: "Стандартный разбор: ранжирование зон и один-два инструмента "
              "на свечу",
    BASIC: "Базовый разбор: подписи и ранжирование зон, без цепочек "
           "инструментов",
    LIMITED: "Ограниченный разбор: только короткие подписи к зонам",
}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    title: str
    repo: str
    filename: str
    download_bytes: int
    min_vram_gib: float
    min_ram_gib: float
    capability: str
    context: int = 32768

    @property
    def download_gib(self) -> float:
        return self.download_bytes / GIB

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"

    @property
    def capability_text(self) -> str:
        return CAPABILITY_TEXT.get(self.capability, "")

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "download_gib": round(self.download_gib, 1),
            "capability": self.capability,
            "capability_text": self.capability_text,
            "context": self.context,
            "url": self.url,
            "filename": self.filename,
        }


# Порядок важен: от крупной к мелкой, отбор идёт первым подходящим.
CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec("qwen3-32b", "Qwen3 32B", "Qwen/Qwen3-32B-GGUF",
              "Qwen3-32B-Q4_K_M.gguf", int(20.0 * GIB), 24.0, 8.0, FULL),
    ModelSpec("qwen3-14b", "Qwen3 14B", "Qwen/Qwen3-14B-GGUF",
              "Qwen3-14B-Q4_K_M.gguf", 9_001_752_960, 12.0, 8.0, FULL),
    ModelSpec("qwen3-8b", "Qwen3 8B", "Qwen/Qwen3-8B-GGUF",
              "Qwen3-8B-Q4_K_M.gguf", 5_027_783_488, 8.0, 8.0, STANDARD),
    ModelSpec("qwen3-4b", "Qwen3 4B", "Qwen/Qwen3-4B-GGUF",
              "Qwen3-4B-Q4_K_M.gguf", int(2.5 * GIB), 6.0, 8.0, BASIC),
    ModelSpec("qwen3-1.7b", "Qwen3 1.7B", "Qwen/Qwen3-1.7B-GGUF",
              "Qwen3-1.7B-Q4_K_M.gguf", int(1.4 * GIB), 4.0, 4.0, LIMITED),
)

BY_KEY = {spec.key: spec for spec in CATALOG}

# Запас на файловую систему и KV-кэш поверх самого файла модели.
DISK_HEADROOM = 1.20


def _find(key: str) -> ModelSpec:
    return BY_KEY[key]


def select(vram_gib: float, ram_gib: float,
           free_disk_gib: float | None = None) -> ModelSpec | None:
    """Подбирает модель под железо. None — если не тянет ничего.

    На GPU модель должна уместиться в видеопамять целиком. Без дискретной
    карты считаем по оперативной памяти: на 6-10 запросов в сутки CPU-инференс
    вполне терпим.
    """
    vram_gib = max(0.0, float(vram_gib or 0))
    ram_gib = max(0.0, float(ram_gib or 0))

    chosen: ModelSpec | None = None

    if vram_gib >= 24:
        chosen = _find("qwen3-32b")
    elif vram_gib >= 12:
        chosen = _find("qwen3-14b")
    elif vram_gib >= 8:
        chosen = _find("qwen3-8b")
    elif vram_gib >= 6:
        chosen = _find("qwen3-4b")
    elif vram_gib >= 4:
        # 4-5 ГБ VRAM: 4B влезает только с выгрузкой части слоёв в RAM.
        chosen = _find("qwen3-4b") if ram_gib >= 16 else _find("qwen3-1.7b")
    else:
        # Дискретной карты нет — считаем на процессоре.
        if ram_gib >= 32:
            chosen = _find("qwen3-14b")
        elif ram_gib >= 16:
            chosen = _find("qwen3-8b")
        elif ram_gib >= 8:
            chosen = _find("qwen3-4b")
        else:
            return None

    if chosen and ram_gib and ram_gib < chosen.min_ram_gib:
        return None

    if free_disk_gib is not None:
        need = chosen.download_gib * DISK_HEADROOM
        if float(free_disk_gib) < need:
            return None

    return chosen


def gpu_layers(spec: ModelSpec, vram_gib: float) -> int:
    """Сколько слоёв отдать видеокарте. -1 = все, 0 = только процессор.

    llama.cpp сам разложит остаток по оперативной памяти, поэтому при нехватке
    видеопамяти достаточно не требовать полной выгрузки.
    """
    vram_gib = max(0.0, float(vram_gib or 0))
    if vram_gib <= 0:
        return 0
    if vram_gib >= spec.min_vram_gib:
        return -1
    return 20 if vram_gib >= 4 else 0
