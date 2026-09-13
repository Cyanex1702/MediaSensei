export const CORE_API_BASE = (process.env.NEXT_PUBLIC_CORE_API_URL || 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '');

export type Project = {
  id: string;
  name: string;
  description?: string;
  data_policy: string;
  created_at?: string;
  updated_at?: string;
};

export type ImageAnalysis = {
  valid: boolean;
  format?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  perceptual_hash?: string | null;
  blur_score?: number | null;
  quality_score?: number | null;
  error?: string | null;
  ocr?: { text?: string; regions?: unknown[] } | null;
};

export type Asset = {
  id: string;
  project_id: string;
  sha256: string;
  original_filename: string;
  media_type: 'image' | 'video' | 'audio' | 'document' | 'tabular' | string;
  byte_size: number;
  state: string;
  created_at: string;
  metadata?: Record<string, unknown>;
  analysis?: ImageAnalysis | Record<string, unknown> | null;
  thumbnail_available?: boolean;
  derivatives?: Array<Record<string, unknown>>;
};

export type Job = {
  id: string;
  project_id: string;
  kind: string;
  state: string;
  progress: number;
  counts: {
    total: number;
    processed: number;
    failed: number;
    skipped: number;
    cached: number;
  };
  processor?: { id: string; version: string };
  created_at: string;
  updated_at: string;
};

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), init?.body instanceof FormData ? 600_000 : 30_000);
  let response: Response;
  try {
    response = await fetch(`${CORE_API_BASE}${path}`, {
      ...init,
      signal: init?.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal,
      headers: {
        ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...init?.headers,
      },
    });
  } catch (error) {
    if (controller.signal.aborted) throw new ApiError('The request timed out. Check Jobs before retrying an upload.', 0, 'TIMEOUT');
    throw new ApiError(error instanceof Error ? `Cannot reach the API: ${error.message}` : 'Cannot reach the API', 0, 'NETWORK_ERROR');
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let code: string | undefined;
    try {
      const payload = (await response.json()) as {
        detail?: string | { message?: string; code?: string };
      };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (payload.detail?.message) {
        message = payload.detail.message;
        code = payload.detail.code;
      }
    } catch {
      // Preserve HTTP status text when the response is not JSON.
    }
    throw new ApiError(message, response.status, code);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError('The API returned an invalid response.', response.status, 'INVALID_RESPONSE');
  }
}

export const api = {
  health: () => request<{ status: string; version: string; workspace: string }>('/health'),
  projects: () => request<{ items: Project[] }>('/projects'),
  createProject: (name: string, description = '') =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description, data_policy: 'local_only' }),
    }),
  assets: (projectId: string) => request<{ items: Asset[] }>(`/projects/${projectId}/assets`),
  setAssetState: (assetId: string, state: 'active' | 'quarantined' | 'excluded') =>
    request<Asset>(`/assets/${assetId}`, {
      method: 'PATCH',
      body: JSON.stringify({ state }),
    }),
  jobs: (projectId: string) =>
    request<{ items: Job[] }>(`/jobs?project_id=${encodeURIComponent(projectId)}&limit=100`),
  controlJob: (jobId: string, action: 'pause' | 'resume' | 'cancel' | 'retry-failed') =>
    request<Job>(`/jobs/${jobId}/${action}`, { method: 'POST' }),
  jobEvents: (jobId: string) => request<{ items: unknown[] }>(`/jobs/${jobId}/events?limit=100`),
  upload: async (projectId: string, file: File) => {
    const body = new FormData();
    body.append('file', file, file.name);
    const isZip = file.name.toLowerCase().endsWith('.zip');
    return request<Record<string, unknown>>(
      isZip ? `/projects/${projectId}/imports/archive` : `/projects/${projectId}/assets`,
      { method: 'POST', body },
    );
  },
  analyzeImages: (projectId: string, assetIds: string[]) =>
    request<Job>(`/projects/${projectId}/images/analyze`, {
      method: 'POST',
      body: JSON.stringify({ asset_ids: assetIds, thumbnail: true, thumbnail_size: 512 }),
    }),
  transformImages: (projectId: string, assetIds: string[]) =>
    request<Job>(`/projects/${projectId}/images/transform`, {
      method: 'POST',
      body: JSON.stringify({
        asset_ids: assetIds,
        width: 1024,
        height: 1024,
        fit: 'contain',
        format: 'JPEG',
        quality: 90,
        background: '#000000',
      }),
    }),
  ocrImages: (projectId: string, assetIds: string[]) =>
    request<Job>(`/projects/${projectId}/images/ocr`, {
      method: 'POST',
      body: JSON.stringify({ asset_ids: assetIds, action: 'detect_only', language: null }),
    }),
  analyzeMedia: (projectId: string, assetIds: string[]) =>
    request<Job>(`/projects/${projectId}/media/analyze`, {
      method: 'POST',
      body: JSON.stringify({ asset_ids: assetIds, validate_decode: false, preview: true }),
    }),
  deriveMedia: (projectId: string, assetIds: string[], format: string) =>
    request<Job>(`/projects/${projectId}/media/derive`, {
      method: 'POST',
      body: JSON.stringify({ asset_ids: assetIds, kind: 'transcode', format }),
    }),
  indexDocuments: (projectId: string, assetIds: string[]) =>
    request<Job>(`/projects/${projectId}/documents/index`, {
      method: 'POST',
      body: JSON.stringify({ asset_ids: assetIds, max_words: 420, overlap_words: 64 }),
    }),
  searchDocuments: (projectId: string, query: string, assetIds: string[]) =>
    request<{ query: string; items: Array<Record<string, unknown>>; stats: Record<string, unknown> }>(
      `/projects/${projectId}/documents/search`,
      {
        method: 'POST',
        body: JSON.stringify({ query, asset_ids: assetIds, limit: 8, minimum_score: 0 }),
      },
    ),
  duplicates: (projectId: string) =>
    request<{ count: number; items: unknown[] }>(`/projects/${projectId}/images/duplicates?threshold=8`, {
      method: 'POST',
    }),
  split: (projectId: string) =>
    request<{ seed: number; strategy: string; counts: Record<string, number> }>(
      `/projects/${projectId}/dataset/split`,
      {
        method: 'POST',
        body: JSON.stringify({ strategy: 'random', seed: 42, train: 0.8, validation: 0.1, test: 0.1 }),
      },
    ),
  leakage: (projectId: string) =>
    request<{ count: number; items: unknown[] }>(`/projects/${projectId}/dataset/leakage?threshold=8`, {
      method: 'POST',
    }),
  tabularDatasets: (projectId: string) =>
    request<{ items: Array<Record<string, unknown>> }>(`/projects/${projectId}/tabular`),
  queryTabular: (datasetId: string, search: string) =>
    request<Record<string, unknown>>(`/tabular/${datasetId}/query`, {
      method: 'POST',
      body: JSON.stringify({
        filters: [],
        search: search.trim() || null,
        sort_by: null,
        descending: false,
        visible_columns: [],
        limit: 100,
        offset: 0,
      }),
    }),
  exportTabular: (datasetId: string, name: string) =>
    request<Record<string, unknown>>(`/tabular/${datasetId}/export`, {
      method: 'POST',
      body: JSON.stringify({ name, format: 'csv', query: null }),
    }),
  exportDataset: (projectId: string, name: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/dataset/export`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  capabilities: () => request<Record<string, unknown>>('/system/capabilities'),
  systemLogs: () => request<{ log_dir: string; logs: Record<string, string> }>('/system/logs?lines=250'),
  plugins: () => request<Record<string, unknown>>('/plugins'),
  rescanPlugins: () => request<Record<string, unknown>>('/plugins/rescan', { method: 'POST' }),
};

export function thumbnailUrl(assetId: string, revision?: string | number | null) {
  const suffix = revision ? `?v=${encodeURIComponent(String(revision))}` : '';
  return `${CORE_API_BASE}/assets/${assetId}/thumbnail${suffix}`;
}

export function contentUrl(assetId: string) {
  return `${CORE_API_BASE}/assets/${assetId}/content`;
}

export function datasetExportDownloadUrl(exportId: string) {
  return `${CORE_API_BASE}/dataset/exports/${exportId}/download`;
}

export function tabularExportDownloadUrl(exportId: string) {
  return `${CORE_API_BASE}/tabular/exports/${exportId}/download`;
}

export function derivedImageUrl(derivedId: string) {
  return `${CORE_API_BASE}/derived/images/${derivedId}/content`;
}

export function derivedMediaUrl(derivedId: string) {
  return `${CORE_API_BASE}/derived/media/${derivedId}/content`;
}
