import os
import numpy as np
import pandas as pd


def load_processed_data(ticker: str) -> pd.DataFrame:
    """Loads cached processed market data from the local data directory."""
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    file_path = os.path.join(base_dir, "data", f"{ticker.lower()}_processed.csv")

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"No cached data found at {file_path}. Run fetch_data.py first."
        )

    # FIX: Tell pandas to look at index position 0 instead of searching for a literal "Date" column header string
    df = pd.read_csv(file_path, parse_dates=True, index_col=0)

    # Standardize the index name so subsequent code knows it's our timeline
    df.index.name = "Date"

    return df


def calculate_rolling_vol(df: pd.DataFrame, window: int = 21) -> pd.Series:
    """Calculates simple rolling standard deviation (volatility)

    and annualizes it. Standard window is 21 trading days (~1 month).
    """
    daily_vol = df["Log_Return"].rolling(window=window).std()
    annualized_vol = daily_vol * np.sqrt(252)
    return annualized_vol


def calculate_ewma_vol(df: pd.DataFrame, lam: float = 0.94) -> pd.Series:
    """Calculates Exponentially Weighted Moving Average (EWMA) volatility

    using a decay factor (lambda). Standard lambda is 0.94.
    """
    alpha = 1 - lam
    daily_variance = (
        df["Log_Return"].pow(2).ewm(alpha=alpha, adjust=False).mean()
    )
    daily_vol = np.sqrt(daily_variance)
    annualized_vol = daily_vol * np.sqrt(252)
    return annualized_vol


if __name__ == "__main__":
    TICKER = "AAPL"

    try:
        print(f"[*] Loading cached data for {TICKER}...")
        data = load_processed_data(TICKER)

        data["Rolling_Vol_21d"] = calculate_rolling_vol(data, window=21)
        data["EWMA_Vol_94"] = calculate_ewma_vol(data, lam=0.94)

        print("\n--- VOLATILITY ANALYSIS VERIFICATION ---")
        clean_summary = data[["Rolling_Vol_21d", "EWMA_Vol_94"]].dropna()

        print("\nLatest Risk Profiles (Most Recent Trading Days):")
        print(clean_summary.tail(5))

        print("\nStatistical Summary of Annualized Volatility:")
        print(clean_summary.describe())

    except Exception as e:
        print(f"[ERROR] Volatility engine failure: {e}")