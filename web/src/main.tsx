import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { RequestError, request } from "./api";
import type { Comparison, Draft, Review, ReviewSummary, Sample, Session } from "./api";
import "./styles.css";

const wholeAmount = new Intl.NumberFormat("en-AU");
const dateFormat = new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeZone: "UTC" });
const percent = new Intl.NumberFormat("en-AU", { style: "percent", maximumFractionDigits: 2 });
const labels = { price: "Market prices", fx: "Currency movement", quantity: "Units held", cash: "Cash balances" };
const money = (value: string, signed = false) => {
  // The API emits fixed-point strings. Round cents without converting money
  // through a binary floating-point value.
  const negative = value.startsWith("-");
  const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0").slice(0, 2));
  const rounded = fraction.length > 2 && fraction[2] >= "5" ? cents + 1n : cents;
  const sign = rounded === 0n ? "" : negative ? "-" : signed ? "+" : "";
  return sign + "$" + wholeAmount.format(rounded / 100n) + "." + String(rounded % 100n).padStart(2, "0");
};
const day = (value: string) => dateFormat.format(new Date(value));

function Report({ review, comparison }: { review: Review; comparison: Comparison | null }) {
  return <article className="panel report">
    <div className="report-heading">
      <div><h2>Portfolio review</h2><p>{day(review.snapshot_date)} · {review.source}</p></div>
      <span className={review.status === "partial" ? "tag warning" : "tag"}>{review.status === "partial" ? "Partial coverage" : "Complete"}</span>
    </div>
    <div className="valuation">
      <p>{review.status === "partial" ? "Covered subtotal (AUD)" : "Portfolio value (AUD)"}</p>
      <strong>{money(review.aud_total ?? review.aud_covered_subtotal)}</strong>
    </div>
    {review.status === "partial" && <p role="status" className="notice">A required close is missing. The subtotal excludes the uncovered position. Portfolio-wide weights and comparison are unavailable.</p>}
    {comparison?.eligible && <section aria-label="Change since previous review" className="change">
      <div className="section-heading"><h3>Change since previous review</h3><strong>{money(comparison.aud_change, true)}</strong></div>
      <dl>{Object.entries(comparison.effects).map(([key, value]) =>
        <div key={key}><dt>{labels[key as keyof typeof labels]}</dt><dd>{money(value, true)}</dd></div>
      )}</dl>
      <p>Balance movement based on the two dated snapshots.</p>
    </section>}
    <a className="download" href={`/api/workbench/v1/reviews/${review.id}/export`}>Download review evidence (JSON)</a>
    <details open>
      <summary>Holdings and valuation evidence</summary>
      <div className="table-wrap"><table>
        <thead><tr><th scope="col">Holding</th><th scope="col">Units or cash</th><th scope="col">Local close</th><th scope="col">FX to AUD</th><th scope="col">Value in AUD</th><th scope="col">Weight</th></tr></thead>
        <tbody>{review.positions.map(row => <tr key={row.instrument}>
          <th scope="row">{row.label}<small>{row.instrument}</small></th><td>{row.quantity}</td>
          <td>{row.instrument.startsWith("CASH:") ? "Cash balance" : row.local_price ? row.currency + " " + row.local_price : "Missing close"}</td>
          <td>{row.aud_fx}</td><td>{row.aud_value === null ? "Unavailable" : money(row.aud_value)}</td>
          <td>{row.weight === null ? "Unavailable" : percent.format(Number(row.weight))}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="method">Method {review.method}. FX is AUD per unit of the quoted currency.</p>
    </details>
  </article>;
}

function App() {
  const [sample, setSample] = useState<Sample | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [date, setDate] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [reports, setReports] = useState<ReviewSummary[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadReview(id: string, history: ReviewSummary[]) {
    const loaded = await request<Review>("/reviews/" + id);
    setReview(loaded);
    setComparison(null);
    const base = history.find(row => row.status === "complete" && row.snapshot_date < loaded.snapshot_date);
    if (base && loaded.status === "complete") {
      setComparison(await request<Comparison>("/reviews/" + id + "/comparison?base=" + encodeURIComponent(base.id)));
    }
  }

  async function refresh(selected?: string) {
    const history = await request<ReviewSummary[]>("/reviews");
    setReports(history);
    if (selected || history[0]) await loadReview(selected ?? history[0].id, history);
  }

  useEffect(() => {
    request<Sample>("/sample").then(value => {
      setSample(value);
      setDate(value.dates[0]);
    }).catch(() => setError("Sample data is unavailable."));
    request<Session>("/session").then(async value => {
      setSession(value);
      await refresh();
    }).catch(error => {
      if (!(error instanceof RequestError) || error.status !== 401) setError("Could not restore the workspace.");
    }).finally(() => setReady(true));
  }, []);

  async function action(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await operation();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function upload(input: Blob, name: string) {
    const form = new FormData();
    form.set("snapshot_date", date);
    form.set("file", input, name);
    setDraft(null);
    setDraft(await request<Draft>("/imports", { method: "POST", body: form }));
  }

  async function confirm() {
    if (!draft) return;
    const job = await request<{ id: string }>("/imports/" + draft.id + "/confirm", { method: "POST" });
    setMessage("Valuation queued.");
    for (let attempt = 0; attempt < 25; attempt++) {
      const status = await request<{ state: string; report_id: string | null }>("/jobs/" + job.id);
      if (status.state === "failed") throw new Error("The worker could not publish this review.");
      if (status.report_id) {
        await refresh(status.report_id);
        setDraft(null);
        setMessage("Review published.");
        return;
      }
      await new Promise(resolve => window.setTimeout(resolve, 600));
    }
    setMessage("Valuation is still queued. Refresh report history to check again.");
  }

  return <>
    <header><div className="topbar">
      <a className="brand" href="/">Portfolio Workbench</a>
      <div className="header-actions"><span className="tag">Synthetic workspace</span>
        {session && <button className="secondary" disabled={busy} onClick={() => void action(async () => {
          await request<void>("/session", { method: "DELETE" });
          setSession(null); setDraft(null); setReports([]); setReview(null); setComparison(null); setFile(null);
        })}>Close workspace</button>}
      </div>
    </div></header>
    <main>
      <div className="intro">
        <h1>{session ? "Review your portfolio" : "Understand what moved your portfolio"}</h1>
        <p>Review ASX and US holdings in AUD. See how prices, exchange rates and changes to your holdings contributed.</p>
      </div>
      {error && <p className="notice warning" role="alert">{error}</p>}
      {message && <p role="status" className="notice">{message}</p>}
      {!session && <section className="panel welcome">
        <h2>Try a sample portfolio</h2>
        <p>This workspace uses synthetic prices and fixtures. Use the sample CSV or create your own synthetic positions.</p>
        <button disabled={!ready || busy || !sample} onClick={() => void action(async () => {
          setSession(await request<Session>("/session", { method: "POST" }));
        })}>Start sample workspace</button>
      </section>}
      {session && <div className="workspace">
        <aside>
          <section className="panel controls" aria-labelledby="import-title">
            <h2 id="import-title">Import holdings</h2>
            <label htmlFor="snapshot-date">Snapshot date</label>
            <select id="snapshot-date" value={date} disabled={busy} onChange={event => {
              setDate(event.target.value); setDraft(null);
            }}>{sample?.dates.map(value => <option key={value} value={value}>{day(value)}</option>)}</select>
            <button disabled={busy || !sample} onClick={() => sample && void action(() => upload(new Blob([sample.csv], { type: "text/csv" }), "sample.csv"))}>Load sample holdings</button>
            <label htmlFor="upload">Or choose a synthetic CSV</label>
            <input id="upload" type="file" accept=".csv,text/csv" disabled={busy} onChange={event => {
              setFile(event.target.files?.[0] ?? null); setDraft(null);
            }} />
            <button className="secondary" disabled={!file || busy} onClick={() => file && void action(() => upload(file, file.name))}>Preview CSV</button>
          </section>
          <section className="panel history" aria-labelledby="history-title">
            <div className="section-heading"><h2 id="history-title">Review history</h2>
              <button className="text-button" disabled={busy} onClick={() => void action(() => refresh(review?.id))}>Refresh</button>
            </div>
            {reports.length === 0 && <p>No published review yet.</p>}
            {reports.map(row => <button className="history-item" key={row.id} disabled={busy} aria-current={row.id === review?.id}
              onClick={() => void action(() => loadReview(row.id, reports))}>
              <span>{day(row.snapshot_date)}</span><small>{row.status === "partial" ? "Partial" : "Complete"}</small>
            </button>)}
          </section>
        </aside>
        <div className="review-area">
          {draft && <section className="panel preview" aria-labelledby="preview-title">
            <div className="section-heading"><h2 id="preview-title">Check imported holdings</h2><p>{day(draft.snapshot_date)}</p></div>
            {!!draft.issues.length && <ul className="notice warning">{draft.issues.map((issue, index) =>
              <li key={index}>{issue.row ? "Row " + issue.row + " · " : ""}{issue.message}</li>
            )}</ul>}
            <dl>{draft.positions.map(row => <div key={row.instrument}><dt>{row.instrument}</dt><dd>{row.quantity}</dd></div>)}</dl>
            <button disabled={busy || draft.issues.length > 0} onClick={() => void action(confirm)}>Confirm and value holdings</button>
          </section>}
          {review ? <Report review={review} comparison={comparison} /> : !draft && <section className="panel empty">
            <h2>Your first review</h2><p>Load sample holdings, then confirm the snapshot to see its AUD valuation and source figures.</p>
          </section>}
        </div>
      </div>}
    </main>
  </>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
