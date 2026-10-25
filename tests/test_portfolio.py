from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from src.api.main import app
from src.domain.portfolio import HoldingsSnapshot, Instrument, Position, Quote, value_holdings

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def instrument(name="AAPL", currency="USD"):
    return Instrument(instrument_id=f"NASDAQ:{name}", ticker=name, exchange="NASDAQ", currency=currency,
        asset_type="share", provider_symbol=name)


def holdings():
    return HoldingsSnapshot(base_currency="USD", positions=(Position(instrument=instrument(), quantity="10"),),
        cash="2000", source="manual", confirmed_at=NOW)


def quote(name="AAPL", price="800", currency="USD"):
    return Quote(instrument_id=f"NASDAQ:{name}", price=price, currency=currency, as_of=NOW, source="test")


def test_cash_and_decimal_valuation():
    result = value_holdings(holdings(), (quote(),))
    assert result.total_value == Decimal("10000")
    assert result.positions[0].weight == Decimal("0.8")
    assert result.cash_weight == Decimal("0.2")
    assert result.holdings_snapshot_id == holdings().snapshot_id


def test_snapshot_is_immutable():
    with pytest.raises(ValidationError):
        holdings().cash = Decimal("0")


def test_equivalent_manual_and_csv_values():
    manual = holdings()
    csv = manual.model_copy(update={"source": "csv"})
    assert value_holdings(manual, (quote(),)).positions == value_holdings(csv, (quote(),)).positions
    assert manual.snapshot_id != csv.snapshot_id


def test_order_independent_identity_and_valuation():
    a = Position(instrument=instrument(), quantity="10")
    b = Position(instrument=instrument("MSFT"), quantity="5")
    one = holdings().model_copy(update={"positions": (a, b)})
    two = holdings().model_copy(update={"positions": (b, a)})
    assert one.snapshot_id == two.snapshot_id
    assert value_holdings(one, (quote(), quote("MSFT", "200"))) == value_holdings(two, (quote("MSFT", "200"), quote()))


@pytest.mark.parametrize("quotes", [(), (quote(), quote()), (quote("OTHER"),)])
def test_unmatched_quotes_rejected(quotes):
    with pytest.raises(ValueError):
        value_holdings(holdings(), quotes)


def test_wrong_quote_currency_rejected():
    with pytest.raises(ValueError):
        value_holdings(holdings(), (quote(currency="AUD"),))


def test_mixed_currency_holdings_rejected():
    with pytest.raises(ValidationError):
        HoldingsSnapshot(base_currency="AUD", positions=(Position(instrument=instrument(), quantity="1"),),
            cash=0, source="manual", confirmed_at=NOW)


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity"])
def test_bad_quantity_rejected(quantity):
    with pytest.raises(ValidationError):
        Position(instrument=instrument(), quantity=quantity)


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        Quote(instrument_id="A", price=1, currency="USD", source="test", as_of=datetime(2026, 1, 1))


def test_quote_unit_multiplier():
    asset = instrument().model_copy(update={"price_multiplier": Decimal("0.01")})
    portfolio = holdings().model_copy(update={"positions": (Position(instrument=asset, quantity="10"),)})
    assert value_holdings(portfolio, (quote(price="80000"),)).positions[0].market_value == Decimal("8000")


def test_stateless_valuation_api():
    response = TestClient(app).post("/api/v2/valuations", json={
        "holdings": holdings().model_dump(mode="json"), "quotes": [quote().model_dump(mode="json")]})
    assert response.status_code == 200
    assert response.json()["data"]["cash_weight"] == "0.2"
    assert response.json()["metadata"]["quote_verification"] == "caller_supplied_unverified"
