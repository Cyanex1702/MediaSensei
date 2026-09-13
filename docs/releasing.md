# Releasing MediaSensei

Published releases should be produced from a clean matching tag. This local candidate is a file-tree snapshot without a Git checkout or tag. The version must match `pyproject.toml`, `package.json`, `package-lock.json`, and the Python package version.

## Local verification

```bash
npm run release:check
python scripts/e2e_smoke.py
python scripts/release.py bundle --platform all
python scripts/release.py verify release/MediaSensei-2.0.0-rc.1-windows.zip
python scripts/release.py build-python
python scripts/release.py checksums
```

The smoke script builds the frontend before starting the production web command, so it does not rely on excluded/stale `dist/` output. The release archive includes the `tests/` directory.

Every platform archive contains one product root and an embedded `RELEASE-MANIFEST.json` with file sizes and SHA-256 digests. Archive paths are traversal-checked. Timestamps, ownership, permissions, ordering, and gzip metadata are normalized from `SOURCE_DATE_EPOCH` or the current commit time.

## CI release

Pushes and pull requests run verification on Windows, Linux, and macOS. It builds and verifies the platform archive but does not upload or publish it. Release publication remains a separate owner action.

For signed distribution, keep the private key outside the repository and run `python scripts/release.py sign ARTIFACT --private-key KEY`. Recipients use `verify-signature` with the corresponding public key. The signature is real cryptographic evidence from that key; MediaSensei does not claim an organization identity unless the release owner controls and publishes that key.

Desktop archives are portable source distributions with one-click launchers. They intentionally do not embed Python, Node.js, FFmpeg, credentials, or private data. Python 3.12+ and Node.js 22.13+ are the only setup prerequisites; FFmpeg remains optional for media operations.

## Current local candidate

See batch-4.md for executed results and platform limits. Native macOS/Linux validation, authenticated provider qualification and signing are owner follow-ups. The current archive was built from a file-tree snapshot, not a clean Git commit. Do not infer a commit identity or signature from its checksum.

Run `python scripts/verify-persistence.py` for API/worker restart acceptance. To verify a wheel, create a clean venv, install `mediasensei-2.0.0rc1-py3-none-any.whl[data,image]` with requirements-lock.txt, then use that venv's Python with `-I` to run the absolute path to scripts/verify-installed-core.py from outside the checkout. The Python wheel supplies the core and plugin SDK; use the platform source archive for the desktop UI and API.

Before upgrading, stop MediaSensei and back up the entire private workspace, including SQLite state and immutable objects. The new integration tables are additive. Keep a pre-upgrade backup if reverting; do not erase new provenance to simulate a downgrade. Native keyring credentials are separate from the workspace backup and are scoped to its absolute path.

For deterministic rebuild comparison, set SOURCE_DATE_EPOCH to the same value, build into two output directories, and compare each artifact's SHA-256. Release verification allows at most 20,000 paths, 64 MiB per file and 512 MiB total uncompressed data. It never extracts an unverified archive.
