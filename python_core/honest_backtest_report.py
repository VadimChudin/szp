"""Собирает наглядный отчёт по двум прогонам honest_backtest (12ч и 48ч)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

GROUPS = ["zones", "random", "round"]
TITLES = {"zones": "Зоны SZP", "random": "Случайные уровни", "round": "Круглые числа"}
COLORS = {"zones": "#d92b2b", "random": "#7a7a7a", "round": "#b58a2b"}


def two_p(s1: int, n1: int, s2: int, n2: int) -> float:
    if not n1 or not n2:
        return 1.0
    pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return math.erfc(abs((s1 / n1 - s2 / n2) / se) / math.sqrt(2))


def bounce_curve(levels: pd.DataFrame, thresholds: list[float]) -> dict:
    touched = levels[levels["touched"]]
    out = {}
    for group in GROUPS:
        part = touched[touched["group"] == group]
        out[group] = [
            (int(((part["outcome"] == "bounce") & (part["excursion"] >= x)).sum()), len(part))
            for x in thresholds
        ]
    return out


def build(runs: dict[str, Path], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    thresholds = [0.75, 1.0, 1.5, 2.0, 2.5, 3.0]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    fig.patch.set_facecolor("white")
    lines: list[str] = []

    lines.append("# Честный бэктест зон Smart Zones Pro\n")
    first_meta = json.loads(next(iter(runs.values())).joinpath("honest_backtest.json").read_text(encoding="utf-8"))["meta"]
    lines.append(f"- Данные: **{first_meta['source']}**")
    lines.append(f"- Период: {first_meta['period'][0]} … {first_meta['period'][1]}")
    lines.append(f"- Свечей: H1 {first_meta['rows']['H1']}, H4 {first_meta['rows']['H4']}, D1 {first_meta['rows']['D1']}")
    lines.append(f"- Отбор зон: MIN_ZONE_SCORE={first_meta['min_zone_score']}, "
                 f"STRONG_ZONES_ONLY={first_meta['strong_zones_only']}, "
                 f"коридор {first_meta['max_zone_distance_pips']:.0f} пипсов")
    lines.append("- Зоны строятся только по прошлым свечам, исход считается только по будущим.")
    lines.append("- Контроль: случайные уровни и круглые числа в том же коридоре, те же правила.\n")

    # ── График 1: доходит ли цена до уровня ──
    ax = axes[0]
    width = 0.35
    for offset, (label, path) in zip((-width / 2, width / 2), runs.items()):
        report = json.loads((path / "honest_backtest.json").read_text(encoding="utf-8"))
        vals = [report["groups"][g]["touch_rate"] * 100 for g in GROUPS]
        ax.bar([i + offset for i in range(len(GROUPS))], vals, width,
               label=label, edgecolor="black", linewidth=0.6,
               color=["#d92b2b" if offset < 0 else "#f08a8a",
                      "#7a7a7a" if offset < 0 else "#b8b8b8",
                      "#b58a2b" if offset < 0 else "#d9bd77"])
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels([TITLES[g] for g in GROUPS], fontsize=9)
    ax.set_ylabel("% уровней, до которых цена дошла")
    ax.set_title("Доходит ли цена до уровня")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # ── График 2: реакция при касании ──
    ax = axes[1]
    for offset, (label, path) in zip((-width / 2, width / 2), runs.items()):
        report = json.loads((path / "honest_backtest.json").read_text(encoding="utf-8"))
        vals = [report["groups"][g]["reaction_rate_given_touch"] * 100 for g in GROUPS]
        ax.bar([i + offset for i in range(len(GROUPS))], vals, width, label=label,
               edgecolor="black", linewidth=0.6,
               color=["#d92b2b" if offset < 0 else "#f08a8a",
                      "#7a7a7a" if offset < 0 else "#b8b8b8",
                      "#b58a2b" if offset < 0 else "#d9bd77"])
    ax.set_xticks(range(len(GROUPS)))
    ax.set_xticklabels([TITLES[g] for g in GROUPS], fontsize=9)
    ax.set_ylabel("% реакций среди коснувшихся")
    ax.set_ylim(0, 100)
    ax.set_title("Реакция, если цена дошла\n(контроль реагирует так же)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    # ── График 3: чистый отскок по силе ухода ──
    ax = axes[2]
    label, path = list(runs.items())[-1]
    levels = pd.read_csv(path / "honest_backtest_levels.csv")
    curve = bounce_curve(levels, thresholds)
    for group in GROUPS:
        ys = [hit / total * 100 if total else 0 for hit, total in curve[group]]
        ax.plot(thresholds, ys, marker="o", color=COLORS[group], label=TITLES[group])
    ax.set_xlabel("Порог ухода от уровня, в ATR")
    ax.set_ylabel("% чистых отскоков среди коснувшихся")
    ax.set_title(f"Сила отскока ({label})")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.suptitle("Зоны против контрольных групп: реакция сама по себе не даёт преимущества",
                 fontsize=13, y=1.02)
    fig.tight_layout()
    chart = out_dir / "honest_backtest.png"
    fig.savefig(chart, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── Таблицы ──
    for label, path in runs.items():
        report = json.loads((path / "honest_backtest.json").read_text(encoding="utf-8"))
        lines.append(f"\n## Горизонт {label}\n")
        lines.append("| Группа | Уровней | Цена дошла | Дошла, % | Реакция при касании | 95% ДИ | Отскок | Закреп | Консолидация |")
        lines.append("|---|---:|---:|---:|---:|---|---:|---:|---:|")
        for group in GROUPS:
            block = report["groups"][group]
            lines.append(
                f"| {TITLES[group]} | {block['levels']} | {block['touched']} | "
                f"{block['touch_rate']*100:.1f}% | {block['reaction_rate_given_touch']*100:.1f}% | "
                f"{block['ci95'][0]*100:.1f}–{block['ci95'][1]*100:.1f}% | "
                f"{block['bounce']} | {block['breakout']} | {block['consolidation']} |")
        sig = report.get("significance", {})
        lines.append(f"\nЗначимость разницы с контролем: p(зоны vs случайные) = "
                     f"{sig.get('zones_vs_random_p')}, p(зоны vs круглые) = {sig.get('zones_vs_round_p')}.")

        levels = pd.read_csv(path / "honest_backtest_levels.csv")
        curve = bounce_curve(levels, thresholds)
        lines.append(f"\n### Чистый отскок по порогу ухода (горизонт {label})\n")
        lines.append("| Порог, ATR | Зоны | Случайные | Круглые | p (зоны vs случайные) |")
        lines.append("|---:|---:|---:|---:|---:|")
        for i, x in enumerate(thresholds):
            z, r, o = curve["zones"][i], curve["random"][i], curve["round"][i]
            p = two_p(z[0], z[1], r[0], r[1])
            lines.append(f"| {x:.2f} | {z[0]}/{z[1]} ({z[0]/z[1]*100:.1f}%) | "
                         f"{r[0]}/{r[1]} ({r[0]/r[1]*100:.1f}%) | "
                         f"{o[0]}/{o[1]} ({o[0]/o[1]*100:.1f}%) | {p:.4f} |")

    (out_dir / "HONEST_BACKTEST.md").write_text("\n".join(lines), encoding="utf-8")
    print("report:", out_dir / "HONEST_BACKTEST.md")
    print("chart:", chart)


if __name__ == "__main__":
    build({"12 часов": Path(__file__).resolve().parent.parent / "output", "48 часов": Path(__file__).resolve().parent.parent / "output" / "h48"},
          Path(__file__).resolve().parent.parent / "docs")
