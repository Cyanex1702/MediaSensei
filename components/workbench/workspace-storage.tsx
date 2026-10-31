"use client";
import { useState } from "react";
import { request } from "@/lib/core-api";
export default function WorkspaceStorage({ projectId }: { projectId: string }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function action(exportManifest = false) {
    setBusy(true);
    setError("");
    try {
      if (exportManifest) {
        const manifest = await request(`/workspace/projects/${projectId}/manifest`);
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = "project-manifest.json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } else setData(await request("/workspace/storage"));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="data-lab lab-panel">
      <h2>Workspace storage and handoff</h2>
      <p>
        Dataset originals and saved versions can share stored objects. Keep backups before moving or
        cleaning a workspace.
      </p>
      <div className="lab-toolbar">
        <button disabled={busy} onClick={() => void action()}>
          Inspect storage
        </button>
        {projectId && (
          <button disabled={busy} onClick={() => void action(true)}>
            Download project manifest
          </button>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <p role="status">
          {String(data.stored_objects)} objects ·{" "}
          {(Number(data.object_bytes) / 1024 ** 2).toFixed(1)} MiB stored ·{" "}
          {(Number(data.disk_free_bytes) / 1024 ** 3).toFixed(1)} GiB disk space free.
        </p>
      )}
      <p>
        Double-click Backup-MediaSensei.bat to stop this app and save a portable, checksum-verified
        backup. Provider credentials remain in the OS store. Double-click Restore-MediaSensei.bat to
        select a backup, verify it, and activate a new restored folder. The existing workspace is
        preserved.
      </p>
      <p>
        Table operations support 200,000 rows and 256 MiB source files. Acquisition providers
        require internet access and may enforce their own rate limits. Native media tools are
        checked during Windows setup.
      </p>
    </section>
  );
}
