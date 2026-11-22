"""Deterministic AUD accounting for the synthetic Workbench workflow."""
import csv
import io
import re
from decimal import Decimal, localcontext

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2_000
IDENTIFIERS = {
    "ASX:BHP": ("AUD", "BHP"),
    "XNAS:AAPL": ("USD", "Apple"),
    "CASH:AUD": ("AUD", "AUD cash"),
    "CASH:USD": ("USD", "USD cash"),
}
FIXTURES = {
    "2026-11-13": ({"ASX:BHP": "50", "XNAS:AAPL": "100"}, "1.50"),
    "2026-11-20": ({"ASX:BHP": "50", "XNAS:AAPL": "110"}, "1.40"),
    "2026-11-27": ({"ASX:BHP": "51"}, "1.42"),
}
SAMPLE_CSV = "instrument,quantity\nASX:BHP,20\nXNAS:AAPL,10\nCASH:AUD,500\nCASH:USD,0\n"
METHOD = "aud-close-fixture-v1"
QUANTITY = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,10})?")


def parse_holdings(data: bytes) -> tuple[list[dict], list[dict]]:
    positions, issues = [], []
    seen = set()
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        if next(reader, None) != ["instrument", "quantity"]:
            return [], [{"row": 1, "message": "Use instrument,quantity as the header."}]
        for row in reader:
            line = reader.line_num
            if line > MAX_ROWS + 1:
                return [], [{"row": line, "message": f"Use at most {MAX_ROWS} data rows."}]
            if not row:
                continue
            if len(row) != 2:
                issues.append({"row": line, "message": "Provide two fields."})
                continue
            instrument, quantity = (field.strip() for field in row)
            if instrument not in IDENTIFIERS:
                issues.append({"row": line, "message": "Instrument is outside the synthetic fixture universe."})
            elif instrument in seen:
                issues.append({"row": line, "message": "Enter one balance per instrument or cash currency."})
            elif not QUANTITY.fullmatch(quantity) or (
                not instrument.startswith("CASH:") and Decimal(quantity) == 0
            ):
                issues.append({"row": line, "message": "Enter a supported nonnegative decimal. Shares must be positive."})
            else:
                positions.append({"instrument": instrument, "quantity": format(Decimal(quantity).normalize(), "f")})
                seen.add(instrument)
            if len(issues) == 25:
                break
    except (UnicodeDecodeError, csv.Error):
        return [], [{"row": None, "message": "Upload valid UTF-8 CSV with reasonably sized fields."}]
    if not {"CASH:AUD", "CASH:USD"} <= seen:
        issues.append({"row": None, "message": "Include explicit AUD and USD cash balances. Use zero if confirmed."})
    if not any(not key.startswith("CASH:") for key in seen):
        issues.append({"row": None, "message": "Include at least one supported listed holding."})
    return sorted(positions, key=lambda row: row["instrument"]), issues


def aud_review(snapshot_date: str, positions: list[dict]) -> dict:
    prices, aud_per_usd = FIXTURES[snapshot_date]
    rows = []
    with localcontext() as ctx:
        ctx.prec = 90
        subtotal = Decimal(0)
        for position in positions:
            key = position["instrument"]
            currency, label = IDENTIFIERS[key]
            quantity = Decimal(position["quantity"])
            price = "1" if key.startswith("CASH:") else prices.get(key)
            fx = "1" if currency == "AUD" else aud_per_usd
            value = quantity * Decimal(price) * Decimal(fx) if price is not None else None
            if value is not None:
                subtotal += value
            rows.append({
                "instrument": key, "label": label, "currency": currency,
                "quantity": format(quantity, "f"), "local_price": price, "aud_fx": fx,
                "aud_value": format(value, "f") if value is not None else None,
                "issue": "Required synthetic close is missing" if value is None else None,
            })
        complete = all(row["issue"] is None for row in rows)
        for row in rows:
            row["weight"] = str(Decimal(row["aud_value"]) / subtotal) if complete and subtotal else None
        return {
            "snapshot_date": snapshot_date, "currency": "AUD", "method": METHOD,
            "source": "Synthetic market fixtures", "status": "complete" if complete else "partial",
            "aud_total": format(subtotal, "f") if complete else None,
            "aud_covered_subtotal": format(subtotal, "f"), "positions": rows,
        }


def compare_reviews(older: dict, current: dict) -> dict:
    if (older["status"] != "complete" or current["status"] != "complete"
            or older["method"] != current["method"]
            or older["snapshot_date"] >= current["snapshot_date"]):
        return {"eligible": False, "reason": "Compare two complete reviews in date order with the same method."}
    old_positions = {row["instrument"]: row for row in older["positions"]}
    current_positions = {row["instrument"]: row for row in current["positions"]}
    with localcontext() as ctx:
        ctx.prec = 90
        effects = dict.fromkeys(("price", "fx", "quantity", "cash"), Decimal(0))
        for key in sorted(old_positions.keys() | current_positions.keys()):
            start = old_positions.get(key)
            end = current_positions.get(key)
            if start is None:
                effects["quantity"] += Decimal(end["aud_value"])
                continue
            if end is None:
                effects["quantity"] -= Decimal(start["aud_value"])
                continue
            q0, p0, f0 = (Decimal(start[field]) for field in ("quantity", "local_price", "aud_fx"))
            q1, p1, f1 = (Decimal(end[field]) for field in ("quantity", "local_price", "aud_fx"))
            effects["price"] += q0 * (p1 - p0) * f0
            effects["fx"] += q0 * p1 * (f1 - f0)
            effects["cash" if key.startswith("CASH:") else "quantity"] += (q1 - q0) * p1 * f1
        delta = Decimal(current["aud_total"]) - Decimal(older["aud_total"])
        if sum(effects.values()) != delta:
            raise ValueError("The valuation bridge did not reconcile.")
        return {"eligible": True, "aud_change": format(delta, "f"),
                "effects": {name: format(value, "f") for name, value in effects.items()}}
