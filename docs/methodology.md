# Portfolio foundation 1.1

## Supported scope

Long-only shares/ETFs, explicit zero-nominal-return cash, and complete shared
price calendars. Stateless AUD/USD holdings contracts require one currency per
portfolio. Existing ticker-based v1 endpoints remain currency-unaware: the USD
UI remains a manually declared USD portfolio, not verified currency coverage.
The domain contracts do not verify listings or resolve provider symbols.

CSV imports, automatic valuation, historical FX, saved accounts, durable jobs,
and broker connections are subsequent work packages. `/api/v2/valuations`
values explicitly supplied quotes; it does not fetch or verify quotes, persist
portfolios, or authorise account access. Its metadata makes that boundary explicit.

## Holdings and valuation

Holdings and quotes are immutable typed records. Holdings IDs are SHA-256 hashes
of canonical serialised holdings (including source and confirmation time), sorted
by instrument ID. Quote joins use instrument IDs. Valuation IDs include the exact
quotes and their timestamps. Hash IDs identify content; they are not ownership
credentials, verification stamps, or persisted database records.

Values use Decimal; mathematical arrays use floats. Quoted price units are scaled
by the instrument's declared multiplier. A $10,000 portfolio with $2,000 cash has
80% invested exposure. v1 input weights remain relative within the invested sleeve;
`cash_weight` separately controls that sleeve's share of total capital.

## Data policy

Provider downloads explicitly request adjusted Close with `auto_adjust=True`.
No forward/backward filling, missing-symbol removal, or silent history shortening
is performed. Missing/non-finite/non-positive prices and ambiguous shapes fail
validation. v1 risk, simulation and optimisation require 252 complete daily return
observations; diagnostics report actual dates and count. This is a minimum data
threshold, not a guarantee of estimate quality. Very high confidence levels have
few empirical tail observations and should be interpreted accordingly.

Cross-exchange calendars, stale quotes, corporate-action reconciliation for actual
account quantities, and historical FX require dedicated future adapters. Adjusted
prices support hypothetical return analysis, not actual realised account returns.

## Risk

Historical VaR is the negative linear-interpolated lower-tail return quantile.
Expected shortfall averages observations at or below that quantile (ties included).
Parametric VaR uses the sample mean and population standard deviation (`ddof=0`)
with a normal lower-tail assumption. Historical risk applies today's constant
exposures to each historical one-day return. It is not a reconstructed investment
history. Losses use positive signs, but a fully positive tail can yield a negative
VaR/ES (a modelled gain threshold); values are not silently clipped to zero.

## Simulation

`lognormal-fixed-holdings-v1` fits mean and sample covariance (`ddof=1`) to daily
log returns. It samples correlated Gaussian log increments with a local seeded
NumPy generator and exponentiates per-asset increments. Asset quantities remain
fixed, asset weights drift, and cash has zero nominal return. This differs from
the old daily rebalanced arithmetic model; results may therefore change.

An eigen decomposition supports singular covariance (e.g. duplicate return series
or zero volatility). Only small floating-point-negative eigenvalues are clipped;
materially indefinite covariance fails. No artificial diagonal volatility is added.
Runs are reproducible in the same numerical environment; equality across different
BLAS/NumPy versions or reordered input assets is not promised bit-for-bit.

All paths determine risk metrics and 10/50/90 percentile bands. The API transfers
at most 100 illustrative paths. The UI uses server-computed bands when present and
supports old responses during deployment transition. Work is bounded to 5 million
asset-day-path cells and 50,000 paths. This bounds work, not wall-clock latency.

## Optimisation

Long-only SLSQP with weights summing to the invested sleeve and cash held fixed.
Cash earns zero. Annualised mean/covariance use 252 observations per year; the
risk-free rate is annual and applies to whole-portfolio Sharpe. Solver success,
finite outputs, sum/bounds and target-return constraints are checked. Zero-volatility
Sharpe optimisation is unavailable, rather than displayed as an infinite estimate.
Failed frontier points are omitted; the API returns an empty frontier if none
converge and the UI explicitly reports that state. Allocations are hypothetical.

## Stress

Current initial allocations are replayed buy-and-hold through the crisis window.
Scenario end dates are inclusive and converted to the provider's exclusive end.
Complete price data and boundary coverage within seven calendar days are required;
this boundary tolerance accommodates holidays but is not exchange-calendar proof.
No pre-listing prices are invented. Missing scenarios have null metrics and an
explicit unavailable state; the UI excludes them from risk charts.

Peak-to-trough maximum drawdown, start-to-trough loss, and terminal change are
separate outputs. `dollar_loss` is retained for UI compatibility and means initial
value multiplied by maximum drawdown magnitude. `estimated_portfolio_bottom` is
initial value multiplied by the minimum normalised path value; those quantities
are not interchangeable.

## Verification and deployment

Run `python -m pip install '.[test,ui]'` and `python -m pytest -q` using Python 3.12.
Normal tests block the provider download boundary and use deterministic fixtures.
Live provider/deployment verification is separate; passing unit tests does not prove
market-data availability or production performance.

Deploy API and UI from the same release. Deploy API first: older UIs can still use
the sampled `trajectories` response, but their calculated bands are approximate
until the new UI uses the provided full-population percentiles. Existing saved
Streamlit session results retain the model label stored at their creation where
available; start a new analysis after updating.
