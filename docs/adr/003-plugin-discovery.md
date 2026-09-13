# ADR-003: Packaging entry points for plugins

Status: Accepted

Third-party plugins are discovered from the `mediasensei.plugins` Python entry-point group. Contracts live in a separately versioned Plugin SDK. Manifests declare API compatibility, capabilities, permissions, and license. Domain entities do not import plugins. Contracts are serializable enough to support future subprocess isolation.
