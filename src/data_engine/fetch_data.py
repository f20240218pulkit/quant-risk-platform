import sys

# Windows WMI Query bypass trick
if sys.platform == "win32":
    import platform

    platform.win32_ver = lambda *args, **kwargs: (
        "10",
        "10.0.build",
        "",
        "multiprocessor",
    )

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_market_data(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetches historical market data for a given ticker, cleans it,

    and calculates simple and log daily returns.
    Handles upstream API shifts defensively.
    """
    print(f"[*] Fetching data for {ticker} from {start} to {end}...")

    # 1. Ingest Data
    # We explicitly pass auto_adjust=False to ask for the raw 'Adj Close' column.
    df = yf.download(ticker, start=start, end=end, auto_adjust=False)

    if df.empty:
        raise ValueError(
            f"No data found for ticker '{ticker}'. Check symbol or dates."
        )

    # 2. Handle MultiIndex Column Structural Shifts
    # If columns look like [('Close', 'AAPL'), ...], extract just the price metric level ('Close')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 3. Defensive Column Check
    # If 'Adj Close' is missing because of an internal library override,
    # then 'Close' is already adjusted. We clone it to keep our pipeline uniform.
    if "Adj Close" not in df.columns:
        if "Close" in df.columns:
            print(
                "[!] 'Adj Close' column missing. Falling back to 'Close' as adjusted proxy."
            )
            df["Adj Close"] = df["Close"]
        else:
            raise KeyError(
                f"Critical Error: Neither 'Adj Close' nor 'Close' found. Columns present: {list(df.columns)}"
            )

    # 4. Standardize and copy columns safely
    keep_cols = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    df = df[keep_cols].copy()

    # 5. Quantitative Calculations
    df["Simple_Return"] = df["Adj Close"].pct_change()
    df["Log_Return"] = np.log(df["Adj Close"] / df["Adj Close"].shift(1))

    # Drop the first row containing NaN values from the return calculations
    df = df.dropna()

    return df


import os

if __name__ == "__main__":
    TICKER = "AAPL"
    START_DATE = "2020-01-01"
    END_DATE = "2025-01-01"

    try:
        # 1. Fetch and process
        data = fetch_market_data(TICKER, START_DATE, END_DATE)

        # 2. Define standard storage architecture paths
        # This resolves paths relative to where this script is, ensuring cross-OS safety
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        output_filename = f"{TICKER.lower()}_processed.csv"
        output_path = os.path.join(data_dir, output_filename)

        # 3. Write data to local cache disk
        data.to_csv(output_path)
        print(f"\n[+] Success! Cached processed data locally at: {output_path}")

        print("\n--- DATA PROCESSING VERIFICATION ---")
        print(f"Data Shape: {data.shape}")
        print("\nFirst 3 rows:")
        print(data[["Adj Close", "Simple_Return", "Log_Return"]].head(3))

    except Exception as e:
        print(f"[ERROR] Failed to execute data engine: {e}")