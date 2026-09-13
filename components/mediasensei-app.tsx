"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  File,
  FileImage,
  FileText,
  FolderOpen,
  HardDrive,
  ImageIcon,
  LoaderCircle,
  Plug,
  RefreshCw,
  Search,
  Server,
  Sparkles,
  UploadCloud,
  Video,
  XCircle,
} from "lucide-react";

import DataLab from "@/components/workbench/data-lab";
import { ThemePicker } from "@/components/workbench/theme-picker";
import { LibraryInspector } from "@/components/workbench/library-inspector";
import AssetLab from "@/components/workbench/asset-lab";
import Sources from "@/components/workbench/sources";
import Integrations from "@/components/workbench/integrations";
import { CommandCenter, Documentation } from "@/components/workbench/command-center";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  api,
  ApiError,
  contentUrl,
  datasetExportDownloadUrl,
  derivedImageUrl,
  derivedMediaUrl,
  thumbnailUrl,
  type Asset,
  type Job,
  type Project,
} from "@/lib/core-api";

type View =
  | "Overview"
  | "Library"
  | "Data Lab"
  | "Image Lab"
  | "Video Lab"
  | "Audio Lab"
  | "Knowledge Lab"
  | "Quality"
  | "Sources"
  | "Model Hub"
  | "Connections"
  | "Playground"
  | "Voices"
  | "Jobs"
  | "Documentation"
  | "System"
  | "Workflows"
  | "Versions"
  | "Exports";
const views: View[] = [
  "Overview",
  "Sources",
  "Library",
  "Data Lab",
  "Image Lab",
  "Video Lab",
  "Audio Lab",
  "Knowledge Lab",
  "Quality",
  "Workflows",
  "Versions",
  "Exports",
  "Jobs",
  "Model Hub",
  "Connections",
  "Playground",
  "Voices",
  "Documentation",
  "System",
];
type Health = { status: string; version: string; workspace: string };

type Notice = { kind: "success" | "error" | "info"; text: string } | null;

const terminalStates = new Set(["completed", "completed_with_errors", "cancelled", "failed"]);

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError)
    return error.code ? `${error.code}: ${error.message}` : error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

function kindLabel(asset: Asset) {
  if (asset.media_type === "image") return "Image";
  if (asset.media_type === "video") return "Video";
  if (asset.media_type === "audio") return "Audio";
  if (asset.media_type === "document") return "Document";
  if (asset.media_type === "tabular") return "Tabular";
  return asset.media_type;
}

function assetIcon(asset: Asset) {
  if (asset.media_type === "image") return ImageIcon;
  if (asset.media_type === "video" || asset.media_type === "audio") return Video;
  if (asset.media_type === "document") return FileText;
  if (asset.media_type === "tabular") return Database;
  return File;
}

export default function MediaSenseiApp() {
  const [requestedOperation, setRequestedOperation] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const openOperation = (id: string) => {
    setRequestedOperation(id);
    window.dispatchEvent(new CustomEvent("sensei.operation", { detail: id }));
    setView("Data Lab");
  };
  const [view, setView] = useState<View>("Overview");
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [libraryType, setLibraryType] = useState("all"),
    [libraryLayout, setLibraryLayout] = useState("grid");
  const selectionProject = useRef("");
  useEffect(() => {
    if (projectId && selectionProject.current === projectId)
      localStorage.setItem("sensei.selection." + projectId, JSON.stringify([...selected]));
  }, [selected, projectId]);
  const [busy, setBusy] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [projectName, setProjectName] = useState("My MediaSensei Project");
  const [datasetResult, setDatasetResult] = useState("");
  const [lastExportId, setLastExportId] = useState("");
  const [pluginSnapshot, setPluginSnapshot] = useState<Record<string, unknown> | null>(null);
  const [capabilities, setCapabilities] = useState<Record<string, unknown> | null>(null);
  const [systemLogs, setSystemLogs] = useState<{
    log_dir: string;
    logs: Record<string, string>;
  } | null>(null);
  const [jobEvents, setJobEvents] = useState<unknown[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const folderInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (projectId) localStorage.setItem("mediasensei.activeProject", projectId);
  }, [projectId]);
  const activeProject = useRef(projectId);
  activeProject.current = projectId;
  const [healthChecked, setHealthChecked] = useState(false);

  const currentProject = projects.find((project) => project.id === projectId) ?? null;
  const latestJobRevision = jobs.reduce(
    (latest, job) => (job.updated_at > latest ? job.updated_at : latest),
    "",
  );

  const loadProjects = useCallback(async () => {
    const response = await api.projects();
    setProjects(response.items);
    setProjectId((current) => {
      const saved = localStorage.getItem("mediasensei.activeProject");
      return (
        current || response.items.find((p) => p.id === saved)?.id || response.items[0]?.id || ""
      );
    });
    return response.items;
  }, []);

  const refreshProject = useCallback(async (id: string) => {
    if (!id) return;
    const [assetResponse, jobResponse] = await Promise.all([api.assets(id), api.jobs(id)]);
    if (activeProject.current !== id) return;
    setAssets(assetResponse.items);
    setJobs(jobResponse.items);
    setSelected((current) => {
      const available = new Set(assetResponse.items.map((asset) => asset.id));
      return new Set([...current].filter((idValue) => available.has(idValue)));
    });
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const result = await api.health();
      setHealth(result);
      setHealthChecked(true);
      const loadedProjects = await loadProjects();
      const id = projectId || loadedProjects[0]?.id;
      if (id && id === activeProject.current) await refreshProject(id);
      try {
        setPluginSnapshot(await api.plugins());
      } catch {
        // Plugin status is non-critical to loading the workspace.
      }
    } catch (error) {
      if (error instanceof ApiError && (error.status === 0 || error.status === 503))
        setHealth(null);
      setHealthChecked(true);
      setNotice({ kind: "error", text: errorMessage(error) });
    }
  }, [loadProjects, projectId, refreshProject]);

  useEffect(() => {
    if (folderInput.current) folderInput.current.setAttribute("webkitdirectory", "");
    void refreshAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setAssets([]);
    setJobs([]);
    selectionProject.current = "";
    try {
      setSelected(
        new Set(JSON.parse(localStorage.getItem("sensei.selection." + projectId) || "[]")),
      );
    } catch {
      setSelected(new Set());
    }
    queueMicrotask(() => {
      selectionProject.current = projectId;
    });
    setDatasetResult("");
    setLastExportId("");
    setJobEvents([]);
    setSelectedJobId("");
    if (!projectId) return;
    void refreshProject(projectId).catch((error) =>
      setNotice({ kind: "error", text: errorMessage(error) }),
    );
  }, [projectId, refreshProject]);

  useEffect(() => {
    if (view !== "System" || !health) return;
    void Promise.all([api.capabilities(), api.systemLogs()])
      .then(([caps, logs]) => {
        setCapabilities(caps);
        setSystemLogs(logs);
      })
      .catch((error) => setNotice({ kind: "error", text: errorMessage(error) }));
  }, [view, health]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await api.health();
        if (cancelled) return;
        setHealth((current) => (current?.version === response.version ? current : response));
        setHealthChecked(true);
      } catch {
        if (!cancelled) {
          setHealth(null);
          setHealthChecked(true);
        }
      }
      if (!cancelled && projectId) {
        try {
          await refreshProject(projectId);
        } catch (error) {
          if (!cancelled) setNotice({ kind: "error", text: errorMessage(error) });
        }
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 4000);
    }
    timer = setTimeout(() => void poll(), 4000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [projectId, refreshProject]);

  const filteredAssets = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return assets;
    return assets.filter(
      (asset) =>
        asset.original_filename.toLowerCase().includes(needle) ||
        asset.media_type.toLowerCase().includes(needle) ||
        asset.sha256.toLowerCase().includes(needle),
    );
  }, [assets, filter]);

  const selectedAssets = assets.filter((asset) => selected.has(asset.id));

  const imageCount = assets.filter((asset) => asset.media_type === "image").length;
  const processedImageCount = assets.filter(
    (asset) => asset.media_type === "image" && Boolean(asset.analysis),
  ).length;
  const runningJobs = jobs.filter((job) => !terminalStates.has(job.state));
  const failedJobs = jobs.filter((job) => job.counts.failed > 0 || job.state.includes("error"));

  async function createProject() {
    const name = projectName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const project = await api.createProject(name);
      await loadProjects();
      setProjectId(project.id);
      setNotice({ kind: "success", text: `Created project “${project.name}”.` });
    } catch (error) {
      setNotice({ kind: "error", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  async function importFiles(files: File[]) {
    if (!projectId || files.length === 0) return;
    setBusy(true);
    setNotice(null);
    let succeeded = 0;
    const failures: string[] = [];
    try {
      for (let index = 0; index < files.length; index += 1) {
        const fileValue = files[index];
        setUploadStatus(`Uploading ${index + 1}/${files.length}: ${fileValue.name}`);
        try {
          const result = await api.upload(projectId, fileValue);
          succeeded += 1;
          if (Number(result.skipped_count) > 0) {
            const skipped = result.skipped as Array<{ name: string; reason: string }>;
            failures.push(
              `${fileValue.name}: ${result.imported_count} imported, ${result.skipped_count} skipped. ${skipped
                .slice(0, 3)
                .map((item) => `${item.name}: ${item.reason}`)
                .join("; ")}`,
            );
          }
        } catch (error) {
          failures.push(`${fileValue.name}: ${errorMessage(error)}`);
        }
      }
      await refreshProject(projectId);
      if (failures.length) {
        setNotice({
          kind: "error",
          text: `Imported ${succeeded}/${files.length}. ${failures.slice(0, 3).join(" | ")}`,
        });
      } else {
        setNotice({
          kind: "success",
          text: `Imported ${succeeded} file${succeeded === 1 ? "" : "s"}. Real processing jobs were queued.`,
        });
      }
    } catch (error) {
      setNotice({ kind: "error", text: errorMessage(error) });
    } finally {
      setUploadStatus("");
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
      if (folderInput.current) folderInput.current.value = "";
    }
  }

  async function execute(label: string, operation: () => Promise<unknown>) {
    if (!projectId) return;
    setBusy(true);
    setNotice({ kind: "info", text: `${label}…` });
    try {
      const result = await operation();
      setNotice({ kind: "success", text: `${label} submitted successfully.` });
      if (label.includes("split") || label.includes("duplicate") || label.includes("leakage")) {
        setDatasetResult(JSON.stringify(result, null, 2));
      }
      await refreshProject(projectId);
    } catch (error) {
      setNotice({ kind: "error", text: `${label} failed: ${errorMessage(error)}` });
    } finally {
      setBusy(false);
    }
  }

  async function showJobEvents(jobId: string) {
    setSelectedJobId(jobId);
    try {
      const response = await api.jobEvents(jobId);
      setJobEvents(response.items);
    } catch (error) {
      setJobEvents([{ error: errorMessage(error) }]);
    }
  }

  const hasProject = Boolean(projectId);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-4 px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
              <Sparkles className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="font-semibold">MediaSensei</div>
              <div className="truncate text-xs text-muted-foreground">
                {currentProject?.name ?? "Real local media workspace"}
              </div>
            </div>
          </div>
          <ThemePicker />
          <CommandCenter
            projectId={projectId}
            onProject={setProjectId}
            onNavigate={(value) => setView(value as View)}
            onOperation={openOperation}
          />
          <div className="ml-auto flex items-center gap-2">
            <Badge variant={health ? "secondary" : "destructive"}>
              {health ? (
                <CheckCircle2 className="mr-1 size-3" />
              ) : (
                <XCircle className="mr-1 size-3" />
              )}
              {health ? "API online" : healthChecked ? "API unavailable" : "Checking API…"}
            </Badge>
            <Button variant="outline" size="sm" onClick={() => void refreshAll()}>
              <RefreshCw className="mr-1 size-4" /> Refresh
            </Button>
          </div>
        </div>
        <div className="mx-auto flex max-w-[1500px] gap-1 overflow-x-auto px-5 pb-2 md:hidden">
          {views.map((item) => (
            <Button
              key={item}
              size="sm"
              variant={view === item ? "secondary" : "ghost"}
              onClick={() => setView(item)}
            >
              {item}
            </Button>
          ))}
        </div>
      </header>

      <div className="sensei-workspace-shell">
        <aside className="sensei-nav" aria-label="Project navigation">
          <div className="lab-eyebrow">PROJECT WORKSPACE</div>
          {views.map((item) => (
            <button
              key={item}
              className={view === item ? "active" : ""}
              onClick={() => setView(item)}
            >
              {item}
            </button>
          ))}
          <div className="sensei-nav-footer">
            MediaSensei 2.0
            <br />
            <span>Local operation workbench</span>
          </div>
        </aside>
        <main className="sensei-workspace-main space-y-5 p-5">
          {notice && (
            <div
              className={`flex items-start gap-2 rounded-xl border p-3 text-sm ${
                notice.kind === "error"
                  ? "border-destructive/40 bg-destructive/10"
                  : notice.kind === "success"
                    ? "border-primary/30 bg-primary/10"
                    : "bg-muted/50"
              }`}
            >
              {notice.kind === "error" ? (
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              ) : (
                <Activity className="mt-0.5 size-4 shrink-0" />
              )}
              <span>{notice.text}</span>
            </div>
          )}

          {!hasProject && (
            <Card>
              <CardHeader>
                <CardTitle>Create your first real project</CardTitle>
                <CardDescription>
                  Create a project to import, process, and organize your local files.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3 sm:flex-row">
                <Input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                />
                <Button disabled={busy} onClick={() => void createProject()}>
                  Create project
                </Button>
              </CardContent>
            </Card>
          )}

          {hasProject && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3">
              <span className="text-sm text-muted-foreground">Project</span>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={projectId}
                disabled={busy}
                onChange={(event) => setProjectId(event.target.value)}
              >
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <Input
                className="ml-auto max-w-xs"
                placeholder="New project name"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
              />
              <Button variant="outline" disabled={busy} onClick={() => void createProject()}>
                New project
              </Button>
            </div>
          )}

          {hasProject && (
            <div hidden={!["Data Lab", "Workflows", "Versions", "Exports"].includes(view)}>
              <DataLab
                requestedTab={
                  ["Workflows", "Versions", "Exports"].includes(view) ? view : undefined
                }
                key={projectId}
                projectId={projectId}
                jobRevision={latestJobRevision}
                requestedOperation={requestedOperation}
                onQueued={() => void refreshProject(projectId)}
              />
            </div>
          )}
          {hasProject && view === "Sources" && <Sources key={projectId} projectId={projectId} />}
          {hasProject && ["Model Hub", "Connections", "Playground", "Voices"].includes(view) && <Integrations key={`${projectId}-${view}`} projectId={projectId} view={view} assets={assets} />}
          {view === "Documentation" && <Documentation onOperation={openOperation} />}

          {hasProject && view === "Overview" && (
            <>
              <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <Metric
                  title="Assets"
                  value={assets.length}
                  icon={HardDrive}
                  detail={`${formatBytes(assets.reduce((sum, asset) => sum + asset.byte_size, 0))} stored`}
                />
                <Metric
                  title="Images analyzed"
                  value={`${processedImageCount}/${imageCount}`}
                  icon={FileImage}
                  detail="From backend image_analysis"
                />
                <Metric
                  title="Active jobs"
                  value={runningJobs.length}
                  icon={Activity}
                  detail={`${failedJobs.length} with failures`}
                />
                <Metric
                  title="Backend"
                  value={health?.version ? `v${health.version}` : "Offline"}
                  icon={Server}
                  detail={health?.workspace ?? "Start the API service"}
                />
              </section>

              <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
                <Card>
                  <CardHeader>
                    <CardTitle>Import real files</CardTitle>
                    <CardDescription>
                      Files are uploaded to content-addressed storage. Images, documents, media and
                      tabular data automatically queue real backend processing. ZIP archives are
                      safely extracted server-side.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => fileInput.current?.click()} disabled={busy}>
                        <UploadCloud className="mr-2 size-4" /> Files or ZIP
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => folderInput.current?.click()}
                        disabled={busy}
                      >
                        <FolderOpen className="mr-2 size-4" /> Folder
                      </Button>
                      <input
                        ref={fileInput}
                        className="hidden"
                        type="file"
                        multiple
                        onChange={(event) => void importFiles(Array.from(event.target.files ?? []))}
                      />
                      <input
                        ref={(input) => {
                          folderInput.current = input;
                          input?.setAttribute("webkitdirectory", "");
                        }}
                        className="hidden"
                        type="file"
                        multiple
                        onChange={(event) => void importFiles(Array.from(event.target.files ?? []))}
                      />
                    </div>
                    {uploadStatus && (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <LoaderCircle className="size-4 animate-spin" /> {uploadStatus}
                      </div>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Supported: common images, video/audio, TXT/MD/PDF/DOCX/HTML,
                      CSV/TSV/JSONL/Parquet/Excel/SQLite/DuckDB, and ZIP archives containing
                      supported files.
                    </p>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Recent jobs</CardTitle>
                    <CardDescription>
                      These states come from the persistent Python job queue.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {jobs.slice(0, 5).map((job) => (
                      <JobRow key={job.id} job={job} onClick={() => void showJobEvents(job.id)} />
                    ))}
                    {jobs.length === 0 && <Empty text="No processing jobs yet." />}
                  </CardContent>
                </Card>
              </section>
            </>
          )}

          {hasProject && view === "Library" && (
            <Card>
              <CardHeader>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                  <div>
                    <CardTitle>Library</CardTitle>
                    <div className="flex gap-2 flex-wrap">
                      <select
                        aria-label="Library modality"
                        value={libraryType}
                        onChange={(e) => setLibraryType(e.target.value)}
                        className="bg-card border rounded p-2"
                      >
                        {["all", "image", "video", "audio", "document", "tabular"].map((t) => (
                          <option key={t} value={t}>
                            {t === "all"
                              ? "All"
                              : t === "tabular"
                                ? "Tables"
                                : t[0].toUpperCase() + t.slice(1) + "s"}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label="Library layout"
                        value={libraryLayout}
                        onChange={(e) => setLibraryLayout(e.target.value)}
                        className="bg-card border rounded p-2"
                      >
                        <option value="grid">Grid</option>
                        <option value="list">List</option>
                      </select>
                    </div>
                    <CardDescription>
                      {assets.length} real catalog assets · {selected.size} selected
                    </CardDescription>
                  </div>
                  <div className="ml-auto flex w-full max-w-xl gap-2 lg:w-auto">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
                      <Input
                        className="pl-9"
                        placeholder="Filter files, type, or SHA-256"
                        value={filter}
                        onChange={(event) => setFilter(event.target.value)}
                      />
                    </div>
                    <Button
                      variant="outline"
                      onClick={() =>
                        setSelected(
                          new Set(
                            filteredAssets
                              .filter((a) => libraryType === "all" || a.media_type === libraryType)
                              .map((asset) => asset.id),
                          ),
                        )
                      }
                    >
                      Select all
                    </Button>
                    <Button variant="ghost" onClick={() => setSelected(new Set())}>
                      Clear
                    </Button>
                  </div>
                  {selected.size > 0 && (
                    <div className="flex flex-wrap gap-2 lg:ml-auto">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void execute("Quarantine selected assets", async () => {
                            await Promise.all(
                              [...selected].map((id) => api.setAssetState(id, "quarantined")),
                            );
                            return { updated: selected.size };
                          })
                        }
                      >
                        Quarantine
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void execute("Reactivate selected assets", async () => {
                            await Promise.all(
                              [...selected].map((id) => api.setAssetState(id, "active")),
                            );
                            return { updated: selected.size };
                          })
                        }
                      >
                        Reactivate
                      </Button>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <LibraryInspector assets={selectedAssets} onNavigate={(v) => setView(v as View)} />
                {filteredAssets.length === 0 ? (
                  <Empty text="No assets match. Import files from Overview." />
                ) : (
                  <div
                    className={
                      libraryLayout === "grid"
                        ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
                        : "library-list grid gap-3"
                    }
                  >
                    {filteredAssets
                      .filter((asset) => libraryType === "all" || asset.media_type === libraryType)
                      .map((asset) => (
                        <AssetCard
                          key={asset.id}
                          asset={asset}
                          selected={selected.has(asset.id)}
                          revision={latestJobRevision}
                          onToggle={() =>
                            setSelected((current) => {
                              const next = new Set(current);
                              if (next.has(asset.id)) next.delete(asset.id);
                              else next.add(asset.id);
                              return next;
                            })
                          }
                        />
                      ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {hasProject &&
            ["Image Lab", "Video Lab", "Audio Lab", "Knowledge Lab"].includes(view) && (
              <AssetLab
                key={`${projectId}-${view}`}
                projectId={projectId}
                modality={
                  view === "Image Lab"
                    ? "image"
                    : view === "Video Lab"
                      ? "video"
                      : view === "Audio Lab"
                        ? "audio"
                        : "document"
                }
                assets={assets}
                selectedIds={[...selected]}
                onRefresh={() => refreshProject(projectId)}
              />
            )}
          {hasProject && view === "Quality" && (
            <div className="grid gap-4 lg:grid-cols-2">
              {view === "Quality" && (
                <ToolCard
                  title="Dataset Lab"
                  description="Duplicate detection, deterministic split assignment, leakage checks, and export run against real catalog assets."
                  icon={Database}
                >
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void execute("Dataset duplicate scan", () => api.duplicates(projectId))
                        }
                      >
                        Find duplicates
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => void execute("Dataset split", () => api.split(projectId))}
                      >
                        80/10/10 split
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void execute("Dataset leakage check", () => api.leakage(projectId))
                        }
                      >
                        Check leakage
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() =>
                          void (async () => {
                            setBusy(true);
                            try {
                              const result = await api.exportDataset(
                                projectId,
                                `export-${Date.now()}`,
                              );
                              const exportId = String(result.id ?? "");
                              setLastExportId(exportId);
                              setDatasetResult(JSON.stringify(result, null, 2));
                              setNotice({
                                kind: "success",
                                text: "Dataset export created on disk.",
                              });
                            } catch (error) {
                              setNotice({
                                kind: "error",
                                text: `Dataset export failed: ${errorMessage(error)}`,
                              });
                            } finally {
                              setBusy(false);
                            }
                          })()
                        }
                      >
                        Export dataset
                      </Button>
                    </div>
                    {lastExportId && (
                      <a
                        className="inline-flex text-sm text-primary hover:underline"
                        href={datasetExportDownloadUrl(lastExportId)}
                      >
                        Download latest export ZIP
                      </a>
                    )}
                    {datasetResult && (
                      <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-3 text-xs">
                        {datasetResult}
                      </pre>
                    )}
                  </div>
                </ToolCard>
              )}
            </div>
          )}

          {hasProject && view === "Jobs" && (
            <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <Card>
                <CardHeader>
                  <CardTitle>Persistent job queue</CardTitle>
                  <CardDescription>
                    Click a job to inspect backend events and failure messages.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {jobs.map((job) => (
                    <JobRow key={job.id} job={job} onClick={() => void showJobEvents(job.id)} />
                  ))}
                  {jobs.length === 0 && <Empty text="No jobs have been queued." />}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Job events</CardTitle>
                  <CardDescription>
                    {selectedJobId || "Select a job to see scheduler/processor events."}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {selectedJobId && (
                    <div className="mb-3 flex flex-wrap gap-2">
                      {(["pause", "resume", "cancel", "retry-failed"] as const).map((action) => (
                        <Button
                          key={action}
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void execute(`Job ${action}`, async () => {
                              await api.controlJob(selectedJobId, action);
                              await showJobEvents(selectedJobId);
                            })
                          }
                        >
                          {action === "retry-failed"
                            ? "Retry failed"
                            : action[0].toUpperCase() + action.slice(1)}
                        </Button>
                      ))}
                    </div>
                  )}
                  <pre className="max-h-[650px] overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">
                    {jobEvents.length ? JSON.stringify(jobEvents, null, 2) : "No job selected."}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}

          {view === "System" && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Backend health</CardTitle>
                  <CardDescription>
                    The app no longer treats “page loaded” as proof the processing engine is
                    healthy.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <Info label="API" value={health ? "Online" : "Offline"} />
                  <Info label="Version" value={health?.version ?? "—"} />
                  <Info label="Workspace" value={health?.workspace ?? "—"} />
                  <Info label="Queued/running jobs" value={String(runningJobs.length)} />
                  <Info label="Failed jobs" value={String(failedJobs.length)} />
                  <Info
                    label="FFmpeg"
                    value={capabilities?.ffmpeg ? String(capabilities.ffmpeg) : "Unavailable"}
                  />
                  <Info
                    label="Tesseract OCR"
                    value={capabilities?.tesseract ? String(capabilities.tesseract) : "Unavailable"}
                  />
                  <Info
                    label="DuckDB / PyArrow"
                    value={`${capabilities?.duckdb ? "DuckDB ✓" : "DuckDB ✗"} · ${capabilities?.pyarrow ? "PyArrow ✓" : "PyArrow ✗"}`}
                  />
                  <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">
                    Launcher process output is written to{" "}
                    <code>.mediasensei-launcher/logs/api.log</code>, <code>worker.log</code>, and{" "}
                    <code>web.log</code>. The launcher now checks API and web health before
                    reporting readiness.
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Live launcher logs</CardTitle>
                  <CardDescription>
                    {systemLogs?.log_dir ?? "Launcher logs become available after startup."}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {(["api", "worker", "web"] as const).map((name) => (
                    <details key={name} className="rounded-lg border p-3">
                      <summary className="cursor-pointer text-sm font-medium">{name}.log</summary>
                      <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-xs">
                        {systemLogs?.logs[name] || "No log output yet."}
                      </pre>
                    </details>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Plugins</CardTitle>
                  <CardDescription>
                    Plugin status is loaded from the real Python plugin runtime.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Button
                    variant="outline"
                    onClick={() =>
                      void execute("Plugin rescan", async () => {
                        const result = await api.rescanPlugins();
                        setPluginSnapshot(result);
                        return result;
                      })
                    }
                  >
                    <Plug className="mr-2 size-4" /> Rescan plugins
                  </Button>
                  <pre className="max-h-96 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">
                    {pluginSnapshot
                      ? JSON.stringify(pluginSnapshot, null, 2)
                      : "Plugin status unavailable."}
                  </pre>
                </CardContent>
              </Card>
            </div>
          )}
        </main>
      </div>
      <div className="sensei-job-drawer">
        <button
          className="drawer-toggle"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(!drawerOpen)}
        >
          <Activity size={16} />
          <strong>Jobs</strong>
          <span>
            {runningJobs.length} active · {failedJobs.length} with failures
          </span>
          <span className="ml-auto">{drawerOpen ? "Close" : "Show progress"}</span>
        </button>
        {drawerOpen && (
          <div className="drawer-content">
            {jobs.slice(0, 8).map((job) => (
              <div className="drawer-job" key={job.id}>
                <JobRow
                  job={job}
                  onClick={() => {
                    setView("Jobs");
                    void showJobEvents(job.id);
                  }}
                />
                <div className="flex gap-2">
                  {!terminalStates.has(job.state) && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void execute("Job control", () =>
                          api.controlJob(job.id, job.state === "paused" ? "resume" : "pause"),
                        )
                      }
                    >
                      {job.state === "paused" ? "Resume" : "Pause"}
                    </Button>
                  )}
                  {!terminalStates.has(job.state) && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void execute("Cancel job", () => api.controlJob(job.id, "cancel"))
                      }
                    >
                      Cancel
                    </Button>
                  )}
                  {job.counts.failed > 0 && (
                    <Button
                      size="sm"
                      onClick={() =>
                        void execute("Retry", () => api.controlJob(job.id, "retry-failed"))
                      }
                    >
                      Retry failed
                    </Button>
                  )}
                </div>
              </div>
            ))}
            {!jobs.length && <p>No jobs yet. Imports and operations will appear here.</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({
  title,
  value,
  detail,
  icon: Icon,
}: {
  title: string;
  value: string | number;
  detail: string;
  icon: typeof Activity;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardDescription>{title}</CardDescription>
          <Icon className="size-4 text-muted-foreground" />
        </div>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{detail}</CardContent>
    </Card>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

function AssetCard({
  asset,
  selected,
  revision,
  onToggle,
}: {
  asset: Asset;
  selected: boolean;
  revision: string;
  onToggle: () => void;
}) {
  const Icon = assetIcon(asset);
  const analysis = asset.analysis as Record<string, unknown> | null | undefined;
  const downloadableDerivatives = (asset.derivatives ?? []).filter(
    (item) => String(item.kind ?? "") !== "thumbnail",
  );
  return (
    <div
      className={`overflow-hidden rounded-xl border bg-card ${selected ? "ring-2 ring-primary" : ""}`}
    >
      <button className="block w-full text-left" onClick={onToggle} type="button">
        <div className="relative aspect-[4/3] overflow-hidden bg-muted">
          {asset.media_type === "image" && asset.thumbnail_available ? (
            <img
              src={thumbnailUrl(asset.id, revision)}
              alt={asset.original_filename}
              className="h-full w-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="grid h-full place-items-center">
              <Icon className="size-12 text-muted-foreground/60" />
            </div>
          )}
          <Badge className="absolute left-2 top-2" variant="secondary">
            {kindLabel(asset)}
          </Badge>
          {selected && <CheckCircle2 className="absolute right-2 top-2 size-5 text-primary" />}
        </div>
        <div className="space-y-1 p-3">
          <div className="truncate text-sm font-medium" title={asset.original_filename}>
            {asset.original_filename}
          </div>
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{formatBytes(asset.byte_size)}</span>
            <span>{asset.state}</span>
          </div>
          {asset.media_type === "image" && analysis && (
            <div className="truncate text-xs text-muted-foreground">
              {String(analysis.width ?? "?")}×{String(analysis.height ?? "?")} · quality{" "}
              {String(analysis.quality_score ?? "—")}
            </div>
          )}
          <div className="truncate font-mono text-[10px] text-muted-foreground">{asset.sha256}</div>
        </div>
      </button>
      <div className="flex flex-wrap gap-x-3 gap-y-1 border-t p-2">
        <a
          className="text-xs text-primary hover:underline"
          href={contentUrl(asset.id)}
          target="_blank"
          rel="noreferrer"
        >
          Open original
        </a>
        {downloadableDerivatives.slice(0, 4).map((item) => {
          const id = String(item.id ?? "");
          if (!id) return null;
          const href = asset.media_type === "image" ? derivedImageUrl(id) : derivedMediaUrl(id);
          return (
            <a key={id} className="text-xs text-primary hover:underline" href={href}>
              {String(item.kind ?? "derived")} {String(item.format ?? "")}
            </a>
          );
        })}
      </div>
    </div>
  );
}

function JobRow({ job, onClick }: { job: Job; onClick: () => void }) {
  const bad = job.counts.failed > 0 || job.state.includes("error");
  const active = !terminalStates.has(job.state);
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-lg border p-3 text-left hover:bg-muted/50"
    >
      <div className="flex items-center gap-3">
        {bad ? (
          <AlertTriangle className="size-4 text-destructive" />
        ) : active ? (
          <LoaderCircle className="size-4 animate-spin text-primary" />
        ) : (
          <CheckCircle2 className="size-4 text-primary" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{job.kind}</span>
            <Badge variant={bad ? "destructive" : "secondary"}>{job.state}</Badge>
          </div>
          <div className="mt-2 flex items-center gap-3">
            <Progress value={job.progress} className="h-1.5 flex-1" />
            <span className="text-xs text-muted-foreground">{job.progress}%</span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {job.counts.processed}/{job.counts.total} processed · {job.counts.cached} cached ·{" "}
            {job.counts.failed} failed
          </div>
        </div>
      </div>
    </button>
  );
}

function ToolCard({
  title,
  description,
  icon: Icon,
  children,
}: {
  title: string;
  description: string;
  icon: typeof Activity;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 text-primary">
            <Icon className="size-5" />
          </div>
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 border-b pb-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-all">{value}</span>
    </div>
  );
}
