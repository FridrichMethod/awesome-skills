"""Bootstrap contract: piped install.sh and downloaded install.ps1 are both install and update."""

from __future__ import annotations

import functools
import http.server
import os
import shlex
import shutil
import subprocess
import sys
import threading

import pytest

from scripts import install_skills as installer
from tests.gitfixtures import ROOT, WINDOWS, Upstream, data_dir, isolate, without_pyyaml

PWSH = shutil.which("pwsh")
ALREADY = "Already current; selection preserved."
# CI sets this so the PowerShell bootstrap tests fail instead of skipping when pwsh is missing.
NEEDS_PWSH = pytest.mark.skipif(
    PWSH is None and os.environ.get("AWESOME_SKILLS_REQUIRE_PWSH") != "1", reason="PowerShell 7 (pwsh) unavailable"
)
# install.sh passes the whole installer as one `python -c` argument; Linux caps a single
# argument at 128 KiB (MAX_ARG_STRLEN), so keep a margin below it.
ARGUMENT_BUDGET = 120 * 1024


def pwsh():
    if PWSH is None:
        pytest.fail("pwsh is required (AWESOME_SKILLS_REQUIRE_PWSH=1) but not on PATH")
    return PWSH


@pytest.fixture
def remote(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    home = isolate(monkeypatch, tmp_path)
    upstream = Upstream(tmp_path)
    env = {**os.environ, "SKILLS_REPOSITORY_URL": upstream.url, "SKILLS_PYTHON": sys.executable}
    return home, env


@pytest.fixture
def served_installer():
    """The installer over HTTP on 127.0.0.1, as raw.githubusercontent.com would serve it."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "scripts"))
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/install_skills.py"
    server.shutdown()
    server.server_close()


def check_contract(home, env, command):
    """First install, a no-op update in one line, exit 75 under the lock, exit 2 for usage errors."""
    first = subprocess.run(command, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert (home / ".claude/skills/alpha/SKILL.md").is_file()
    assert (home / ".codex/skills" / installer.ROUTER / "SKILL.md").is_file()
    again = subprocess.run(command, env=env, capture_output=True, text=True)
    assert again.returncode == 0, again.stderr
    assert again.stdout.strip() == ALREADY
    with installer.state_lock(installer.native(data_dir(home))):
        busy = subprocess.run(command, env=env, capture_output=True, text=True)
    assert busy.returncode == installer.LOCK_BUSY, busy.stderr
    usage = subprocess.run([*command, "--enable", "alpha"], env=env, capture_output=True, text=True)
    assert usage.returncode == 2, usage.stderr


@pytest.mark.skipif(WINDOWS or not shutil.which("bash") or not shutil.which("curl"), reason="needs bash and curl")
def test_piped_install_sh(remote, tmp_path):
    home, env = remote
    env = without_pyyaml(tmp_path, env)  # as on a fresh host: the bootstraps need no PyYAML
    env["SKILLS_INSTALLER_URL"] = (ROOT / "scripts/install_skills.py").as_uri()
    piped = tmp_path / "pipe.sh"  # stands in for `curl -fsSL .../install.sh | bash -s -- ARGS`
    piped.write_text(f'exec bash -s -- "$@" < {shlex.quote(str(ROOT / "install.sh"))}\n')
    check_contract(home, env, ["bash", str(piped)])
    missing = subprocess.run(["bash", str(piped)], env={**env, "SKILLS_PYTHON": "no-such-python"}, capture_output=True)
    assert missing.returncode == 1 and b"Python 3.11+ is required" in missing.stderr


def test_installer_fits_in_one_python_c_argument():
    size = (ROOT / "scripts/install_skills.py").stat().st_size
    assert size < ARGUMENT_BUDGET, f"install_skills.py is {size} bytes; curl | bash would break near 128 KiB"


@NEEDS_PWSH
def test_downloaded_install_ps1(remote, tmp_path, served_installer):
    home, env = remote
    env = without_pyyaml(tmp_path, env)
    env["SKILLS_INSTALLER_URL"] = served_installer
    alone = tmp_path / "download/install.ps1"  # no checkout next to it: download mode
    alone.parent.mkdir()
    shutil.copyfile(ROOT / "install.ps1", alone)
    check_contract(home, env, [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(alone)])
    unreachable = {**env, "SKILLS_INSTALLER_URL": served_installer.replace("install_skills.py", "missing.py")}
    failed = subprocess.run(
        [pwsh(), "-NoProfile", "-File", str(alone)], env=unreachable, capture_output=True, text=True
    )
    assert failed.returncode == 1 and "could not download the installer" in failed.stderr


@NEEDS_PWSH
def test_install_ps1_from_a_checkout_uses_the_adjacent_installer(remote, tmp_path):
    home, env = remote
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    shutil.copyfile(ROOT / "install.ps1", checkout / "install.ps1")
    shutil.copytree(tmp_path / "upstream/skills", checkout / "skills")
    command = [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(checkout / "install.ps1")]
    result = subprocess.run([*command, "--claude-only", "--selection", "beta"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sorted(os.listdir(home / ".claude/skills")) == ["beta"]
    assert not (data_dir(home) / installer.CLONE).exists(), "a checkout install needs no library clone"
