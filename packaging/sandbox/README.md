# Native plugin sandbox profiles

MediaSensei's analyzer host always uses a scrubbed environment, exact source fingerprint, timeout, request cap, and response cap. Release builds can add native containment:

- **Linux:** use Bubblewrap with a read-only root, private temporary directory, and no network namespace.
- **macOS:** invoke `sandbox-exec -f packaging/sandbox/macos-plugin.sb` where that legacy host facility is available.
- **Windows:** the host uses a hidden detached process boundary; signed release provenance and Defender reputation are supplied by release CI. AppContainer packaging requires a future MSIX certificate and identity.

The release verifier treats this profile as product source and includes it in every bundle. Native wrappers are opportunistic because Bubblewrap and `sandbox-exec` availability varies by host.