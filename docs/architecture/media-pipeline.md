# Video and audio pipeline

Media processing is an infrastructure adapter over the same immutable asset, job, cache, and catalog boundaries used elsewhere in MediaSensei.

## Inspection

`FFmpegToolchain.probe` invokes `ffprobe` directly with an argument array and parses a size-capped JSON response. `MediaPipeline.inspect` records container, duration, bit rate, source size, video codec/dimensions/FPS/pixel format, audio codec/sample rate/channels/layout, bounded tags, and exact FFmpeg version. Optional full-decode validation maps all streams to FFmpeg's null muxer.

## Derivatives

Video thumbnails and audio waveform PNGs, MP4/WebM video transcodes, WAV/FLAC/MP3/OGG audio transcodes, and bounded clips are staged under the workspace temporary directory and imported into SHA-256 storage only after successful completion. Raw source paths are opened read-only and never selected as output destinations. Catalog rows deduplicate the same source/kind/canonical-parameter combination.

## Execution safety

The adapter does not invoke a shell. File paths occupy individual arguments, formats/codecs/colors are allowlisted, dimensions and time ranges are bounded, stdout metadata is capped, stderr persisted to job errors is truncated, metadata is stripped from outputs, and subprocess timeouts are finite. Media processors declare high CPU/disk hints so the adaptive scheduler can apply backpressure. Missing `ffmpeg` or `ffprobe` creates an isolated retryable job-item failure rather than corrupting the source or blocking unrelated work.
