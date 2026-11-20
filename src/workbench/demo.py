"""Generate a labelled offline example with no external market-data dependency."""
from datetime import date, timedelta

from src.workbench.inputs import HOLDINGS_HEADER, PRICES_HEADER

HOLDINGS_SAMPLE = (
    HOLDINGS_HEADER + "\n"
    "XNAS,ALFA,share,USD,80\n"
    "ARCX,BETA,etf,USD,35\n"
).encode()


def demo_closes() -> bytes:
    rows = [PRICES_HEADER]
    session = date(2024, 1, 2)
    prices = [100.0, 180.0]
    symbols = [("XNAS", "ALFA"), ("ARCX", "BETA")]
    for index in range(260):
        if index:
            seasonal = (index % 11 - 5) / 1000
            market_move = -.065 if index in (64, 129, 194) else 0
            prices[0] *= 1.0017 + seasonal + market_move
            prices[1] *= 1.0005 - seasonal / 2 + market_move / 3
        for (exchange, ticker), close in zip(symbols, prices):
            rows.append(f"{session},{exchange},{ticker},USD,{close:.4f}")
        session += timedelta(days=1)
        while session.weekday() >= 5:
            session += timedelta(days=1)
    return ("\n".join(rows) + "\n").encode()
