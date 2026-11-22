import { useEffect, useState } from "react";
import { request } from "./api";
import type { Review } from "./api";
import { day, money } from "./format";

type Job = { id: string };
type Rule = { id: string; instrument: string; threshold: string | number; last_date: string | null };
type Alert = {
  id: string; instrument: string; snapshot_date: string; weight: string | number;
  threshold: string | number; acknowledged_at: string | null;
};
type Monitor = {
  schedule: { enabled: boolean; last_period: string | null };
  listings: string[]; rules: Rule[]; alerts: Alert[];
};
type NewsEntry = {
  id: string; instrument: string; date: string; title: string; category: string; url?: string;
};
type Experiment = {
  runs: Record<string, Record<string, number | null>>; news_covered_asset_sessions: number;
};

const json = (method: string, body: object): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "The action could not be completed.";

function useTask() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try {
      await task();
    } catch (error) {
      setError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, notice, run, setNotice, setError };
}

function Feedback({ error, notice }: { error: string; notice?: string }) {
  return <>{error && <p role="alert" className="notice warning">{error}</p>}
    {notice && <p role="status" className="notice">{notice}</p>}</>;
}

export function Scenario({ review }: { review: Review }) {
  const positions = review.positions.filter(row => !row.instrument.startsWith("CASH:"));
  const [instrument, setInstrument] = useState(positions[0]?.instrument ?? "");
  const [shock, setShock] = useState("-10");
  const [result, setResult] = useState<{ scenario_aud: string; aud_change: string } | null>(null);
  const task = useTask();
  return <section className="panel flow" aria-labelledby="scenario-title">
    <h2 id="scenario-title">What-if scenario</h2>
    <p>Change the price of one holding. All other prices, quantities and exchange rates stay fixed.</p>
    <Feedback error={task.error} />
    {review.status === "complete" ? <form className="flow" onSubmit={event => {
      event.preventDefault();
      void task.run(async () => setResult(await request("/reviews/" + review.id + "/scenario",
        json("POST", { instrument, change_percent: shock }))));
    }}>
      <div className="fields">
        <label>Scenario holding<select value={instrument} onChange={event => { setInstrument(event.target.value); setResult(null); }}>
          {positions.map(row => <option key={row.instrument} value={row.instrument}>{row.label}</option>)}
        </select></label>
        <label>Price change (%)<input type="number" min="-100" max="1000" step="0.0001" required
          value={shock} onChange={event => { setShock(event.target.value); setResult(null); }} /></label>
      </div>
      <button disabled={task.busy || !instrument}>Calculate scenario</button>
      {result && <p role="status" className="notice">Scenario value <strong>{money(result.scenario_aud)}</strong>. Change <strong>{money(result.aud_change, true)}</strong>.</p>}
    </form> : <p className="notice warning">Complete price coverage is required for a portfolio scenario.</p>}
  </section>;
}

export function Monitoring({ dates, onPublish }: {
  dates: string[]; onPublish: (job: Job) => Promise<void>;
}) {
  const [data, setData] = useState<Monitor | null>(null);
  const [selected, setSelected] = useState("");
  const [threshold, setThreshold] = useState("50");
  const [date, setDate] = useState(dates.at(-1) ?? "");
  const task = useTask();

  async function refresh() {
    const monitor = await request<Monitor>("/monitor");
    setData(monitor);
    setSelected(current => current || monitor.listings[0] || "");
  }

  useEffect(() => { void task.run(refresh); }, []);

  return <div className="dashboard-grid">
    <section className="panel flow" aria-labelledby="refresh-title">
      <h2 id="refresh-title">Refresh a review</h2>
      <p>Use the latest confirmed holdings at or before the selected date. The next report keeps their original holdings date.</p>
      <label>Refresh date<select value={date} onChange={event => setDate(event.target.value)}>
        {dates.map(value => <option key={value} value={value}>{day(value)}</option>)}
      </select></label>
      <button disabled={task.busy || !date} onClick={() => void task.run(async () => {
        const job = await request<Job>("/refresh", json("POST", { snapshot_date: date }));
        await onPublish(job);
      })}>Queue refresh</button>
      <label className="checkbox">
        <input type="checkbox" checked={data?.schedule.enabled ?? false} disabled={!data || task.busy}
          onChange={event => {
            const enabled = event.target.checked;
            void task.run(async () => {
              await request("/monitor/schedule", json("PUT", { enabled }));
              await refresh();
              task.setNotice(enabled ? "Scheduled refresh enabled." : "Scheduled refresh paused.");
            });
          }} /> Refresh automatically when new end-of-day observations are available
      </label>
      {data?.schedule.last_period && <p>Last scheduled period {day(data.schedule.last_period)}.</p>}
      <Feedback error={task.error} notice={task.notice} />
    </section>
    <section className="panel flow" aria-labelledby="rules-title">
      <h2 id="rules-title">Concentration alerts</h2>
      <p>Get an in-app alert when a holding crosses your weight threshold on an eligible newer review.</p>
      <form className="flow" onSubmit={event => {
        event.preventDefault();
        void task.run(async () => {
          await request("/monitor/rules", json("POST", { instrument: selected, threshold }));
          await refresh();
          task.setNotice("Concentration rule saved.");
        });
      }}>
        <div className="fields">
          <label>Holding<select value={selected} onChange={event => setSelected(event.target.value)}>
            {data?.listings.map(item => <option key={item}>{item}</option>)}
          </select></label>
          <label>Portfolio weight (%)<input type="number" min="0.0001" max="100" step="0.0001" required value={threshold}
            onChange={event => setThreshold(event.target.value)} /></label>
        </div>
        <button disabled={task.busy || !selected}>Add concentration rule</button>
      </form>
      {data?.rules.length === 0 && <p>No rules yet.</p>}
      {data?.rules.map(rule => <div className="list-row" key={rule.id}>
        <span>{rule.instrument} · {Number(rule.threshold)}%{rule.last_date ? " · evaluated " + day(rule.last_date) : " · awaiting a review"}</span>
        <button className="text-button" disabled={task.busy} aria-label={`Remove ${rule.instrument} rule at ${Number(rule.threshold)} percent`}
          onClick={() => void task.run(async () => {
            await request("/monitor/rules/" + rule.id, { method: "DELETE" });
            await refresh();
          })}>Remove</button>
      </div>)}
    </section>
    <section className="panel flow wide" aria-labelledby="alerts-title">
      <div className="section-heading"><h2 id="alerts-title">Alert inbox</h2>
        <button className="text-button" disabled={task.busy} onClick={() => void task.run(refresh)}>Refresh inbox</button></div>
      {data?.alerts.length === 0 && <p>No concentration crossings yet.</p>}
      {data?.alerts.map(alert => <div key={alert.id} className="list-row">
        <div><strong>{alert.instrument} crossed {Number(alert.threshold)}%</strong>
          <p>{day(alert.snapshot_date)} · portfolio weight {Number(alert.weight).toFixed(2)}%</p></div>
        {alert.acknowledged_at ? <span className="tag">Read</span> : <button className="secondary" disabled={task.busy}
          onClick={() => void task.run(async () => {
            await request("/monitor/alerts/" + alert.id + "/read", { method: "PUT" });
            await refresh();
          })}>Mark as read</button>}
      </div>)}
    </section>
  </div>;
}

export function Research({ review, synthetic }: { review: Review | null; synthetic: boolean }) {
  const [events, setEvents] = useState<NewsEntry[] | null>(null);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [ppo, setPpo] = useState(false);
  const task = useTask();

  useEffect(() => {
    if (!review) return;
    const ctrl = new AbortController();
    request<{ events: NewsEntry[] }>("/reviews/" + review.id + "/events", { signal: ctrl.signal })
      .then(result => setEvents(result.events))
      .catch(error => { if (!ctrl.signal.aborted) task.setError(errorMessage(error)); });
    return () => ctrl.abort();
  }, [review?.id]);

  return <div className="dashboard-grid">
    <section className="panel flow" aria-labelledby="events-title">
      <h2 id="events-title">Holdings events</h2>
      <p>{review ? "Available by the " + day(review.snapshot_date) + " review." : "Publish or select a review to see its holdings events."}</p>
      {synthetic && <span className="tag">Illustrative events</span>}
      {events?.length === 0 && <p>No eligible events for these holdings.</p>}
      {events?.map(event => <article className="event" key={event.id}>
        <small>{event.instrument} · {event.category} · {day(event.date)}</small>
        <h3>{event.title}</h3>
        {event.url && <a href={event.url} target="_blank" rel="noopener noreferrer">Open source evidence</a>}
      </article>)}
    </section>
    <section className="panel flow" aria-labelledby="research-title">
      <h2 id="research-title">NewsAlpha research</h2>
      <p>Compare strategy baselines on a fixed synthetic dataset with matched execution costs and news cutoffs.</p>
      <label className="checkbox"><input type="checkbox" checked={ppo} disabled={task.busy}
        onChange={event => { setPpo(event.target.checked); setExperiment(null); }} /> Include PPO research presets</label>
      <button disabled={task.busy} onClick={() => void task.run(async () => {
        setExperiment(await request<Experiment>("/research?ppo=" + ppo));
      })}>{task.busy ? "Running experiment…" : "Run sample experiment"}</button>
      <Feedback error={task.error} />
      {experiment && <>
        <p>{experiment.news_covered_asset_sessions} asset sessions with eligible news.</p>
        <div className="table-wrap"><table>
          <thead><tr><th scope="col">Strategy</th><th scope="col">Total return</th><th scope="col">Drawdown</th></tr></thead>
          <tbody>{Object.entries(experiment.runs).map(([name, metrics]) => <tr key={name}>
            <th scope="row">{name}</th>
            <td>{displayReturn(metrics.period_return)}</td><td>{displayReturn(metrics.max_drawdown)}</td>
          </tr>)}</tbody>
        </table></div>
        <a className="download" href={`/api/workbench/v1/research?download=true&ppo=${ppo}`}>Download experiment evidence</a>
      </>}
    </section>
  </div>;
}

function displayReturn(value: number | null | undefined) {
  return typeof value === "number" ? (value * 100).toFixed(2) + "%" : "Unavailable";
}

export function Settings({ onDelete, synthetic }: { onDelete: () => void; synthetic: boolean }) {
  const [phrase, setPhrase] = useState("");
  const task = useTask();
  return <div className="dashboard-grid">
    <section className="panel flow">
      <h2>Export workspace</h2>
      <p>Download the published reviews, concentration rules and recent in-app alerts available in this workspace.</p>
      {!synthetic && <p><a href="/auth/login">Sign in again</a> if your last sign-in was more than 15 minutes ago.</p>}
      <a className="download" href="/api/workbench/v1/workspace/export">Download workspace data</a>
    </section>
    <section className="panel flow">
      <h2>Delete workspace</h2>
      <p>This removes workspace data and ends the current session. Type DELETE to continue.</p>
      <form className="flow" onSubmit={event => {
        event.preventDefault();
        void task.run(async () => {
          await request("/workspace", json("DELETE", { confirm: phrase }));
          onDelete();
        });
      }}>
        <label>Confirmation<input value={phrase} onChange={event => setPhrase(event.target.value)} autoComplete="off" /></label>
        <button className="danger" disabled={task.busy || phrase !== "DELETE"}>Delete workspace permanently</button>
      </form>
      <Feedback error={task.error} />
    </section>
  </div>;
}
