#!/usr/bin/env python3
"""Start the local API and web app, exercise critical release flows, then stop cleanly."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SmokeFailure(RuntimeError):
    pass


def request(
    url: str, *, method: str = "GET", payload: dict[str, object] | None = None
) -> dict[str, object] | str:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers=headers, method=method), timeout=5
    ) as response:
        content = response.read()
        if response.status >= 400:
            raise SmokeFailure(f"Request failed with HTTP {response.status}: {url}")
        if "application/json" in response.headers.get("Content-Type", ""):
            return json.loads(content)
        return content.decode(errors="replace")


def wait_for(url: str, process: subprocess.Popen[bytes], seconds: int = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(f"Process exited before becoming ready: {url}")
        try:
            request(url)
            return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise SmokeFailure(f"Timed out waiting for {url}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            shell=False,
        )
    else:
        os.kill(-process.pid, 15)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def run_smoke(*, api_only: bool = False, skip_build: bool = False) -> dict[str, object]:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not api_only and not npm:
        raise SmokeFailure("npm is unavailable")
    with tempfile.TemporaryDirectory(dir=ROOT.parent) as directory:
        environment = dict(os.environ)
        package_sources = [
            str(ROOT / "packages" / "core" / "src"),
            str(ROOT / "packages" / "plugin-sdk" / "src"),
        ]
        existing_pythonpath = environment.get("PYTHONPATH")
        if existing_pythonpath:
            package_sources.append(existing_pythonpath)
        environment["PYTHONPATH"] = os.pathsep.join(package_sources)
        environment["NEXT_PUBLIC_CORE_API_URL"] = "http://127.0.0.1:8765/api/v1"
        environment["MEDIASENSEI_API_PORT"] = "8765"
        environment["MEDIASENSEI_WEB_PORT"] = "3765"
        environment["MEDIASENSEI_SMOKE_WEB_URL"] = "http://127.0.0.1:3765"
        environment["MEDIASENSEI_WORKSPACE"] = str(Path(directory) / "workspace")
        import io
        import zipfile

        from PIL import Image
        fixture_dir = Path(directory) / "fixtures"
        fixture_dir.mkdir()
        image = io.BytesIO()
        Image.new("RGB", (64, 48), "green").save(image, format="PNG")
        (fixture_dir / "photo.png").write_bytes(image.getvalue())
        (fixture_dir / "table.csv").write_text("species,count\nfox,2\nowl,3\n")
        with zipfile.ZipFile(fixture_dir / "nested.zip", "w") as bundle:
            bundle.writestr("nested/zip notes.txt", "Foxes explore woodland habitats.")
        environment["MEDIASENSEI_SMOKE_FIXTURES"] = str(fixture_dir)
        log_dir = Path(directory) / "logs"
        log_dir.mkdir()
        api_log = (log_dir / "api.log").open("wb")
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
            ],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if os.name == "nt"
            else 0,
        )
        worker_log = (log_dir / "worker.log").open("wb")
        worker = subprocess.Popen([sys.executable, "-m", "mediasensei.cli", "worker", "run"], cwd=ROOT, env=environment, stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        web: subprocess.Popen[bytes] | None = None
        web_log = None
        try:
            try:
                wait_for("http://127.0.0.1:8765/api/v1/plugins", api)
            except SmokeFailure as error:
                api_log.flush()
                log_tail = (log_dir / "api.log").read_text(errors="replace")[-8000:]
                raise SmokeFailure(f"{error}\nAPI log:\n{log_tail}") from error
            inventory = request("http://127.0.0.1:8765/api/v1/plugins")
            assert isinstance(inventory, dict)
            reloaded = request("http://127.0.0.1:8765/api/v1/plugins/rescan", method="POST")
            assert isinstance(reloaded, dict)
            if int(str(reloaded["generation"])) <= int(str(inventory["generation"])):
                raise SmokeFailure("Plugin runtime generation did not advance")
            project = request(
                "http://127.0.0.1:8765/api/v1/projects",
                method="POST",
                payload={"name": "Release smoke", "data_policy": "local_only"},
            )
            if not isinstance(project, dict) or not project.get("id"):
                raise SmokeFailure("Project creation smoke check failed")
            if not api_only:
                if not skip_build:
                    build = subprocess.run(
                        [str(npm), "run", "build"],
                        cwd=ROOT,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        shell=False,
                    )
                    if build.returncode != 0:
                        raise SmokeFailure(
                            "Frontend build failed before smoke start:\n"
                            + build.stdout.decode(errors="replace")[-8000:]
                        )
                web_log = (log_dir / "web.log").open("wb")
                web = subprocess.Popen(
                    [str(npm), "run", "start", "--", "--ip", "127.0.0.1", "--port", "3765"],
                    cwd=ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=web_log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                    if os.name == "nt"
                    else 0,
                )
                try:
                    wait_for("http://127.0.0.1:3765/", web, 90)
                except SmokeFailure as error:
                    raise SmokeFailure(str(error) + "\n" + (log_dir / "web.log").read_text(errors="replace")[-8000:]) from error
                subprocess.run([shutil.which("node") or "node", "scripts/browser-smoke.mjs"], cwd=ROOT, env=environment, check=True)
                if worker.poll() is not None:
                    raise SmokeFailure("Worker exited during integration tests")
            return {
                "ok": True,
                "api": True,
                "web": not api_only,
                "plugin_generation": reloaded["generation"],
            }
        finally:
            if web is not None:
                stop_process(web)
            stop_process(worker)
            worker_log.close()
            stop_process(api)
            api_log.close()
            if web_log is not None:
                web_log.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--skip-build", action="store_true", help="Reuse a build already configured for the smoke API on port 8765")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_smoke(api_only=args.api_only, skip_build=args.skip_build), indent=2))
        return 0
    except (OSError, SmokeFailure, subprocess.SubprocessError) as error:
        print(f"E2E smoke failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
