"use client";
import { useEffect, useRef, useState } from "react";
import { Search, X, BookOpen, Command } from "lucide-react";
import { batch, type SearchHit } from "@/lib/batch-api";
import { lab, type Operation } from "@/lib/workbench-api";
import { request } from "@/lib/core-api";
export function CommandCenter({
  projectId,
  onProject,
  onNavigate,
  onOperation,
}: {
  projectId: string;
  onProject: (id: string) => void;
  onNavigate: (view: string) => void;
  onOperation: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(""),
    [hits, setHits] = useState<SearchHit[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        dialog.current?.showModal();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    let done = false;
    const timer = setTimeout(
      () =>
        batch
          .search(query, projectId)
          .then((r) => {
            if (!done) {
              const recent = JSON.parse(localStorage.getItem("sensei.recent") || "[]") as string[];
              const favorites = JSON.parse(
                localStorage.getItem("sensei-favorites") || "[]",
              ) as string[];
              setHits(
                r.items.sort(
                  (a, b) =>
                    Number(favorites.includes(b.id)) -
                    Number(favorites.includes(a.id)) +
                    Number(recent.includes(b.id)) -
                    Number(recent.includes(a.id)),
                ),
              );
              setError("");
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
  }, [query, projectId]);
  function select(hit: SearchHit) {
    if (hit.project_id) onProject(hit.project_id);
    if (hit.dataset_id && hit.project_id) {
      localStorage.setItem(`sensei.dataset.${hit.project_id}`, hit.dataset_id);
      window.dispatchEvent(
        new CustomEvent("sensei.dataset", {
          detail: { project: hit.project_id, id: hit.dataset_id },
        }),
      );
    }
    if (hit.operation && hit.view === "Data Lab") onOperation(hit.operation);
    else onNavigate(hit.view ?? "Documentation");
    dialog.current?.close();
  }
  return (
    <>
      <button
        className="command-trigger"
        onClick={() => {
          dialog.current?.showModal();
          input.current?.focus();
        }}
      >
        <Search size={16} />
        <span>Search workspace & functions</span>
        <kbd>Ctrl K</kbd>
      </button>
      <dialog ref={dialog} className="sensei-command">
        <div className="command-input">
          <Search size={19} />
          <input
            ref={input}
            aria-label="Search operations and navigation"
            placeholder="What would you like to do?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button aria-label="Close search" onClick={() => dialog.current?.close()}>
            <X size={18} />
          </button>
        </div>
        <div className="command-results">
          {error && <p role="alert">{error}</p>}
          <p>OPERATIONS · PROJECTS · ASSETS · JOBS · RECIPES · FUNCTIONS</p>
          {hits.map((h) =>
            h.url ? (
              <a
                className="function-result"
                style={{ display: "block" }}
                key={h.kind + h.id}
                href={h.url}
                target="_blank"
                rel="noreferrer"
              >
                <strong>{h.name}</strong>
                <small>{h.description}</small>
                <em>{h.kind}</em>
              </a>
            ) : (
              <button key={h.kind + h.id} onClick={() => select(h)}>
                <Command size={17} />
                <span>
                  <strong>{h.name}</strong>
                  <small>{h.description}</small>
                </span>
                <em>{h.kind}</em>
              </button>
            ),
          )}
          {!hits.length && !error && <p>No matching workspace item.</p>}
          <p>NAVIGATION AND SETTINGS</p>
          {[
            "Overview",
            "Library",
            "Data Lab",
            "Image Lab",
            "Video Lab",
            "Audio Lab",
            "Knowledge Lab",
            "Quality",
            "Sources",
            "Workflows",
            "Versions",
            "Exports",
            "Jobs",
            "Documentation",
            "System",
          ]
            .filter((v) => v.toLowerCase().includes(query.toLowerCase()))
            .map((v) => (
              <button
                key={v}
                onClick={() => {
                  onNavigate(v);
                  dialog.current?.close();
                }}
              >
                <BookOpen size={16} />
                {v}
              </button>
            ))}
        </div>
      </dialog>
    </>
  );
}
export function Documentation({ onOperation }: { onOperation: (id: string) => void }) {
  const [ops, setOps] = useState<Operation[]>([]),
    [query, setQuery] = useState(""),
    [functions, setFunctions] = useState<SearchHit[]>([]),
    [guides, setGuides] = useState<Array<{ id: string; name: string; description: string }>>([]),
    [error, setError] = useState(""),
    [tab, setTab] = useState("Guides");
  useEffect(() => {
    lab
      .operations()
      .then((r) => setOps(r.items))
      .catch((e) => setError(String(e)));
    request<{ items: typeof guides }>("/lab/guides")
      .then((r) => setGuides(r.items))
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (tab !== "Function Explorer") return;
    let done = false;
    const timer = setTimeout(
      () =>
        batch
          .functions(query)
          .then((r) => {
            if (!done) setFunctions(r.items);
          })
          .catch((e) => setError(String(e))),
      250,
    );
    return () => {
      done = true;
      clearTimeout(timer);
    };
  }, [query, tab]);
  return (
    <section className="data-lab lab-panel">
      <div className="lab-eyebrow">LEARN WHILE YOU WORK</div>
      <h1>Documentation and discovery</h1>
      <div className="lab-tabs">
        {["Guides", "Operations", "Function Explorer"].map((t) => (
          <button className={t === tab ? "active" : ""} key={t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
      <label>
        Find a concept
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="correlation, missing values, split…"
        />
      </label>
      {tab === "Guides" && (
        <div className="docs-grid">
          {guides
            .filter((g) =>
              (g.name + " " + g.description).toLowerCase().includes(query.toLowerCase()),
            )
            .map((g) => (
              <article key={g.id}>
                <h2>{g.name}</h2>
                <p>{g.description}</p>
              </article>
            ))}
        </div>
      )}
      {tab === "Operations" && (
        <div className="docs-grid">
          {ops
            .filter((o) =>
              `${o.name} ${o.aliases.join(" ")}`.toLowerCase().includes(query.toLowerCase()),
            )
            .map((o) => (
              <article key={o.id}>
                <small>
                  {o.category} · {o.backend}
                </small>
                <h2>{o.name}</h2>
                <p>{o.description}</p>
                <h3>Parameters</h3>
                {Object.entries(o.parameter_schema).map(([k, p]) => (
                  <p key={k}>
                    <strong>{p.title}</strong> — {p.choices?.join(", ") ?? p.type}
                    {p.default !== undefined && ` · default ${JSON.stringify(p.default)}`}
                  </p>
                ))}
                {o.warnings.map((w) => (
                  <p className="lab-warning" key={w}>
                    {w}
                  </p>
                ))}
                <p>
                  Preview first. A report leaves the working dataset intact; a transformation
                  creates a new content-addressed result. Review warnings and inspect parameter
                  types before applying.
                </p>
                <button onClick={() => onOperation(o.id)}>Open in Data Lab</button>
              </article>
            ))}
        </div>
      )}
      {tab === "Function Explorer" && (
        <>
          <p>
            Search public APIs found in installed capability libraries. Signatures and descriptions
            come from your installed versions. A library function may have no visual operation; it
            is documented here without running code.
          </p>
          {functions.map((f) => (
            <article className="function-result" key={f.id}>
              <small>
                {f.library} · installed {f.version}
              </small>
              <h2>{f.name}</h2>
              <code>{f.signature}</code>
              <p>{f.description}</p>
              <a href={f.url} target="_blank" rel="noreferrer">
                Official API documentation
              </a>
              {f.operation ? (
                <button onClick={() => onOperation(f.operation!)}>
                  Open related visual operation
                </button>
              ) : (
                <p className="lab-muted">
                  Available library function; no visual wrapper is registered.
                </p>
              )}
            </article>
          ))}
        </>
      )}
    </section>
  );
}
