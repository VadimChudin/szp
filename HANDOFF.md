# HANDOFF: Smart Zones Pro (szp) — Project State & Architecture

**Дата:** 2 сентября 2026 | **Версия:** v5.1.0 (Latest) | **Статус:** ✅ Production-Ready  
**Мейнтейнер:** Vadim Chudin | **Язык:** Python 3.10+ (core), MQL4/MQL5 (indicators)

---

## 🎯 Что это за проект?

**Smart Zones Pro** — торговый индикатор для MetaTrader 4/5, выявляющий **сильные зоны поддержки/сопротивления** золота (XAUUSD) на основе:
- Кластеризации теней (вики) свечей на H1/H4/D1
- Активности крупных игроков (аномальные объёмы)
- Независимой валидации через эталонный фид **Dukascopy**

**Цель:** одинаковые, надёжные зоны на всех брокерах, включая локальные (RoboForex, и др.).

---

## 📦 Архитектура

```
MetaTrader 4/5 (MT4/MT5)
    ↓↑ (ZeroMQ или USB/сеть при необходимости)
    ↓
Python Bridge Server (FastAPI, http://localhost:5000)
    ↓↑ (JSON: зоны ← свечи)
    ↓
Zone Detector (многотаймфрейм H1/H4/D1)
    ├─ Data Fetcher → CSV от MT5 + yfinance (GC=F) + Dukascopy
    ├─ Zone Detector → кластеризация + скоринг
    ├─ Broker Normalize → валидация по Dukascopy + оффсет
    └─ Footprint Window (Tk GUI) → визуализация + торговля
```

**Данные:**
- **MT4/MT5:** OHLC в реал-тайме (CSV либо прямой API).
- **Dukascopy:** независимый тиковый фид золота (для валидации).
- **yfinance:** фьючерс GC=F как дополнительный источник.
- **Кэширование:** Parquet в `/cache/` для ускорения (параллельная загрузка Dukascopy).

---

## 🏗️ Структура проекта

```
szp/
├── python_core/             # Основная логика
│   ├── zone_detector.py     (630 строк) — детектор зон, кластеризация, скоринг
│   ├── footprint_data.py    (1029 строк) — профиль объёма + свечи из тиков
│   ├── bridge_server.py     (462 строк) — FastAPI сервер (MT ↔ Python)
│   ├── broker_normalize.py  (176 строк) — [NEW v5.1] валидация по Dukascopy
│   ├── dukascopy_loader.py  (143 строк) — загрузка тиков Dukascopy (кэшированно)
│   ├── data_fetcher.py      (358 строк) — OHLC из CSV/API/yfinance
│   ├── footprint_window.py  (970 строк) — [v5] Tk GUI (Apple-стиль, ZAKREP toggle)
│   ├── config.py            (362 строк) — центральная конфигурация
│   ├── zone_reaction.py     (опц.) — реакция цены (пробой/ретест)
│   ├── main.py              — точка входа
│   ├── requirements.txt      — зависимости
│   └── tests/               (17 файлов, 2002 строк)
│       ├── test_zone_detector.py       (302 строк)
│       ├── test_zone_confirmation.py   (323 строк)
│       ├── test_broker_normalize.py    (69 строк) [NEW v5.1]
│       ├── test_data_fetcher.py        (136 строк)
│       └── ... (ещё 13)
│
├── mql/                     # Индикаторы MetaTrader
│   ├── MT5/Indicators/StrongZones.mq5
│   └── MT4/Indicators/StrongZones.mq4
│
├── installer/               # Inno Setup шаблон
├── .github/workflows/       # CI/CD (GitHub Actions)
│   └── build-turnkey.yml    — автосборка на теги v*.*.* 
├── setup.iss                — Inno Setup конфиг
├── README.md                — основная документация
├── INSTALL.md               — инструкции установки
└── [bat files]              — START_BRIDGE.bat, BUILD_INSTALLER.bat и т.д.
```

---

## 🔑 Ключевые файлы для понимания

| Файл | Строк | Роль |
|------|-------|------|
| **zone_detector.py** | 630 | ⭐ Ядро: кластеризация теней → зоны + скоринг |
| **config.py** | 362 | Параметры (SYMBOL, ZONE_WIDTH, MIN_SCORE, валидация) |
| **bridge_server.py** | 462 | FastAPI: читает CSV → вычисляет зоны → JSON |
| **broker_normalize.py** | 176 | [NEW] Валидация/канон по Dukascopy + сдвиг оффсета |
| **footprint_data.py** | 1029 | Профиль объёма + собирает свечи из тиков |
| **footprint_window.py** | 970 | [UPDATED] Tk GUI, ZAKREP toggle кнопка |
| **test_zone_detector.py** | 302 | Бэктесты: 75% реакции зон vs 29% случайных |

---

## 🚀 Версионирование & Релизы

**Текущая версия:** `v5.1.0` (Latest) — выпущена **2 сентября 2026**  
**Предыдущие:** v5.0.0, v4.2.7 и др.

**CI/CD:** GitHub Actions + Inno Setup
- Тег `v*.*.* ` → **Stable** сборка (MT компиляция + PyInstaller + установщик)
- Ветка `experiment/v*-rc` → **validation** (проверка, но без публикации)

**Установщик:** `SmartZonesPro_Setup_Stable_v5.1.0.exe` (48.2 МБ)  
**Скачать:** [github.com/VadimChudin/szp/releases/tag/v5.1.0](https://github.com/VadimChudin/szp/releases/tag/v5.1.0)

---

## 📋 Что было сделано в последних сеансах

### v5.1.0 — Broker Normalization via Dukascopy

#### 1. Тумблер ZAKREP в футпринте
- **Файл:** `footprint_window.py` (новая кнопка в тулбаре)
- **Функция:** вкл/выкл метки ZAKREP (закреп за зоной на H1)
- **Изменения:**
  ```javascript
  let showZakrep = true;
  <button id="zk-btn" onclick="toggleZakrep()">ZAKREP</button>
  if (showZakrep && z.reaction && z.reaction.type === 'BREAKOUT') { ... }
  ```
- **Статус:** ✅ Коммит `b95ee12`

#### 2. Валидация зон по Dukascopy (новый модуль)
- **Файл:** `broker_normalize.py` (176 строк, новый)
- **Задача:** одинаковые зоны на всех брокерах, независимо от спреда
- **Режимы работы** (конфиг `VALIDATION_MODE`):
  1. **`validate`** (по умолчанию) — сохраняет только брокерские зоны, подтверждённые Dukascopy (допуск $5, настраивается)
  2. **`canonical`** — зоны считаются **целиком по Dukascopy** → идентичны на всех брокерах
  3. **`off`** — отключить валидацию (как раньше)
  
- **Best-effort:** если Dukascopy недоступен, расчёт не падает — возвращает брокерские зоны

#### 3. Нормализация оффсета брокера
- **Флаг:** `BROKER_OFFSET_ENABLED` (по умолчанию включен)
- **Логика:** линия зоны сдвигается на `(цена брокера − цена Dukascopy)`
  - У RoboForex XAUUSD ≈ спот, оффсет < $1
  - Но сдвиг гарантирует, что зона лежит **точно на графике брокера**
  - Никакого расхождения между брокерами → один набор зон везде
  
#### 4. Конфигурация
- **Новые переменные в `config.py`:**
  ```python
  VALIDATION_MODE = validate | canonical | off
  VALIDATION_TOLERANCE = 5.0  # $ (допуск совпадения зон)
  BROKER_OFFSET_ENABLED = True
  DUKA_SYMBOL = "XAUUSD"
  DUKA_DAYS = 5
  ```

#### 5. Интеграция в pipeline
- **Файл:** `bridge_server.py` (строка 214+)
- **Процесс:**
  ```python
  zones = detect_zones(data)
  zones = update_snapshot(zones, data)
  # NEW ↓
  zones = normalize_broker_zones(zones, data)  # валидация/канон + оффсет
  ```
- **Асинхронность:** зоны применяются **после** snapshot, **перед** JSON export

#### 6. Тестирование
- **Новый файл:** `test_broker_normalize.py` (69 строк)
- **Тесты (7 новых):**
  - `test_validate_keeps_matching` — валидация фильтрует неподтвержденные
  - `test_validate_empty_canonical` — best-effort без эталона
  - `test_compute_offset` — расчёт оффсета
  - `test_shift_zone_applies_offset` — применение сдвига
  - `test_current_price` — извлечение текущей цены
  - `test_config_defaults` — дефолты конфига
  
- **Статус:** ✅ 191 тест (17 файлов), все зелёные

#### 7. CI/CD & Релиз
- **Валидационная сборка** (`experiment/v5.1-rc`): ✅ success (шаги 1–16)
  - Python тесты (191/191 passed)
  - MQL5 компиляция ✅
  - MQL4 компиляция ✅
  - PyInstaller → SmartZonesPro.exe ✅
  - Inno Setup → установщик ✅
  
- **Стабильная сборка** (тег `v5.1.0`): ✅ success (шаги 1–16)
  - Установщик собран: `SmartZonesPro_Setup_Stable_v5.1.0.exe` (48.2 МБ)
  - Релиз опубликован как Latest (не draft)
  
- **Коммиты в main:**
  - `628660d` — Broker-normalized zones via Dukascopy + footprint ZAKREP toggle
  - `b95ee12` — Footprint: add ZAKREP on/off toggle button

---

## ⚙️ Как запустить локально

### 1. Установка зависимостей
```bash
cd python_core
pip install -r requirements.txt
```

### 2. Запуск bridge server
```bash
python bridge_server.py
```
Запустится на `http://localhost:5000`

### 3. Запуск footprint GUI
```bash
python footprint_window.py
```

### 4. Запуск бэктестов
```bash
pytest tests/ -q
# или конкретный тест:
pytest tests/test_zone_detector.py -v
```

### 5. Конфигурация
**Переменные окружения** (`.env` или системные):
```bash
SYMBOL=XAUUSD
ZONE_WIDTH=0.5
MIN_ZONE_SCORE=10
VALIDATION_MODE=validate        # validate | canonical | off
VALIDATION_TOLERANCE=5.0        # $
BROKER_OFFSET_ENABLED=true
DUKA_SYMBOL=XAUUSD
DUKA_DAYS=5
```

---

## 🔧 Что нужно добавить / улучшить в будущем

### High Priority (для полноты)

1. **Документация по Dukascopy API**
   - Текущий: `dukascopy_loader.py` работает, но без docstrings
   - Нужно: расширить документацию по кэшированию и форматам данных

2. **Тестирование Dukascopy fallback**
   - Текущий: best-effort логика есть, но не протестирована в реальности
   - Нужно: интеграционные тесты (mock Dukascopy unavailable)

3. **UI улучшения footprint_window**
   - ZAKREP кнопка добавлена, но нет переключения для других режимов реакции
   - Возможно: добавить dropdown для `VALIDATION_MODE` выбора прямо в GUI

4. **Экспорт настроек**
   - Текущий: конфиг只 через .env
   - Нужно: сохранение последнего выбранного режима в localStorage / конфиг-файл

### Medium Priority

5. **Оптимизация Dukascopy loader**
   - Текущий: параллельная загрузка (5 воркеров)
   - Нужно: кэширование по дате (не переливать кэш каждый день)

6. **Нормализация данных из разных источников**
   - Текущий: Dukascopy + yfinance + CSV
   - Нужно: детальная обработка расхождений между источниками

7. **Реакция зон в MT4/MT5**
   - Текущий: MT показывает зоны, но реакция рассчитывается в Python
   - Нужно: синхронизация реакции с индикатором MT

### Low Priority (Nice to Have)

8. **Telegram/Email alerts** при образовании новой сильной зоны
9. **Ночной бэктест** на недельной основе с отправкой отчёта
10. **WebSocket live streaming** зон вместо polling CSV

---

## 📊 Статистика

| Метрика | Значение |
|---------|----------|
| **Python строк кода** | ~5,500 (core + tests) |
| **Модулей** | 36 (активные + legacy) |
| **Тестов** | 191 (17 файлов, 2002 строк) |
| **Тестовое покрытие** | ~80% (основная логика) |
| **Производительность** | Зоны вычисляются за <1 сек на 2+ года истории |
| **Эффективность зон** | 75% реакции (vs 29% случайных уровней) |

---

## 🎓 Контекст для нового агента

### Если ты берёшься за улучшение:

1. **Перед любым коммитом:** запусти `pytest tests/ -q` — все 191 тест должны быть зелёными
2. **Новая фича для брокера?** → обнови `config.py` и добавь тест в `test_broker_normalize.py`
3. **Изменение в зонах?** → проверь影响на `zone_detector.py` тесты и бэктесты
4. **MQL изменение?** → коммит в `main`, тег `v*.*.* `, CI сам скомпилирует
5. **Для локального тестирования MT:** используй `START_BRIDGE.bat` и `START_FOOTPRINT.bat`

### Главные файлы для чтения:

1. **zone_detector.py** — как считаются зоны (самое важное)
2. **config.py** — где все параметры, куда добавлять новые флаги
3. **bridge_server.py** — как данные текут из MT в Python и обратно
4. **broker_normalize.py** — новый функционал валидации

---

## 🔗 Ссылки

- **GitHub:** https://github.com/VadimChudin/szp
- **Релизы:** https://github.com/VadimChudin/szp/releases
- **Текущий релиз:** v5.1.0 (Latest)
- **Текущий коммит:** `628660d` (main)

---

**Статус на 2 сентября 2026:** ✅ Production-ready, последний релиз v5.1.0 с валидацией по Dukascopy и нормализацией оффсета брокера.
