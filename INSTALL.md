# Smart Zones Pro — Инструкция по установке

## Требования
- MetaTrader 4 (RoboForex или любой другой брокер)
- Python 3.10+ (установлен на компьютере)
- Интернет (для обновления данных COMEX)

---

## Шаг 1: Установка Python-зависимостей

Откройте командную строку и выполните:

```bash
cd d:\smart-zones-pro\python_core
pip install -r requirements.txt
```

---

## Шаг 2: Установка индикатора в MT4

### Автоматический способ:
```bash
python d:\smart-zones-pro\python_core\sync_zones_to_mt4.py --install
```

### Ручной способ:
1. Откройте MetaTrader 4
2. Меню **Файл** → **Открыть каталог данных**
3. Перейдите в папку `MQL4/Indicators/`
4. Скопируйте туда файл `d:\smart-zones-pro\mql\MT4\Indicators\StrongZones.mq4`
5. Перезапустите MT4
6. В **Навигаторе** (Ctrl+N) найдите индикатор `StrongZones`
7. Перетащите его на график XAU/USD

---

## Шаг 3: Запуск Python-сервера

В командной строке:

```bash
python d:\smart-zones-pro\python_core\bridge_server.py
```

Сервер запустится и будет пересчитывать зоны каждые 4 часа (на закрытие H4).

Для однократного расчёта:

```bash
python d:\smart-zones-pro\python_core\bridge_server.py --once
```

---

## Шаг 4: Синхронизация зон с MT4

После каждого пересчёта зон (или автоматически):

```bash
python d:\smart-zones-pro\python_core\sync_zones_to_mt4.py
```

Это скопирует файл `zones_output.json` в папку MT4, и индикатор автоматически его прочитает.

---

## Настройки индикатора в MT4

| Параметр | Значение | Описание |
|----------|----------|----------|
| RefreshSeconds | 10 | Как часто проверять обновления (сек) |
| ZoneColorStrong | Red | Цвет зон с Score >= 11 |
| ShowLabels | true | Показывать подписи зон |
| ShowRectangles | true | Рисовать прямоугольники |
| EnableAlerts | true | Алерты при касании зоны |
| AlertDistance | 5.0 | Расстояние до зоны для алерта ($) |

---

## Структура файлов

```
d:\smart-zones-pro\
├── python_core\
│   ├── main.py              # Основной пайплайн
│   ├── bridge_server.py     # Мост MT4 ↔ Python
│   ├── config.py            # Настройки алгоритма
│   ├── data_fetcher.py      # Загрузка свечей
│   ├── zone_detector.py     # Кластеризация фитилей
│   ├── volume_filter.py     # Фильтр крупного игрока
│   ├── visualizer.py        # Генерация графиков
│   ├── sync_zones_to_mt4.py # Синхронизация с MT4
│   └── data\                # CSV с реальными данными
├── mql\
│   └── MT4\Indicators\
│       └── StrongZones.mq4  # Индикатор MT4
├── data_bridge\
│   └── zones_output.json    # JSON с зонами (читает MT4)
└── output\
    ├── zones_H4_*.png       # Графики H4
    └── zones_H1_*.png       # Графики H1
```
