"use client";
import { useEffect, useRef, useState } from "react";
import { request, thumbnailUrl } from "@/lib/core-api";
type Row = Record<string, unknown>;
type Plan = { id: string; spec: Row; queries: unknown[]; providers: unknown[]; strategy: Row };
type Run = Row & { id: string; state: string };
type Candidate = Row & {
  id: string;
  asset_id?: string;
  decisions: { decision: string; reason: string; scores: Row }[];
};
type Review = { run: Run; items: Candidate[]; total: number; queries: Row[]; rejections: Row[] };
const post = <T,>(url: string, body: unknown = {}) =>
  request<T>(url, { method: "POST", body: JSON.stringify(body) });
const str = (x: unknown) => String(x ?? "");
const list = (x: unknown) => (Array.isArray(x) ? x.map(String) : []);
const split = (x: string) =>
  x
    .split(/\n|,/)
    .map((x) => x.trim())
    .filter(Boolean);
export default function Sources({ projectId }: { projectId: string }) {
  const [prompt, setPrompt] = useState(
      "Find 200 red fox photographs in snowy forests, minimum 1024 pixels.",
    ),
    [plan, setPlan] = useState<Plan | null>(null),
    [form, setForm] = useState<Row>({}),
    [dirty, setDirty] = useState(false),
    [consent, setConsent] = useState(false),
    [count, setCount] = useState(10),
    [runs, setRuns] = useState<Run[]>([]),
    [runId, setRunId] = useState(""),
    [review, setReview] = useState<Review | null>(null),
    [filter, setFilter] = useState("review"),
    [offset, setOffset] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [rate, setRate] = useState(0);
  const prior = useRef<{ bytes: number; at: number } | null>(null);
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  function apply(p: Plan) {
    const s = p.spec,
      t = s.target as Row,
      b = s.budget as Row;
    setPlan(p);
    setForm({
      ...s,
      target_count: t?.count ?? 100,
      max_candidates: b?.max_candidates ?? 1500,
      max_download_bytes: b?.max_download_bytes ?? 26843545600,
      max_storage_bytes: b?.max_storage_bytes ?? 21474836480,
      max_requests: b?.max_requests ?? 2000,
    });
    setDirty(false);
    setConsent(false);
  }
  function change(key: string, value: unknown) {
    setForm({ ...form, [key]: value });
    setDirty(true);
    setConsent(false);
  }
  async function loadRuns() {
    const r = await request<{ items: Run[] }>(`/lab/projects/${projectId}/acquisition-runs`);
    setRuns(r.items);
    if (!runId && r.items.length) setRunId(r.items[0].id);
  }
  useEffect(() => {
    void loadRuns().catch((e) => setError(String(e)));
  }, [projectId]);
  useEffect(() => {
    if (!runId) return;
    let live = true;
    prior.current = null;
    const tick = async () => {
      try {
        const r = await request<Review>(
          `/lab/acquisition/runs/${runId}/review?state=${filter}&offset=${offset}`,
        );
        if (!live) return;
        setReview(r);
        const now = Date.now(),
          bytes = Number(r.run.bytes_downloaded ?? 0),
          old = prior.current;
        if (old) setRate(Math.max(0, (bytes - old.bytes) / ((now - old.at) / 1000)));
        prior.current = { bytes, at: now };
      } catch (e) {
        if (live) setError(String(e));
      }
    };
    void tick();
    const timer = setInterval(tick, 3000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [runId, filter, offset]);
  async function start(test: boolean) {
    if (!plan || dirty || !consent) return;
    await post(`/lab/projects/${projectId}/acquisition-consent`, { allow_remote: true });
    const r = await post<{ run: Run }>(`/acquisition/plans/${plan.id}/${test ? "test" : "start"}`, {
      allow_remote: true,
      count,
    });
    setRunId(r.run.id);
    setOffset(0);
    setConsent(false);
    setNotice(`${test ? "Test" : "Acquisition"} started. Review progress below.`);
    await loadRuns();
  }
  const num = (key: string, label: string, min: number, max: number) => (
    <label key={key}>
      {label}
      <input
        aria-label={label}
        type="number"
        min={min}
        max={max}
        value={Number(form[key] ?? min)}
        onChange={(e) => change(key, Number(e.target.value))}
      />
    </label>
  );
  const lines = (key: string, label: string) => (
    <label key={key}>
      {label}
      <textarea
        aria-label={label}
        rows={3}
        value={typeof form[key] === "string" ? String(form[key]) : list(form[key]).join("\n")}
        onChange={(e) => change(key, e.target.value)}
      />
    </label>
  );
  return (
    <section className="data-lab batch-lab">
      <div className="lab-eyebrow">SOURCES / ACQUIRE FROM WEB</div>
      <h1>Build a reviewed dataset.</h1>
      <p>
        Describe the target, inspect the plan, then explicitly authorize a test or acquisition.
        Planning does not download candidates.
      </p>
      <label>
        Acquisition request
        <textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </label>
      <button
        className="primary"
        disabled={busy || !prompt.trim()}
        onClick={() =>
          void act(async () => {
            const r = await post<{ plan: Plan }>(`/projects/${projectId}/acquisition/requests`, {
              prompt,
            });
            apply(r.plan);
            setNotice("Plan ready. No downloads have started.");
          })
        }
      >
        Preview acquisition plan
      </button>
      {error && (
        <p role="alert" className="lab-alert">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="lab-warning">
          {notice}
        </p>
      )}
      {plan && (
        <div className="lab-panel">
          <h2>Editable acquisition plan</h2>
          <label>
            Topic and context
            <input value={str(form.topic)} onChange={(e) => change("topic", e.target.value)} />
          </label>
          <div className="lab-fields">
            {num("target_count", "Accepted target", 1, 100000)}
            {num("min_width", "Minimum width", 1, 100000)}
            {num("min_height", "Minimum height", 1, 100000)}
            {num("max_candidates", "Candidate budget", 1, 1000000)}
            {num("min_quality", "Minimum quality", 0, 100)}
            {num("near_duplicate_threshold", "Duplicate distance", 0, 64)}
            {num("max_download_bytes", "Download budget (bytes)", 1, 1073741824000)}
            {num("max_storage_bytes", "Storage budget (bytes)", 1, 1073741824000)}
            {num("max_requests", "Request budget", 1, 100000)}
            {lines("queries", "Search queries (one per line)")}
            {lines("provider_ids", "Provider IDs (one per line)")}
            {lines("categories", "Categories / topic context")}
            {lines("allowed_licenses", "Allowed license labels (empty allows any; exact match)")}
            {lines("allowed_domains", "Allowed source domains (empty allows any)")}
            <label>
              Relevance strategy
              <select
                value={str(form.relevance_strategy ?? "auto")}
                onChange={(e) => change("relevance_strategy", e.target.value)}
              >
                {["auto", "metadata", "manual", "disabled"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            {[
              "reject_exact_duplicates",
              "reject_near_duplicates",
              "reject_text_heavy",
              "replenish_until_target",
            ].map((k) => (
              <label key={k} className="lab-check">
                <input
                  type="checkbox"
                  checked={Boolean(form[k])}
                  onChange={(e) => change(k, e.target.checked)}
                />
                {k.replaceAll("_", " ")}
              </label>
            ))}
          </div>
          <details>
            <summary>Provider capabilities and plan strategy</summary>
            <pre className="batch-details">{JSON.stringify(plan.strategy, null, 2)}</pre>
          </details>
          <div className="lab-toolbar">
            <button
              disabled={busy || !dirty}
              onClick={() =>
                void act(async () => {
                  const r = await post<{ plan: Plan }>(
                    `/projects/${projectId}/acquisition/plans`,
                    Object.fromEntries(
                      Object.entries(form).map(([k, v]) => [
                        [
                          "queries",
                          "provider_ids",
                          "categories",
                          "allowed_licenses",
                          "allowed_domains",
                        ].includes(k)
                          ? k
                          : k,
                        [
                          "queries",
                          "provider_ids",
                          "categories",
                          "allowed_licenses",
                          "allowed_domains",
                        ].includes(k) && typeof v === "string"
                          ? split(v)
                          : v,
                      ]),
                    ),
                  );
                  apply(r.plan);
                  setNotice("Updated plan saved. Review it before starting.");
                })
              }
            >
              Save edited plan
            </button>
            {dirty && <span>Save edits before starting.</span>}
          </div>
          <label className="lab-check">
            <input
              type="checkbox"
              checked={consent}
              disabled={dirty}
              onChange={(e) => setConsent(e.target.checked)}
            />
            I authorize external discovery and downloads for this plan and enable approved external
            access for this project.
          </label>
          <div className="lab-toolbar">
            <label>
              Test candidates
              <input
                type="number"
                min={1}
                max={100}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </label>
            <button
              disabled={busy || dirty || !consent || count < 1 || count > 100}
              onClick={() => void act(() => start(true))}
            >
              Test {count} candidates
            </button>
            <button
              className="primary"
              disabled={busy || dirty || !consent}
              onClick={() => void act(() => start(false))}
            >
              Start acquisition
            </button>
          </div>
        </div>
      )}
      <div className="lab-panel">
        <div className="lab-toolbar">
          <label>
            Acquisition history
            <select
              aria-label="Acquisition history"
              value={runId}
              onChange={(e) => {
                setRunId(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">No run selected</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {str((r.spec as Row)?.topic)} · {r.state} · {r.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button disabled={busy} onClick={() => void act(loadRuns)}>
            Refresh history
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await post(`/lab/projects/${projectId}/acquisition-consent`, {
                  allow_remote: false,
                });
                setConsent(false);
                setNotice(
                  "Project set to local-only. Running acquisition will stop at its next policy check.",
                );
              })
            }
          >
            Disable external access
          </button>
        </div>
        {review && (
          <>
            <h2>Progress · {review.run.state}</h2>
            <progress
              max={Number(review.run.target_count ?? 1)}
              value={Number(review.run.accepted_count ?? 0)}
            />
            <div className="lab-stats">
              {[
                ["Target", "target_count"],
                ["Accepted", "accepted_count"],
                ["Needs review", "review_count"],
                ["Rejected", "rejected_count"],
                ["Candidates", "discovered_count"],
                ["Failed", "failed_count"],
              ].map(([label, key]) => (
                <div key={key}>
                  <span>{label}</span>
                  <strong>{str(review.run[key])}</strong>
                </div>
              ))}
            </div>
            <p>
              Yield {(Number(review.run.observed_yield ?? 0) * 100).toFixed(1)}% · downloaded{" "}
              {(Number(review.run.bytes_downloaded ?? 0) / 1048576).toFixed(2)} MB ·{" "}
              {(rate / 1024).toFixed(1)} KB/s
            </p>
            {Boolean(review.run.stop_reason || review.run.error) && (
              <p className="lab-warning">{str(review.run.stop_reason || review.run.error)}</p>
            )}
            <div className="lab-toolbar">
              {["pause", "resume", "cancel"].map((action) => (
                <button
                  key={action}
                  disabled={busy || ["completed", "cancelled"].includes(review.run.state)}
                  onClick={() =>
                    void act(async () => {
                      await post(`/acquisition/runs/${runId}/${action}`);
                      const r = await request<Review>(
                        `/lab/acquisition/runs/${runId}/review?state=${filter}&offset=${offset}`,
                      );
                      setReview(r);
                    })
                  }
                >
                  {action}
                </button>
              ))}
            </div>
            <details>
              <summary>Query and provider progress</summary>
              {review.queries.map((q, i) => (
                <p key={i}>
                  {str(q.provider_id)} · {str(q.query)} · {str(q.evaluated_count)} evaluated /{" "}
                  {str(q.accepted_count)} accepted {q.exhausted ? "· exhausted" : ""}
                </p>
              ))}
            </details>
            {review.rejections.length > 0 && (
              <p>
                Rejection reasons:{" "}
                {review.rejections.map((r) => `${str(r.reason)} (${str(r.count)})`).join(" · ")}
              </p>
            )}
            <nav className="lab-tabs" aria-label="Candidate states">
              {[
                ["review", "Needs review"],
                ["accepted", "Accepted"],
                ["rejected", "Rejected"],
                ["", "All"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  aria-current={filter === value ? "page" : undefined}
                  onClick={() => {
                    setFilter(value);
                    setOffset(0);
                  }}
                >
                  {label}
                </button>
              ))}
            </nav>
            <p>{review.total} candidates in this view</p>
            <div className="batch-candidates">
              {review.items.map((c) => (
                <article className="lab-panel batch-candidate" key={c.id}>
                  {c.asset_id ? (
                    <img loading="lazy" src={thumbnailUrl(c.asset_id)} alt={str(c.title)} />
                  ) : (
                    <p>Preview unavailable · {str(c.state)}</p>
                  )}
                  <h3>{str(c.title) || str(c.remote_id)}</h3>
                  <p>
                    {str(c.provider_id)} · {str(c.license) || "License unknown"} ·{" "}
                    {str(c.declared_width)}×{str(c.declared_height)}
                  </p>
                  <p>Query: {str(c.query)}</p>
                  <a
                    href={str(c.landing_page_url || c.source_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open source
                  </a>
                  {c.decisions.map((d, i) => (
                    <p key={i}>
                      {d.decision}: {d.reason} · {JSON.stringify(d.scores)}
                    </p>
                  ))}
                  {Boolean(c.error) && <p>{str(c.error)}</p>}
                  <div className="lab-toolbar">
                    {["accept", "review", "reject"].map((decision) => (
                      <button
                        key={decision}
                        disabled={busy || (decision === "accept" && !c.asset_id)}
                        onClick={() =>
                          void act(async () => {
                            await post(`/acquisition/candidates/${c.id}/decision`, { decision });
                            const r = await request<Review>(
                              `/lab/acquisition/runs/${runId}/review?state=${filter}&offset=${offset}`,
                            );
                            setReview(r);
                          })
                        }
                      >
                        {decision}
                      </button>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <div className="lab-toolbar">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
                Previous candidates
              </button>
              <button disabled={offset + 50 >= review.total} onClick={() => setOffset(offset + 50)}>
                Next candidates
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
