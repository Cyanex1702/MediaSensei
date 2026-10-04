import { request, CORE_API_BASE } from "@/lib/core-api";
export type Row = Record<string, unknown>;
export type Parameter = {
  title: string;
  type: string;
  default?: unknown;
  choices?: string[];
  minimum?: number;
  maximum?: number;
  optional?: boolean;
};
export type Operation = {
  id: string;
  name: string;
  category: string;
  description: string;
  backend: string;
  version: string;
  aliases: string[];
  warnings: string[];
  parameter_schema: Record<string, Parameter>;
};
export type Dataset = {
  id: string;
  name: string;
  project_id: string;
  revision: number;
  head_key: string;
  root_key: string;
};
export type Column = {
  name: string;
  dtype: string;
  missing: number;
  unique: number;
  numeric: boolean;
  mean?: number;
  median?: number;
  std?: number;
  min?: number;
  max?: number;
  outliers?: number;
};
export type Finding = {
  title: string;
  reason: string;
  operation: string;
  parameters: Record<string, unknown>;
};
export type Overview = {
  dataset: Dataset;
  profile: {
    rows: number;
    column_count: number;
    columns: Column[];
    duplicates: number;
    memory_bytes: number;
    findings: Finding[];
  };
};
export type Step = { operation: string; parameters: Record<string, unknown> };
export type Chart = {
  kind: string;
  title: string;
  columns?: string[];
  values: Array<Record<string, unknown>>;
};
export type Preview = {
  before: Row[];
  after: Row[];
  before_columns: string[];
  after_columns: string[];
  rows_before: number;
  rows_after: number;
  sample_size: number;
  revision: number;
  chart: Chart | null;
  python: string;
  warnings: string[];
};
export type Run = {
  id: string;
  job_id: string;
  state: string;
  created_at: string;
  data: {
    steps: Step[];
    error?: string;
    runtime_seconds?: number;
    cache_hit?: boolean;
    history?: Array<{ chart: Chart | null; operation: string }>;
  };
};
export type Version = {
  id: string;
  name: string;
  created_at: string;
  manifest: Dataset & { profile: Overview["profile"] };
};
export type Recipe = { id: string; name: string; steps: Step[] };
const post = <T>(url: string, body: unknown) =>
  request<T>(`/lab${url}`, { method: "POST", body: JSON.stringify(body) });
export const lab = {
  operations: () => request<{ items: Operation[] }>("/lab/operations"),
  datasets: (project: string) => request<{ items: Dataset[] }>(`/lab/projects/${project}/datasets`),
  adopt: (id: string) => post<Dataset>(`/datasets/from-table/${id}`, {}),
  overview: (id: string) => request<Overview>(`/lab/datasets/${id}`),
  rows: (id: string, offset: number, search: string, sort: string) =>
    request<{ columns: string[]; rows: Row[]; total: number }>(
      `/lab/datasets/${id}/rows?offset=${offset}&search=${encodeURIComponent(search)}&sort_by=${encodeURIComponent(sort)}`,
    ),
  preview: (id: string, step: Step) =>
    post<Preview>(`/datasets/${id}/preview`, { ...step, sample: 100 }),
  run: (id: string, steps: Step[], revision: number) =>
    post<{ job_id: string; run_id: string }>(`/datasets/${id}/runs`, { steps, revision }),
  runs: (id: string) => request<{ items: Run[] }>(`/lab/datasets/${id}/runs`),
  versions: (id: string) => request<{ items: Version[] }>(`/lab/datasets/${id}/versions`),
  version: (id: string, name: string) => post<Version>(`/datasets/${id}/versions`, { name }),
  restore: (id: string, version: string, revision: number) =>
    post<Dataset>(`/datasets/${id}/versions/${version}/restore`, { revision }),
  recipes: () => request<{ items: Recipe[] }>("/lab/recipes"),
  saveRecipe: (name: string, steps: Step[]) => post<Recipe>("/recipes", { name, steps }),
  dryRun: (id: string, steps: Step[], revision: number) =>
    post<{ after: Row[]; history: Array<{ name: string; rows: number; columns: number }> }>(
      `/datasets/${id}/workflow-preview`,
      { steps, revision },
    ),
  python: (id: string, steps: Step[], revision: number) =>
    post<{ code: string }>(`/datasets/${id}/python`, { steps, revision }),
  exportUrl: (id: string, version = "", bundle = false) =>
    `${CORE_API_BASE}/lab/datasets/${id}/export?version_id=${version}&bundle=${bundle}`,
};
export function downloadText(name: string, content: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
