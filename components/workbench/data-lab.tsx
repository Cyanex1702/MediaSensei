"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  Play,
  Plus,
  Search,
  Sparkles,
  Star,
  X,
} from "lucide-react";
import { api } from "@/lib/core-api";
import {
  lab,
  downloadText,
  type Operation,
  type Dataset,
  type Overview,
  type Step,
  type Preview,
  type Run,
  type Version,
  type Chart,
  type Row,
} from "@/lib/workbench-api";
import { DataChart, DataGrid } from "./data-views";
import { VisualizationReport } from "./visualization-report";
import { ParameterFields, QueryTools, WorkflowEditor, VersionCompare } from "./advanced-tools";
import { batch, type Query, type SavedChart } from "@/lib/batch-api";

type Props = {
  requestedTab?: string;
  projectId: string;
  jobRevision: string;
  requestedOperation?: string;
  onQueued: () => void;
};
export default function DataLab({
  requestedTab,
  projectId,
  jobRevision,
  requestedOperation,
  onQueued,
}: Props) {
  const [query, setQuery] = useState<Query>({ conditions: [] }),
    [positions, setPositions] = useState<number[]>([]),
    [selection, setSelection] = useState<number[]>([]),
    [visible, setVisible] = useState<string[]>([]),
    [sampleMode, setSampleMode] = useState("first"),
    [savedCharts, setSavedCharts] = useState<SavedChart[]>([]),
    [category, setCategory] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]),
    [sources, setSources] = useState<Array<Record<string, unknown>>>([]),
    [id, setId] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null),
    [rows, setRows] = useState<Row[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0),
    [search, setSearch] = useState(""),
    [sort, setSort] = useState("");
  const [operations, setOperations] = useState<Operation[]>([]),
    [opId, setOpId] = useState("profile"),
    [params, setParams] = useState<Record<string, unknown>>({}),
    [opSearch, setOpSearch] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null),
    [chart, setChart] = useState<Chart | null>(null),
    [runs, setRuns] = useState<Run[]>([]),
    [versions, setVersions] = useState<Version[]>([]);
  const [tab, setTab] = useState("Explore"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [column, setColumn] = useState("");
  const [steps, setSteps] = useState<Step[]>([]),
    [name, setName] = useState("My preparation workflow"),
    [guide, setGuide] = useState(true),
    [expert, setExpert] = useState(false),
    [favorites, setFavorites] = useState<string[]>([]);
  useEffect(() => {
    const dataset = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail.project === projectId) setId(detail.id);
    };
    const operation = (event: Event) => {
      setOpId((event as CustomEvent).detail);
      setTab("Explore");
    };
    window.addEventListener("sensei.dataset", dataset);
    window.addEventListener("sensei.operation", operation);
    return () => {
      window.removeEventListener("sensei.dataset", dataset);
      window.removeEventListener("sensei.operation", operation);
    };
  }, [projectId]);
  useEffect(() => {
    if (requestedTab) setTab(requestedTab);
  }, [requestedTab]);
  useEffect(() => {
    try {
      setGuide(localStorage.getItem("sensei.guide") !== "false");
      setExpert(localStorage.getItem("sensei.expert") === "true");
    } catch {}
  }, []);
  useEffect(() => {
    if (id)
      batch
        .charts(id)
        .then((r) => setSavedCharts(r.items))
        .catch((e) => setError(String(e)));
  }, [id]);
  useEffect(() => {
    setSelection([]);
  }, [id, overview?.dataset.revision]);
  useEffect(() => {
    if (id) localStorage.setItem(`sensei.dataset.${projectId}`, id);
  }, [id, projectId]);
  const active = useRef(id);
  active.current = id;
  const operation = operations.find((o) => o.id === opId),
    selectedColumn = overview?.profile.columns.find((c) => c.name === column);
  const step = { operation: opId, parameters: params };
  const loadList = useCallback(async () => {
    const [ds, ts] = await Promise.all([lab.datasets(projectId), api.tabularDatasets(projectId)]);
    setDatasets(ds.items);
    setSources(ts.items.filter((t) => t.normalized_object_key));
    setId(
      (old) =>
        old ||
        ds.items.find((d) => d.id === localStorage.getItem(`sensei.dataset.${projectId}`))?.id ||
        ds.items[0]?.id ||
        "",
    );
  }, [projectId]);
  useEffect(() => {
    let done = false;
    lab
      .operations()
      .then((r) => {
        if (!done) setOperations(r.items);
      })
      .catch((e) => setError(String(e)));
    try {
      setFavorites(JSON.parse(localStorage.getItem("sensei-favorites") || "[]"));
    } catch {}
    return () => {
      done = true;
    };
  }, []);
  useEffect(() => {
    setId("");
    setOverview(null);
    setSteps([]);
    setPreview(null);
    setRows([]);
    loadList().catch((e) => setError(String(e)));
  }, [loadList]);
  useEffect(() => {
    if (requestedOperation) {
      setOpId(requestedOperation);
      setTab("Explore");
    }
  }, [requestedOperation]);
  const refresh = useCallback(async () => {
    if (!id) return;
    const [ov, rr, vv] = await Promise.all([lab.overview(id), lab.runs(id), lab.versions(id)]);
    if (active.current !== id) return;
    setOverview(ov);
    setRuns(rr.items);
    setVersions(vv.items);
    const latest = rr.items.find((r) => r.state === "completed");
    const c = latest?.data.history?.findLast((h) => h.chart)?.chart;
    if (c) setChart(c);
  }, [id]);
  useEffect(() => {
    refresh().catch((e) => setError(String(e)));
  }, [refresh, jobRevision]);
  useEffect(() => {
    let done = false;
    if (!id) return;
    const timer = setTimeout(
      () =>
        batch
          .query(id, { ...query, offset, search, sort_by: sort })
          .then((r) => {
            if (!done) {
              setRows(r.rows);
              setPositions(r.positions);
              setTotal(r.total);
            }
          })
          .catch((e) => {
            if (!done) setError(String(e));
          }),
      200,
    );
    return () => {
      done = true;
      clearTimeout(timer);
    };
  }, [id, offset, search, sort, query, overview?.dataset.revision]);
  useEffect(() => {
    setOffset(0);
    setSearch("");
    setSort("");
    setPreview(null);
    setChart(null);
    setColumn("");
    setVisible([]);
    setQuery({ conditions: [] });
  }, [id]);
  useEffect(() => {
    const defaults = Object.fromEntries(
      Object.entries(operation?.parameter_schema ?? {})
        .filter(([, v]) => v.default !== undefined)
        .map(([k, v]) => [k, v.default]),
    );
    setParams(defaults);
    setPreview(null);
  }, [operation]);
  async function action(fn: () => Promise<void>) {
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
  function choose(id: string, values: Record<string, unknown> = {}) {
    setOpId(id);
    setTimeout(() => setParams(values), 0);
    setPreview(null);
    setMessage("");
  }
  async function adopt(source: string) {
    await action(async () => {
      const ds = await lab.adopt(source);
      await loadList();
      setId(ds.id);
      setMessage("Working dataset created. Imported source remains unchanged.");
    });
  }
  async function run(selected: Step[]) {
    if (!overview) return;
    await action(async () => {
      await lab.run(id, selected, overview.dataset.revision);
      const recent = JSON.parse(localStorage.getItem("sensei.recent") || "[]") as string[];
      localStorage.setItem(
        "sensei.recent",
        JSON.stringify([...new Set([...selected.map((s) => s.operation), ...recent])].slice(0, 20)),
      );
      setPreview(null);
      setMessage("Operation queued. Follow its progress in the job drawer.");
      onQueued();
      await refresh();
    });
  }
  function favorite() {
    const next = favorites.includes(opId)
      ? favorites.filter((x) => x !== opId)
      : [...favorites, opId];
    setFavorites(next);
    localStorage.setItem("sensei-favorites", JSON.stringify(next));
  }
  const shown = operations
    .filter(
      (o) =>
        (!category || o.category === category) &&
        `${o.name} ${o.aliases.join(" ")} ${o.description}`
          .toLowerCase()
          .includes(opSearch.toLowerCase()),
    )
    .sort((a, b) => Number(favorites.includes(b.id)) - Number(favorites.includes(a.id)));
  return (
    <section className="data-lab">
      <div className="lab-heading">
        <div>
          <div className="lab-eyebrow">WORKSPACE / DATA LAB</div>
          <h1>Understand. Prepare. Reproduce.</h1>
          <p>Explore your data, preview a change, then apply it to a working copy.</p>
        </div>
        <span className="lab-local">
          <span />
          Local execution
        </span>
      </div>
      {error && (
        <div role="alert" className="lab-alert">
          {error}
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      {message && (
        <p role="status" className="lab-message">
          {message}
        </p>
      )}
      <div className="lab-toolbar">
        <label>
          Dataset
          <select aria-label="Working dataset" value={id} onChange={(e) => setId(e.target.value)}>
            <option value="">Choose a working dataset</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Create from import
          <select
            aria-label="Create from imported table"
            value=""
            disabled={busy}
            onChange={(e) => void adopt(e.target.value)}
          >
            <option value="">Choose an inspected table…</option>
            {sources.map((s) => (
              <option key={String(s.id)} value={String(s.id)}>
                {String(s.name)}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => void action(loadList)}>Refresh imports</button>
        <span className="lab-revision">
          Working copy · revision {overview?.dataset.revision ?? "—"}
        </span>
      </div>
      {!id ? (
        <div className="lab-empty-state">
          <FlaskConical size={36} />
          <h2>Start with a table</h2>
          <p>
            Import CSV, Excel, or Parquet from Overview. Once its inspection job completes, choose
            it above to create a working dataset.
          </p>
          <p>
            Your original file stays intact. Every applied operation records its inputs and
            parameters.
          </p>
        </div>
      ) : (
        <>
          <div className="lab-stats">
            <div>
              <span>Rows</span>
              <strong>{overview?.profile.rows.toLocaleString() ?? "…"}</strong>
            </div>
            <div>
              <span>Columns</span>
              <strong>{overview?.profile.column_count ?? "…"}</strong>
            </div>
            <div>
              <span>Missing cells</span>
              <strong>
                {overview?.profile.columns.reduce((n, c) => n + c.missing, 0).toLocaleString() ??
                  "…"}
              </strong>
            </div>
            <div>
              <span>Duplicate rows</span>
              <strong>{overview?.profile.duplicates.toLocaleString() ?? "…"}</strong>
            </div>
            <div className="lab-stats-note">
              Immutable source<span>Changes apply only to the working copy</span>
            </div>
          </div>
          <div className="lab-layout">
            <div className="lab-main">
              <div className="lab-tabs" role="tablist">
                {[
                  "Explore",
                  "Visualize",
                  "Quality",
                  "Workflows",
                  "Versions",
                  "Exports",
                  "History",
                ].map((t) => (
                  <button
                    key={t}
                    role="tab"
                    aria-selected={t === tab}
                    className={t === tab ? "active" : ""}
                    onClick={() => setTab(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
              {tab === "Explore" && (
                <>
                  <div className="lab-task-categories">
                    {[
                      "",
                      "Explore",
                      "Clean",
                      "Transform",
                      "Combine",
                      "Statistics",
                      "Features",
                      "ML Preparation",
                      "Quality",
                    ].map((c) => (
                      <button
                        key={c}
                        className={category === c ? "active" : ""}
                        onClick={() => {
                          setCategory(c);
                          const op = operations.find((o) => !c || o.category === c);
                          if (op) setOpId(op.id);
                        }}
                      >
                        {c || "All operations"}
                      </button>
                    ))}
                  </div>
                  <QueryTools
                    id={id}
                    columns={overview?.profile.columns.map((c) => c.name) ?? []}
                    query={query}
                    onChange={(q) => {
                      setQuery(q);
                      setOffset(0);
                      if (q.search !== undefined) setSearch(q.search);
                      if (q.sort_by !== undefined) setSort(q.sort_by);
                    }}
                    visible={visible}
                    onVisible={setVisible}
                    selected={selection}
                    onExclude={() =>
                      void run([{ operation: "exclude", parameters: { rows: selection } }])
                    }
                  />
                  <div className="lab-table-tools">
                    <Search size={17} />
                    <input
                      aria-label="Search table rows"
                      placeholder="Search this table…"
                      value={search}
                      onChange={(e) => {
                        setSearch(e.target.value);
                        setOffset(0);
                      }}
                    />
                    <select
                      aria-label="Sort by column"
                      value={sort}
                      onChange={(e) => setSort(e.target.value)}
                    >
                      <option value="">Original order</option>
                      {overview?.profile.columns.map((c) => (
                        <option key={c.name}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  <DataGrid
                    rows={rows}
                    columns={visible.length ? visible : undefined}
                    positions={positions}
                    selected={selection}
                    onSelection={setSelection}
                    onColumn={setColumn}
                  />
                  <div className="lab-pagination">
                    <span>
                      {total ? offset + 1 : 0}–{Math.min(offset + 50, total)} of{" "}
                      {total.toLocaleString()} rows · click a column for its profile
                    </span>
                    <button
                      aria-label="Previous rows"
                      disabled={!offset}
                      onClick={() => setOffset(offset - 50)}
                    >
                      <ChevronLeft size={17} />
                    </button>
                    <button
                      aria-label="Next rows"
                      disabled={offset + 50 >= total}
                      onClick={() => setOffset(offset + 50)}
                    >
                      <ChevronRight size={17} />
                    </button>
                  </div>
                </>
              )}
              {tab === "Visualize" && (
                <div className="lab-panel">
                  <h2>Suggested visualizations</h2>
                  <p>Choose chart axes, grouping and aggregation in Chart builder.</p>
                  <button onClick={() => choose("chart")}>Open chart builder</button>
                  {overview?.profile.findings
                    .filter((f) => ["chart", "correlation", "distribution"].includes(f.operation))
                    .slice(0, 5)
                    .map((f, i) => (
                      <article key={i}>
                        <strong>{f.title}</strong>
                        <p>{f.reason}</p>
                        <button onClick={() => choose(f.operation, f.parameters)}>
                          Configure visualization
                        </button>
                      </article>
                    ))}
                  <div className="lab-suggestions">
                    <button
                      onClick={() => {
                        choose("missing");
                        void action(async () => {
                          const p = await lab.preview(id, { operation: "missing", parameters: {} });
                          setChart(p.chart);
                        });
                      }}
                    >
                      Missing values<span>Find columns needing attention</span>
                    </button>
                    <button
                      onClick={() => {
                        choose("correlation");
                        void action(async () => {
                          const p = await lab.preview(id, {
                            operation: "correlation",
                            parameters: {},
                          });
                          setChart(p.chart);
                        });
                      }}
                    >
                      Correlation heatmap<span>Compare numeric relationships</span>
                    </button>
                    <button onClick={() => choose("distribution")}>
                      Column distribution<span>Choose a column in the inspector</span>
                    </button>
                  </div>
                  {chart ? (
                    <>
                      <DataChart chart={chart} />
                      <label>
                        Chart name
                        <input value={name} onChange={(e) => setName(e.target.value)} />
                      </label>
                      <button
                        disabled={busy || !chart}
                        onClick={() =>
                          void action(async () => {
                            await batch.saveChart(
                              id,
                              name,
                              (chart as Chart & { definition?: Step }).definition ?? step,
                            );
                            setSavedCharts((await batch.charts(id)).items);
                            setMessage(
                              "Chart definition and full-data result saved with its input hash.",
                            );
                          })
                        }
                      >
                        Save chart / add to report
                      </button>
                    </>
                  ) : (
                    <p className="lab-empty">
                      Choose a visualization or preview Column distribution. Previews use the first
                      100 rows; run for full-dataset results.
                    </p>
                  )}
                  <h3>Saved charts and report</h3>
                  {savedCharts.map((c) => (
                    <button key={c.id} onClick={() => setChart(c.chart)}>
                      {c.name}
                    </button>
                  ))}
                  <VisualizationReport charts={savedCharts} />
                </div>
              )}
              {tab === "Quality" && (
                <div className="lab-panel">
                  <h2>Evidence before recommendations</h2>
                  <p>
                    These checks use your current working dataset. Review each finding before
                    applying a change.
                  </p>
                  {overview?.profile.findings.map((f, i) => (
                    <article className="lab-finding" key={i}>
                      <strong>{f.title}</strong>
                      <p>{f.reason}</p>
                      <button onClick={() => choose(f.operation, f.parameters)}>
                        Inspect recommended operation
                      </button>
                    </article>
                  ))}
                </div>
              )}
              {tab === "Workflows" && (
                <WorkflowEditor
                  id={id}
                  projectId={projectId}
                  revision={overview?.dataset.revision ?? 0}
                  steps={steps}
                  setSteps={setSteps}
                  operations={operations}
                  datasets={datasets}
                  columns={overview?.profile.columns.map((c) => c.name) ?? []}
                  onQueued={onQueued}
                />
              )}
              {tab === "Versions" && (
                <div className="lab-panel">
                  <h2>Immutable dataset versions</h2>
                  <VersionCompare
                    id={id}
                    versions={versions}
                    columns={overview?.profile.columns.map((c) => c.name) ?? []}
                  />
                  <p>
                    A version freezes the current data hash and operation history. Restoring changes
                    the working copy; saved versions remain intact.
                  </p>
                  <label>
                    Version name
                    <input value={name} onChange={(e) => setName(e.target.value)} />
                  </label>
                  <button
                    className="primary"
                    disabled={busy || !name.trim()}
                    onClick={() =>
                      void action(async () => {
                        await lab.version(id, name);
                        await refresh();
                        setMessage("Dataset version created.");
                      })
                    }
                  >
                    Create version
                  </button>
                  <div className="lab-version-list">
                    {versions.map((v) => (
                      <article key={v.id}>
                        <div>
                          <strong>{v.name}</strong>
                          <p>
                            {v.manifest.profile.rows.toLocaleString()} rows ·{" "}
                            {v.manifest.profile.column_count} columns · revision{" "}
                            {v.manifest.revision}
                          </p>
                          <small>{new Date(v.created_at).toLocaleString()}</small>
                          <p>
                            Compared with working copy:{" "}
                            {(overview?.profile.rows ?? 0) - v.manifest.profile.rows} rows,{" "}
                            {(overview?.profile.column_count ?? 0) -
                              v.manifest.profile.column_count}{" "}
                            columns
                          </p>
                        </div>
                        <div className="lab-actions">
                          <a href={lab.exportUrl(id, v.id)}>Parquet</a>
                          <a href={lab.exportUrl(id, v.id, true)}>Reproducibility bundle</a>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void action(async () => {
                                await lab.restore(id, v.id, overview?.dataset.revision ?? 0);
                                await refresh();
                                setPreview(null);
                                setMessage("Working copy restored. Saved versions are unchanged.");
                              })
                            }
                          >
                            Restore working copy
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                  <a className="lab-download" href={lab.exportUrl(id)}>
                    <ArrowDownToLine size={17} />
                    Export current working copy as Parquet
                  </a>
                </div>
              )}
              {tab === "Exports" && (
                <div className="lab-panel">
                  <h2>Export and reproduce</h2>
                  <p>
                    Export the working table or choose a saved version. Bundles contain original
                    normalized input, additional join snapshots, operation provenance, checksums and
                    exact replay code.
                  </p>
                  <div className="lab-actions">
                    <a href={lab.exportUrl(id)}>Working Parquet</a>
                    <a href={lab.exportUrl(id, "", true)}>Working reproducibility bundle</a>
                  </div>
                  {versions.map((v) => (
                    <div className="lab-step" key={v.id}>
                      <span>{v.name}</span>
                      <a href={lab.exportUrl(id, v.id)}>Parquet</a>
                      <a href={lab.exportUrl(id, v.id, true)}>Bundle</a>
                    </div>
                  ))}
                </div>
              )}
              {tab === "History" && (
                <div className="lab-panel">
                  <h2>Operation history</h2>
                  {runs.map((r) => (
                    <article className="lab-run" key={r.id}>
                      <strong>
                        {r.data.steps
                          .map(
                            (s) =>
                              operations.find((o) => o.id === s.operation)?.name ?? s.operation,
                          )
                          .join(" → ")}
                      </strong>
                      <span className={`lab-state ${r.state}`}>{r.state}</span>
                      <p>
                        {new Date(r.created_at).toLocaleString()}{" "}
                        {r.data.runtime_seconds !== undefined && `· ${r.data.runtime_seconds}s`}{" "}
                        {r.data.cache_hit && "· reused stored output"}
                      </p>
                      {r.data.error && <p role="alert">{r.data.error}</p>}
                      <details>
                        <summary>Parameters and provenance</summary>
                        <pre>{JSON.stringify(r.data, null, 2)}</pre>
                      </details>
                    </article>
                  ))}
                  {!runs.length && (
                    <p className="lab-empty">
                      Applied operations will appear here, including failures.
                    </p>
                  )}
                </div>
              )}
              {preview && (
                <section className="lab-preview">
                  <div className="lab-preview-title">
                    <h2>
                      Preview · {sampleMode} {preview.sample_size} rows
                    </h2>
                    <button aria-label="Close preview" onClick={() => setPreview(null)}>
                      <X size={18} />
                    </button>
                  </div>
                  <p>
                    {preview.rows_before} → {preview.rows_after} sample rows. Full-dataset results
                    may differ; source and working copy are unchanged.
                  </p>
                  <div className="lab-before-after">
                    <div>
                      <h3>Before</h3>
                      <DataGrid rows={preview.before} columns={preview.before_columns} />
                    </div>
                    <div>
                      <h3>After</h3>
                      <DataGrid rows={preview.after} columns={preview.after_columns} />
                    </div>
                  </div>
                  {preview.chart && <DataChart chart={preview.chart} />}
                  <details>
                    <summary>Show equivalent Python</summary>
                    <pre>{preview.python}</pre>
                    <button onClick={() => downloadText("operation.py", preview.python)}>
                      Export script
                    </button>
                  </details>
                </section>
              )}
            </div>
            <aside className="lab-inspector">
              <div className="lab-inspector-title">
                <h2>Inspector</h2>
                <label className="lab-check">
                  <input
                    type="checkbox"
                    checked={expert}
                    onChange={(e) => {
                      setExpert(e.target.checked);
                      localStorage.setItem("sensei.expert", String(e.target.checked));
                    }}
                  />
                  Expert
                </label>
              </div>
              {selectedColumn && (
                <section className="lab-column-profile">
                  <div>
                    <h3>{selectedColumn.name}</h3>
                    <button aria-label="Close column profile" onClick={() => setColumn("")}>
                      <X size={15} />
                    </button>
                  </div>
                  <p>{selectedColumn.dtype}</p>
                  <dl>
                    {Object.entries(selectedColumn)
                      .filter(([k]) => !["name", "dtype", "numeric", "samples"].includes(k))
                      .map(([k, v]) => (
                        <div key={k}>
                          <dt>{k}</dt>
                          <dd>
                            {typeof v === "number"
                              ? Number(v.toFixed(3)).toLocaleString()
                              : String(v)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                </section>
              )}
              <label>
                Find an operation
                <input
                  placeholder="Try ‘heat map’ or ‘missing’"
                  value={opSearch}
                  onChange={(e) => setOpSearch(e.target.value)}
                />
              </label>
              <select aria-label="Operation" value={opId} onChange={(e) => setOpId(e.target.value)}>
                {shown.map((o) => (
                  <option key={o.id} value={o.id}>
                    {favorites.includes(o.id) ? "★ " : ""}
                    {o.name}
                  </option>
                ))}
              </select>
              <div className="lab-operation-title">
                <h3>{operation?.name}</h3>
                <button
                  aria-label="Favorite operation"
                  aria-pressed={favorites.includes(opId)}
                  onClick={favorite}
                >
                  <Star size={17} fill={favorites.includes(opId) ? "currentColor" : "none"} />
                </button>
              </div>
              <p>{operation?.description}</p>
              {expert && (
                <p className="lab-muted">
                  {operation?.backend} · operation v{operation?.version}
                  <br />
                  Input: {overview?.dataset.name} · revision {overview?.dataset.revision}
                </p>
              )}
              <ParameterFields
                schema={operation?.parameter_schema ?? {}}
                values={params}
                onChange={(p) => {
                  setParams(p);
                  setPreview(null);
                }}
                columns={overview?.profile.columns.map((c) => c.name) ?? []}
                datasets={datasets}
              />
              <details>
                <summary>When to use this operation</summary>
                <p>{operation?.description}</p>
                <p>
                  Use a sample preview to verify assumptions and parameters. Do not fit transforms
                  on evaluation data; create a split and use Fit training preprocessing for ML
                  preparation.
                </p>
                <p>
                  Backend: {operation?.backend}. Operation v{operation?.version}. Numeric operations
                  require numeric columns; joins require compatible keys. Review exclusions before
                  applying.
                </p>
              </details>
              <label>
                Preview sample
                <select value={sampleMode} onChange={(e) => setSampleMode(e.target.value)}>
                  {["first", "random", "representative", "selected"].map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </label>
              {operation?.warnings.map((w) => (
                <p className="lab-warning" key={w}>
                  {w}
                </p>
              ))}
              <div className="lab-actions">
                <button
                  disabled={busy || !overview}
                  onClick={() =>
                    void action(async () => {
                      const result = await batch.preview(id, step, sampleMode, selection);
                      setPreview(result);
                      if (result.chart) setChart(result.chart);
                    })
                  }
                >
                  <FlaskConical size={16} />
                  {busy ? "Working…" : "Preview"}
                </button>
                <button
                  className="primary"
                  disabled={busy || !overview}
                  onClick={() => void run([step])}
                >
                  <Play size={16} />
                  Run
                </button>
              </div>
              <button
                disabled={busy}
                className="lab-add"
                onClick={() => {
                  setSteps([...steps, { ...step, parameters: { ...params } }]);
                  setMessage("Added to workflow. Open Workflows to arrange or run steps.");
                }}
              >
                <Plus size={16} />
                Add to workflow
              </button>
              <section className="lab-guide">
                <label className="lab-check">
                  <input
                    type="checkbox"
                    checked={guide}
                    onChange={(e) => {
                      setGuide(e.target.checked);
                      localStorage.setItem("sensei.guide", String(e.target.checked));
                    }}
                  />
                  <Sparkles size={16} />
                  Sensei Guide
                </label>
                {guide && (
                  <>
                    {overview?.profile.findings.slice(0, 3).map((f, i) => (
                      <div key={i}>
                        <strong>{f.title}</strong>
                        <p>{f.reason}</p>
                        <button onClick={() => choose(f.operation, f.parameters)}>Review</button>
                      </div>
                    ))}
                    {!overview?.profile.findings.length && (
                      <p>
                        No issues detected by these checks. Inspect distributions and confirm the
                        dataset matches your intended use.
                      </p>
                    )}
                  </>
                )}
              </section>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
