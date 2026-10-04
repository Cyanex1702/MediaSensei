# Plugin Runtime architecture

MediaSensei 0.10 keeps Plugin API 1.5 stable while hardening the host boundary. Plugins enter through the `mediasensei.plugins` entry-point group and expose one validated `PluginRegistration`.

## Compatibility and hostile-record gate

The loader validates slugs, versions, API compatibility, declared capabilities, permissions, structural protocols, unique identities, and a maximum of 64 implementations per capability. SDK records reject non-web or credential-bearing URLs, duplicate/oversized discovery pages, negative dimensions or byte counts, non-finite budgets and scores, invalid decisions, long text, and metadata or score maps above 64 KiB.

Each installed entry point still loads independently. Invalid manifests and duplicate names are rejected, unexpected failures become safe diagnostic codes, and healthy neighbors remain available.

## Trust boundary

Local executable plugins are deny-by-default. `PluginTrustStore` persists an allow-list under the MediaSensei workspace, atomically binding plugin name and version to an exact SHA-256 source fingerprint and its declared permissions. Changing any byte makes the file untrusted until explicitly approved again. Trust is local to a workspace and can be listed or revoked without editing the plugin.

Trust approval imports the file to validate its registration. Authors and operators must review source before approval. Package signing and native operating-system sandbox profiles belong to the release milestone.

## Subprocess analyzer host

`PluginSubprocessExecutor` revalidates the fingerprint and starts a dedicated Python process without a shell. Only basic OS path/temp variables are retained; application tokens and credentials are omitted. The JSON request is limited to 64 KiB, the response to 1 MiB, and execution defaults to 15 seconds with a hard five-minute configuration ceiling. The child checks the fingerprint again before import. Timeouts, malformed results, oversized output, and third-party exceptions become stable safe errors.

## Explicit reloads

`PluginRuntimeManager` publishes immutable runtime snapshots. Reads never trigger discovery. An explicit reload builds and validates a replacement runtime, then atomically swaps it under a lock and advances its generation. The API surfaces both inventory and `POST /api/v1/plugins/rescan` so clients can display exactly when extensions changed.

## Author workflow

`mediasensei plugin create --capability analyzer` and `--capability discovery-provider` produce installable `src/` packages, entry-point declarations, API 1.5 registrations, compatibility tests, and READMEs. The SDK includes `py.typed` for downstream type checking.