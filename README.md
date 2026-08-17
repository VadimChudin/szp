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
│
│   ├── volume_filter.py  # Фильтрация по объёму (крупный игрок)
│   └── visualizer.py     # mplfinance визуализация
├── mql/                  # Индикаторы MetaTrader
│   ├── MT5/
│   └── MT4/
└── README.md
```

## Каналы сборки и установщики

Проект поддерживает два независимых канала, которые собираются в одно
каталожное хранилище `Output/`, но никогда не перезаписывают друг друга:

| Канал | Триггер | Имя установщика | Каталог установки |
|---|---|---|---|
| Stable | тег `v2.1.0` | `SmartZonesPro_Setup_Stable_v2.1.0.exe` | `SmartZonesPro\\Stable` |
| Experimental | ветка `devin/**` или тег `exp-v2.1.0` | `SmartZonesPro_Setup_Experimental_v2.1.0.exe` | `SmartZonesPro\\Experimental` |

Сборка из экспериментальной ветки получает версию вида `0.0.0.<run_number>` и
внутреннюю метку с каналом и коротким SHA коммита. Поэтому установленное
приложение и MQL-компоненты можно связать с конкретным запуском CI. Тег
`exp-v*` публикуется как GitHub prerelease, а обычный `v*` — как стабильный
релиз.

Оба канала используют разные `AppId` Inno Setup и разные каталоги установки,
поэтому Stable и Experimental можно держать на одном компьютере одновременно.
При обновлении установщик удаляет только предыдущую версию своего канала.

Для локальной сборки стабильного установщика:

```powershell
iscc.exe /DAppVer=2.1.0 /DAppChannel=Stable setup.iss
```

Для локальной экспериментальной сборки:

```powershell
iscc.exe /DAppVer=0.0.0.1 /DAppChannel=Experimental setup.iss
```


## Инкрементальный жизненный цикл зон

Отображаемый список зон хранится в `data_bridge/active_zones_snapshot.json`. Детектор используется для поиска кандидатов, но существующий список не пересоздаётся для каждого вызова: bridge применяет изменения только после появления нового закрытого H4-бара. Для того же H4-бара обновление идемпотентно.

На новом H4-цикле активные зоны сохраняются, если не было подтверждённого теста или пробоя. Кандидат занимает свободное место либо заменяет только слабейшую активную зону, если его `score` строго выше. Касание переводит зону в `TESTED`; при включённом `TEST_INVALIDATES_ZONE=1` подтверждённое касание снимает её, а закрытие телом свечи за пределами зоны всегда создаёт `INVALIDATED`. События пишутся в `data_bridge/zone_events.jsonl`.

По умолчанию ширина зоны рассчитывается от ATR H4 и ограничивается `ZONE_WIDTH_MIN`/`ZONE_WIDTH_MAX`. Для режимной модели можно установить `ZONE_WIDTH_MODE=regime`; `fixed` сохраняет прежнюю фиксированную ширину. Основные параметры задаются через `.env`:

```text
ZONE_WIDTH_MODE=atr
ATR_PERIOD=14
ATR_MULTIPLIER=0.5
ZONE_WIDTH_MIN=0.50
ZONE_WIDTH_MAX=8.00
TEST_INVALIDATES_ZONE=1
ZONE_EVENT_LOG_ENABLED=1
```

## Walk-forward backtest и калибровка score

`python_core/backtest.py` разделяет formation window и future window: зона строится только на свечах до момента оценки, а результат проверяется на следующих свечах. Это предотвращает look-ahead bias. `python_core/score_calibration.py` группирует исходы по диапазонам score и возвращает эмпирическую частоту реакции и надёжность выборки. Эти коэффициенты являются отчётом для калибровки и не изменяют scoring молча.

```python
from backtest import walk_forward, summarize
from score_calibration import calibrate

outcomes = walk_forward(h4_frame, detector, warmup=100, horizon=6)
report = summarize(outcomes)
calibration = calibrate(outcomes, bucket_size=2, min_samples=10)
```

Backtest требует реальный исторический экспорт свечей. Синтетические данные разрешены только для unit-тестов и не должны использоваться для оценки торгового качества.


## Line-only zones and possible SL levels

The chart now renders each active zone as one actionable horizontal price line at `zone.price`. The stored `top`, `bottom`, and `width` fields remain available for lifecycle, invalidation and risk calculations, but they are no longer painted as a broad rectangle. MT4/MT5 and the Footprint window use the same line-first visual language.

Possible SL levels are informational liquidity candidates; the application does not place orders. For a support zone below the current price, the candidate is below the zone. For a resistance zone above the current price, the candidate is above the zone. The level combines the zone edge, a bounded ATR buffer and the nearest recent structural swing. The JSON includes `sl.side`, `sl.price`, `sl.probability`, `sl.buffer`, `sl.atr` and `sl.rationale`; the chart shows it as a separate dashed line. The probability is a heuristic ranking of liquidity exposure, not a win-rate guarantee.

The MQL indicators independently apply the same structural/ATR principle at render time, so the line remains available even when the terminal reads a legacy JSON file. Old rectangle and SL-cloud objects are no longer created for active zones. Accumulation boxes remain separate visual objects and are not zone ranges.


## Six active lines: three above and three below

The active H4 snapshot has a fixed visual contract: **six real price lines**, consisting of **three above** and **three below** the current price. On each side, candidates are ranked by **score first** and then by **proximity to the current price**. The snapshot changes only after a newly closed H4 candle. A new candidate can replace only the weakest line on the same side, so a strong upper zone cannot remove a lower protective level, and vice versa.

If a side has fewer than three zones meeting `MIN_ZONE_SCORE`, the application fills the remaining slots with the best real weaker candidates. These fallback zones are rendered as **red lines** and carry `is_fallback: true` in JSON. Confirmed zones retain the gold/market colour hierarchy. A possible SL is not a zone: it is rendered independently as a **thin violet dashed line** with an explicit `SL` label.

MT4 and MT5 enforce the same hard display guard of six JSON zones. This prevents a stale producer, terminal cache, or older JSON file from drawing ten or twenty active lines. Accumulation boxes remain independent analytical objects and are not active SZP zones.
