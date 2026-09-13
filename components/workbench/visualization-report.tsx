"use client";
import { useRef } from "react";
import { type SavedChart } from "@/lib/batch-api";
import { downloadText } from "@/lib/workbench-api";
import { DataChart } from "./data-views";
export function VisualizationReport({ charts }: { charts: SavedChart[] }) {
  const root = useRef<HTMLDivElement>(null);
  function exportReport() {
    if (!root.current) return;
    const clone = root.current.cloneNode(true) as HTMLElement;
    const originals = root.current.querySelectorAll("svg,svg *"),
      copies = clone.querySelectorAll("svg,svg *");
    originals.forEach((node, i) => {
      const style = getComputedStyle(node);
      (copies[i] as SVGElement).style.cssText = [
        "fill",
        "stroke",
        "font-size",
        "font-family",
        "color",
      ]
        .map((k) => `${k}:${style.getPropertyValue(k)}`)
        .join(";");
    });
    clone.querySelectorAll("button").forEach((b) => b.remove());
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--card"),
      fg = getComputedStyle(document.documentElement).getPropertyValue("--foreground");
    downloadText(
      "visualization-report.html",
      `<!doctype html><html><meta charset="utf-8"><title>MediaSensei visualization report</title><style>body{font:15px system-ui;background:${bg};color:${fg};max-width:1100px;margin:30px auto;padding:20px}svg{max-width:100%}article{break-inside:avoid;padding:20px 0;border-bottom:1px solid #888}table{border-collapse:collapse}td,th{border:1px solid #888;padding:8px}button{display:none}</style><body><h1>MediaSensei visualization report</h1>${clone.innerHTML}</body></html>`,
      "text/html",
    );
  }
  return (
    <details>
      <summary>Report · {charts.length} saved visualizations</summary>
      <button disabled={!charts.length} onClick={exportReport}>
        Export report
      </button>
      <div ref={root}>
        {charts.map((c) => (
          <article key={c.id}>
            <h2>{c.name}</h2>
            <DataChart chart={c.chart} />
          </article>
        ))}
      </div>
    </details>
  );
}
