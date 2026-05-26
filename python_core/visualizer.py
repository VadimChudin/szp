"""
visualizer.py — Визуализация зон на свечном графике.

Используется для:
  1. Отладки алгоритма (проверка зон на исторических данных)
  2. Генерации скриншотов для заказчика (proof-of-concept)
  3. Экспорта интерактивных графиков

Зависимости: mplfinance, matplotlib
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Headless mode (для серверов без GUI)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
from datetime import datetime

import config

# Пробуем импортировать mplfinance
try:
    import mplfinance as mpf
    MPF_AVAILABLE = True
except ImportError:
    MPF_AVAILABLE = False
    print("[visualizer] WARN: mplfinance not installed, using basic matplotlib.")


def plot_zones_mplfinance(
    df: pd.DataFrame,
    zones: list,
    title: str = "Smart Zones Pro — XAU/USD",
    save_path: str = None,
    show: bool = False,
    timeframe_label: str = "H4",
) -> str:
    """
    Рисует свечной график с накладными зонами через mplfinance.

    Args:
        df: OHLC DataFrame (нужен DatetimeIndex)
        zones: list[Zone] из zone_detector
        title: Заголовок графика
        save_path: Путь для сохранения PNG (если None — авто-генерация)
        show: Показать окно (для десктопа)
        timeframe_label: Подпись таймфрейма

    Returns:
        str: Путь к сохранённому файлу
    """
    if not MPF_AVAILABLE:
        return plot_zones_basic(df, zones, title, save_path)

    # Подготовка DataFrame для mplfinance (нужен DatetimeIndex)
    plot_df = df.copy()
    if 'time' in plot_df.columns:
        plot_df.set_index('time', inplace=True)
    if not isinstance(plot_df.index, pd.DatetimeIndex):
        plot_df.index = pd.to_datetime(plot_df.index)
    # mplfinance ожидает колонку 'volume', а у нас 'tick_volume'
    if 'tick_volume' in plot_df.columns and 'volume' not in plot_df.columns:
        plot_df.rename(columns={'tick_volume': 'volume'}, inplace=True)

    # Стиль графика — тёмная тема как в MT4
    mc = mpf.make_marketcolors(
        up='#26a69a',       # Зелёные бычьи свечи
        down='#ef5350',     # Красные медвежьи
        edge='inherit',
        wick='inherit',
        volume='in',
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style='nightclouds',
        figcolor='#1a1a2e',
        facecolor='#16213e',
        gridcolor='#2a2a4a',
        gridstyle='--',
        gridaxis='both',
        y_on_right=True,
        rc={
            'font.size': 9,
            'axes.labelcolor': '#e0e0e0',
            'xtick.color': '#e0e0e0',
            'ytick.color': '#e0e0e0',
        }
    )

    # Рисуем зоны как горизонтальные полосы (hlines / fill_between)
    hlines_prices = []
    hlines_colors = []
    for zone in zones:
        if zone.score >= 9:
            color = config.ZONE_COLOR_STRONG
        elif zone.score >= 7:
            color = config.ZONE_COLOR_MEDIUM
        else:
            color = config.ZONE_COLOR_WEAK
        hlines_prices.append(zone.price)
        hlines_colors.append(color)

    # Настройка hlines
    hline_kwargs = {}
    if hlines_prices:
        hline_kwargs = dict(
            hlines=dict(
                hlines=hlines_prices,
                colors=hlines_colors,
                linewidths=[2 if z.score >= 9 else 1.5 for z in zones],
                linestyle=['-' if z.score >= 9 else '--' for z in zones],
                alpha=0.8,
            )
        )

    # Сохранение
    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir = Path(r"d:\smart-zones-pro\output")
        save_dir.mkdir(exist_ok=True)
        save_path = str(save_dir / f"zones_{timeframe_label}_{timestamp}.png")

    fig, axes = mpf.plot(
        plot_df,
        type='candle',
        style=style,
        title=f"\n{title} ({timeframe_label})",
        ylabel='Price ($)',
        volume=('tick_volume' in plot_df.columns),
        figsize=(18, 10),
        returnfig=True,
        **hline_kwargs,
    )

    # Добавляем зоны-прямоугольники (полупрозрачные полосы ±width)
    ax_main = axes[0]
    for zone in zones:
        if zone.score >= 9:
            color = '#FF0000'
            alpha = 0.15
        elif zone.score >= 7:
            color = '#FF4D4D'
            alpha = 0.10
        else:
            color = '#FF9999'
            alpha = 0.07

        ax_main.axhspan(
            zone.bottom, zone.top,
            color=color, alpha=alpha,
            zorder=0,
        )

        # Подпись зоны (слева)
        ax_main.text(
            0.01, zone.price,
            f" {zone.label}",
            transform=ax_main.get_yaxis_transform(),
            fontsize=8,
            color='white',
            va='center',
            ha='left',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='#333333', alpha=0.7),
            zorder=5,
        )

        # Подсветка фитилей (маркеры на свечах, которые сформировали зону)
        if hasattr(zone, 'wick_points') and zone.wick_points:
            for wp in zone.wick_points:
                wp_time = pd.Timestamp(wp['time'])
                if wp_time in plot_df.index:
                    x_pos = plot_df.index.get_loc(wp_time)
                    marker = 'v' if wp['wick_type'] == 'upper' else '^'
                    # Цвет маркера по таймфрейму
                    mk_color = '#FFD700' if wp['tf'] == 'D1' else '#FFA500' if wp['tf'] == 'H4' else '#FFFF00'
                    ax_main.plot(
                        x_pos, wp['price'],
                        marker=marker,
                        markersize=7,
                        color=mk_color,
                        markeredgecolor='white',
                        markeredgewidth=0.5,
                        zorder=4,
                        alpha=0.9,
                    )

    fig.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    if show:
        plt.show()
    else:
        plt.close(fig)

    print(f"[visualizer] Chart saved to: {save_path}")
    return save_path


def plot_zones_basic(
    df: pd.DataFrame,
    zones: list,
    title: str = "Smart Zones Pro",
    save_path: str = None,
) -> str:
    """
    Fallback-визуализация без mplfinance (простой matplotlib).
    """
    fig, ax = plt.subplots(figsize=(16, 8), facecolor='#1a1a2e')
    ax.set_facecolor('#16213e')

    # Рисуем цену линией
    if 'time' in df.columns:
        x = df['time']
    else:
        x = range(len(df))

    ax.plot(x, df['close'], color='#e0e0e0', linewidth=1, alpha=0.8)
    ax.fill_between(x, df['low'], df['high'], color='#2a2a4a', alpha=0.3)

    # Рисуем зоны
    for zone in zones:
        color = '#FF0000' if zone.score >= 9 else '#FF4D4D'
        ax.axhspan(zone.bottom, zone.top, color=color, alpha=0.15)
        ax.axhline(zone.price, color=color, linewidth=1.5, alpha=0.6)
        ax.text(
            x.iloc[-1] if hasattr(x, 'iloc') else x[-1],
            zone.price,
            f" {zone.label}",
            fontsize=8, color='white', va='center',
        )

    ax.set_title(title, color='white', fontsize=14)
    ax.set_ylabel('Price ($)', color='#e0e0e0')
    ax.tick_params(colors='#e0e0e0')
    ax.grid(True, alpha=0.2)

    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir = Path("./output")
        save_dir.mkdir(exist_ok=True)
        save_path = str(save_dir / f"zones_basic_{timestamp}.png")

    fig.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close(fig)
    print(f"[visualizer] Basic chart saved to: {save_path}")
    return save_path


if __name__ == "__main__":
    from data_fetcher import generate_sample_data
    from zone_detector import detect_zones
    from volume_filter import get_volume_flags_all_tf

    data = generate_sample_data()
    vol_flags = get_volume_flags_all_tf(data)
    zones = detect_zones(data, vol_flags)

    # Рисуем на H4
    path = plot_zones_mplfinance(data["H4"], zones, timeframe_label="H4")
    print(f"Done! Open: {path}")
