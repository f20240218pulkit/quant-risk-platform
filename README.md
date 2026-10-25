# Quant Risk Platform

A Python portfolio analytics API and Streamlit dashboard for historical VaR,
expected shortfall, correlated simulation, long-only optimisation and crisis replay.

## Foundation release 1.1

- Explicit cash exposure across risk, simulation, optimisation and stress replay.
- Immutable single-currency holdings/valuation contracts with identity-based quote joins.
- Strict market-data validation and labelled ticker alignment.
- Fixed-holdings lognormal simulation with local seeded randomness.
- Checked optimiser convergence and constraints.
- Compact simulation responses with full-population percentile bands.
- Unavailable crisis history displayed separately from successful zero-loss results.
- Deterministic API, engine, domain and Streamlit integration tests.

These are hypothetical model analyses. They do not reconstruct actual account
performance. Read [methodology and supported boundaries](docs/methodology.md).

## Run locally

Use Python 3.12:

```bash
git clone https://github.com/f20240218pulkit/quant-risk-platform.git
cd quant-risk-platform
python -m venv .venv
# Activate the virtual environment using your shell's activation command.
python -m pip install '.[test,ui]'
python -m pytest -q
python -m uvicorn src.api.main:app --reload
```

In a second terminal, activate the same environment and launch the UI:

```bash
python -m streamlit run src/ui/app.py
```

Set `API_BASE_URL=http://127.0.0.1:8000` in the UI terminal to use the local API;
otherwise the UI retains its hosted API default. Open API documentation at
`http://127.0.0.1:8000/docs`. Docker Compose supplies the internal API address.

## API and portfolio contracts

The four existing `/api/v1` analytics endpoints remain available. Weighted
requests accept relative asset weights plus a separate `cash_weight` (default 0).
Risk, simulation and optimisation require at least 252 daily return observations.
Simulation transfers at most 100 illustrative paths; risk and percentile bands use
all simulated paths. Client charts should consume the supplied `percentiles`.

`POST /api/v2/valuations` accepts `holdings` and `quotes`, derives market values and
weights, and preserves cash. Quotes are caller-supplied and unverified. This
endpoint does not fetch prices, verify listings, save portfolios, or grant account
access. Holdings contracts currently support a single AUD or USD currency.

## Next work packages

CSV import/review, instrument resolution, automatic current-price valuation,
portfolio-based analysis orchestration, historical FX, authenticated saved
portfolios, durable jobs and broker connections are not implemented yet. Existing
v1 ticker inputs do not verify currency; the dashboard remains USD-labelled.
