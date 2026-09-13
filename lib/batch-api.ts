import { request } from "@/lib/core-api";
import type { Step, Row, Chart } from "./workbench-api";
const post = <T>(path: string, body: unknown) =>
  request<T>("/lab" + path, { method: "POST", body: JSON.stringify(body) });
export type Query = {
  search?: string;
  sort_by?: string;
  descending?: boolean;
  conditions?: unknown[];
  match?: string;
  offset?: number;
  limit?: number;
  remember?: boolean;
};
export type SavedChart = {
  id: string;
  name: string;
  chart: Chart;
  definition: Record<string, unknown>;
};
export type SavedWorkflow = { id: string; name: string; steps: Step[] };
export type SearchHit = {
  id: string;
  kind: string;
  name: string;
  description: string;
  operation?: string;
  view?: string;
  project_id?: string;
  dataset_id?: string;
  url?: string;
  signature?: string;
  library?: string;
  version?: string;
};
export const batch = {
  query: (id: string, q: Query) =>
    post<{ rows: Row[]; positions: number[]; columns: string[]; total: number; revision: number }>(
      `/datasets/${id}/query`,
      q,
    ),
  queries: (id: string) =>
    request<{ items: Array<{ id: string; query: Query }> }>(`/lab/datasets/${id}/queries`),
  compare: (id: string, left: string, right: string, identity: string, target: string) =>
    request<Record<string, unknown>>(
      `/lab/datasets/${id}/compare?left=${left}&right=${right}&identity=${encodeURIComponent(identity)}&target=${encodeURIComponent(target)}`,
    ),
  charts: (id: string) => request<{ items: SavedChart[] }>(`/lab/datasets/${id}/charts`),
  saveChart: (id: string, name: string, definition: Record<string, unknown>) =>
    post<SavedChart>(`/datasets/${id}/charts`, { name, definition }),
  workflows: (project: string) =>
    request<{ items: SavedWorkflow[] }>(`/lab/projects/${project}/workflows`),
  saveWorkflow: (project: string, name: string, steps: Step[], id?: string) =>
    post<SavedWorkflow>(`/projects/${project}/workflows`, { name, steps, id }),
  saveRecipe: (name: string, steps: Step[], id?: string) =>
    post<SavedWorkflow>("/recipes", { name, steps, id }),
  dryRun: (id: string, steps: Step[], revision: number, bindings: Record<string, unknown>) =>
    post<{ after: Row[]; history: Array<{ name: string; rows: number; columns: number }> }>(
      `/datasets/${id}/workflow-preview`,
      { steps, revision, bindings },
    ),
  run: (id: string, steps: Step[], revision: number, bindings: Record<string, unknown>) =>
    post<{ job_id: string }>(`/datasets/${id}/runs`, { steps, revision, bindings }),
  python: (id: string, steps: Step[], revision: number, bindings: Record<string, unknown>) =>
    post<{ code: string }>(`/datasets/${id}/python`, { steps, revision, bindings }),
  preview: (id: string, step: Step, mode: string, selected: number[]) =>
    post<import("./workbench-api").Preview>(`/datasets/${id}/preview`, {
      ...step,
      mode,
      selected,
      sample: 100,
    }),
  search: (q: string, project = "") =>
    request<{ items: SearchHit[] }>(`/lab/search?q=${encodeURIComponent(q)}&project_id=${project}`),
  functions: (q: string) =>
    request<{ items: SearchHit[] }>(`/lab/functions?q=${encodeURIComponent(q)}`),
};
