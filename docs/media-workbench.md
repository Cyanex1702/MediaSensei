# Media tools and Batch 2

Run `start.bat` from the extracted release directory. Import files in Overview or directly in Image, Video, Audio and Knowledge Lab. Keep Forest selected for the original green and dark appearance; Spectrum, Charcoal and Beige remain available.

## Native tools

Video and Audio Lab require FFmpeg and ffprobe. MediaSensei checks PATH or explicit `MEDIASENSEI_FFMPEG` / `MEDIASENSEI_FFPROBE` entries in `.env`. Configure a local installation with:

```powershell
python scripts/configure-media-tools.py --ffmpeg-dir "D:\Tools\ffmpeg\bin"
```

Restart MediaSensei after configuration. Obtain Windows builds through [FFmpeg's official download page](https://ffmpeg.org/download.html). Filter behavior follows the [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html). Native executables are not redistributed in the source archive.

OCR uses Tesseract when installed; set a non-PATH executable with:

```powershell
python scripts/configure-media-tools.py --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Windows automatically uses its built-in OCR engine when Tesseract is absent. The requested Windows OCR language must be installed. Use `eng` or `en` for English. Missing languages/tools produce retryable job errors. Windows OCR does not provide numeric confidence, so results correctly use null confidence.

## Workflows

1. Select an asset in a lab, or select the explicit all-active-assets checkbox for batch execution.
2. Open Transforms, Process or Prepare. Edit parameters and preview or estimate before running.
3. Run the operation. Jobs shows durable progress and pause/cancel/retry controls.
4. Open Outputs for previews, playable audio/video, reports and checksummed bundles. Add an artifact to Library to use it as input to another operation or dataset export. Originals remain intact.
5. Image Dataset provides deterministic split assignment, leakage checks and immutable export snapshots. Knowledge Export produces a complete RAG bundle after all active documents have been indexed.

Knowledge chunk counts use Unicode words and punctuation, not model-specific tokens. Retrieval currently uses local lexical feature-hash embeddings. Source/page/heading locators and exact index settings are included in the RAG bundle. The model hub and learned adapters are Batch 3.

## Acquisition

Open Sources, describe the dataset and preview the plan. Edit the target, topic, queries, providers, quality/duplicate filters and budgets. Optional license labels use an exact case-insensitive match; domain filters match a host or its subdomains. Unknown licenses are rejected when a license allowlist is set.

Save edited plans before starting. Check the explicit remote consent box for Test N or Start. This enables approved external access for that project; it does not upload existing local assets. Candidate review shows local retained previews, source links, provider/query/license details and decision scores/reasons. Accepted/review/rejected tabs and run history persist. Pause, resume and cancel apply to the existing durable engine. Disable external access to return the project to local-only operation.
