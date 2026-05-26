"""
tick_reader.py — Чтение и агрегация тиков из MT4 EA.

Читает tick_buffer.csv из Common/Files/, классифицирует тики
по ценовым уровням с реальным buy/sell разделением.

Используется для построения РЕАЛЬНЫХ футпринтов (не эмуляции).
"""

import os
import csv
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

# ── Путь к Common/Files MT4 ──────────────────────────────────────────
MT4_COMMON_FILES = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"


class Tick:
    """Один тик из буфера MT4."""
    __slots__ = ["timestamp_ms", "bid", "ask", "direction", "volume"]

    def __init__(self, timestamp_ms: int, bid: float, ask: float, direction: str, volume: float = 1.0):
        self.timestamp_ms = timestamp_ms
        self.bid = bid
        self.ask = ask
        self.direction = direction  # "BUY", "SELL", "NEUTRAL"
        self.volume = volume

    @property
    def price(self) -> float:
        """Цена тика (mid-point bid/ask)."""
        return (self.bid + self.ask) / 2.0

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000)

    def __repr__(self):
        return f"Tick({self.dt:%H:%M:%S} {self.bid:.2f} {self.direction})"


class TickReader:
    """
    Читает и парсит tick_buffer.csv от MT4 EA SmartZonesCollector.
    
    Формат файла:
        # broker=RoboForex, symbol=XAUUSD, server=RoboForex-ECN, digits=2, point=0.01
        timestamp_ms,bid,ask,direction
        1713580800123,4856.32,4856.55,BUY
        ...
    """

    def __init__(self, symbol: str = "XAUUSD"):
        self.symbol = symbol
        self._tick_file = self._find_tick_file()
        self._ticks: list[Tick] = []
        self._last_read_pos: int = 0
        self._metadata: dict = {}

    def _find_tick_file(self) -> Optional[Path]:
        """Ищет файл тиков в Common/Files."""
        if not MT4_COMMON_FILES.exists():
            return None

        # Пробуем точное имя
        exact = MT4_COMMON_FILES / f"smartzones_ticks_{self.symbol}.csv"
        if exact.exists():
            return exact

        # Ищем любой файл тиков
        for f in MT4_COMMON_FILES.glob("smartzones_ticks_*.csv"):
            return f

        return None

    @property
    def is_available(self) -> bool:
        """Доступен ли файл тиков."""
        return self._tick_file is not None and self._tick_file.exists()

    @property
    def tick_count(self) -> int:
        return len(self._ticks)

    def read_all(self) -> list[Tick]:
        """Читает все тики из файла (полная перезагрузка)."""
        if not self.is_available:
            print(f"[tick_reader] Tick file not found for {self.symbol}")
            return []

        ticks = []
        try:
            with open(self._tick_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or line.startswith('timestamp'):
                        # Парсим метаданные из комментария
                        if line.startswith('# '):
                            self._parse_metadata(line)
                        continue

                    parts = line.split(',')
                    if len(parts) < 4:
                        continue

                    try:
                        tick = Tick(
                            timestamp_ms=int(parts[0]),
                            bid=float(parts[1]),
                            ask=float(parts[2]),
                            direction=parts[3].strip()
                        )
                        ticks.append(tick)
                    except (ValueError, IndexError):
                        continue

        except Exception as e:
            print(f"[tick_reader] Error reading ticks: {e}")
            return []

        self._ticks = ticks
        if ticks:
            dt_start = ticks[0].dt
            dt_end = ticks[-1].dt
            print(f"[tick_reader] Loaded {len(ticks)} ticks "
                  f"({dt_start:%Y-%m-%d %H:%M} -> {dt_end:%H:%M:%S})")
        else:
            print("[tick_reader] No ticks in buffer")

        return ticks

    def _parse_metadata(self, line: str):
        """Парсит метаданные из строки # broker=..., symbol=..."""
        line = line.lstrip('# ')
        for pair in line.split(','):
            pair = pair.strip()
            if '=' in pair:
                key, val = pair.split('=', 1)
                self._metadata[key.strip()] = val.strip()

    def get_ticks_for_period(self, start: datetime, end: datetime) -> list[Tick]:
        """Возвращает тики за указанный период."""
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        return [t for t in self._ticks if start_ms <= t.timestamp_ms < end_ms]

    def aggregate_to_levels(
        self,
        ticks: list[Tick],
        price_step: float
    ) -> dict[float, dict]:
        """
        Агрегирует тики в ценовые уровни с реальным buy/sell.

        Args:
            ticks: список тиков
            price_step: шаг ценовой сетки (например 2.0 для H1)

        Returns:
            {price_level: {"buy": float, "sell": float, "delta": float}}
        """
        import math

        levels: dict[float, dict] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "delta": 0.0})

        for tick in ticks:
            # Привязываем тик к ячейке: p всегда означает нижнюю границу ячейки [p, p+step)
            lvl = math.floor(tick.bid / price_step) * price_step
            lvl = round(lvl, 2)

            if tick.direction == "BUY":
                levels[lvl]["buy"] += tick.volume
                levels[lvl]["delta"] += tick.volume
            elif tick.direction == "SELL":
                levels[lvl]["sell"] += tick.volume
                levels[lvl]["delta"] -= tick.volume
            # NEUTRAL пропускаем

        return dict(levels)

    def build_candle_from_ticks(
        self,
        ohlc: dict,
        ticks: list[Tick],
        price_step: float,
        time_str: str = "",
        m1_candles: list = None
    ) -> dict:
        """
        Строит данные кластерной свечи из реальных тиков.

        Args:
            ohlc: {"open": float, "high": float, "low": float, "close": float, 
                   "volume": float, "time": str/datetime}
            ticks: список тиков, попадающих в эту свечу
            price_step: шаг ценовой сетки
            time_str: строка времени для отображения

        Returns:
            dict совместимый с FootprintCandle
        """
        import math

        o = ohlc["open"]
        h = ohlc["high"]
        l = ohlc["low"]
        c = ohlc["close"]

        # Если есть тики — строим реальный профиль
        if ticks:
            levels = self.aggregate_to_levels(ticks, price_step)

            # Заполняем пустые уровни (от пола low до пола high)
            start_lvl = math.floor(l / price_step) * price_step
            end_lvl = math.floor(h / price_step) * price_step
            price = start_lvl
            while price <= end_lvl + price_step * 0.1:
                rounded = round(price, 2)
                if rounded not in levels:
                    levels[rounded] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                price += price_step

            total_buy = sum(v["buy"] for v in levels.values())
            total_sell = sum(v["sell"] for v in levels.values())

            return {
                "time_str": time_str,
                "open": o, "high": h, "low": l, "close": c,
                "total_volume": total_buy + total_sell,
                "buy_volume": total_buy,
                "sell_volume": total_sell,
                "delta": total_buy - total_sell,
                "levels": levels,
                "is_real": True,  # Флаг: реальные данные из тиков
            }
            
        # 2. Если тиков нет, но передана история M1 — детальная реконструкция
        elif m1_candles and len(m1_candles) > 0:
            from collections import defaultdict
            levels: dict[float, dict] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "delta": 0.0})
            
            total_buy = 0.0
            total_sell = 0.0
            
            for m1 in m1_candles:
                m1_o = m1["open"]
                m1_h = m1["high"]
                m1_l = m1["low"]
                m1_c = m1["close"]
                m1_v = m1["volume"]
                
                # Классификация M1 свечи
                is_bull = m1_c >= m1_o
                # Реалистичное разделение объёма
                m1_buy = m1_v * (0.6 if is_bull else 0.4)
                m1_sell = m1_v - m1_buy
                
                total_buy += m1_buy
                total_sell += m1_sell
                
                # Распределяем объем M1 только ВНУТРИ её собственного диапазона H-L
                start_lvl = math.floor(m1_l / price_step) * price_step
                end_lvl = math.floor(m1_h / price_step) * price_step
                
                cells = 0
                p = start_lvl
                while p <= end_lvl + price_step * 0.1:
                    cells += 1
                    p += price_step
                    
                if cells > 0:
                    b_cell = m1_buy / cells
                    s_cell = m1_sell / cells
                    p = start_lvl
                    while p <= end_lvl + price_step * 0.5:
                        rounded = round(p, 2)
                        levels[rounded]["buy"] += b_cell
                        levels[rounded]["sell"] += s_cell
                        levels[rounded]["delta"] += (b_cell - s_cell)
                        p += price_step
                        
            # Заполняем пустоты для родительской H1 свечи нулями
            start_lvl = math.floor(l / price_step) * price_step
            end_lvl = math.floor(h / price_step) * price_step
            p = start_lvl
            while p <= end_lvl + price_step * 0.1:
                rounded = round(p, 2)
                if rounded not in levels:
                    levels[rounded] = {"buy": 0.0, "sell": 0.0, "delta": 0.0}
                p += price_step

            return {
                "time_str": time_str,
                "open": o, "high": h, "low": l, "close": c,
                "total_volume": total_buy + total_sell,
                "buy_volume": total_buy,
                "sell_volume": total_sell,
                "delta": total_buy - total_sell,
                "levels": dict(levels),
                "is_real": False,  # Историческая реконструкция
            }
        else:
            # Нет тиков (старая свеча) и нет M1. Эмулируем базовый профиль, чтобы не было пустых блоков.
            from collections import defaultdict
            levels: dict[float, dict] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "delta": 0.0})
            
            # Эмуляция: 60/40 в сторону свечи
            vol = ohlc.get("volume", 0)
            is_bull = c >= o
            buy_ratio = 0.55 if is_bull else 0.45
            buy_vol = vol * buy_ratio
            sell_vol = vol - buy_vol
            
            start_lvl = math.floor(l / price_step) * price_step
            end_lvl = math.floor(h / price_step) * price_step
            
            price = start_lvl
            cells = 0
            while price <= end_lvl + price_step * 0.1:
                cells += 1
                price += price_step
                
            if cells > 0:
                # Bell Curve (Normal Distribution) to make historic footprints look realistic
                mid_price = (h + l) / 2.0
                sigma = (h - l) / 6.0 if (h - l) > 0 else 1.0 # 99% rule
                
                weights = []
                price = start_lvl
                while price <= end_lvl + price_step * 0.1:
                    # Gaussian formula
                    w = math.exp(-0.5 * ((price - mid_price) / sigma)**2)
                    weights.append((price, w))
                    price += price_step
                    
                total_w = sum(w for _, w in weights)
                
                for p_val, w in weights:
                    rounded = round(p_val, 2)
                    ratio = w / total_w if total_w > 0 else 1.0/cells
                    b_real = buy_vol * ratio
                    s_real = sell_vol * ratio
                    levels[rounded] = {
                        "buy": b_real, 
                        "sell": s_real, 
                        "delta": b_real - s_real
                    }

            return {
                "time_str": time_str,
                "open": o, "high": h, "low": l, "close": c,
                "total_volume": vol,
                "buy_volume": buy_vol,
                "sell_volume": sell_vol,
                "delta": buy_vol - sell_vol,
                "levels": dict(levels),
                "is_real": False,
            }


# ── Глобальный экземпляр ─────────────────────────────────────────────
_reader: Optional[TickReader] = None


def get_tick_reader(symbol: str = "XAUUSD") -> TickReader:
    """Возвращает (или создаёт) глобальный TickReader."""
    global _reader
    if _reader is None:
        _reader = TickReader(symbol)
    return _reader


# ── Тест ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    reader = get_tick_reader()
    print(f"Tick file available: {reader.is_available}")
    if reader._tick_file:
        print(f"Tick file path: {reader._tick_file}")

    if reader.is_available:
        ticks = reader.read_all()
        print(f"Total ticks: {len(ticks)}")

        if ticks:
            # Показать последние 10 тиков
            print("\nLast 10 ticks:")
            for t in ticks[-10:]:
                print(f"  {t}")

            # Тест агрегации
            print("\nAggregation test (step=$2.0, last 1000 ticks):")
            sample = ticks[-1000:] if len(ticks) >= 1000 else ticks
            levels = reader.aggregate_to_levels(sample, 2.0)
            sorted_lvls = sorted(levels.items(), key=lambda x: x[1]["buy"] + x[1]["sell"], reverse=True)
            for price, data in sorted_lvls[:10]:
                print(f"  ${price:.2f}: BUY {data['buy']:.0f} | SELL {data['sell']:.0f} | D:{data['delta']:+.0f}")
    else:
        print("No tick data. Start SmartZonesCollector EA in MT4 first.")
