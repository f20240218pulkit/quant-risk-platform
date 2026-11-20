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


def demo_research() -> tuple[bytes, bytes]:
    """Synthetic UTC sessions with late news and deterministic price gaps."""
    import csv
    from io import StringIO
    from src.workbench.research_data import BARS_HEADER, NEWS_HEADER

    bars, news = StringIO(), StringIO()
    bar_writer, news_writer = csv.writer(bars), csv.writer(news)
    bar_writer.writerow(BARS_HEADER.split(","))
    news_writer.writerow(NEWS_HEADER.split(","))
    prices = [100., 120., 85.]
    symbols = ["XNAS:ALFA", "ARCX:BETA", "XNYS:DELTA"]
    session = date(2024, 1, 2)
    for i in range(180):
        for j, symbol in enumerate(symbols):
            gap = ((i * 5 + j) % 13 - 6) * .0007
            movement = ((i * (j + 1) + 3 * j) % 21 - 10) * .0013 + .0007
            opening = prices[j] * (1 + gap)
            prices[j] = opening * (1 + movement)
            bar_writer.writerow([session, symbol, f"{session}T14:30:00Z", f"{session}T21:00:00Z",
                                 f"{opening:.6f}", f"{prices[j]:.6f}"])
            if i % 6 == j:
                score = [0, .6, -.7][(i // 6 + j) % 3]
                news_writer.writerow([f"demo-{i}-{j}", symbol, f"{session}T20:55:00Z",
                                      f"{session}T21:30:00Z", "Synthetic",
                                      f"https://example.com/synthetic/{i}-{j}", f"Synthetic event {i} for {symbol}", score])
        session += timedelta(days=1)
        while session.weekday() >= 5:
            session += timedelta(days=1)
    return bars.getvalue().encode(), news.getvalue().encode()


def demo_fx() -> tuple[bytes, bytes, bytes]:
    holdings = HOLDINGS_SAMPLE.replace(b"ARCX,BETA,etf,USD", b"XASX,BETA,etf,AUD")
    closes = demo_closes().replace(b"ARCX,BETA,USD", b"XASX,BETA,AUD")
    sessions = sorted({line.split(",")[0] for line in closes.decode().splitlines()[1:]})
    rates = [f"{session},{1.4 + i / 2000:.4f}" for i, session in enumerate(sessions)]
    return holdings, closes, ("date,aud_per_usd\n" + "\n".join(rates) + "\n").encode()
