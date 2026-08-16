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
