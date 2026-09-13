# ADR 008: Shell-free FFmpeg boundary

Status: accepted

MediaSensei invokes `ffmpeg` and `ffprobe` only through a bounded adapter that passes an argument array with shell execution disabled. Paths are resolved, user-controlled format choices are allowlisted, time/dimension values are bounded, probe output and persisted errors are capped, and every command has a timeout.

Outputs are staged separately and imported into content-addressed storage; source objects are never output targets. Deterministic cache identity includes the exact FFmpeg version, while derivative catalog records retain source hash, canonical parameters, MIME type, duration, and tool revision.

This preserves local portability without binding the domain to FFmpeg. A missing executable is a retryable per-item processing failure, so installing FFmpeg and retrying failed items does not repeat completed work.
