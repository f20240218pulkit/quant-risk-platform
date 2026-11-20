# Portfolio Workbench operations

## Run and deploy

Use Python 3.12 and install `.[ui,test]` from the repository root. Run
`python -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.maxUploadSize=6`.
The previous API and dashboard entry points are separate. For a Streamlit Community
Cloud demo use the root `streamlit_app.py` entry point, Python 3.12 and the feature
branch until reviewed. Root requirements install UI and backend calculation dependencies.
Leave private data integrations disabled in a public demo.

## Confirmed review

Upload exchange-qualified holdings and closes or use sample data. A review supports
long-only listed shares, ETFs and cash. Downside risk uses daily constant exposures.
Comparison replays fixed holdings and cash. Simulation uses existing lognormal
fixed-holdings paths. Optimisation keeps cash fixed. Constant-return assets can have
undefined correlation. Unavailable solver or crisis outputs are presented explicitly.

An optional personal Yahoo Finance connector uses `WORKBENCH_YAHOO_PERSONAL_USE=1`.
Enable it only where you have verified the provider's terms and your data rights.
The connector checks listing type, exchange and currency, requires 253 matching
completed closes and rejects a close older than seven days. It uses the latest
unadjusted close for valuation, adjusted history for analytics, and separate
explicit histories for named crisis windows. No general data licence is implied.
Market access and listing coverage vary. CSV input remains available when the
provider rejects a request.

## Strategy research

Upload bars with `session,instrument,open_at,close_at,open,close` and up to 20
instruments over 100–1,500 shared sessions. Use comparable price units across bars.
The pilot ledger models fractional long-only fills, proportional fees/slippage,
and zero-return cash. Splits and dividends need a consistent upstream adjustment
or a future corporate-action ledger. Stock selection, data revisions and broker
execution effects can bias research.

Optional news uses `story_id,instrument,published_at,available_at,source,url,headline,sentiment`.
Availability must follow publication and only observations available by a decision
cutoff become features. The first observed duplicate wins. URL and source link
back to evidence. Uploaded scores are caller-supplied. News volume distinguishes
neutral news from no coverage. The demo uses synthetic scores.

Ridge signals refit using expanding windows and a purged next-open-to-following-open
label. They share rankings, execution and costs for the sentiment comparison. Default
charts start after the first simulated fill, and risk metrics include its costs.
The export includes each trade, dates, daily weights, settings, dataset fingerprint,
and matched ablation and cost sensitivity. Retain the original inputs for reruns.
Hyperparameters are fixed for this pilot. A separate untouched research holdout,
uncertainty study and proper corporate actions are required for stronger claims.

The optional NumPy PPO variant uses a clipped Gaussian policy with a linear value
baseline and a shared ledger. It runs with seeds 7 and 19 and evaluates the price
and news variants against the same held-out history. Training consumes earlier
sessions only. It is intentionally a bounded research experiment.

For local FinBERT, install `.[ui,sentiment]`, acquire the approved local model
cache, and set `WORKBENCH_FINBERT_REVISION` to an exact 40-character revision.
Use safetensors. ProsusAI's model card lists a noncommercial licence. Check model
and training data terms for your use case and obtain separate permission or use
another approved model before commercial use. The app does not fetch weights or
send headlines to an inference service.

## Private workspace and worker

Without `WORKBENCH_DB`, the demo uses a private temporary database per browser
session. With `WORKBENCH_DB=/path/to/private/review.sqlite3`, configure Streamlit
OIDC through `.streamlit/secrets.toml` with the provider metadata URL, redirect
URI, client credentials and cookie secret. Configure TLS, an owner-only
persistent directory, backups and restoration, and appropriate host access.
The app validates issuer, subject and expiration claims and keys each storage
operation to the verified identity. Personal data should be tested on a
private deployment.

Run a worker with `python -m src.workbench.worker` in the same deployment and
database volume. It supports research and manually queued or daily Yahoo price refresh
jobs. Enable Yahoo personal-use mode in both the UI and worker for refresh jobs. Multiple worker processes coordinate through SQLite claim leases, retries
and idempotent job IDs. Run one iteration with `--once`. Accepted refreshes
create a new review. Threshold rules produce in-app alerts when a matching
review is saved. Failed jobs never replace a saved review. Alert delivery is in-app. Daily refresh is opt-in for each saved price review and requires the worker to remain running. Multi-instance
hosting would require a shared database and private artefact backend.

## Read-only broker pilot

Install `.[ui,accounts,broker]` and configure OIDC. Set
`WORKBENCH_BROKER_OWNER` to the SHA-256 of the JSON array containing the exact
OIDC issuer and subject (Python default separators, ensure_ascii=True).
Set `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY` as server secrets for a
SnapTrade **Personal** account. The connection portal requests read permissions.
The user can list investment accounts, import supported holdings and cash,
reconnect, and disconnect from the linked accounts. The refresh rejects disabled
connections, unsupported assets, negative positions and unexpected empty imports.
Cash equivalents are counted only through broker cash. Data can be cached upstream.
Confirm brokerage availability with the provider before relying on it. CMC Invest
specific access and commercial multi-user integration are future work. The
synthetic broker feed exercises the review workflow without credentials.

## Currency analysis

The FX input is `date,aud_per_usd`. Supply AUD for one USD on every matched
session. Convert security values and foreign cash at the report-date FX rate,
and apply the complete FX history before calculating base-currency returns.
The supplied files must reconcile exchange holidays and close-time differences.
The provided price series measure hypothetical historical exposure rather than
transaction-based account performance.

## Verification

`python -m pytest -q` exercises known-value accounting, cutoff handling, order
alignment, matched ablation, FX exposure, storage ownership, alert deduplication,
retries and worker lease recovery. Offline and controlled fixtures cover the
sample and upload flows. The Yahoo, OIDC, SnapTrade and FinBERT integrations each
need deployment-specific live acceptance checks with authorised resources.
