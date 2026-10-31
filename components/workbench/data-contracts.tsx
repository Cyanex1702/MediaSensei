"use client";
import { useEffect, useState } from "react";
import { request } from "@/lib/core-api";
type Rule = { column: string; check: string; value: string };
type Contract = { rules: Rule[]; dictionary: Record<string, string> };
export default function DataContracts({ projectId }: { projectId: string }) {
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]),
    [dataset, setDataset] = useState("");
  const [columns, setColumns] = useState<string[]>([]),
    [contract, setContract] = useState<Contract>({ rules: [], dictionary: {} }),
    [error, setError] = useState(""),
    [result, setResult] = useState<Record<string, unknown> | null>(null),
    [busy, setBusy] = useState(false),
    [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    request<{ items: { id: string; name: string }[] }>(`/lab/projects/${projectId}/datasets`)
      .then((r) => {
        if (active) {
          setDatasets(r.items);
          setDataset(r.items[0]?.id ?? "");
        }
      })
      .catch((e) => setError(String(e)));
    return () => {
      active = false;
    };
  }, [projectId]);
  useEffect(() => {
    let active = true;
    setReady(false);
    setError("");
    setResult(null);
    setContract({ rules: [], dictionary: {} });
    setColumns([]);
    if (dataset)
      Promise.all([
        request<Contract>(`/contracts/${dataset}`),
        request<{ profile: { columns: { name: string }[] } }>(`/lab/datasets/${dataset}`),
      ])
        .then(([c, o]) => {
          if (active) {
            setReady(true);
            setContract(c);
            setColumns(o.profile.columns.map((c) => c.name));
          }
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    return () => {
      active = false;
    };
  }, [dataset]);
  async function save(run = false) {
    if (!ready || !dataset) return;
    setBusy(true);
    setError("");
    try {
      await request(`/contracts/${dataset}`, { method: "PUT", body: JSON.stringify(contract) });
      if (run) setResult(await request(`/contracts/${dataset}/evaluate`, { method: "POST" }));
      else setResult({ message: "Contract saved. Run checks again after changing your dataset." });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function update(index: number, patch: Partial<Rule>) {
    setContract({
      ...contract,
      rules: contract.rules.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    });
    setResult(null);
  }
  function download() {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "data-quality-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <section className="data-lab lab-panel">
      <h2>Saved data contracts</h2>
      <p>
        Choose a working dataset from Data Lab. Save quality rules and a column dictionary, then run
        them on the current revision. Checks report problems without changing rows.
      </p>
      {error && <p role="alert">{error}</p>}
      <label>
        Working dataset
        <select
          aria-label="Contract dataset"
          value={dataset}
          disabled={busy}
          onChange={(e) => setDataset(e.target.value)}
        >
          <option value="">Choose a dataset</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      {!datasets.length && (
        <p>Import a table in Overview, then create a working dataset in Data Lab.</p>
      )}
      {dataset && (
        <>
          <h3>Quality rules</h3>
          {contract.rules.map((rule, index) => (
            <div key={index} className="contract-rule">
              <label>
                Column
                <select
                  aria-label={`Rule column ${index + 1}`}
                  value={rule.column}
                  onChange={(e) => update(index, { column: e.target.value })}
                >
                  {columns.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label>
                Check
                <select
                  aria-label={`Rule check ${index + 1}`}
                  value={rule.check}
                  onChange={(e) => update(index, { check: e.target.value })}
                >
                  {["required", "unique", "numeric", "minimum", "maximum", "allowed"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              {["minimum", "maximum", "allowed"].includes(rule.check) && (
                <label>
                  {rule.check === "allowed" ? "Allowed values, separated by commas" : "Bound"}
                  <input
                    aria-label={`Rule value ${index + 1}`}
                    value={rule.value}
                    onChange={(e) => update(index, { value: e.target.value })}
                  />
                </label>
              )}
              <button
                disabled={busy}
                onClick={() =>
                  setContract({ ...contract, rules: contract.rules.filter((_, i) => i !== index) })
                }
              >
                Remove rule {index + 1}
              </button>
            </div>
          ))}
          <button
            disabled={busy || !ready || !columns.length}
            onClick={() =>
              setContract({
                ...contract,
                rules: [...contract.rules, { column: columns[0], check: "required", value: "" }],
              })
            }
          >
            Add quality rule
          </button>
          <details>
            <summary>Column dictionary</summary>
            {columns.map((c) => (
              <label key={c}>
                {c}
                <input
                  value={contract.dictionary[c] ?? ""}
                  maxLength={2000}
                  onChange={(e) =>
                    setContract({
                      ...contract,
                      dictionary: { ...contract.dictionary, [c]: e.target.value },
                    })
                  }
                  placeholder="Meaning, units, role and source"
                />
              </label>
            ))}
          </details>
          <div className="lab-toolbar">
            <button disabled={busy || !ready} onClick={() => void save()}>
              Save contract
            </button>
            <button disabled={busy || !ready} onClick={() => void save(true)}>
              Save and run checks
            </button>
            {result && <button onClick={download}>Download quality report</button>}
          </div>
          {result && (
            <>
              <p role="status">
                {result.message
                  ? String(result.message)
                  : `${result.passed ? "Passed" : "Needs attention"}: ${result.failed_rows} of ${result.row_count} rows fail checks. Revision ${result.revision}.`}
              </p>
              <details>
                <summary>Results and up to 100 offending rows</summary>
                <pre style={{ overflow: "auto", maxHeight: 400 }}>
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            </>
          )}
        </>
      )}
    </section>
  );
}
