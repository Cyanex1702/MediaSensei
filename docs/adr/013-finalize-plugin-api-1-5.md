# ADR 013: Finalize capability registrations in Plugin API 1.5

## Status

Accepted for the Plugin Integration and SDK Finalization milestone.

## Context

The original entry-point loader returned arbitrary objects, trusted plugin-declared API strings, and stopped on import errors. Acquisition contracts in 1.4 used `Any`, so third-party authors lacked stable request/result records and discovered providers were not connected to the runtime.

## Decision

A plugin entry point must expose a `PluginRegistration` whose validated manifest exactly matches its supplied structural implementations. Plugin API 1.5 publishes typed acquisition records, compatibility checks, stable capability identifiers, normalized permissions, isolated diagnostics, and a typed package marker. Entry points load independently and may not shadow duplicate plugin or provider identities. Valid discovery providers are adapted into the default acquisition registry. Other acquisition capability implementations are registered for explicit selection.

Openverse becomes the second built-in production discovery adapter, providing enough independent provider evidence to stabilize the discovery contract. License metadata remains provenance, not a legal guarantee.

## Consequences

Plugin authors get deterministic scaffolding, validation, typing, and diagnostics. A broken plugin cannot prevent healthy plugins or the application from starting, while incompatible packages fail closed. This milestone stabilizes the integration boundary; the next milestone focuses on hostile-input hardening, subprocess isolation, templates, and broader reliability testing.