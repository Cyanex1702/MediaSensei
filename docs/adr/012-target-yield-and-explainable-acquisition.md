# ADR 012: Target accepted yield with explainable decisions

## Status

Accepted for Milestone 8.

## Context

Discovery result counts do not predict usable dataset size because corruption, resolution, duplicates, quality, relevance, and policy remove candidates. A fixed download count therefore under-delivers unpredictably and obscures why.

## Decision

Define the image target as accepted assets. Persist discovered, downloaded, evaluated, accepted, rejected, review, failed, bytes, requests, cycles, observed yield, and next-batch estimates. Replenish in adaptive bounded batches until the target or an explicit safety/provider boundary. Every acceptance, rejection, review, and terminal download failure records a stable reason, evaluator identity/version, and scores. Below-target terminal runs use `completed_with_shortfall` and a stop reason.

## Consequences

Runs are measurable, resumable, and auditable. No-AI metadata evaluation and human review remain fully useful. Learned relevance adapters can be added later without weakening deterministic validation, provenance, or stopping rules.