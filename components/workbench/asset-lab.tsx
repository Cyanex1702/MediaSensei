"use client";
import { useEffect, useRef, useState } from "react";
import { api, request, CORE_API_BASE, contentUrl, type Asset } from "@/lib/core-api";
import type { Operation } from "@/lib/workbench-api";
import { ParameterFields } from "./advanced-tools";

type Row = Record<string, unknown>;
type Output = {
  id: string;
  asset_id: string;
  filename: string;
  operation: string;
  report: Row;
  artifacts: { name: string; mime: string }[];
  provenance: Row;
};
const post = <T,>(url: string, body: unknown) =>
  request<T>(url, { method: "POST", body: JSON.stringify(body) });
const text = (x: unknown) => (typeof x === "object" ? JSON.stringify(x) : String(x ?? "—"));
function Detail({ value }: { value: unknown }) {
  return <pre className="lab-json batch-details">{JSON.stringify(value, null, 2)}</pre>;
}
function Bars({ data, title }: { data: Record<string, number>; title: string }) {
  const max = Math.max(1, ...Object.values(data));
  return (
    <figure className="lab-panel">
      <figcaption>{title}</figcaption>
      {Object.entries(data).map(([label, n]) => (
        <div className="batch-bar" key={label}>
          <span>{label}</span>
          <meter min={0} max={max} value={n} />
          <strong>{n}</strong>
        </div>
      ))}
    </figure>
  );
}
export default function AssetLab({
  projectId,
  modality,
  assets,
  selectedIds,
  onRefresh,
}: {
  projectId: string;
  modality: "image" | "video" | "audio" | "document";
  assets: Asset[];
  selectedIds: string[];
  onRefresh: () => Promise<void>;
}) {
  const eligible = assets.filter((a) => a.media_type === modality),
    initial = eligible.find((a) => selectedIds.includes(a.id))?.id ?? eligible[0]?.id ?? "";
  const [assetId, setAssetId] = useState(initial),
    [batchAll, setBatchAll] = useState(false),
    [tab, setTab] = useState("Explore"),
    [op, setOp] = useState<Operation | null>(null),
    [params, setParams] = useState<Row>({}),
    [preview, setPreview] = useState<{ image?: string; report: Row } | null>(null),
    [report, setReport] = useState<unknown>(null),
    [outputs, setOutputs] = useState<Output[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [query, setQuery] = useState(""),
    [hits, setHits] = useState<Row[]>([]),
    [chunks, setChunks] = useState<{ items: Row[]; total: number; index: Row | null }>({
      items: [],
      total: 0,
      index: null,
    }),
    [offset, setOffset] = useState(0),
    [distributions, setDistributions] = useState<Record<string, Record<string, number>>>({}),
    [ocrAction, setOcrAction] = useState("detect_only"),
    [language, setLanguage] = useState("eng"),
    [threshold, setThreshold] = useState(8),
    [splitStrategy, setSplitStrategy] = useState("random"),
    [seed, setSeed] = useState(42),
    [minResolution, setMinResolution] = useState(512);
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const asset = eligible.find((a) => a.id === assetId),
    operation =
      modality === "image"
        ? "image.edit"
        : modality === "document"
          ? "document.prepare"
          : `${modality}.process`;
  const ids = batchAll
    ? eligible.filter((a) => a.state === "active").map((a) => a.id)
    : [assetId].filter(Boolean);
  const tabs =
    modality === "image"
      ? [
          "Explore",
          "Transforms",
          "Quality",
          "Duplicates",
          "OCR",
          "Visualization",
          "Metadata",
          "Dataset",
          "Outputs",
        ]
      : modality === "document"
        ? [
            "Explore",
            "Structure",
            "Prepare",
            "Chunks",
            "Search",
            "Embeddings",
            "Quality",
            "Export",
            "Outputs",
          ]
        : ["Explore", "Process", "Outputs"];
  async function loadOutputs() {
    const r = await request<{ items: Output[] }>(`/lab/projects/${projectId}/asset-outputs`);
    setOutputs(r.items.filter((o) => o.operation.startsWith(modality + ".")));
  }
  useEffect(() => {
    let live = true;
    request<{ items: Operation[] }>(`/lab/operations?modality=${modality}`)
      .then((r) => {
        const found = r.items.find((o) => o.id === operation);
        if (live && found) {
          setOp(found);
          setParams(
            Object.fromEntries(
              Object.entries(found.parameter_schema).map(([k, v]) => [k, v.default]),
            ),
          );
        }
      })
      .catch((e) => setError(String(e)));
    return () => {
      live = false;
    };
  }, [modality, operation]);
  useEffect(() => {
    if (!eligible.some((a) => a.id === assetId)) setAssetId(initial);
  }, [assetId, initial, eligible]);
  useEffect(() => {
    let live = true;
    const tick = () =>
      request<{ items: Output[] }>(`/lab/projects/${projectId}/asset-outputs`)
        .then((r) => {
          if (live) setOutputs(r.items.filter((o) => o.operation.startsWith(modality + ".")));
        })
        .catch((e) => {
          if (live) setError(String(e));
        });
    void tick();
    const timer = setInterval(tick, 4000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [projectId, modality]);
  useEffect(() => {
    setPreview(null);
    setReport(null);
    setOffset(0);
  }, [assetId]);
  useEffect(() => {
    if (modality !== "document" || !assetId) return;
    let live = true;
    request<typeof chunks>(`/lab/documents/${assetId}/chunks?offset=${offset}`)
      .then((r) => {
        if (live) setChunks(r);
      })
      .catch((e) => {
        if (live) setError(String(e));
      });
    return () => {
      live = false;
    };
  }, [assetId, offset, modality, outputs.length]);
  async function act(fn: () => Promise<unknown>, message = "") {
    setBusy(true);
    setError("");
    try {
      const r = await fn();
      if (r !== undefined) setReport(r);
      if (message) setNotice(message);
      await onRefresh();
      await loadOutputs();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function enqueue() {
    return post(`/lab/projects/${projectId}/asset-operations`, {
      operation,
      asset_ids: ids,
      parameters: params,
    });
  }
  const update = (p: Row) => {
    setParams(p);
    setPreview(null);
  };
  const selectedOutputs = outputs.filter((o) => batchAll || o.asset_id === assetId);
  return (
    <section className="data-lab batch-lab">
      <div className="lab-eyebrow">{modality.toUpperCase()} LAB / LOCAL WORKSPACE</div>
      <h1>
        {modality === "document"
          ? "Knowledge Lab"
          : `${modality[0].toUpperCase() + modality.slice(1)} Lab`}
      </h1>
      <div className="lab-toolbar">
        <label>
          Asset
          <select
            aria-label="Lab asset"
            value={assetId}
            onChange={(e) => setAssetId(e.target.value)}
          >
            <option value="">Select an asset</option>
            {eligible.map((a) => (
              <option key={a.id} value={a.id}>
                {a.original_filename} · {a.state}
              </option>
            ))}
          </select>
        </label>
        <label className="lab-check">
          <input
            type="checkbox"
            checked={batchAll}
            onChange={(e) => setBatchAll(e.target.checked)}
          />
          Apply to all active {modality} assets (
          {eligible.filter((a) => a.state === "active").length})
        </label>
        <label className="batch-upload">
          Import {modality}
          <input
            aria-label={`Import ${modality}`}
            type="file"
            multiple
            accept={modality === "document" ? ".txt,.md,.html,.pdf,.docx" : `${modality}/*`}
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              void act(async () => {
                for (const f of files) await api.upload(projectId, f);
              }, "Files imported; preparation jobs are visible in Jobs.");
              e.target.value = "";
            }}
          />
        </label>
      </div>
      <nav className="lab-tabs" aria-label="Lab sections">
        {tabs.map((t) => (
          <button
            key={t}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => {
              setTab(t);
              setReport(null);
            }}
          >
            {t}
          </button>
        ))}
      </nav>
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
      {!asset ? (
        <p>Import files above or select assets from Library to begin.</p>
      ) : (
        <>
          {tab === "Explore" && (
            <div className="batch-columns">
              <div className="lab-panel">
                {modality === "image" ? (
                  <img
                    className="batch-preview"
                    src={contentUrl(assetId)}
                    alt={asset.original_filename}
                  />
                ) : modality === "video" ? (
                  <video
                    ref={(e) => {
                      mediaRef.current = e;
                    }}
                    className="batch-preview"
                    controls
                    preload="metadata"
                    src={contentUrl(assetId)}
                  />
                ) : modality === "audio" ? (
                  <audio
                    ref={(e) => {
                      mediaRef.current = e;
                    }}
                    controls
                    preload="metadata"
                    src={contentUrl(assetId)}
                  />
                ) : (
                  <>
                    <h2>{asset.original_filename}</h2>
                    <p>{chunks.total} indexed chunks</p>
                    <a href={contentUrl(assetId)} download>
                      Download original document
                    </a>
                    <p>
                      Prepare text, inspect source structure and compare chunking strategies before
                      indexing.
                    </p>
                  </>
                )}
                {(modality === "audio" || modality === "video") && (
                  <div className="lab-toolbar">
                    <button
                      onClick={() => {
                        update({
                          ...params,
                          start: Math.round((mediaRef.current?.currentTime ?? 0) * 100) / 100,
                        });
                        setTab("Process");
                      }}
                    >
                      Use playhead as trim start
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(
                          () =>
                            post(`/lab/projects/${projectId}/asset-operations`, {
                              operation,
                              asset_ids: ids,
                              parameters: {
                                ...params,
                                action: modality === "audio" ? "waveform" : "thumbnail",
                              },
                            }),
                          "Preview queued; open Outputs when the job completes.",
                        )
                      }
                    >
                      Create {modality === "audio" ? "waveform" : "thumbnail"}
                    </button>
                  </div>
                )}
              </div>
              <div className="lab-panel">
                <h2>Metadata</h2>
                <dl className="batch-metadata">
                  {Object.entries({
                    name: asset.original_filename,
                    bytes: asset.byte_size,
                    state: asset.state,
                    sha256: asset.sha256,
                    ...asset.analysis,
                  }).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k.replaceAll("_", " ")}</dt>
                      <dd>{text(v)}</dd>
                    </div>
                  ))}
                </dl>
                {modality !== "document" && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(
                        () =>
                          modality === "image"
                            ? api.analyzeImages(projectId, ids)
                            : api.analyzeMedia(projectId, ids),
                        "Inspection queued.",
                      )
                    }
                  >
                    Analyze + previews
                  </button>
                )}
              </div>
            </div>
          )}
          {["Transforms", "Prepare", "Process"].includes(tab) && (
            <>
              <div className="batch-columns">
                <div className="lab-panel">
                  <h2>{op?.name}</h2>
                  <div className="lab-fields">
                    {op && (
                      <ParameterFields
                        schema={op.parameter_schema}
                        values={params}
                        onChange={update}
                        columns={[]}
                      />
                    )}
                  </div>
                  <div className="lab-toolbar">
                    <button
                      disabled={busy || !op}
                      onClick={() =>
                        void act(async () => {
                          const r = await post<{ image?: string; report: Row }>(
                            `/lab/assets/${assetId}/preview`,
                            { operation, parameters: params },
                          );
                          setPreview(r);
                        })
                      }
                    >
                      {modality === "image"
                        ? "Preview transform"
                        : modality === "document"
                          ? "Preview and compare chunks"
                          : "Estimate output"}
                    </button>
                    <button
                      className="primary"
                      disabled={busy || !op || ids.length === 0}
                      onClick={() =>
                        void act(
                          enqueue,
                          `${ids.length} asset(s) queued. Follow progress in Jobs; saved results appear in Outputs.`,
                        )
                      }
                    >
                      Run on {ids.length} asset(s)
                    </button>
                  </div>
                </div>
                <div className="lab-panel">
                  <h2>{modality === "image" ? "Before / after" : "Preparation preview"}</h2>
                  {modality === "image" && (
                    <div className="batch-before-after">
                      <figure>
                        <img src={contentUrl(assetId)} alt="Before transform" />
                        <figcaption>Original</figcaption>
                      </figure>
                      {preview?.image && (
                        <figure>
                          <img src={preview.image} alt="After transform preview" />
                          <figcaption>Preview (display capped at 1200px)</figcaption>
                        </figure>
                      )}
                    </div>
                  )}
                  {preview && <Detail value={preview.report} />}
                  <p>
                    Inputs remain immutable. Runs save parameters, source hashes and downloadable
                    outputs. Media estimates do not run a conversion.
                  </p>
                </div>
              </div>
            </>
          )}
          {modality === "image" && ["Metadata", "Visualization"].includes(tab) && (
            <>
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    if (tab === "Visualization")
                      setDistributions(
                        await request(`/lab/projects/${projectId}/image-distributions`),
                      );
                    return request(`/lab/assets/${assetId}/image-details`);
                  })
                }
              >
                Load {tab.toLowerCase()}
              </button>
              <div className="batch-columns">
                {Object.entries(distributions).map(([k, v]) => (
                  <Bars key={k} title={k.replaceAll("_", " ")} data={v} />
                ))}
              </div>
              {Boolean(report) &&
                report !== null &&
                typeof report === "object" &&
                "histogram" in report &&
                Object.entries((report as { histogram: Record<string, number[]> }).histogram).map(
                  ([k, v]) => (
                    <Bars
                      key={k}
                      title={`${k} histogram (512px sample)`}
                      data={Object.fromEntries(v.map((n, i) => [String(i * 16), n]))}
                    />
                  ),
                )}
              {Boolean(report) && <Detail value={report} />}
            </>
          )}
          {modality === "image" && tab === "Quality" && (
            <div className="lab-panel">
              <h2>Quality findings</h2>
              <label>
                Minimum dimension
                <input
                  type="number"
                  value={minResolution}
                  min={1}
                  onChange={(e) => setMinResolution(Number(e.target.value))}
                />
              </label>
              {eligible
                .filter((a) => {
                  const x = a.analysis ?? {};
                  return (
                    x.valid === false ||
                    Number(x.width ?? 0) < minResolution ||
                    Number(x.height ?? 0) < minResolution ||
                    Number(x.blur_score ?? 100) < 50
                  );
                })
                .map((a) => (
                  <div className="batch-finding" key={a.id}>
                    <span>
                      {a.original_filename} ·{" "}
                      {a.analysis?.valid === false
                        ? "Cannot decode"
                        : `Resolution ${text(a.analysis?.width)}×${text(a.analysis?.height)}, blur score ${text(a.analysis?.blur_score)}`}
                    </span>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(() =>
                          api.setAssetState(
                            a.id,
                            a.state === "quarantined" ? "active" : "quarantined",
                          ),
                        )
                      }
                    >
                      {a.state === "quarantined" ? "Restore" : "Quarantine"}
                    </button>
                  </div>
                ))}
              <p>Blur scores are heuristic. Review images before excluding them.</p>
            </div>
          )}
          {modality === "image" && tab === "Duplicates" && (
            <>
              <label>
                Near-duplicate distance
                <input
                  type="number"
                  min={0}
                  max={64}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                />
              </label>
              <button
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    post(`/projects/${projectId}/images/duplicates?threshold=${threshold}`, {}),
                  )
                }
              >
                Find exact and near duplicates
              </button>
              {Boolean(report) && <Detail value={report} />}
            </>
          )}
          {modality === "image" && tab === "OCR" && (
            <div className="lab-panel">
              <h2>OCR and text filtering</h2>
              <label>
                OCR action
                <select value={ocrAction} onChange={(e) => setOcrAction(e.target.value)}>
                  {["detect_only", "store_text", "filter", "quarantine"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label>
                OCR language
                <input value={language} onChange={(e) => setLanguage(e.target.value)} />
              </label>
              <button
                disabled={busy}
                onClick={() =>
                  void act(
                    () =>
                      post(`/projects/${projectId}/images/ocr`, {
                        asset_ids: ids,
                        action: ocrAction,
                        language,
                      }),
                    "OCR queued. Text and regions appear in asset metadata after completion.",
                  )
                }
              >
                Run OCR
              </button>
              <Detail value={asset.analysis?.ocr ?? "No OCR result yet"} />
              <p>
                Uses Tesseract when configured, with Windows built-in OCR as an offline fallback.
                The requested language must be installed. Recognition stores word boxes and provider
                provenance.
              </p>
            </div>
          )}
          {modality === "image" && tab === "Dataset" && (
            <div className="lab-panel">
              <h2>Dataset split and export</h2>
              <label>
                Strategy
                <select value={splitStrategy} onChange={(e) => setSplitStrategy(e.target.value)}>
                  {["random", "stratified", "group_aware", "source_aware"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label>
                Seed
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                />
              </label>
              <div className="lab-toolbar">
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      post(`/projects/${projectId}/dataset/split`, {
                        strategy: splitStrategy,
                        seed,
                        train: 0.8,
                        validation: 0.1,
                        test: 0.1,
                      }),
                    )
                  }
                >
                  Apply 80/10/10 split
                </button>
                <button disabled={busy} onClick={() => void act(() => api.leakage(projectId))}>
                  Check leakage
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      const r = await api.exportDataset(projectId, `image-dataset-${Date.now()}`);
                      setNotice("Export snapshot saved.");
                      return r;
                    })
                  }
                >
                  Create dataset export
                </button>
              </div>
              {Boolean(report) && (
                <>
                  <Detail value={report} />
                  {report !== null && typeof report === "object" && "id" in report && (
                    <a href={`${CORE_API_BASE}/dataset/exports/${text(report.id)}/download`}>
                      Download dataset snapshot
                    </a>
                  )}
                </>
              )}
            </div>
          )}
          {modality === "document" && ["Structure", "Quality"].includes(tab) && (
            <>
              <button
                disabled={busy || !op}
                onClick={() =>
                  void act(async () => {
                    const r = await post<{ report: Row }>(`/lab/assets/${assetId}/preview`, {
                      operation,
                      parameters: params,
                    });
                    return tab === "Structure"
                      ? r.report.blocks
                      : { quality: r.report.quality, comparison: r.report.comparison };
                  })
                }
              >
                Inspect {tab.toLowerCase()}
              </button>
              {Boolean(report) && <Detail value={report} />}
            </>
          )}
          {modality === "document" && tab === "Chunks" && (
            <>
              <p>
                {chunks.total} chunks · {chunks.index ? "Indexed" : "Not indexed"}
              </p>
              {chunks.items.map((c) => (
                <article className="lab-panel" key={text(c.id)}>
                  <small>
                    {asset.original_filename} · {text(c.locator)}
                  </small>
                  <p className="batch-chunk">{text(c.text)}</p>
                </article>
              ))}
              <div className="lab-toolbar">
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
                  Previous chunks
                </button>
                <button
                  disabled={offset + 50 >= chunks.total}
                  onClick={() => setOffset(offset + 50)}
                >
                  Next chunks
                </button>
              </div>
            </>
          )}
          {modality === "document" && tab === "Search" && (
            <>
              <label>
                Retrieval query
                <textarea value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <button
                disabled={busy || !query.trim()}
                onClick={() =>
                  void act(async () => {
                    const r = await api.searchDocuments(projectId, query, batchAll ? [] : ids);
                    setHits(r.items);
                  })
                }
              >
                Search indexed content
              </button>
              {hits.map((h, i) => (
                <article className="lab-panel" key={i}>
                  <h3>
                    {text(h.filename)} · score {Number(h.score).toFixed(3)}
                  </h3>
                  <small>{text(h.locator)}</small>
                  <p className="batch-chunk">{text(h.text)}</p>
                </article>
              ))}
            </>
          )}
          {modality === "document" && tab === "Embeddings" && (
            <>
              <h2>Offline retrieval index</h2>
              <p>
                Signed feature hashing provides deterministic lexical retrieval without downloading
                a model. A learned model can be connected in Batch 3.
              </p>
              <Detail value={chunks.index} />
            </>
          )}
          {modality === "document" && tab === "Export" && (
            <div className="lab-panel">
              <h2>Complete RAG bundle</h2>
              <p>
                Includes original documents, all indexed chunks, embedding vectors, index metadata,
                retrieval configuration, dataset card, provenance and SHA-256 checksums. Every
                active document must be indexed.
              </p>
              <a className="primary" href={`${CORE_API_BASE}/lab/projects/${projectId}/rag-bundle`}>
                Download RAG bundle
              </a>
            </div>
          )}
          {tab === "Outputs" && (
            <>
              {selectedOutputs.length === 0 && (
                <p>No saved outputs yet. Run a preparation operation and follow its job in Jobs.</p>
              )}
              {selectedOutputs.map((o) => (
                <article className="lab-panel" key={o.id}>
                  <h2>
                    {o.filename} · {o.operation}
                  </h2>
                  <a href={`${CORE_API_BASE}/lab/asset-outputs/${o.id}/download`}>
                    Download output bundle + provenance
                  </a>
                  <div className="batch-artifacts">
                    {o.artifacts.map((a, i) => {
                      const url = `${CORE_API_BASE}/lab/asset-outputs/${o.id}/artifacts/${i}`;
                      return (
                        <figure key={i}>
                          {a.mime.startsWith("image/") ? (
                            <img src={url} alt={a.name} loading="lazy" />
                          ) : a.mime.startsWith("video/") ? (
                            <video controls preload="metadata" src={url} />
                          ) : a.mime.startsWith("audio/") ? (
                            <audio controls preload="metadata" src={url} />
                          ) : null}
                          <figcaption>
                            <a href={url} download>
                              {a.name}
                            </a>
                            {(a.mime.startsWith("image/") ||
                              a.mime.startsWith("video/") ||
                              a.mime.startsWith("audio/") ||
                              a.mime === "text/plain") && (
                              <button
                                disabled={busy}
                                onClick={() =>
                                  void act(
                                    () =>
                                      post(`/lab/asset-outputs/${o.id}/artifacts/${i}/adopt`, {}),
                                    "Output added to Library with source provenance; inspection queued.",
                                  )
                                }
                              >
                                Add to Library
                              </button>
                            )}
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                  <details>
                    <summary>Report and provenance</summary>
                    <Detail value={{ report: o.report, provenance: o.provenance }} />
                  </details>
                </article>
              ))}
            </>
          )}
        </>
      )}
    </section>
  );
}
