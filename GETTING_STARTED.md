# MediaSensei rc.2: getting started

Extract the ZIP into a permanent folder, then double-click **MediaSensei-Windows.bat**.

On first launch it checks Python and Node.js, uses Windows App Installer (winget) to install missing prerequisites, attempts FFmpeg and Tesseract setup, creates a private Python environment, installs pinned application dependencies, builds the frontend and opens the browser. First setup needs internet, at least 5 GiB free disk space, and may show installer/UAC prompts. Processing pauses below 2 GiB free; the app displays an explanation. Keep the folder writable. Subsequent launches reuse installed requirements and an unchanged successful build.

If Windows App Installer is unavailable, install Python 3.13 and Node.js 22.13 or newer, then run the BAT again. Optional native-tool installation failures are displayed; table/data workflows still work. Delete `.mediasensei-media-setup` to retry optional installation on the next launch. Logs are in `.mediasensei-launcher/logs`. Stop services with **Stop-MediaSensei-Windows.bat**.

## Task: prepare a dataset

1. Create a project in Overview. Import a CSV, TSV, Excel, SQLite, DuckDB, JSON/JSONL or Parquet file. Database/workbook imports ask which table/sheet to use.
2. For semicolon/tab/pipe-delimited input, enable **Choose CSV/TSV delimiter and preserve text identifiers before upload**. Keep columns as text when identifiers such as 00123 must retain leading zeros. UTF-8 input with a named, unique header is required for CSV/TSV. Malformed records fail with line information; examine Jobs.
3. Wait for inspection in Jobs. In Data Lab, choose **Create from import** to create a working dataset. Originals remain unchanged.
4. Inspect missingness and types, preview transformations, then run them. Use explicit type conversions on text columns when numerical analysis is needed. Create a split before fitted preprocessing to avoid leakage.
5. In Quality, choose the working dataset. Add required/unique/numeric/minimum/maximum/allowed-category rules. Save column meanings/units in the dictionary. **Save and run checks** evaluates the current revision; download its report. Up to 100 offending rows are included, with total failure counts. Rerun after transformations; checks do not automatically block workflows.
6. Save a version before important changes. Exports provides tables and replay/notebook bundles. The project manifest in System inventories source assets and table versions; it does not contain dataset bytes or replace a backup.

Table inspection and transformations are bounded to 200,000 rows, 256 MiB source files and a 1 GiB decoded working-data allowance. Split/query larger sources outside this bounded workbench before importing. These are limits, not arbitrary-scale support.

## Task: gather images

In Sources, request an image collection, preview the plan, and inspect the enforced filters. `CC0 only`, `CC-BY only` and `CC-BY-SA only` map to license families; a version in the explicit allowed-label field restricts the version too. CC-BY does not permit CC-BY-NC or CC-BY-SA. Other licensing instructions and exclusions are rejected rather than silently ignored: use explicit plan fields where supported and review candidates manually.

Sources discovery is image-only. Use Connections for the existing provider dataset-import workflow; CSV/document/audio/video requests are not converted into image searches. Default relevance uses candidate title/description, never the search query, and does not examine visual semantics. Manual review remains useful. Direct URLs may lack license metadata and therefore fail a configured license filter.

Remote collection requires project permission AND explicit run authorization. A failed provider, exhausted budget or insufficient yield produces an explicit shortfall. Provider discovery may return network errors or rate limits depending on environment and account access. HTTPS uses OS trust verification; certificate validation is not disabled.

## Task: reuse and recover work

In Library, set the filename/hash search and modality, give the collection a name, and save the filters. Collections persist and match newly imported assets.

Double-click **Backup-MediaSensei.bat** to stop this launcher's services and write a portable backup into `backups/`. It snapshots committed SQLite WAL state and records SHA-256 checksums. Credentials remain in the OS key store and are excluded. Do not run independent API/worker processes during backup.

Double-click **Restore-MediaSensei.bat** to choose a backup and parent folder. It verifies checksums, restores into a NEW timestamped directory, stops the launcher's services and switches `.env` to that restored workspace. Existing workspaces are preserved. Start the app again and re-save provider credentials for the new location. The backup ZIP contains your data; keep it private.

Storage inspection in System reports object usage and disk space. Automatic deletion/garbage collection is intentionally not provided yet: files can be shared by originals, versions, exports and caches. Do not delete content-addressed objects manually.
