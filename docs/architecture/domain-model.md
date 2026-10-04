# Domain model

- **Workspace** owns projects, connections, plugins, models, storage, and credentials.
- **Project** is the policy and provenance boundary for a data-engineering effort.
- **Source** records origin, provider revision, license metadata, and import configuration.
- **ProviderImport** records a requested provider/dataset/revision, policy-safe selection limits, the resolved immutable snapshot, counters, and manifest hash. **ProviderImportFile** is its restart checkpoint and asset link.
- **Asset** is one immutable physical object addressed by SHA-256. It is not a training example.
- **ContentUnit** is an addressable region such as a page, paragraph, provenance-bearing document chunk, frame, scene, or audio segment.
- **Sample** assembles assets/content units with labels or targets into one ML example.
- **Feature** is computed information with provider, model revision, parameters, timestamp, and input hash. Document embeddings persist against ContentUnit identity with exact dimensions and model revision. Image analysis is content-keyed by SHA-256 so exact duplicates reuse metadata, pHash, blur, and OCR results.
- **Annotation** is extensible structured human or machine output.
- **Dataset** is a logical collection of samples; **DatasetVersion** is an immutable snapshot.
- **Pipeline** is a reusable graph; **PipelineRun** and **Job** persist execution and checkpoints.
- **Split** assigns samples deterministically using random, stratified, group-aware, source-aware, or manual rules and a stored seed.
- **Export** is a reproducible materialization with processed media, Parquet metadata, manifests, dataset cards, and checksums.

Lineage always points from derived output to source asset/content unit, processor and parameters, model revision where relevant, dataset version, and export.
