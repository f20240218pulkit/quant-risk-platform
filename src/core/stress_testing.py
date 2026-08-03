import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, List, Union

# Historical crisis date windows
CRISIS_SCENARIOS = {
    "2008_GFC": {
        "name": "2008 Great Financial Crisis",
        "start": "2008-09-01",
        "end": "2009-03-09"
    },
    "2020_COVID": {
        "name": "2020 COVID-19 Liquidity Shock",
        "start": "2020-02-19",
        "end": "2020-03-23"
    },
    "2022_INFLATION": {
        "name": "2022 Tech & Rate Hike Sell-Off",
        "start": "2022-01-03",
        "end": "2022-12-30"
    }
}

def run_stress_test(
    tickers: List[str],
    weights: Union[List[float], np.ndarray],
    portfolio_value: float = 100000.0
) -> Dict[str, Dict[str, Union[float, str]]]:
    """
    Replays historical black swan crisis windows on a custom portfolio 
    to calculate peak-to-trough max drawdowns and estimated dollar impacts.
    """
    cleaned_tickers = [t.strip().upper() for t in tickers]
    weights = np.array(weights) / np.sum(weights)  # Normalize weights
    
    results = {}
    
    for scenario_key, scenario_info in CRISIS_SCENARIOS.items():
        try:
            # Download historical price data for the specific crisis window
            raw_data = yf.download(
                tickers=cleaned_tickers,
                start=scenario_info["start"],
                end=scenario_info["end"],
                progress=False
            )
            
            if "Adj Close" in raw_data:
                prices = raw_data["Adj Close"]
            elif "Close" in raw_data:
                prices = raw_data["Close"]
            else:
                prices = raw_data

            if isinstance(prices, pd.Series):
                prices = prices.to_frame(name=cleaned_tickers[0])

            prices = prices.ffill().bfill()
            
            # Check if all requested assets were active during this historical period
            missing_tickers = [t for t in cleaned_tickers if t not in prices.columns or prices[t].isna().all()]
            
            if missing_tickers:
                results[scenario_key] = {
                    "scenario_name": scenario_info["name"],
                    "status": "Incomplete Data",
                    "note": f"Assets not trading during this era: {', '.join(missing_tickers)}",
                    "max_drawdown_pct": 0.0,
                    "dollar_loss": 0.0
                }
                continue
                
            # Normalize price series to 1.0 at start of crisis
            normalized_prices = prices / prices.iloc[0]
            
            # Compute daily weighted portfolio value indexed to 1.0
            portfolio_indexed = np.dot(normalized_prices, weights)
            portfolio_series = pd.Series(portfolio_indexed, index=prices.index)
            
            # Calculate Peak-to-Trough Maximum Drawdown
            running_max = portfolio_series.cummax()
            drawdown_series = (portfolio_series - running_max) / running_max
            max_drawdown_pct = float(drawdown_series.min())
            
            dollar_loss = float(portfolio_value * abs(max_drawdown_pct))
            
            results[scenario_key] = {
                "scenario_name": scenario_info["name"],
                "status": "Success",
                "max_drawdown_pct": float(max_drawdown_pct),
                "dollar_loss": float(dollar_loss),
                "estimated_portfolio_bottom": float(portfolio_value - dollar_loss)
            }
            
        except Exception as e:
            results[scenario_key] = {
                "scenario_name": scenario_info["name"],
                "status": "Error",
                "note": str(e),
                "max_drawdown_pct": 0.0,
                "dollar_loss": 0.0
            }
            
    return results

if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    root_dir = Path(__file__).resolve().parent.parent.parent
    if str(root_dir) not in sys.path:
        sys.path.append(str(root_dir))
        
    test_tickers = ["AAPL", "MSFT", "SPY", "GLD"]
    test_weights = [0.25, 0.25, 0.25, 0.25]
    portfolio_val = 100000.0
    
    print(f"Replaying historical shock scenarios on ${portfolio_val:,.2f} portfolio...")
    print(f"Holdings: {', '.join(test_tickers)}\n")
    
    stress_results = run_stress_test(test_tickers, test_weights, portfolio_val)
    
    print("--- HISTORICAL STRESS-TEST REPORT ---")
    for key, data in stress_results.items():
        print(f"\nScenario: {data['scenario_name']}")
        if data["status"] == "Success":
            print(f"  Max Peak-to-Trough Drawdown: {data['max_drawdown_pct']*100:.2f}%")
            print(f"  Estimated Dollar Impact:     -${data['dollar_loss']:,.2f}")
            print(f"  Simulated Portfolio Floor:   ${data['estimated_portfolio_bottom']:,.2f}")
        else:
            print(f"  Status: {data['status']} ({data.get('note', '')})")