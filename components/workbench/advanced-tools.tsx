"use client";
import { useEffect, useState } from "react";
import type { Dataset, Operation, Parameter, Row, Step } from "@/lib/workbench-api";
import { downloadText } from "@/lib/workbench-api";
import { batch, type Query } from "@/lib/batch-api";
import { DataGrid } from "./data-views";
export function ParameterFields({
  schema,
  values,
  onChange,
  columns,
  datasets = [],
}: {
  schema: Record<string, Parameter>;
  values: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
  columns: string[];
  datasets?: Dataset[];
}) {
  return (
    <>
      {Object.entries(schema).map(([key, s]) => (
        <label key={key}>
          {s.title}
          {s.type === "columns" ? (
            <div className="lab-column-options">
              {columns.map((c) => (
                <label className="lab-check" key={c}>
                  <input
                    type="checkbox"
                    checked={Array.isArray(values[key]) && (values[key] as string[]).includes(c)}
                    onChange={(e) => {
                      const old = Array.isArray(values[key]) ? (values[key] as string[]) : [];
                      onChange({
                        ...values,
                        [key]: e.target.checked ? [...old, c] : old.filter((x) => x !== c),
                      });
                    }}
                  />
                  {c}
                </label>
              ))}
              <small>Unset uses all columns; select explicitly when needed.</small>
            </div>
          ) : s.type === "json" ? (
            <textarea
              aria-label={s.title}
              className="lab-json"
              value={
                typeof values[key] === "string"
                  ? (values[key] as string)
                  : JSON.stringify(values[key] ?? s.default, null, 2)
              }
              onChange={(e) => onChange({ ...values, [key]: e.target.value })}
            />
          ) : ["column", "enum", "dataset"].includes(s.type) ? (
            <select
              aria-label={s.title}
              value={String(values[key] ?? "")}
              onChange={(e) => onChange({ ...values, [key]: e.target.value })}
            >
              <option value="">Choose…</option>
              {s.type === "dataset"
                ? datasets.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))
                : (s.choices ?? columns).map((c) => <option key={c}>{c}</option>)}
            </select>
          ) : s.type === "boolean" ? (
            <input
              type="checkbox"
              checked={Boolean(values[key])}
              onChange={(e) => onChange({ ...values, [key]: e.target.checked })}
            />
          ) : (
            <input
              type={s.type === "number" ? "number" : "text"}
              step="any"
              min={s.minimum}
              max={s.maximum}
              value={String(values[key] ?? "")}
              onChange={(e) =>
                onChange({
                  ...values,
                  [key]: s.type === "number" ? Number(e.target.value) : e.target.value,
                })
              }
            />
          )}
        </label>
      ))}
    </>
  );
}
export function QueryTools({
  id,
  columns,
  query,
  onChange,
  visible,
  onVisible,
  selected,
  onExclude,
}: {
  id: string;
  columns: string[];
  query: Query;
  onChange: (q: Query) => void;
  visible: string[];
  onVisible: (v: string[]) => void;
  selected: number[];
  onExclude: () => void;
}) {
  const [column, setColumn] = useState(""),
    [operator, setOperator] = useState("eq"),
    [value, setValue] = useState(""),
    [history, setHistory] = useState<Array<{ id: string; query: Query }>>([]),
    [error, setError] = useState("");
  useEffect(() => {
    batch
      .queries(id)
      .then((r) => setHistory(r.items))
      .catch((e) => setError(String(e)));
  }, [id, query]);
  return (
    <div className="lab-query-tools">
      <div className="lab-data-summary">
        {selected.length} selected rows · {query.conditions?.length ?? 0} conditions ·{" "}
        {visible.length || columns.length} visible columns{" "}
        <button disabled={!selected.length} onClick={onExclude}>
          Exclude selected from working copy
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      <details>
        <summary>Filters, visible columns and query history</summary>
        <div className="lab-inline">
          <label>
            Filter column
            <select aria-label="Filter column" value={column} onChange={(e) => setColumn(e.target.value)}>
              <option value="">Choose…</option>
              {columns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            Condition
            <select aria-label="Condition" value={operator} onChange={(e) => setOperator(e.target.value)}>
              {[
                "eq",
                "ne",
                "gt",
                "ge",
                "lt",
                "le",
                "contains",
                "regex",
                "in",
                "between_dates",
                "is_null",
                "not_null",
              ].map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </label>
          <label>
            Value
            <input
              value={value}
              placeholder={
                ["in", "between_dates"].includes(operator) ? 'JSON list, e.g. ["a","b"]' : "Value"
              }
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
          <button
            disabled={!column}
            onClick={() => {
              try {
                const v = ["in", "between_dates"].includes(operator) ? JSON.parse(value) : value;
                onChange({
                  ...query,
                  offset: 0,
                  conditions: [...(query.conditions ?? []), { column, operator, value: v }],
                  remember: true,
                });
                setError("");
              } catch {
                setError("Enter a JSON list for categories or date endpoints.");
              }
            }}
          >
            Add condition
          </button>
        </div>
        <label>
          Match
          <select
            value={query.match ?? "all"}
            onChange={(e) => onChange({ ...query, match: e.target.value })}
          >
            <option value="all">All conditions</option>
            <option value="any">Any condition</option>
          </select>
        </label>
        {(query.conditions ?? []).map((c, i) => (
          <span className="lab-chip" key={i}>
            {JSON.stringify(c)}
            <button
              aria-label={`Remove condition ${i + 1}`}
              onClick={() =>
                onChange({ ...query, conditions: query.conditions?.filter((_, j) => j !== i) })
              }
            >
              ×
            </button>
          </span>
        ))}
        <label className="lab-check">
          <input
            type="checkbox"
            checked={query.descending ?? false}
            onChange={(e) => onChange({ ...query, descending: e.target.checked })}
          />
          Descending sort
        </label>
        <div>
          {columns.map((c) => (
            <label className="lab-chip" key={c}>
              <input
                type="checkbox"
                checked={!visible.length || visible.includes(c)}
                onChange={(e) => {
                  const old = visible.length ? visible : columns;
                  const next = e.target.checked ? [...old, c] : old.filter((x) => x !== c);
                  if (next.length) onVisible(next);
                }}
              />
              {c}
            </label>
          ))}
        </div>
        <label>
          Saved queries
          <select
            value=""
            onChange={(e) => {
              const q = history.find((h) => h.id === e.target.value)?.query;
              if (q) onChange({ ...q, remember: false });
            }}
          >
            <option value="">Restore a previous query…</option>
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {h.query.search || "All text"} · {h.query.conditions?.length ?? 0} filters ·{" "}
                {h.query.sort_by || "original order"}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => onChange({ ...query, remember: true })}>Save current query</button>
      </details>
    </div>
  );
}
export function WorkflowEditor({
  id,
  projectId,
  revision,
  steps,
  setSteps,
  operations,
  datasets,
  columns,
  onQueued,
}: {
  id: string;
  projectId: string;
  revision: number;
  steps: Step[];
  setSteps: (s: Step[]) => void;
  operations: Operation[];
  datasets: Dataset[];
  columns: string[];
  onQueued: () => void;
}) {
  const [name, setName] = useState("My preparation workflow"),
    [recipes, setRecipes] = useState<Array<{ id: string; name: string; steps: Step[] }>>([]),
    [workflows, setWorkflows] = useState<typeof recipes>([]),
    [recipeId, setRecipeId] = useState(""),
    [workflowId, setWorkflowId] = useState(""),
    [bindings, setBindings] = useState<Record<string, unknown>>({}),
    [result, setResult] = useState<Row[]>([]),
    [message, setMessage] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [code, setCode] = useState(""),
    [editing, setEditing] = useState(-1);
  const load = async () => {
    const { lab } = await import("@/lib/workbench-api");
    setRecipes((await lab.recipes()).items);
    setWorkflows((await batch.workflows(projectId)).items);
  };
  useEffect(() => {
    void load().catch((e) => setError(String(e)));
  }, [projectId]);
  const vars: Record<string, string> = {};
  JSON.stringify(steps).replace(/\{\{(\w+)(?::([^}]*))?\}\}/g, (_, key, def) => {
    vars[key] = def ?? "";
    return "";
  });
  const bound = Object.fromEntries(
    Object.entries(bindings).map(([k, v]) => {
      try {
        return [k, JSON.parse(String(v))];
      } catch {
        return [k, v];
      }
    }),
  );
  async function action(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="lab-panel">
      <h2>Workflow builder</h2>
      <p>
        Each node takes a TabularDataset and passes its result to the next node. Combine adds a
        second dataset input. Successful steps are checkpointed for retries.
      </p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {steps.map((s, i) => (
        <div key={i}>
          <div className="lab-step">
            <b>{i + 1}</b>
            <span>
              {operations.find((o) => o.id === s.operation)?.name ?? s.operation}
              <small> · TabularDataset → TabularDataset</small>
            </span>
            <button onClick={() => setEditing(editing === i ? -1 : i)}>Edit</button>
            <button
              disabled={!i}
              onClick={() => {
                const n = [...steps];
                [n[i - 1], n[i]] = [n[i], n[i - 1]];
                setSteps(n);
              }}
            >
              ↑
            </button>
            <button
              disabled={i === steps.length - 1}
              onClick={() => {
                const n = [...steps];
                [n[i + 1], n[i]] = [n[i], n[i + 1]];
                setSteps(n);
              }}
            >
              ↓
            </button>
            <button
              aria-label={`Remove step ${i + 1}`}
              onClick={() => setSteps(steps.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </div>
          {editing === i && (
            <div className="lab-node-editor">
              <ParameterFields
                schema={operations.find((o) => o.id === s.operation)?.parameter_schema ?? {}}
                columns={columns}
                datasets={datasets}
                values={s.parameters}
                onChange={(p) =>
                  setSteps(steps.map((x, j) => (j === i ? { ...x, parameters: p } : x)))
                }
              />
              <label>
                Parameter template (supports {"{{target}}"} and {"{{seed:42}}"})
                <textarea
                  defaultValue={JSON.stringify(s.parameters, null, 2)}
                  onBlur={(e) => {
                    try {
                      const p = JSON.parse(e.target.value);
                      setSteps(steps.map((x, j) => (j === i ? { ...x, parameters: p } : x)));
                      setError("");
                    } catch {
                      setError("Parameter template must be valid JSON.");
                    }
                  }}
                />
              </label>
            </div>
          )}
        </div>
      ))}
      {!steps.length && <p>Add configured operations from the inspector.</p>}
      {Object.entries(vars).map(([key, def]) => (
        <label key={key}>
          Recipe parameter: {key}
          <input
            placeholder={def || "Required value"}
            value={String(bindings[key] ?? "")}
            onChange={(e) => setBindings({ ...bindings, [key]: e.target.value })}
          />
        </label>
      ))}
      <div className="lab-actions">
        <button
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => {
              const r = await batch.dryRun(id, steps, revision, bound);
              setResult(r.after);
              setMessage(r.history.map((h) => `${h.name}: ${h.rows} rows`).join(" → "));
            })
          }
        >
          Dry run · 100 rows
        </button>
        <button
          className="primary"
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => {
              await batch.run(id, steps, revision, bound);
              onQueued();
              setMessage("Workflow queued. Inspect its progress and retry failures in Jobs.");
            })
          }
        >
          Run workflow
        </button>
        <button
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => setCode((await batch.python(id, steps, revision, bound)).code))
          }
        >
          Show equivalent Python
        </button>
      </div>
      {result.length > 0 && <DataGrid rows={result} />}
      <label>
        Workflow / recipe name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="lab-actions">
        <button
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => {
              const r = await batch.saveWorkflow(projectId, name, steps, workflowId || undefined);
              setWorkflowId(r.id);
              await load();
              setMessage("Workflow saved.");
            })
          }
        >
          Save workflow
        </button>
        <button
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => {
              const r = await batch.saveRecipe(name, steps, recipeId || undefined);
              setRecipeId(r.id);
              await load();
              setMessage("Recipe saved.");
            })
          }
        >
          Save recipe
        </button>
        <button
          disabled={busy || !steps.length}
          onClick={() =>
            void action(async () => {
              await batch.saveRecipe(name + " copy", steps);
              await load();
              setMessage("Recipe duplicated.");
            })
          }
        >
          Duplicate recipe
        </button>
        <button
          disabled={!steps.length}
          onClick={() =>
            downloadText(
              "recipe.json",
              JSON.stringify({ format: "mediasensei.recipe", version: 1, name, steps }, null, 2),
              "application/json",
            )
          }
        >
          Export recipe
        </button>
        <label>
          Import recipe
          <input
            type="file"
            accept=".json"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                void action(async () => {
                  if (file.size > 200000) throw new Error("Recipe exceeds 200 KB.");
                  const r = JSON.parse(await file.text());
                  const saved = await batch.saveRecipe(r.name, r.steps);
                  setRecipeId(saved.id);
                  setSteps(saved.steps);
                  setName(saved.name);
                  await load();
                  setMessage("Recipe imported and validated.");
                });
            }}
          />
        </label>
      </div>
      <div className="lab-inline">
        <label>
          Saved workflows
          <select
            value=""
            onChange={(e) => {
              const r = workflows.find((x) => x.id === e.target.value);
              if (r) {
                setSteps(r.steps);
                setName(r.name);
                setWorkflowId(r.id);
                setRecipeId("");
              }
            }}
          >
            <option value="">Load workflow…</option>
            {workflows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Your recipes
          <select
            value=""
            onChange={(e) => {
              const r = recipes.find((x) => x.id === e.target.value);
              if (r) {
                setSteps(r.steps);
                setName(r.name);
                setRecipeId(r.id);
                setWorkflowId("");
                setBindings({});
              }
            }}
          >
            <option value="">Load recipe…</option>
            {recipes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {code && (
        <details open>
          <summary>Equivalent Python</summary>
          <pre className="lab-code">{code}</pre>
          <div className="lab-actions">
            <button
              onClick={() =>
                void action(async () => {
                  await navigator.clipboard.writeText(code);
                  setMessage("Code copied.");
                })
              }
            >
              Copy code
            </button>
            <button onClick={() => downloadText("workflow.py", code)}>Export script</button>
            <button
              onClick={() =>
                downloadText(
                  "workflow.ipynb",
                  JSON.stringify(
                    {
                      nbformat: 4,
                      nbformat_minor: 5,
                      metadata: {
                        kernelspec: {
                          name: "python3",
                          display_name: "Python 3",
                          language: "python",
                        },
                      },
                      cells: [
                        {
                          id: "workflow",
                          cell_type: "code",
                          execution_count: null,
                          metadata: {},
                          outputs: [],
                          source: code.split("\n").map((l) => l + "\n"),
                        },
                      ],
                    },
                    null,
                    2,
                  ),
                  "application/json",
                )
              }
            >
              Export notebook
            </button>
          </div>
        </details>
      )}
    </div>
  );
}
export function VersionCompare({
  id,
  versions,
  columns,
}: {
  id: string;
  versions: Array<{ id: string; name: string }>;
  columns: string[];
}) {
  const [left, setLeft] = useState(""),
    [right, setRight] = useState(""),
    [identity, setIdentity] = useState(""),
    [target, setTarget] = useState(""),
    [result, setResult] = useState<Record<string, unknown> | null>(null),
    [error, setError] = useState("");
  return (
    <section>
      <h3>Compare snapshots</h3>
      <div className="lab-inline">
        <label>
          From
          <select aria-label="From" value={left} onChange={(e) => setLeft(e.target.value)}>
            <option value="">Choose version…</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          To
          <select aria-label="To" value={right} onChange={(e) => setRight(e.target.value)}>
            <option value="">Working copy</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sample identity
          <select aria-label="Sample identity" value={identity} onChange={(e) => setIdentity(e.target.value)}>
            <option value="">Exact row values</option>
            {columns.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Label column
          <select aria-label="Label column" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">None</option>
            {columns.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button
          disabled={!left}
          onClick={() => {
            setError("");
            batch
              .compare(id, left, right, identity, target)
              .then(setResult)
              .catch((e) => setError(String(e)));
          }}
        >
          Compare versions
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {result && (
        <>
          <p>
            {String(result.samples_added)} samples added · {String(result.samples_removed)} removed
          </p>
          <p>
            Columns added: {(result.columns_added as string[]).join(", ") || "none"} · removed:{" "}
            {(result.columns_removed as string[]).join(", ") || "none"}
          </p>
          <DataGrid
            rows={(result.changes as Row[]).map((r) => ({
              column: r.column,
              kind: r.kind,
              changed: r.count,
            }))}
          />
          <details>
            <summary>Quality and transformation differences</summary>
            <pre className="lab-code">
              {JSON.stringify(
                {
                  before: result.quality_before,
                  after: result.quality_after,
                  transforms_before: result.transforms_before,
                  transforms_after: result.transforms_after,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <div className="lab-before-after">
            <DataGrid rows={result.before as Row[]} />
            <DataGrid rows={result.after as Row[]} />
          </div>
        </>
      )}
    </section>
  );
}
