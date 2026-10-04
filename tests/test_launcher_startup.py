from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from scripts import mediasensei_launcher as launcher


@pytest.fixture
def isolated_launcher(tmp_path, monkeypatch):
    root = tmp_path / 'folder with spaces'
    root.mkdir()
    state = root / '.mediasensei-launcher'
    monkeypatch.setattr(launcher, 'ROOT', root)
    monkeypatch.setattr(launcher, 'STATE_DIR', state)
    monkeypatch.setattr(launcher, 'LOG_DIR', state / 'logs')
    monkeypatch.setattr(launcher, 'STARTUP_STATUS', state / 'startup-status.json')
    return state


def test_slow_service_can_become_ready_after_old_timeout(isolated_launcher, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(launcher.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(launcher, '_alive', lambda pid: True)
    monkeypatch.setattr(launcher, '_probe_url', lambda url: (clock[0] >= 75, 'warming up' if clock[0] < 75 else 'HTTP 200'))
    assert launcher._wait_for_services({'api': 1, 'worker': 2, 'web': 3}, 180)
    status = json.loads((isolated_launcher / 'startup-status.json').read_text())
    assert status['elapsed_seconds'] == 75
    assert status['ready']


def test_exited_service_reports_immediately(isolated_launcher, monkeypatch):
    monkeypatch.setattr(launcher, '_alive', lambda pid: pid != 3)
    monkeypatch.setattr(launcher, '_probe_url', lambda url: (True, 'HTTP 200'))
    monkeypatch.setattr(launcher.time, 'sleep', lambda _: pytest.fail('Exited services must not wait'))
    assert not launcher._wait_for_services({'api': 1, 'worker': 2, 'web': 3}, 180)
    status = json.loads((isolated_launcher / 'startup-status.json').read_text())
    assert status['services']['web']['detail'] == 'process exited'
    assert 'web: process exited' in (isolated_launcher / 'logs/launcher.log').read_text()


def test_timeout_preserves_probe_error(isolated_launcher, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(launcher.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(launcher, '_alive', lambda pid: True)
    monkeypatch.setattr(launcher, '_probe_url', lambda url: (False, 'connection refused'))
    assert not launcher._wait_for_services({'api': 1, 'web': 3}, 10)
    status = json.loads((isolated_launcher / 'startup-status.json').read_text())
    assert status['elapsed_seconds'] == 10
    assert status['services']['web']['detail'] == 'connection refused'


@pytest.mark.skipif(os.name != 'nt' or not shutil.which('npm.cmd'), reason='Windows npm required')
def test_windows_batch_output_is_captured(isolated_launcher):
    child = launcher._spawn('web', [shutil.which('npm.cmd'), '--version'])
    try:
        assert child.wait(timeout=30) == 0
    finally:
        if child.poll() is None:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, check=False)
    lines = (isolated_launcher / 'logs/web.log').read_text().splitlines()
    assert any(line.strip() and line.strip()[0].isdigit() for line in lines)


def test_production_build_reused_until_source_or_api_origin_changes(isolated_launcher, monkeypatch):
    root = launcher.ROOT
    (root / 'app').mkdir()
    source = root / 'app/page.tsx'
    source.write_text('first')
    output = root / 'dist/server/wrangler.json'
    calls = []
    def build(command):
        calls.append(command)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{}')
    monkeypatch.setattr(launcher, 'run', build)
    launcher.ensure_web_build('npm')
    launcher.ensure_web_build('npm')
    assert len(calls) == 1
    source.write_text('second')
    launcher.ensure_web_build('npm')
    assert len(calls) == 2
    monkeypatch.setenv('NEXT_PUBLIC_CORE_API_URL', 'http://127.0.0.1:9999/api/v1')
    launcher.ensure_web_build('npm')
    assert len(calls) == 3
    output.unlink()
    launcher.ensure_web_build('npm')
    assert len(calls) == 4


def test_update_stops_services_before_install_and_keeps_existing_venv(isolated_launcher, monkeypatch):
    root = launcher.ROOT
    venv = root / '.venv'
    executable = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable.parent.mkdir(parents=True)
    executable.touch()
    (root / '.env').write_text('')
    monkeypatch.setattr(launcher, 'VENV', venv)
    monkeypatch.setattr(launcher, 'STAMP', isolated_launcher / 'dependencies.json')
    monkeypatch.setattr(launcher, 'prerequisites', lambda: ('node', 'npm'))
    monkeypatch.setattr(launcher, 'dependency_fingerprint', lambda: 'new')
    monkeypatch.setattr(launcher, 'process_status', lambda: {'web': 123})
    calls = []
    monkeypatch.setattr(launcher, 'stop', lambda: calls.append('stop'))
    monkeypatch.setattr(launcher, 'run', lambda command, **kwargs: calls.append(command))
    launcher.sync_dependencies(force=True)
    assert calls[0] == 'stop'
    assert not any(isinstance(call, list) and 'venv' in call for call in calls)
    assert calls[-1] == ['npm', 'ci']
