"""
download_real_data.py — Загрузка реальных данных XAU/USD через yfinance.

Gold Futures (GC=F) используется как прокси для XAU/USD.
Сохраняет CSV файлы для H1, H4, D1 в папку data/.
"""

import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

import paths

OUTPUT_DIR = paths.LOCAL_DATA_DIR
SYMBOL = "GC=F"  # Gold Futures (прокси для XAU/USD)


def download_and_save():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Downloading {SYMBOL} data from Yahoo Finance...")

    # ── H1 (1h) — yfinance дает максимум 730 дней для часовых ──
    print("\n[H1] Downloading hourly data...")
    h1 = yf.download(SYMBOL, period="60d", interval="1h", progress=False)
    if not h1.empty:
        h1_df = h1.reset_index()
        # Flatten MultiIndex columns if present
        if hasattr(h1_df.columns, 'get_level_values'):
            h1_df.columns = [c[0] if isinstance(c, tuple) else c for c in h1_df.columns]
        h1_df.rename(columns={
            'Datetime': 'time', 'Date': 'time',
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'tick_volume'
        }, inplace=True)
        # Ensure 'time' column exists
        if 'time' not in h1_df.columns:
            for col in h1_df.columns:
                if 'date' in col.lower() or 'time' in col.lower():
                    h1_df.rename(columns={col: 'time'}, inplace=True)
                    break
        cols = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
        available = [c for c in cols if c in h1_df.columns]
        h1_df = h1_df[available]
        h1_df.to_csv(OUTPUT_DIR / "XAUUSD_H1.csv", index=False)
        print(f"  H1: {len(h1_df)} bars saved ({h1_df['time'].iloc[0]} -> {h1_df['time'].iloc[-1]})")

    # ── H4 (yfinance не поддерживает 4h напрямую, ресемплим из H1) ──
    print("\n[H4] Resampling from H1...")
    if not h1.empty:
        # Flatten MultiIndex columns
        h1_flat = h1.copy()
        if isinstance(h1_flat.columns, pd.MultiIndex):
            h1_flat.columns = [c[0] for c in h1_flat.columns]
        h4 = h1_flat.resample('4h').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()
        h4_df = h4.reset_index()
        h4_df.rename(columns={
            'Datetime': 'time', 'Date': 'time',
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'tick_volume'
        }, inplace=True)
        if 'time' not in h4_df.columns:
            for col in h4_df.columns:
                if 'date' in col.lower() or 'time' in col.lower():
                    h4_df.rename(columns={col: 'time'}, inplace=True)
                    break
        cols = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
        available = [c for c in cols if c in h4_df.columns]
        h4_df = h4_df[available]
        h4_df.to_csv(OUTPUT_DIR / "XAUUSD_H4.csv", index=False)
        print(f"  H4: {len(h4_df)} bars saved ({h4_df['time'].iloc[0]} -> {h4_df['time'].iloc[-1]})")

    # ── D1 (1d) — берем за полгода ──
    print("\n[D1] Downloading daily data...")
    d1 = yf.download(SYMBOL, period="6mo", interval="1d", progress=False)
    if not d1.empty:
        d1_df = d1.reset_index()
        if hasattr(d1_df.columns, 'get_level_values'):
            d1_df.columns = [c[0] if isinstance(c, tuple) else c for c in d1_df.columns]
        d1_df.rename(columns={
            'Datetime': 'time', 'Date': 'time',
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'tick_volume'
        }, inplace=True)
        if 'time' not in d1_df.columns:
            for col in d1_df.columns:
                if 'date' in col.lower() or 'time' in col.lower():
                    d1_df.rename(columns={col: 'time'}, inplace=True)
                    break
        cols = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
        available = [c for c in cols if c in d1_df.columns]
        d1_df = d1_df[available]
        d1_df.to_csv(OUTPUT_DIR / "XAUUSD_D1.csv", index=False)
        print(f"  D1: {len(d1_df)} bars saved ({d1_df['time'].iloc[0]} -> {d1_df['time'].iloc[-1]})")

    print(f"\nAll data saved to: {OUTPUT_DIR}")
    print("Files:")
    for f in OUTPUT_DIR.glob("*.csv"):
        print(f"  {f.name} ({f.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    download_and_save()
