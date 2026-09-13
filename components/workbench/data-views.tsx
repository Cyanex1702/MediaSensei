"use client";
import { useRef, useState } from "react";
import {
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { downloadText, type Chart, type Row } from "@/lib/workbench-api";
export function DataGrid({
  rows,
  columns,
  onColumn,
  positions,
  selected,
  onSelection,
}: {
  rows: Row[];
  columns?: string[];
  onColumn?: (name: string) => void;
  positions?: number[];
  selected?: number[];
  onSelection?: (ids: number[]) => void;
}) {
  const names = columns ?? Object.keys(rows[0] ?? {});
  return (
    <div className="lab-grid-scroll">
      <table className="lab-grid">
        <thead>
          <tr>
            <th>
              {onSelection ? (
                <input
                  aria-label="Select page"
                  type="checkbox"
                  checked={!!positions?.length && positions.every((i) => selected?.includes(i))}
                  onChange={(e) =>
                    onSelection(
                      e.target.checked
                        ? [...new Set([...(selected ?? []), ...(positions ?? [])])]
                        : (selected ?? []).filter((i) => !positions?.includes(i)),
                    )
                  }
                />
              ) : (
                "#"
              )}
            </th>
            {names.map((name) => (
              <th key={name}>
                <button onClick={() => onColumn?.(name)}>{name}</button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const pos = positions?.[i] ?? i;
            return (
              <tr key={pos} aria-selected={selected?.includes(pos)}>
                <td className="lab-row-number">
                  {onSelection ? (
                    <input
                      aria-label={`Select row ${pos + 1}`}
                      type="checkbox"
                      checked={selected?.includes(pos) ?? false}
                      onChange={(e) =>
                        onSelection(
                          e.target.checked
                            ? [...(selected ?? []), pos]
                            : (selected ?? []).filter((v) => v !== pos),
                        )
                      }
                    />
                  ) : (
                    pos + 1
                  )}
                </td>
                {names.map((name) => (
                  <td key={name}>
                    {row[name] === null || row[name] === undefined ? (
                      <span className="lab-null">missing</span>
                    ) : typeof row[name] === "object" ? (
                      JSON.stringify(row[name])
                    ) : (
                      String(row[name])
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length && <p className="lab-empty">No rows match this view.</p>}
    </div>
  );
}
export function DataChart({ chart }: { chart: Chart }) {
  const [active, setActive] = useState(""),
    [error, setError] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const extended = chart as Chart & { x?: string; y?: string; group?: string; series?: string[] };
  async function exportImage(png = false) {
    try {
      const source = ref.current?.querySelector("svg");
      if (!source) throw new Error("Use data export for this report.");
      const clone = source.cloneNode(true) as SVGElement;
      const originals = [source, ...source.querySelectorAll("*")],
        copies = [clone, ...clone.querySelectorAll("*")];
      originals.forEach((node, i) => {
        const s = getComputedStyle(node);
        (copies[i] as SVGElement).style.cssText = [
          "fill",
          "stroke",
          "color",
          "font-size",
          "font-family",
        ]
          .map((k) => `${k}:${s.getPropertyValue(k)}`)
          .join(";");
      });
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const text = new XMLSerializer().serializeToString(clone);
      if (!png) {
        downloadText("chart.svg", text, "image/svg+xml");
        return;
      }
      const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = source.clientWidth * 2 || 1200;
        canvas.height = source.clientHeight * 2 || 600;
        const ctx = canvas.getContext("2d")!;
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--card");
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const a = document.createElement("a");
        a.download = "chart.png";
        a.href = canvas.toDataURL();
        a.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (e) {
      setError(String(e));
    }
  }
  const color = "var(--primary)";
  let visual;
  if (chart.kind === "table") visual = <DataGrid rows={chart.values} />;
  else if (["heatmap", "missingness"].includes(chart.kind)) {
    const cols = chart.columns ?? [];
    const matrix = chart.values;
    const size = 40,
      width = Math.max(400, cols.length * size + 140),
      height = Math.min(500, matrix.length * size + 55);
    const cellHeight = Math.min(size, 440 / Math.max(matrix.length, 1));
    visual = (
      <div className="lab-heatmap" style={{ overflow: "auto", display: "block" }}>
        <svg role="img" aria-label={chart.title} width={width} height={height}>
          <g transform="translate(135,45)">
            {cols.map((c, j) => (
              <text
                key={c}
                x={j * size + size / 2}
                y={-12}
                textAnchor="middle"
                fontSize="10"
                fill="var(--foreground)"
              >
                {c.slice(0, 8)}
              </text>
            ))}
            {matrix.map((r, i) => (
              <g key={i}>
                <text
                  x={-8}
                  y={i * cellHeight + cellHeight * 0.65}
                  textAnchor="end"
                  fontSize="10"
                  fill="var(--foreground)"
                >
                  {chart.kind === "heatmap" ? cols[i] : i + 1}
                </text>
                {cols.map((c, j) => {
                  const v = r[c];
                  const n = typeof v === "number" ? v : 0;
                  const label = `${cols[i] ?? `row ${i + 1}`} / ${c}: ${v === null ? "undefined" : n.toFixed(3)}`;
                  return (
                    <g
                      key={c}
                      tabIndex={0}
                      role="button"
                      aria-label={label}
                      onFocus={() => setActive(label)}
                      onMouseEnter={() => setActive(label)}
                      onClick={() => setActive(label)}
                    >
                      <title>{label}</title>
                      <rect
                        x={j * size}
                        y={i * cellHeight}
                        width={size - 2}
                        height={Math.max(cellHeight - 1, 1)}
                        fill={n < 0 ? "var(--chart-5)" : "var(--primary)"}
                        opacity={Math.abs(n) * 0.8 + 0.12}
                      />
                      {cellHeight > 18 && (
                        <text
                          x={j * size + size / 2}
                          y={i * cellHeight + cellHeight * 0.65}
                          textAnchor="middle"
                          fontSize="10"
                          fill="var(--foreground)"
                        >
                          {v === null ? "—" : n.toFixed(2)}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            ))}
          </g>
        </svg>
        <p aria-live="polite">{active || "Hover or focus a cell to inspect its value."}</p>
      </div>
    );
  } else if (chart.kind === "box") {
    const r = chart.values[0] ?? {},
      min = Number(r.min),
      max = Number(r.max),
      scale = (v: unknown) => 50 + ((Number(v) - min) / (max - min || 1)) * 500;
    visual = (
      <svg viewBox="0 0 600 180" role="img" aria-label="Five number box plot">
        <line x1="50" x2="550" y1="75" y2="75" stroke={color} />
        <rect
          x={scale(r.q1)}
          y="45"
          width={Math.max(1, scale(r.q3) - scale(r.q1))}
          height="60"
          fill="var(--accent)"
          stroke={color}
        />
        <line x1={scale(r.median)} x2={scale(r.median)} y1="45" y2="105" stroke={color} />
        {["min", "q1", "median", "q3", "max"].map((key, i) => (
          <g key={key}>
            <title>
              {key}: {String(r[key])}
            </title>
            <text
              x={50 + i * 125}
              y="140"
              textAnchor="middle"
              fill="var(--foreground)"
              fontSize="12"
            >
              {key}: {Number(r[key]).toPrecision(3)}
            </text>
          </g>
        ))}
      </svg>
    );
  } else if (chart.kind === "violin") {
    const data = chart.values;
    const max = Math.max(...data.map((v) => Number(v.value)), 1e-9),
      x0 = Number(data[0]?.x),
      x1 = Number(data.at(-1)?.x),
      scale = (v: unknown) => 40 + ((Number(v) - x0) / (x1 - x0 || 1)) * 520;
    const upper = data.map((v) => `${scale(v.x)},${100 - (Number(v.value) / max) * 70}`).join(" "),
      lower = [...data]
        .reverse()
        .map((v) => `${scale(v.x)},${100 + (Number(v.value) / max) * 70}`)
        .join(" ");
    visual = (
      <svg viewBox="0 0 600 210" role="img" aria-label="Violin density">
        <polygon points={upper + " " + lower} fill="var(--accent)" stroke={color} />
        <text x="40" y="200" fill="var(--foreground)">
          {x0.toPrecision(3)}
        </text>
        <text x="500" y="200" fill="var(--foreground)">
          {x1.toPrecision(3)}
        </text>
        <title>Symmetric Gaussian kernel density estimate</title>
      </svg>
    );
  } else if (["scatter", "bubble", "qq", "outlier", "pair"].includes(chart.kind)) {
    const pairs =
      chart.kind === "pair"
        ? (chart.columns ?? []).flatMap((a, i) =>
            (chart.columns ?? []).slice(i + 1).map((b) => [a, b]),
          )
        : [
            [
              chart.kind === "qq" || chart.kind === "outlier" ? "x" : (extended.x ?? "x"),
              chart.kind === "qq" || chart.kind === "outlier" ? "y" : (extended.y ?? "y"),
            ],
          ];
    visual = (
      <div className={chart.kind === "pair" ? "docs-grid" : ""}>
        {pairs.map(([x, y]) => (
          <div key={x + y}>
            <p>
              {x} / {y}
            </p>
            <ResponsiveContainer width="100%" height={290}>
              <ScatterChart>
                <CartesianGrid stroke="var(--border)" />
                <XAxis type="number" dataKey={x} name={x} domain={["auto", "auto"]} />
                <YAxis type="number" dataKey={y} name={y} domain={["auto", "auto"]} />
                {chart.kind === "bubble" && extended.group && (
                  <ZAxis dataKey={extended.group} range={[30, 300]} />
                )}
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={chart.values} fill={color} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>
    );
  } else if (["line", "rolling", "density"].includes(chart.kind))
    visual = (
      <ResponsiveContainer width="100%" height={310}>
        <LineChart data={chart.values}>
          <CartesianGrid stroke="var(--border)" />
          <XAxis dataKey={chart.kind === "density" ? "x" : "name"} />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="value" stroke={color} dot={false} />
          <Brush dataKey={chart.kind === "density" ? "x" : "name"} height={22} stroke={color} />
        </LineChart>
      </ResponsiveContainer>
    );
  else if (chart.kind === "error")
    visual = (
      <ResponsiveContainer width="100%" height={290}>
        <ComposedChart data={chart.values}>
          <XAxis dataKey="name" />
          <YAxis domain={["auto", "auto"]} />
          <Tooltip />
          <Bar dataKey="value" fill={color}>
            <ErrorBar dataKey="error" width={12} stroke="var(--foreground)" />
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    );
  else
    visual = (
      <ResponsiveContainer width="100%" height={310}>
        <BarChart data={chart.values}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} interval="preserveStartEnd" />
          <YAxis />
          <Tooltip />
          {(extended.series ?? ["value"]).map((s, i) => (
            <Bar
              key={s}
              dataKey={s}
              fill={`var(--chart-${(i % 5) + 1})`}
              stackId={chart.kind === "stacked" ? "stack" : undefined}
            />
          ))}
          <Brush dataKey="name" height={22} stroke={color} />
        </BarChart>
      </ResponsiveContainer>
    );
  return (
    <div className="lab-chart">
      <h3>{chart.title}</h3>
      <div ref={ref}>{visual}</div>
      {error && <p role="alert">{error}</p>}
      <div className="lab-chart-actions">
        <button onClick={() => void exportImage()}>Export SVG</button>
        <button onClick={() => void exportImage(true)}>Export PNG</button>
        <button
          onClick={() =>
            downloadText("chart-data.json", JSON.stringify(chart, null, 2), "application/json")
          }
        >
          Export chart data
        </button>
      </div>
      <p className="lab-muted">
        Charts use bounded points and category counts. Drag the range handles where shown to zoom or
        pan; hover to inspect values.
      </p>
    </div>
  );
}
