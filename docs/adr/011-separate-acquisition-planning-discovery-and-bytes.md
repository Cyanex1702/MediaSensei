# ADR 011: Separate acquisition planning, discovery, and byte transfer

## Status

Accepted for Milestone 8.

## Context

A prompt is ambiguous, search results are not trusted assets, and remote byte transfer changes the project’s security and cost posture. Combining those operations would hide provider choices, prevent review, and make network permission too broad.

## Decision

Compile prompts or manual input into a validated, persisted `AcquisitionSpec` and inspectable plan without network access. Discovery is a metadata-only provider contract. Starting a run is a separate operation requiring explicit remote authorization and a project policy that permits external data. The downloader independently enforces redirect, public-address, MIME, and byte constraints before candidates can enter validation and immutable storage.

## Consequences

Users can inspect and test plans before granting network access. Provider adapters cannot silently bypass the download safety boundary. The extra lifecycle records are intentional audit evidence and provide stable restart checkpoints.