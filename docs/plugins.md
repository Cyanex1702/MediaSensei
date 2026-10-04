# Plugin development

MediaSensei Plugin API 1.5 uses the `mediasensei.plugins` entry-point group. Each entry point exposes one `PluginRegistration`; declared capabilities must exactly match supplied implementations.

```toml
[project.entry-points."mediasensei.plugins"]
my_plugin = "my_package.plugin:PLUGIN"
```

Generate either finalized template:

```bash
mediasensei plugin create my-analyzer --capability analyzer
mediasensei plugin create my-search --capability discovery-provider
```

## Trust and isolated analyzers

Local analyzer execution is deny-by-default. Validation reports the exact SHA-256 source fingerprint, and trust records bind name, version, permissions, and fingerprint. Any byte change invalidates that approval.

```bash
mediasensei plugin validate ./my_plugin/plugin.py
mediasensei plugin trust ./my_plugin/plugin.py
mediasensei plugin trusted
mediasensei plugin analyze ./my_plugin/plugin.py sha256:OBJECT --parameters '{"mode":"fast"}'
mediasensei plugin revoke my-plugin
```

Trusted analyzers run in a child Python process with a scrubbed environment, 64 KiB request cap, 1 MiB response cap, and a configurable timeout bounded to five minutes. Third-party exception text and tracebacks are not returned. Trust approval validates and imports the entry point, so review source before approving; native sandbox availability depends on the host, while release archives support detached signature verification.

## Runtime reliability

Discovery pages are capped at 500 unique candidates. URLs, lengths, dimensions, budgets, elapsed time, score maps, and metadata are validated for shape, finite values, and bounded serialized size. Registrations are capped at 64 implementations per capability. Plugin loading still isolates broken neighbors and exposes safe diagnostics.

Runtime refresh is explicit: `GET /api/v1/plugins` returns `generation`, `loaded_at`, and `reload_policy`; `POST /api/v1/plugins/rescan` validates a replacement snapshot and advances the generation. There is no file watcher and no silent hot swap.

See `plugins/official/example_metadata_analyzer`, the [Plugin Runtime architecture](architecture/plugin-runtime.md), and the [hardening decision](adr/014-harden-plugin-execution.md).