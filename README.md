# Smart Zones Pro

Индикатор сильных зон поддержки/сопротивления для XAU/USD.  
Определяет зоны на основе кластеризации теней (фитилей) H1/H4/D1 и активности крупных игроков.

## Архитектура

```
MetaTrader 4/5 ←→ ZeroMQ ←→ Python Core ←→ Data Sources
```

## Быстрый старт

```bash
cd python_core
pip install -r requirements.txt
python main.py
```

## Структура проекта

```
smart-zones-pro/
├── python_core/          # Серверная аналитика
│   ├── main.py           # Точка входа
│   ├── config.py         # Настройки
│   ├── data_fetcher.py   # Получение свечей (MT5 API / CSV)
│   ├── zone_detector.py  # Кластеризация теней
│   ├── scorer.py         # Скоринг зон (весовая система)
│   ├── volume_filter.py  # Фильтрация по объёму (крупный игрок)
│   └── visualizer.py     # mplfinance визуализация
├── mql/                  # Индикаторы MetaTrader
│   ├── MT5/
│   └── MT4/
└── README.md
```
