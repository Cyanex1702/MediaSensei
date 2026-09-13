#!/usr/bin/env python3
"""MediaSensei one-click dependency manager and local app launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".mediasensei-launcher"
VENV = ROOT / ".venv"
STAMP = STATE_DIR / "dependencies.json"
PIDS = STATE_DIR / "processes.json"
LOG_DIR = STATE_DIR / "logs"
STARTUP_STATUS = STATE_DIR / "startup-status.json"
MIN_PYTHON = (3, 12)
MIN_NODE = (22, 13, 0)
PYTHON_EXTRAS = "image,data"


class LauncherError(RuntimeError):
    pass


def report(message: str) -> None:
    """Keep launcher messages available even when a Windows terminal closes."""
    print(message, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "launcher.log").open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}\n")


def parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in value.strip().lstrip("vV").split("."):
        digits = "".join(character for character in token if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def dependency_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative in ("pyproject.toml", "requirements-lock.txt", "package-lock.json"):
        path = ROOT / relative
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    digest.update(f"python>={MIN_PYTHON};node>={MIN_NODE};extras={PYTHON_EXTRAS}".encode())
    return digest.hexdigest()


def run(command: Sequence[str], *, dry_run: bool = False) -> None:
    report("  > " + " ".join(command))
    if not dry_run:
        subprocess.run(list(command), cwd=ROOT, check=True, shell=False)


def prerequisites() -> tuple[str, str]:
    if sys.version_info < MIN_PYTHON:
        raise LauncherError(
            "Python 3.12 or newer is required. Download it from python.org/downloads."
        )
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise LauncherError(
            "Node.js 22.13 or newer is required. Download the LTS release from nodejs.org."
        )
    result = subprocess.run([node, "--version"], text=True, capture_output=True, check=True)
    if parse_version(result.stdout) < MIN_NODE:
        raise LauncherError("Node.js 22.13 or newer is required. Update it from nodejs.org.")
    return node, npm


def sync_dependencies(*, force: bool = False, dry_run: bool = False) -> None:
    _, npm = prerequisites()
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
    fingerprint = dependency_fingerprint()
    previous = {}
    if STAMP.exists():
        try:
            previous = json.loads(STAMP.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    venv_python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    created_venv = not venv_python.exists()
    if force or created_venv:
        report("Preparing MediaSensei's private Python environment...")
        run([sys.executable, "-m", "venv", str(VENV)], dry_run=dry_run)
    if force or previous.get("fingerprint") != fingerprint or not (ROOT / "node_modules" / ".bin" / "vinext").exists() or created_venv:
        report("Installing or updating MediaSensei requirements...")
        run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run)
        run(
            [str(venv_python), "-m", "pip", "install", "-e", f".[{PYTHON_EXTRAS}]", "-c", "requirements-lock.txt"], dry_run=dry_run
        )
        run([npm, "ci"], dry_run=dry_run)
        if not dry_run:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            STAMP.write_text(
                json.dumps({"fingerprint": fingerprint}, indent=2) + "\n", encoding="utf-8"
            )
    else:
        report("Requirements are already up to date.")


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) TERMINATES processes on Windows; use a query handle.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _identity(pid: int) -> str:
    """Bind stored PIDs to creation times so stale state cannot stop unrelated apps."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            created, ended, system, user = (wintypes.FILETIME() for _ in range(4))
            if kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(system), ctypes.byref(user)):
                return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
            return ""
        finally:
            kernel.CloseHandle(handle)
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def process_status() -> dict[str, int]:
    if not PIDS.exists():
        return {}
    try:
        values = json.loads(PIDS.read_text(encoding="utf-8"))
        return {str(name): int(item["pid"]) for name, item in values.items()
                if isinstance(item, dict) and _alive(int(item["pid"]))
                and item.get("identity") and item["identity"] == _identity(int(item["pid"]))}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {}


def _spawn(name: str, command: Sequence[str]) -> subprocess.Popen[bytes]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = (LOG_DIR / f"{name}.log").open("ab")
    log.write(f"\n--- {datetime.now(UTC).isoformat(timespec='seconds')} Starting {name} ---\n".encode())
    log.flush()
    try:
        if os.name == "nt":
            # DETACHED_PROCESS suppresses npm.cmd output on Windows.
            # CREATE_NO_WINDOW keeps the service hidden and preserves log handles.
            return subprocess.Popen(
                list(command),
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ),
            )
        return subprocess.Popen(
            list(command),
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=True,
        )
    finally:
        log.close()


def start(*, dry_run: bool = False, open_browser: bool = True, development: bool = False) -> None:
    sync_dependencies(dry_run=dry_run)
    running = process_status()
    if running:
        report("MediaSensei is already running.")
    if dry_run:
        report("Would start the API, worker, and web app at http://localhost:3000/")
        return
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    assert npm
    # Use the same .env for API, worker, web configuration and health URLs.
    from_env = subprocess.check_output([str(python), "-c", "import json; from dotenv import dotenv_values; print(json.dumps(dotenv_values('.env')))"], cwd=ROOT, text=True)
    for key, value in json.loads(from_env).items():
        if value is not None:
            os.environ.setdefault(key, value)
    api_port = os.environ.get("MEDIASENSEI_API_PORT", "8000")
    web_port = os.environ.get("MEDIASENSEI_WEB_PORT", "3000")
    os.environ.setdefault("NEXT_PUBLIC_CORE_API_URL", f"http://127.0.0.1:{api_port}/api/v1")
    try:
        startup_timeout = int(os.environ.get("MEDIASENSEI_STARTUP_TIMEOUT_SECONDS", "180"))
        if not 10 <= startup_timeout <= 1800:
            raise ValueError
    except ValueError as error:
        raise LauncherError("MEDIASENSEI_STARTUP_TIMEOUT_SECONDS must be an integer from 10 to 1800.") from error
    processes = dict(running)
    if not development and "web" not in processes:
        run([npm, "run", "build"])

    commands = {
        "api": [
            str(python),
            "-m",
            "uvicorn",
            "apps.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            api_port,
        ],
        "worker": [str(python), "-m", "mediasensei.cli", "worker", "run"],
        "web": [npm, "run", "dev"] if development else [npm, "run", "start", "--", "--ip", "127.0.0.1", "--port", web_port],
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for name, command in commands.items():
            if name not in processes:
                processes[name] = _spawn(name, command).pid
            records = {name: {"pid": pid, "identity": _identity(pid)} for name, pid in processes.items()}
            PIDS.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    except OSError:
        stop()
        raise
    report(f"Starting MediaSensei at http://127.0.0.1:{web_port}/ ...")
    report(f"Service logs: {LOG_DIR}")
    if _wait_for_services(processes, startup_timeout):
        report("MediaSensei is ready: web + API + worker are running.")
        if open_browser:
            try:
                opened = webbrowser.open(f"http://127.0.0.1:{web_port}/")
            except webbrowser.Error:
                opened = False
            if not opened:
                report(f"Could not open the browser automatically. Open http://127.0.0.1:{web_port}/ manually; services are running.")
    else:
        stop()
        raise LauncherError(f"Startup failed. The service status above is saved in {STARTUP_STATUS}; details are in {LOG_DIR}.")


def _probe_url(url: str) -> tuple[bool, str]:
    try:
        # These are loopback services; a system HTTP proxy must not intercept them.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            return response.status == 200, f"HTTP {response.status}"
    except OSError as error:
        return False, str(error)


def _url_ready(url: str) -> bool:
    return _probe_url(url)[0]


def _wait_for_services(processes: dict[str, int], seconds: int) -> bool:
    started = time.monotonic()
    deadline = started + seconds
    last_report = started - 15
    urls = {
        "api": f"http://127.0.0.1:{os.environ.get('MEDIASENSEI_API_PORT', '8000')}/health",
        "web": f"http://127.0.0.1:{os.environ.get('MEDIASENSEI_WEB_PORT', '3000')}/",
    }
    while True:
        statuses = {}
        exited = False
        for name, pid in processes.items():
            alive = _alive(pid)
            ready, detail = (True, "running") if alive else (False, "process exited")
            if alive and name in urls:
                ready, detail = _probe_url(urls[name])
            statuses[name] = {"pid": pid, "alive": alive, "ready": ready, "detail": detail}
            exited |= not alive
        ready = all(item["ready"] for item in statuses.values())
        now = time.monotonic()
        finished = ready or exited or now >= deadline
        if finished or now - last_report >= 15:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            STARTUP_STATUS.write_text(json.dumps({
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "elapsed_seconds": round(now - started, 1),
                "timeout_seconds": seconds,
                "ready": ready,
                "services": statuses,
            }, indent=2) + "\n", encoding="utf-8")
            report("Startup: " + "; ".join(f"{name}: {item['detail']}" for name, item in statuses.items()))
            last_report = now
        if finished:
            return ready
        time.sleep(0.5)


def stop() -> None:
    values = process_status()
    if not values:
        report("MediaSensei is not running.")
        return
    for name, pid in values.items():
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    shell=False,
                )
            else:
                os.kill(-pid, 15)
            report(f"Stopped {name}.")
        except OSError:
            pass
    PIDS.unlink(missing_ok=True)


def status() -> None:
    values = process_status()
    if values:
        report(
            "MediaSensei is running: "
            + ", ".join(f"{name} ({pid})" for name, pid in values.items())
        )
    else:
        report("MediaSensei is not running.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install, update, and open MediaSensei without command-line setup."
    )
    parser.add_argument(
        "action", choices=("start", "dev", "setup", "update", "stop", "status"), nargs="?", default="start"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action in {"start", "dev"}:
            start(dry_run=args.dry_run, open_browser=not args.no_browser, development=args.action == "dev")
        elif args.action == "setup":
            sync_dependencies(dry_run=args.dry_run)
        elif args.action == "update":
            sync_dependencies(force=True, dry_run=args.dry_run)
            report("MediaSensei requirements are up to date.")
        elif args.action == "stop":
            stop()
        else:
            status()
        return 0
    except (LauncherError, subprocess.CalledProcessError, OSError) as error:
        report(f"\nMediaSensei setup could not finish: {error}")
        report("You can close this window after reading the message above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
