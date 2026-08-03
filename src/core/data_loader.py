import yfinance as yf
import pandas as pd
import numpy as np
from typing import List, Tuple, Optional

def fetch_portfolio_data(
    tickers: List[str],
    start_date: str = "2020-01-01",
    end_date: Optional[str] = None
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetches historical adjusted close prices for a portfolio of tickers 
    and computes daily percentage returns.
    
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (prices_df, returns_df)
    """
    # Sanitize ticker inputs
    cleaned_tickers = [t.strip().upper() for t in tickers]
    
    # Fetch historical price data
    raw_data = yf.download(
        tickers=cleaned_tickers, 
        start=start_date, 
        end=end_date, 
        progress=False
    )
    
    # Extract Adjusted Close prices (fallback to Close if Adj Close isn't present)
    if "Adj Close" in raw_data:
        prices = raw_data["Adj Close"]
    elif "Close" in raw_data:
        prices = raw_data["Close"]
    else:
        prices = raw_data

    # Handle edge case when requesting a single ticker (returns Series instead of DataFrame)
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=cleaned_tickers[0])
        
    # Data cleaning: forward-fill missing trading days and drop empty rows
    prices = prices.ffill().dropna()
    
    # Compute daily arithmetic percentage returns
    returns = prices.pct_change().dropna()
    
    return prices, returns

if __name__ == "__main__":
    # Test fetch with a multi-asset allocation portfolio
    test_tickers = ["AAPL", "MSFT", "NVDA", "SPY", "GLD"]
    print(f"Fetching market data for: {', '.join(test_tickers)}...")
    
    prices, returns = fetch_portfolio_data(test_tickers, start_date="2023-01-01")
    
    print("\n--- LATEST DAILY PRICES ---")
    print(prices.tail())
    
    print("\n--- LATEST DAILY RETURNS ---")
    print(returns.tail())
    
    print(f"\nSuccessfully downloaded {len(prices)} trading days of data.")