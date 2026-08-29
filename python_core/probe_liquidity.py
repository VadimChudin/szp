"""
probe_liquidity.py — Диагностика источников ликвидности.

Запускать ПЕРЕД тем, как включать подтверждение в боевом режиме. Скрипт не
меняет ни одного файла и ничего не рисует: он только спрашивает у терминала
и у сети, что реально доступно, и печатает ответ.

Зачем нужен отдельный скрипт: доступность стакана и тиков зависит от брокера,
счёта и региона, а не от кода. Гадать здесь нельзя — можно только замерить.
Результат этого замера определяет, какой режим подтверждения имеет смысл
включать.

Запуск:
    python probe_liquidity.py
"""

from __future__ import annotations

import sys
from datetime import datetime

import config


LINE = "─" * 78


def head(title: str) -> None:
    print()
    print(LINE)
    print(f"  {title}")
    print(LINE)


def probe_terminal() -> bool:
    head("1. Терминал MetaTrader 5")
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("  ✗ пакет MetaTrader5 не установлен (pip install MetaTrader5)")
        return False

    if not mt5.initialize():
        print(f"  ✗ initialize() не прошёл: {mt5.last_error()}")
        print("    Терминал должен быть запущен и залогинен.")
        return False

    info = mt5.terminal_info()
    acc = mt5.account_info()
    print(f"  ✓ подключено: {getattr(info, 'name', '?')} build {getattr(info, 'build', '?')}")
    if acc:
        print(f"    брокер: {acc.company}   сервер: {acc.server}")

    from data_fetcher import resolve_mt5_symbol
    resolved = resolve_mt5_symbol(config.SYMBOL)
    if resolved:
        si = mt5.symbol_info(resolved)
        print(f"  ✓ символ: {resolved}  digits={getattr(si, 'digits', '?')}  "
              f"point={getattr(si, 'point', '?')}")
    else:
        print(f"  ✗ символ {config.SYMBOL} у брокера не найден")

    mt5.shutdown()
    return bool(resolved)


def probe_dom_source() -> None:
    head("2. Стакан (Depth of Market)")
    from liquidity_source import probe_dom

    r = probe_dom()
    if r["available"]:
        print(f"  ✓ стакан доступен: {r['levels']} уровней")
        for lvl in r["sample"]:
            side = "BID" if lvl["type"] in (1, 2) else "ASK"
            print(f"      {side}  ${lvl['price']:.2f}  x{lvl['volume']:.2f}")
        print()
        print("    Брокер отдаёт книгу заявок — редкий случай для CFD на золото.")
        print("    Её можно подмешать в подтверждение БЛИЖНИХ зон (до ~50 пипсов).")
        print("    Для дальних зон книга бесполезна: лимиты туда не выставляют.")
    else:
        print(f"  ✗ стакана нет: {r['reason']}")
        print()
        print("    Это ожидаемо. Ритейл-брокер не биржа, книгу заявок по CFD")
        print("    он не публикует. Подтверждение строится не на стакане, а на")
        print("    профиле реально проторгованного объёма — см. пункт 3.")


def probe_ticks() -> bool:
    head("3. Тиковая история")
    from liquidity_source import fetch_ticks_mt5

    t0 = datetime.now()
    ticks = fetch_ticks_mt5()
    elapsed = (datetime.now() - t0).total_seconds()

    if ticks is None or ticks.empty:
        print(f"  ✗ тиков нет (запрос занял {elapsed:.1f}с)")
        print("    Профиль будет строиться по свечам — грубее, но работает.")
        return False

    directional = (ticks["direction"] != "NEUTRAL").sum()
    print(f"  ✓ получено {len(ticks):,} тиков за {config.TICK_HISTORY_DAYS} дн "
          f"({elapsed:.1f}с)")
    print(f"    период: {ticks['time'].min()} — {ticks['time'].max()}")
    print(f"    цена:   ${ticks['price'].min():.2f} — ${ticks['price'].max():.2f}")
    print(f"    с направлением агрессора: {directional:,} "
          f"({directional / len(ticks):.0%})")

    if directional / max(len(ticks), 1) < 0.3:
        print()
        print("    Агрессор определяется редко — проверка по дельте будет")
        print("    в основном нейтральной. Это не поломка, а свойство фида.")
    return True


def probe_profile(has_ticks: bool) -> None:
    head("4. Профиль объёма")
    from data_fetcher import fetch_all_timeframes
    from liquidity_source import build_liquidity_profile

    try:
        data = fetch_all_timeframes(config.SYMBOL)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ свечи не получены: {e}")
        return

    profile = build_liquidity_profile(data)
    if profile is None:
        print("  ✗ профиль не построен")
        return

    val, vah = profile.value_area()
    nodes = profile.nodes(config.HVN_RATIO, config.LVN_RATIO)
    print(f"  ✓ источник: {profile.source}")
    print(f"    строк: {profile.prices.size} по ${profile.row_height:.2f}")
    print(f"    POC: ${profile.poc:.2f}")
    print(f"    Value Area (70%): ${val:.2f} — ${vah:.2f}")
    print(f"    HVN: {len(nodes['hvn'])} уровней   LVN: {len(nodes['lvn'])} уровней")

    if not has_ticks:
        print()
        print("    Профиль построен по свечам: объём каждой свечи размазан по")
        print("    её диапазону. Крупные узлы он показывает верно, тонкую")
        print("    структуру — нет. Дельта в этом режиме недоступна.")


def probe_pools() -> None:
    head("5. Пулы ликвидности (равные экстремумы)")
    from data_fetcher import fetch_all_timeframes
    from zone_confirmation import find_liquidity_pools

    try:
        data = fetch_all_timeframes(config.SYMBOL)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ свечи не получены: {e}")
        return

    df = data.get("H4")
    if df is None or df.empty:
        print("  ✗ нет H4")
        return

    pools = find_liquidity_pools(df)
    fresh = [p for p in pools if not p["swept"]]
    print(f"  ✓ найдено {len(pools)} пулов, из них неснятых: {len(fresh)}")
    for p in sorted(fresh, key=lambda x: -x["touches"])[:10]:
        kind = "над ценой (стопы шортов)" if p["kind"] == "high" else "под ценой (стопы лонгов)"
        print(f"      ${p['level']:>9.2f}  касаний {p['touches']}  {kind}")


def probe_binance() -> None:
    head("6. Binance (для справки)")
    try:
        import requests
        r = requests.get(f"{config.BINANCE_BASE_URL}/fapi/v1/ticker/price",
                         params={"symbol": config.BINANCE_SYMBOL}, timeout=10)
        if r.status_code == 451:
            print("  ✗ HTTP 451 — доступ заблокирован по региону")
            print("    Источник нерабочий, в подтверждении не участвует.")
        elif r.status_code == 200:
            print(f"  ✓ доступен: {r.json()}")
        else:
            print(f"  ✗ HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ недоступен: {e}")


def main() -> int:
    print()
    print("=" * 78)
    print(f"  ДИАГНОСТИКА ИСТОЧНИКОВ ЛИКВИДНОСТИ — {config.SYMBOL}")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 78)

    ok = probe_terminal()
    if ok:
        probe_dom_source()
        has_ticks = probe_ticks()
    else:
        has_ticks = False
        print("\n  Терминал недоступен — проверки 2 и 3 пропущены.")

    probe_profile(has_ticks)
    probe_pools()
    probe_binance()

    head("ВЫВОД")
    if has_ticks:
        print("  Тики есть → LIQUIDITY_SOURCE=auto даст профиль по тикам.")
        print("  Это лучший доступный режим, дельта будет считаться.")
    else:
        print("  Тиков нет → профиль строится по свечам.")
        print("  Проверка по узлам объёма работает, проверка по дельте — нет.")
    print()
    print("  Порядок действий:")
    print("    1) CONFIRMATION_MODE=annotate — посмотреть цифры, ничего не меняя")
    print("    2) сверить вердикты с тем, как зоны отработали на графике")
    print("    3) откалибровать HVN_RATIO / пороги под свой инструмент")
    print("    4) только потом включать filter или rerank")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
