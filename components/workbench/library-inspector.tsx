"use client";
import { useState } from "react";
import type { Asset } from "@/lib/core-api";
export function LibraryInspector({
  assets,
  onNavigate,
}: {
  assets: Asset[];
  onNavigate: (view: string) => void;
}) {
  const [guide, setGuide] = useState(true);
  const findings = assets.flatMap((a) => {
    const p = (a.analysis ?? {}) as Record<string, unknown>;
    const result: Array<{ title: string; reason: string; view: string }> = [];
    if (p.valid === false)
      result.push({
        title: `${a.original_filename}: invalid media`,
        reason: String(
          p.error ?? "Inspection failed. Review the file and job error before using it.",
        ),
        view: "Jobs",
      });
    if (
      a.media_type === "image" &&
      typeof p.width === "number" &&
      typeof p.height === "number" &&
      Math.min(p.width, p.height) < 512
    )
      result.push({
        title: `${a.original_filename}: ${p.width} × ${p.height}`,
        reason:
          "Low-resolution images may not support the intended training size. Inspect before excluding or upscaling.",
        view: "Image Lab",
      });
    if (typeof p.blur_score === "number" && p.blur_score < 20)
      result.push({
        title: `${a.original_filename}: low sharpness (${p.blur_score.toFixed(1)})`,
        reason:
          "Review this image for blur; the metric is a screening signal rather than a final quality decision.",
        view: "Image Lab",
      });
    return result;
  });
  return (
    <details className="data-lab lab-panel" open={assets.length > 0}>
      <summary>Selection inspector · {assets.length} assets</summary>
      {assets.slice(0, 20).map((a) => (
        <details key={a.id}>
          <summary>
            {a.original_filename} · {a.state}
          </summary>
          <dl>
            <dt>Source hash</dt>
            <dd style={{ overflowWrap: "anywhere" }}>{a.sha256}</dd>
            <dt>Type / size</dt>
            <dd>
              {a.media_type} · {a.byte_size.toLocaleString()} bytes
            </dd>
          </dl>
          <pre className="lab-code">{JSON.stringify(a.analysis ?? {}, null, 2)}</pre>
        </details>
      ))}
      <label className="lab-check">
        <input type="checkbox" checked={guide} onChange={(e) => setGuide(e.target.checked)} />
        Sensei Guide for this selection
      </label>
      {guide &&
        findings.slice(0, 20).map((f, i) => (
          <article className="lab-finding" key={i}>
            <strong>{f.title}</strong>
            <p>{f.reason}</p>
            <button onClick={() => onNavigate(f.view)}>Review finding</button>
          </article>
        ))}
      {guide && !findings.length && (
        <p>
          No issues detected by these selection checks. Inspect metadata and your intended use
          before preparing the dataset.
        </p>
      )}
    </details>
  );
}
