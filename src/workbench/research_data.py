"""Point-in-time inputs for historical research."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit

import numpy as np
import pandas as pd

from src.workbench.inputs import ImportIssue, _decimal, _rows

BARS_HEADER = "session,instrument,open_at,close_at,open,close"
NEWS_HEADER = "story_id,instrument,published_at,available_at,source,url,headline,sentiment"
MAX_BARS_BYTES = 6 * 1024 * 1024
MAX_NEWS_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ResearchData:
    opens: pd.DataFrame
    closes: pd.DataFrame
    cutoffs: pd.DatetimeIndex
    news: pd.DataFrame
    dataset_id: str
    score_source: str


def _timestamp(value):
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("Timestamps must include UTC or an offset.")
    return moment.astimezone(timezone.utc)


def parse_research_data(bars, news=None, scorer=None):
    rows = {}
    for line, row in _rows(bars, BARS_HEADER, MAX_BARS_BYTES, 30_000):
        try:
            session = date.fromisoformat(row["session"])
            if row["session"] != session.isoformat():
                raise ValueError("Use YYYY-MM-DD for sessions.")
            key = row["instrument"].upper()
            if not key or len(key) > 32:
                raise ValueError("Provide a non-empty instrument ID.")
            opened, closed = _timestamp(row["open_at"]), _timestamp(row["close_at"])
            if not opened < closed or closed > datetime.now(timezone.utc):
                raise ValueError("Use completed sessions with open before close.")
            prices = tuple(float(_decimal(row[column])) for column in ("open", "close"))
            if any(not np.isfinite(p) or not 1e-10 <= p <= 1e12 for p in prices):
                raise ValueError("Open and close prices must be positive, finite and within supported limits.")
            if key in rows.setdefault(session, {}):
                raise ValueError("Duplicate instrument in session.")
            rows[session][key] = opened, closed, *prices
        except (ValueError, OverflowError) as exc:
            raise ImportIssue(f"Bars line {line}: {exc}") from exc
    sessions = sorted(rows)
    symbols = sorted(rows[sessions[0]])
    if not 100 <= len(sessions) <= 1500 or len(symbols) > 20:
        raise ImportIssue("Use 100–1,500 shared sessions and at most 20 instruments.")
    open_rows, close_rows, cutoffs = [], [], []
    prior_close = None
    for session in sessions:
        day = rows[session]
        if day.keys() != set(symbols):
            raise ImportIssue(f"Missing or extra instruments on {session}.")
        stamps = {(entry[0], entry[1]) for entry in day.values()}
        if len(stamps) != 1:
            raise ImportIssue(f"Instruments need the same session timestamps on {session}.")
        opened, closed = stamps.pop()
        if prior_close is not None and opened <= prior_close:
            raise ImportIssue(f"Session {session} opens before or at the previous close.")
        open_rows.append([day[k][2] for k in symbols])
        close_rows.append([day[k][3] for k in symbols])
        cutoffs.append(closed)
        prior_close = closed
    events = [] if news is None else parse_news(news, symbols, scorer)
    label = "none" if news is None else (scorer.version if scorer else "caller-supplied headline scores")
    digest = sha256()
    for part in (bars, news or b"", label.encode()):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return ResearchData(
        pd.DataFrame(open_rows, index=pd.to_datetime(sessions), columns=symbols),
        pd.DataFrame(close_rows, index=pd.to_datetime(sessions), columns=symbols),
        pd.DatetimeIndex(cutoffs), pd.DataFrame(events), digest.hexdigest(), label,
    )


def parse_news(news, symbols, scorer=None):
    events = []
    for line, row in _rows(news, NEWS_HEADER, MAX_NEWS_BYTES, 5000, field_limit=2048):
        try:
            if not row["story_id"] or not row["headline"] or not row["source"]:
                raise ValueError("Story ID, headline and source are required.")
            link = urlsplit(row["url"])
            if link.scheme not in {"http", "https"} or not link.hostname or link.username is not None:
                raise ValueError("Provide a valid HTTP(S) source link.")
            key = row["instrument"].upper()
            if key not in symbols:
                raise ValueError(f"Unknown research instrument {key}.")
            published = _timestamp(row["published_at"])
            available = _timestamp(row["available_at"])
            if available < published:
                raise ValueError("Availability cannot precede publication.")
            score = None if scorer else float(_decimal(row["sentiment"]))
            if score is not None and not -1 <= score <= 1:
                raise ValueError("Sentiment must be within [-1, 1].")
            events.append({**row, "instrument": key, "available_at": available,
                           "published_at": published, "score": score})
        except (ValueError, OverflowError) as exc:
            raise ImportIssue(f"News line {line}: {exc}") from exc
    seen_ids, seen_headlines = set(), set()
    unique = []
    # First observed copy wins. Keep a separate event per associated instrument.
    for event in sorted(events, key=lambda item: item["available_at"]):
        key = event["instrument"], event["story_id"]
        headline = event["instrument"], " ".join(event["headline"].casefold().split())
        if key in seen_ids or headline in seen_headlines:
            continue
        unique.append(event)
        seen_ids.add(key)
        seen_headlines.add(headline)
    if scorer:
        scores = scorer([item["headline"] for item in unique])
        for event, score in zip(unique, scores, strict=True):
            if not np.isfinite(score) or not -1 <= score <= 1:
                raise ImportIssue("Headline scorer returned an invalid value.")
            event["score"] = float(score)
    return unique


def news_features(data, window=5):
    values = np.zeros(data.closes.shape)
    counts = np.zeros(data.closes.shape)
    if not data.news.empty:
        for event in data.news.itertuples(index=False):
            index = data.cutoffs.searchsorted(event.available_at, side="left")
            if index >= len(data.cutoffs):
                continue
            if index == 0 and event.available_at < data.cutoffs[0] - pd.Timedelta(days=7):
                continue
            column = data.closes.columns.get_loc(event.instrument)
            values[index, column] += event.score
            counts[index, column] += 1
    counts = pd.DataFrame(counts).rolling(window, min_periods=1).sum().to_numpy()
    values = pd.DataFrame(values).rolling(window, min_periods=1).sum().to_numpy()
    means = np.divide(values, counts, out=np.zeros_like(values), where=counts > 0)
    return np.stack((means, np.log1p(counts)), axis=-1)
