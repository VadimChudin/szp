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
| Stable | тег `v3.0.0` | `SmartZonesPro_Setup_Stable_v3.0.0.exe` | `SmartZonesPro\Stable` |
| Experimental | ветка `devin/**` или тег `exp-v3.0.0` | `SmartZonesPro_Setup_Experimental_v3.0.0.exe` | `SmartZonesPro\Experimental` |

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
iscc.exe /DAppVer=3.0.0 /DAppChannel=Stable setup.iss
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

Since v3.0.0 the chart is zones-only by default. Possible SL levels are drawn only when the indicator input `ShowSL` is enabled (`false` by default); previously the SL block ran unconditionally for every zone and added six dashed lines plus six labels on top of the six zones. Accumulation boxes are likewise off by default (`ShowAccumulation = false`, `ACCUMULATION_ENABLED=0`), and projected round levels are disabled (`PROJECT_ROUND_LEVELS=0`) so that every line on the chart corresponds to a real wick cluster.


## Активные линии: общий лимит, без квоты по сторонам

Начиная с v6.0.0 у снапшота **нет схемы «3 сверху + 3 снизу»**. Действует один
общий лимит `MAX_ZONES_ON_CHART` (по умолчанию `6`, диапазон `1..500`): зоны
отбираются по близости к цене в пределах скопа, и вся квота может уйти на одну
сторону, если реальные уровни есть только сверху или только снизу. Снапшот
меняется только после закрытия новой H4-свечи.

Если реальных зон в скопе меньше лимита — рисуется столько, сколько есть.
Уровни «из воздуха» не достраиваются: `PROJECT_ROUND_LEVELS=0`, а
`projected_levels()` в рабочем пути отбора не вызывается. Слабые кандидаты
(ниже `MIN_ZONE_SCORE`) — это реальные уровни, они добирают лимит и помечаются
`is_fallback: true`, рисуясь **красными линиями**. Возможный SL зоной не
является: он рисуется отдельной **тонкой фиолетовой пунктирной линией** с
подписью `SL`.

Лимит линий в терминале задаётся входом индикатора `MaxZonesToDraw` (по
умолчанию `6`, зажимается в `1..500`) и должен совпадать с
`MAX_ZONES_ON_CHART`. До v6.0.2 в MT4/MT5 стояла жёсткая шестёрка, поэтому
значения выше 6 не доходили до графика: Python отдавал больше зон, а терминал
молча отбрасывал лишние. Боксы накопления — независимые аналитические объекты,
активными зонами SZP они не считаются.

## Полоса отображения зон (скоп)

Видимая область задаётся **скопом** — это вся ширина окна в пунктах, половина
вверх и половина вниз от цены. Значение произвольное: `ZONE_SCOPE_PIPS=800`
даёт ±400 пунктов (±$40 при `PIP_SIZE=0.1`), `2000` — ±$100, и так далее.
Настраивается в окне настроек («Скоп, пункты») или через `.env`.

Зоны внутри скопа отбираются по близости к цене; ограничения «не ближе N
пипсов» нет — уровень вплотную к цене показывается. Параметры лестницы ниже
остались в конфиге для совместимости и используются только опциональным
режимом слотов, который по умолчанию выключен:

| Параметр | По умолчанию | Смысл |
|---|---|---|
| `PIP_SIZE` | `0.1` | сколько долларов в одном пипсе XAU/USD на клиентском терминале |
| `ZONE_NEAREST_MIN_PIPS` / `ZONE_NEAREST_MAX_PIPS` | `200` / `300` | окно для ближайшей зоны на стороне |
| `ZONE_GAP_MIN_PIPS` / `ZONE_GAP_MAX_PIPS` | `200` / `300` | шаг до каждой следующей зоны |
| `ZONE_BAND_TOLERANCE` | `0.25` | допуск «примерно там», когда в окне нет реальных теней |

Шаг считается **относительно предыдущей выбранной зоны**, а не по фиксированным
окнам от цены: абсолютные окна давали жадный перекос — слот забирал дальний край
своего диапазона, и ближняя полоса оставалась пустой. `score` теперь решает
только внутри слота и не может вытянуть набор из ренжа.

`CLUSTER_TOLERANCE` (склейка близких уровней) и максимальная ширина зоны
заданы в конфиге явными значениями в долларах, чтобы склейка шире шага не
схлопывала соседние зоны в одну линию.

Зона, вышедшая из полосы, снимается с графика на ближайшем закрытии H4 и
пишет в журнал событие `zone_out_of_band`. Состав по-прежнему меняется только
после закрытия H4-свечи, а отработанная зона исчезает при обновлении.
