# ADR 007 — Key image analysis by immutable content

Status: accepted

Image metadata, pHash, blur, OCR, and derivative recipes are functions of immutable bytes plus explicit processor parameters. They are therefore stored by source SHA-256 rather than by asset id. Multiple catalog assets that reference identical bytes reuse analysis and deterministic cache entries without losing project-level labels, state, split, or provenance.

Derivatives remain separate content-addressed objects. Dataset samples reference catalog assets, while analysis and derived objects reference content hashes. This avoids repeating expensive work and prevents cached results from accidentally binding to the first project asset that requested them.
