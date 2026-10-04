# Image pipeline

The image vertical slice keeps source objects immutable and keys deterministic work by source SHA-256, processor id/version, parameters, and model revision.

```text
immutable object
  → Pillow verify/load + EXIF transpose
  → metadata + blur score + 64-bit DCT pHash
  → content-addressed thumbnail
  → optional Tesseract OCR adapter
  → content-addressed resize/convert derivative
  → duplicate groups
  → deterministic dataset split
  → cross-split exact/pHash leakage findings
  → processed media + metadata.parquet + manifest.json + dataset_card.md
```

## Safety and persistence

- Raw objects are opened read-only and never overwritten.
- Derivatives are written to a temporary file, SHA-256 verified, and atomically imported into the object store.
- Analysis is keyed by source hash so physically identical assets reuse one content-level result.
- OCR text and regions are stored separately. Detect, filter, quarantine, and store-text actions are explicit; OCR never deletes a source image.
- Random, stratified, group-aware, source-aware, and manual split strategies store their seed and assignments.
- Exact and perceptual cross-split matches are persisted as explainable issues.
- Exports are staged in a sibling temporary directory, then atomically renamed only after media, Parquet metadata, manifest, and dataset card succeed.

## Processor ids

- `image.inspect@1.0.0`: validation, normalized metadata, pHash, blur score, and thumbnail.
- `image.transform@1.0.0`: contain, cover/crop, pad, or stretch plus JPEG/PNG/WebP conversion.
- `image.ocr@1.0.0`: non-cacheable provider execution with isolated item failures and retry support.

The default OCR adapter invokes Tesseract without a shell and records provider/version metadata. Third-party providers implement the public `OCRProvider` protocol.
