# Smart Zones Pro — Инструкция по установке

## Требования
- **MetaTrader 4** или **MetaTrader 5** (любой брокер — RoboForex и др.)
- **Python 3.10+** установлен на компьютере (только для запуска из исходников;
  для готового `.exe` Python не нужен)
- Интернет (для подгрузки крипто-дельты с Binance — опционально)

> **Путь установки.** Приложение полностью **относительное** — можно поставить
> в любую папку (`C:\Program Files\SmartZonesPro\`, `D:\Trading\SZP\`, и т.п.).
> Все примеры ниже используют переменную `<SZP>` — это корень репозитория /
> установленной папки приложения.

---

## Шаг 0: Настройка `.env` (один раз)

В корне приложения скопируйте `.env.example` → `.env` и заполните:

```
ENABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=123456:ABC...   # от @BotFather
TELEGRAM_CHAT_ID=987654321         # ваш chat id (через @userinfobot)
```

Остальные параметры (`SYMBOL`, `MAX_ZONES_ON_CHART`, `MIN_ZONE_SCORE`,
`DATA_SOURCE`) можно оставить по умолчанию.

---

## Шаг 1: Установка Python-зависимостей

```bash
cd <SZP>\python_core
pip install -r requirements.txt
```

---

## Шаг 2: Установка индикатора и EA в MT4 / MT5

### Автоматически (рекомендуется):
```bash
python <SZP>\python_core\sync_zones_to_mt4.py --install
```
Скрипт сам найдёт все терминалы MetaTrader на компьютере и положит туда:
- MT4: `StrongZones.mq4` (индикатор) + `SmartZonesCollector.mq4` (EA)
- MT5: `StrongZones.mq5` (индикатор) + `SmartZonesCollector.mq5` (EA)

### Вручную:
1. В MT4/MT5: **Файл → Открыть каталог данных**
2. Скопировать:
   - MT4: `<SZP>\mql\MT4\Indicators\StrongZones.mq4` → `MQL4\Indicators\`
   - MT4: `<SZP>\mql\MT4\Experts\SmartZonesCollector.mq4` → `MQL4\Experts\`
   - MT5: `<SZP>\mql\MT5\Indicators\StrongZones.mq5` → `MQL5\Indicators\`
   - MT5: `<SZP>\mql\MT5\Experts\SmartZonesCollector.mq5` → `MQL5\Experts\`
3. Перезапустить терминал, найти `StrongZones` в Навигаторе, перетащить на график

---

## Шаг 3: Запуск Python-сервера

```bash
python <SZP>\python_core\bridge_server.py
```

Сервер ловит обновления от EA, пересчитывает зоны и пишет
`zones_output.json` — его читает индикатор и рисует зоны.

Однократный пересчёт:
```bash
python <SZP>\python_core\bridge_server.py --once
```

Или дважды кликнуть по `START_BRIDGE.bat` в корне репо.

---

## Шаг 4: Синхронизация зон с MT4 (опционально, обычно делает мост сам)

```bash
python <SZP>\python_core\sync_zones_to_mt4.py
```

---

## Настройки индикатора в MT4 / MT5

| Параметр | Значение | Описание |
|----------|----------|----------|
| `RefreshSeconds` | 10 | Как часто проверять обновления (сек) |
| `ZoneColorStrong` | Gold | Цвет зон с Score ≥ 11 |
| `ShowLabels` | true | Показывать подписи зон |
| `ShowRectangles` | true | Полупрозрачные прямоугольники зон |
| `ShowScoreBadge` | true | Бейдж со скором справа от зоны |
| `EnableAlerts` | true | Алерты при касании зоны |
| `AlertDistance` | 5.0 | Расстояние до зоны для алерта ($) |

---

## Структура файлов

```
<SZP>\
├── .env.example             # Шаблон конфигурации (копируется в .env)
├── python_core\
│   ├── main.py              # Основной пайплайн
│   ├── bridge_server.py     # Мост MT4/MT5 ↔ Python
│   ├── config.py            # Настройки (читает из .env)
│   ├── paths.py             # Резолвинг путей (relocatable)
│   ├── data_fetcher.py      # Загрузка свечей
│   ├── zone_detector.py     # Кластеризация фитилей
│   ├── volume_filter.py     # Фильтр крупного игрока
│   ├── footprint_data.py    # Кластерный профиль (футпринт)
│   ├── footprint_window.py  # Окно футпринта (pywebview)
│   ├── telegram_bot.py      # Уведомления в Telegram
│   ├── sync_zones_to_mt4.py # Установка/синхронизация MQL
│   └── data\                # Кэш CSV с реальными данными
├── mql\
│   ├── MT4\Indicators\StrongZones.mq4
│   ├── MT4\Experts\SmartZonesCollector.mq4
│   ├── MT5\Indicators\StrongZones.mq5
│   └── MT5\Experts\SmartZonesCollector.mq5
├── data_bridge\
│   └── zones_output.json    # JSON с зонами (читает MT4/MT5)
└── output\
    ├── zones_H4_*.png
    └── zones_H1_*.png
```
