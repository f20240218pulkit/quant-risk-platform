"""Read-only broker normalisation and an owner-bound SnapTrade Personal adapter."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
import csv
import os
from urllib.parse import urlsplit

from src.workbench.inputs import HOLDINGS_HEADER, MARKET, SYMBOL, ImportIssue

BROKER_OFFLINE_POSITIONS = [
    {"instrument": {"kind": "stock", "exchange": "XNAS", "raw_symbol": "ALFA", "currency": "USD"},
     "units": "80", "cash_equivalent": False},
    {"instrument": {"kind": "etf", "exchange": "ARCX", "raw_symbol": "BETA", "currency": "USD"},
     "units": "35", "cash_equivalent": False},
]
BROKER_OFFLINE_CASH = [{"currency": {"code": "USD"}, "cash": "2000", "buying_power": "4000"}]


def _amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ImportIssue("The broker did not report a numeric balance or quantity.") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1e15"):
        raise ImportIssue("The account contains negative or invalid amounts.")
    return result


def reconcile(positions, balances):
    if not positions:
        raise ImportIssue("Broker returned no positions. The previous imported snapshot is retained.")
    total_by_key, cash = {}, {}
    for row in balances:
        currency = row["currency"]["code"]
        if currency not in {"USD", "AUD"} or currency in cash:
            raise ImportIssue("Invalid or repeated broker cash currency.")
        cash[currency] = _amount(row["cash"])
    if not cash:
        raise ImportIssue("Broker did not report cash balances.")
    for item in positions:
        if item.get("cash_equivalent") is True:
            continue  # Already counted in the broker's reported cash.
        instrument = item["instrument"]
        exchange = (instrument.get("exchange") or "").upper()
        ticker = (instrument.get("raw_symbol") or "").upper()
        currency = instrument["currency"]
        kind = {"stock": "share", "etf": "etf"}.get(instrument["kind"])
        if not kind or MARKET.get(exchange) != currency or not SYMBOL.fullmatch(ticker):
            raise ImportIssue("A broker holding has an unsupported instrument type, exchange or currency.")
        quantity = _amount(item["units"])
        if quantity == 0:
            continue
        key = exchange, ticker, currency
        if key in total_by_key and total_by_key[key][0] != kind:
            raise ImportIssue("Conflicting security types in broker positions.")
        total_by_key[key] = kind, total_by_key.get(key, (kind, Decimal(0)))[1] + quantity
    if not total_by_key or len(total_by_key) > 50:
        raise ImportIssue("Broker imports require 1–50 supported holdings. The previous snapshot is retained.")
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(HOLDINGS_HEADER.split(","))
    for (exchange, ticker, currency), (kind, quantity) in sorted(total_by_key.items()):
        writer.writerow([exchange, ticker, kind, currency, format(quantity, "f")])
    return {"holdings": output.getvalue(), "cash": {code: format(amount, "f") for code, amount in cash.items()}}


class PersonalBroker:
    def __init__(self, api):
        self.api = api

    @classmethod
    def for_owner(cls, owner):
        key = os.getenv("WORKBENCH_BROKER_OWNER")
        if not key or owner != key:
            raise ImportIssue("Live brokerage access is available to the configured owner.")
        try:
            from snaptrade_client import SnapTrade, SnapTradeAuth
        except ImportError as exc:
            raise ImportIssue("Install the optional broker dependency.") from exc
        try:
            auth = SnapTradeAuth.personal_api_key(
                client_id=os.environ["SNAPTRADE_CLIENT_ID"], consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"])
        except KeyError as exc:
            raise ImportIssue("Configure the server-side SnapTrade credentials.") from exc
        return cls(SnapTrade(auth=auth))

    def portal(self, connection=None):
        kwargs = {"reconnect": connection} if connection else {}
        link = self.api.authentication.login_snap_trade_user(connection_type="read", timeout=10, **kwargs).body["redirectURI"]
        url = urlsplit(link)
        if (url.scheme != "https" or not url.hostname or
                not (url.hostname == "snaptrade.com" or url.hostname.endswith(".snaptrade.com")) or url.username):
            raise ImportIssue("Broker returned an unexpected connection link.")
        return link

    def accounts(self):
        rows = self.api.account_information.list_all_user_accounts(timeout=10).body["results"]
        return [row for row in rows if row.get("kind") == "investment"]

    def connection(self, connection):
        return self.api.connections.detail_brokerage_authorization(authorization_id=connection, timeout=10).body

    def sync(self, account):
        connection = self.connection(account["brokerage_authorization"])
        if connection.get("disabled") is not False:
            raise ImportIssue("Connection is disabled or its health is unknown. Reconnect before refreshing.")
        api = self.api.account_information
        data = api.get_all_account_positions(account_id=account["id"], timeout=10).body
        cash = api.get_user_account_balance(account_id=account["id"], timeout=10).body
        return {**reconcile(data["results"], cash), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "freshness": "Broker-reported balance and positions may be cached"}

    def disconnect(self, connection):
        self.api.connections.delete_connection(connection_id=connection, timeout=10)
