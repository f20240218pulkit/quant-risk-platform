# Portfolio Workbench implementation and verification plan

## System contract

React and TypeScript serve the user workflow. A same-origin FastAPI service owns sessions, imports, report retrieval and permissions. PostgreSQL stores the confirmed snapshots, pending reviews and immutable report evidence. A separate Python worker publishes reviews. External providers enter through versioned adapter contracts. The current Streamlit application stays available as the previous workbench and research reference.

## Build order and release evidence

| Step | Implementation sequence | Evidence required before advancing |
|---|---|---|
| 1. Establish the baseline | Branch from the verified Workbench head. Keep the existing API and Streamlit CI. Freeze mixed-market fixtures and expected AUD values before writing the engine. | Exact reviewed source revision, baseline tests and an independently reconciled fixture. |
| 2. Define contracts and storage | Publish the CSV schema and limits. Add Alembic migrations for workspace, session, imports, review jobs and reports. Give API and worker explicit transaction scopes. | Fresh Postgres migration, duplicate import and confirmation invariants, workspace-consistent links, downgrade rehearsal, and runtime-role isolation checks. |
| 3. Prove one complete workflow | Create isolated demo workspaces. Parse a snapshot and persist row-level issues. Confirm a valid preview and queue a job atomically. Compute and publish with the synthetic provider. Build navigation, review evidence, history, comparison and partial coverage in React. | An actual browser completes both dated reviews and a partial third review. Verify expired or unauthenticated access, a second workspace, retries and persistence in PostgreSQL. |
| 4. Harden refresh and deployment | Adopt approved listing, price, FX and corporate-action adapters. Pin source and cutoff versions. Move from short fixture transactions to leased jobs before network calls. Run scheduler and retry logic under burst, outage, stale inputs and corrections. Add log redaction, readiness, metrics, budget thresholds and a tested restore runbook. | Independently reconcile feed fixtures and live sandbox samples. Demonstrate recovery without overwriting historical evidence. Verify a deployment on the intended hosting platform. |
| 5. Verify production identity and data lifecycle | Provision isolated staging identity and database roles. Connect managed OIDC code flow with PKCE, nonce and state. Add recent-auth export and deletion, revocation, cleanup receipts and restore replay. Rotate and audit service credentials. | Two hosted identities, expiry and logout, browser session and CSRF checks, database-role isolation, authorized export, deletion, interrupted cleanup and backup restore. Obtain data-rights and privacy approval before real uploads. |
| 6. Add useful recurring features | Verify a real broker file before offering its adapter. Add verified account-source reconciliation, scheduled valuations, user-created threshold rules, atomic notification intents and opt-in delivery. | Compare redacted positions and cash with source records. Simulate stale holdings, holidays, missing quotes, state re-arming, retries, manual replay and opt-out. |
| 7. Extend NewsAlpha and analytics | Ingest rights-cleared source-linked events with issuer mapping and timestamp evidence. Evaluate usefulness against typed event rules. Keep ML experiments on a separate queue and artifact boundary, with point-in-time universe, purged evaluation, baselines, matched ablations and run manifests. Add look-through, broker sync or transaction returns only with verified data contracts. | Independent dataset and rights review, reproducible model run and tested portfolio/event isolation. Each extension has a bounded failure mode with no bearing on core accounting. |
| 8. Launch and operate | Produce staging acceptance evidence and start invited testing when requested. Review incident ownership, recovery, capacity, provider costs, accessibility and support. Enable production capabilities incrementally. | No open material financial correctness or isolation issue, documented residual risks, rollback evidence, and a defined owner for each ongoing control. |

## First slice traceable fixture

Use the same positions on 13 and 20 November 2026. Hold 20 synthetic BHP units, 10 synthetic AAPL units, and A$500 cash with explicit USD cash of zero. BHP stays at A$50. AAPL moves from US$100 to US$110 and AUD per USD from 1.50 to 1.40. The two portfolio values must be A$3,000 and A$3,040. Price accounts for +A$150 and FX accounts for −A$110. A third fixture omits the required AAPL close and must show a scoped subtotal without full-portfolio weights or comparison. Dates indicate fixture snapshots and are not a market-session feed.

## Connection and verification order

1. Start PostgreSQL and migrate from an empty database. Start FastAPI and its worker with the same connection configuration and the agreed runtime role.
2. Build the browser assets. Open the web service on one origin and create a private synthetic workspace.
3. Upload and inspect a bounded CSV. Confirm the draft. The API transaction marks it confirmed and inserts one job. The browser waits on the report list.
4. The worker claims one due job, reads the confirmed data in the appropriate workspace, computes the report with the pinned fixtures, and stores the evidence before committing the completion status. This quick fixture operation uses a short database transaction. Live network and heavy work require leases before that boundary expands.
5. Open a second dated review. Reconcile the balance bridge and source evidence. Verify malformed CSV, missing quote coverage, duplicate confirmation, another workspace and a server restart.
6. Run the existing suite alongside v2 tests. Test through the browser rather than inferring UI success from API responses.

The synthetic slice is a verified integration milestone. Production readiness also requires real data, managed identity, operational and user acceptance.

## Run the checkpoint locally

With Docker Engine and Compose installed, run from the repository root.

```sh
docker compose -f deployment/compose.workbench.yml up --build
```

Open http://127.0.0.1:8001. Select **Start sample workspace**. In order, choose 13, 20 and 27 November 2026, then **Load sample holdings** and **Confirm and value holdings** for each date. Use **Review history** to reopen earlier results. Compose uses a persistent test volume, a separate migration role, a restricted runtime role and a loopback-only port. Its disposable local credentials must stay local.

For native development, install `.[product,test]`, then `npm --prefix web ci` and `npm --prefix web run build`. Create the runtime role before migrating an empty PostgreSQL database using the owner connection and `python -m alembic upgrade head`. Switch both application processes to the runtime connection via `WORKBENCH_DATABASE_URL`, set `WORKBENCH_DEMO_MODE=1`, and run:

```sh
python -m uvicorn src.product.api:create_app --factory --port 8001
python -m src.product.worker
```

Run the two processes in separate terminals. Set `WORKBENCH_TEST_DATABASE_URL` to a disposable migrated runtime database for the PostgreSQL integration test. Run `python -m pytest -q tests/test_product.py`, then `python tests/product_browser_smoke.py` against the running processes with Playwright and Chromium installed. The browser test owns independent opaque synthetic sessions. It exercises persisted API state and a separate worker process.

## Implementation sequence by component

### Web, API and persistence

1. Start the app shell with the sample workspace entry, an import panel, a review area and history. Keep anonymous sample content distinct from private reports. Clear browser state on logout. Add keyboard focus and accessible names to every interactive control.
2. Finalise request and response schemas before extending the screens. Generate the TypeScript client when the wire contracts are stabilised. Keep dates timezone-aware and money as decimal strings until formatting. Add API compatibility checks and status handling for invalid input, expired sessions, failed jobs and partial evidence.
3. Serve the static build on the same origin as the API. Limit request bodies at ingress. Cache fingerprinted public assets independently from private data. Verify a reload resolves the session from the API and loads its own history.
4. Separate private report and draft rows by workspace. Add portfolio and explicit broker-source ownership keys in the next schema version. Use composite references wherever an ID crosses a tenancy boundary, apply workspace context inside a transaction, and test the runtime role without owner or RLS bypass privileges.
5. Ingest source data into a draft with row-level errors. Where multiple active drafts can update the same account, compare source generations at confirmation. Store the confirmed effective timestamp and evidence atomically with the intent. Keep the upload retry, confirmation retry, and report publication idempotency keys separate.
6. Compare a report only with an eligible earlier version using the same method and comparable coverage. Use a supplied quote/currency identity and report date before doing arithmetic. Preserve every published snapshot and methodology version. Return partial status with an explicit denominator scope. Add export tests for both allowed and denied access.

### Valuation, market data and worker

1. Validate listing identity, currencies, regular and special sessions, and source permission for each output. Introduce a provider interface for raw close, adjusted history, FX and corporate actions. Keep the fixture adapter for CI. Record whether each timestamp is from the provider or observed by ingestion.
2. Pin a report cutoff and choose a policy for scheduled and manual pricing. Resolve completed venue sessions, the eligible FX timestamp and holdings effective time independently. Exercise Sydney and US daylight-saving mismatch, early closes, holidays and late data.
3. Quantify position value as quantity × eligible raw close × conversion. Compare exact fixture values to a hand-calculated reference. Publish covered subtotal and reason on missing data, preserve the dated last complete result, and suppress weights and alerts that require a complete denominator.
4. Before adding external I/O, claim jobs with short transactions and a lease token. Complete under a valid token and current source generation. Reclaim expired work, back off on recoverable failures, and bound permanent failures. Test a lost worker, simultaneous claim, late completion, provider outage and repeat confirmation.
5. Schedule stable portfolio/date intents and deduplicate requests for shared market observations. Pass market status and staleness through to the user. Record a correction against the earlier report without mutating its evidence.
6. For alerts, keep rule versions and last eligible state. Use one intent for a below-to-at-or-above crossing and re-arm only after a subsequent eligible result falls below. Commit alert state and its outbox row with the publish. Verify retries, opt-out and ambiguous provider timeouts before enabling delivery.

### Identity, release engineering and operations

1. Use one managed OIDC integration for sign-in, recovery and revocation. Enforce exact origin, HTTPS in hosted environments, CSRF protection and recently verified identity for exports and deletion where required. Map external subjects to workspaces without relying on email as identity.
2. Provision separate staging and production environment secrets and roles. Separate the web session and job dispatcher permissions before real uploads. Apply forward-compatible schema migrations through a dedicated owner and use first-run verification after releases.
3. For deletion, revoke sessions, fence jobs, remove private rows and objects under the approved retention policy, and replay deletion evidence after backup restore. Check the failure path with a job claimed before deletion and with exports already queued.
4. Build and test the exact deployment image. Run service-level checks for database readiness, oldest ready job, report yield, provider failure and stale snapshots. Use a measured latency and recovery objective. Rehearse restore, rollback and provider downtime before extending access.
5. Do the rights, market-data and privacy reviews before live activation. Compare vendor coverage and actual sandbox data. Leave synthetic mode available independently. Add recurring use acceptance once real-user testing resumes.

### NewsAlpha and optional analytics

1. Ingest permitted event metadata and source URLs. Persist issuer, publish and observed times and source revisions. Resolve to held listings through stable issuer IDs. Surface an unknown issuer separately and avoid implying that a story caused a price move.
2. Measure rules on a labelled set of relevance and mapping examples before using a classifier. Evaluate publication cutoff, duplicate events and material omissions. Failures in event ingestion must never block a valuation.
3. Run research on separately authorised datasets and compute. Record point-in-time universes, dataset digests, code revision and parameters. Keep identical costs and execution assumptions for baseline, ridge, sentiment ablation and any PPO comparisons, with walk-forward validation and a held-out period.
4. Enable ETF look-through, broker sync and transaction-based performance only after their own input and reconciliation phases. Keep model output out of the deterministic accounting path and repeat financial test cases after every new data source.

## Checkpoint boundaries

The initial checkpoint introduced a disposable identity flow and PostgreSQL-backed sample workspaces. It uses one workspace-level history, two supported synthetic listings, and three explicit fixture dates. Reconciliation is performed by replacing the CSV and previewing it again. The sections below describe the product after the integration of the follow-up workflows. The existing Streamlit capabilities remain independently testable.

## Integrated product walkthrough

1. Open the local app and start a sample workspace. Under **Monitor**, add an AAPL rule at 50.5%.
2. Under **Review**, load and confirm the 13 November sample. It values the portfolio at A$3,000 and establishes the rule's initial state.
3. Under **Monitor**, choose 20 November and queue a refresh. The report is A$3,040, with holdings still dated 13 November, and the weight crossing appears in the inbox. Mark it read or pause scheduled refresh from the same page.
4. For the 20 November review, run a −10% scenario on Apple. The hypothetical portfolio value is A$2,886. Download the report evidence or return to the earlier report through history.
5. Open **NewsAlpha** to see the eligible illustrative events. Run the comparison experiment with or without PPO and view or download the synthetic results.
6. Confirm the 27 November sample to see a partial valuation. No full total, whole-portfolio weights, comparison or scenario is shown for that review.
7. Open **Settings** to download the available workspace data or permanently delete the demonstration workspace.

The automatic scheduler queues the newest available eligible report period for enabled workspaces. A manual refresh can be used to replay a specific sample date. Alerts are in-app only. Review publication and alert transition are atomic. Reclaimed jobs may repeat computation, but an expired lease cannot commit, even if the old process later recovers.

## Private integration configuration

Only the local synthetic mode is runnable with the default Compose configuration. The private service is fail-closed at startup. It requires HTTPS, a configured managed OIDC issuer with code flow and PKCE, invited subject IDs, configured database runtime and migration roles, and an operator-approved observation file. The same immutable file revision must be mounted in both API and worker. Replacing it requires a controlled restart of both services. Scope any usage, display, export and retention to written provider rights.

| Variable | Purpose |
|---|---|
| `WORKBENCH_ORIGIN` | Bare HTTPS origin. Register its exact `/auth/callback` redirect with the identity provider. |
| `WORKBENCH_OIDC_ISSUER`, `WORKBENCH_OIDC_CLIENT_ID`, `WORKBENCH_OIDC_CLIENT_SECRET` | Operator-managed identity configuration. Use real provider credentials from the deployment secret store. |
| `WORKBENCH_OIDC_STATE_SECRET` | A securely generated state cookie signing secret, 32 characters or more. |
| `WORKBENCH_OIDC_ALLOWED_SUBJECTS` | Space-separated verified subject IDs explicitly invited to the private environment. |
| `WORKBENCH_APPROVED_MARKET_FILE` | An operator-managed local JSON file, not writable by users. See `ApprovedMarketFile` in `src/product/market.py`. |
| `WORKBENCH_APPROVED_DATA` | Set to `1` only after confirming licensing for actual intended purposes. |
| `WORKBENCH_DEMO_MODE` | Set to `1` for synthetic sample use. Leave unset for managed identity and approved observations. |

Supply `source`, a unique `revision`, a listing map keyed by exchange and ticker, and a `periods` map keyed by report date. Each period contains a timezone-aware `cutoff`, native-currency prices keyed by listing, and optional AUD-per-USD rate. Every observation records `value`, `observed_at`, and `available_at`. Optional events have stable IDs, a listing key, an evidence URL and availability timestamp. Only include quotes, rates and events eligible by the cutoff. This adapter does not make external provider calls or infer market holidays or corporate actions. The operator must verify the session and split basis before publishing each period.

Managed OIDC and the file adapter are integration boundaries, with no deployed identity tenant or licensed feed configured by this repository. External email, commercial broker sync, multi-account reconciliation, ETF look-through and transaction performance are separate work. The current UI supports one combined holdings snapshot per import, an in-app inbox and fixed synthetic strategy presets.
