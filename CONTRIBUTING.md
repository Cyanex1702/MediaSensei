# Contributing to MediaSensei

Thanks for contributing to MediaSensei. This repository contains both the browser application and the local Python processing core, so changes should keep both sides in sync where applicable.

## Development setup

Prerequisites:

- Python 3.12+
- Node.js 22.13+ (Node 24 LTS recommended)
- npm

From the repository root:

```sh
cp .env.example .env
sh setup.sh
```

On Windows, use `setup.bat` instead. The setup process creates the private Python environment and installs the JavaScript dependencies.

## Run locally

```sh
sh start-dev.sh
```

On Windows, use `start-dev.bat`.

## Checks before opening a pull request

Run the same core checks used by CI:

```sh
npm run lint
npm test
.venv/bin/python -m ruff check apps packages scripts tests
npm run build
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

For browser coverage, install Chromium once and run the end-to-end suite:

```sh
npx playwright install chromium
npm run test:e2e
```

Native FFmpeg/Tesseract-dependent checks may be skipped when those tools are unavailable. Note any skipped platform/native-media coverage in the pull request.

## Pull requests

Keep pull requests focused and include:

- a short description of the change and why it is needed;
- tests for changed behavior when practical;
- any migration, environment, or compatibility notes;
- screenshots for visible UI changes;
- documentation updates for user-facing behavior.

Do not commit `.env`, local workspaces, virtual environments, generated build output, credentials, private keys, or user data. See `.gitignore` and `SECURITY.md` for repository and security guidance.
