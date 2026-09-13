# Models, connections, Playground and voices

## Model Hub

Import documents and let their indexing jobs finish. In Model Hub select documents, name a model, and choose fitted TF-IDF retrieval or a supervised language classifier. For classification, provide labels such as `en` and `fr` for documents in at least two languages. Click Train locally, wait for Jobs, then Refresh integrations.

Select a revision to verify its checksum, download its JSON, archive it or reactivate it. Importing the same JSON preserves the revision. A retrieval model must index the selected documents before querying. The adapter fits lexical vocabulary and IDF weights; it is not a neural semantic embedding. Language classification uses multinomial Naive Bayes; its scores are not calibrated confidence. Unrecognized text returns `und`.

The workspace owns model revisions; training sources are restricted to the chosen project. Model exports include source hashes and vocabulary, which can reveal training terms. Treat them as part of the dataset. RAG exports include the exact fitted models used by their indexes. Archival prevents new indexing/training inference while retaining prior provenance.

## Connections

Save a Hugging Face token in Connections. It is stored in Windows Credential Manager, macOS Keychain or an available supported Linux native keyring. A locked, missing or unsupported backend fails closed. SQLite stores only the name, provider and connection ID. Connection IDs are scoped to the workspace path in the OS store; after moving a workspace, save its credentials again.

Install the optional provider package with `python -m pip install -e ".[providers]" -c requirements-lock.txt`. Enable the project's external-access policy through Sources, select a saved connection and dataset, and explicitly authorize each import. Access and revocation are checked when the worker starts and before each file download. Revocation stops subsequent downloads; an already in-flight request cannot be recalled. The provider resolves the requested revision to its immutable commit. No provider runs merely because a connection is saved.

Revoke a connection to disable it and remove its OS credential. If the OS store is locked during removal, the connection remains disabled and the error tells you removal failed. Unlock the store and retry. Never put tokens in script literals, project names or model metadata.

## Playground

Adopt an imported table in Data Lab. Select it in Playground and enter calls such as:

```python
data = fill_missing(data, columns=["income"], strategy="mean")
data = drop_duplicates(data, columns=["email"])
```

Use Function Explorer for installed parameter names. Validate and save stores the exact source hash and compiled plan. Run script queues the shared workflow engine against the selected dataset revision; inspect outputs in Data Lab and Jobs. Scripts support only assignments to `data`, registered table operations, and literal keyword values. General Python, imports, loops, file access and network access are unavailable. A saved script is inert until explicitly run.

## Voices and transcription

On Windows, select an installed System.Speech voice, name a personality and save its speaking rate. Select a document of at most 5,000 characters and Generate speech. After Jobs completes, Refresh integrations to play the WAV and download its provenance. This adapter does not clone voices. Other operating systems report this Windows adapter unavailable.

For local ASR, obtain a trusted [whisper.cpp build](https://github.com/ggml-org/whisper.cpp/releases) and compatible [GGML model](https://github.com/ggml-org/whisper.cpp/tree/master/models). Set `MEDIASENSEI_WHISPER_CPP` to the `whisper-cli` executable and `MEDIASENSEI_WHISPER_MODEL` to its model file before starting both API and worker. Keep the build's companion libraries together. Configure FFmpeg and ffprobe as described in the media guide. The application never downloads these files automatically.

The UI transcribes the first 60 seconds on two CPU threads; the typed API accepts a duration up to 600 seconds. Model and executable SHA-256 values are pinned at queue time and checked again before and after execution. A changed revision fails the job. Outputs retain tool/model provenance. Recognition accuracy depends on the chosen model and recording; the release test covers a short English synthetic speech sample only.
