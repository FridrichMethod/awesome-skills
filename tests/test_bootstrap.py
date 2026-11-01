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
from pathlib import Path

import pytest

from scripts import install_skills as installer
from tests.gitfixtures import ROOT, WINDOWS, Upstream, data_dir, isolate, put, snapshot, without_pyyaml

PWSH = shutil.which("pwsh")
ALREADY = "Already current; selection preserved."
# CI sets this so the PowerShell bootstrap tests fail instead of skipping when pwsh is missing.
NEEDS_PWSH = pytest.mark.skipif(
    PWSH is None and os.environ.get("AWESOME_SKILLS_REQUIRE_PWSH") != "1", reason="PowerShell 7 (pwsh) unavailable"
)
# Linux caps one argument at 128 KiB (MAX_ARG_STRLEN), so install.sh feeds the downloaded installer
# to Python on standard input instead of as a `python -c` argument.
MAX_ARG_STRLEN = 128 * 1024


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
    return home, env, upstream


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


def plant_modules(directory: Path) -> Path:
    """A json.py where a bootstrap's Python might look first (its working or temporary directory, the
    script's own folder): imported, it writes a marker. Returns the marker's path."""
    marker = directory.parent / f"{directory.name}-planted-module-ran"
    put(directory / "json.py", f"open({str(marker)!r}, 'w').close()\nraise SystemExit(97)\n")
    return marker


def check_contract(home, env, command, cwd=None):
    """First install, a no-op update in one line, exit 75 under the lock, exit 2 for usage errors."""
    first = subprocess.run(command, env=env, capture_output=True, text=True, cwd=cwd)
    assert first.returncode == 0, first.stderr
    assert (home / ".claude/skills/alpha/SKILL.md").is_file()
    assert (home / ".codex/skills" / installer.ROUTER / "SKILL.md").is_file()
    again = subprocess.run(command, env=env, capture_output=True, text=True, cwd=cwd)
    assert again.returncode == 0, again.stderr
    assert again.stdout.strip() == ALREADY
    with installer.state_lock(installer.native(data_dir(home))):
        busy = subprocess.run(command, env=env, capture_output=True, text=True, cwd=cwd)
    assert busy.returncode == installer.LOCK_BUSY, busy.stderr
    usage = subprocess.run([*command, "--enable", "alpha"], env=env, capture_output=True, text=True, cwd=cwd)
    assert usage.returncode == 2, usage.stderr


@pytest.mark.skipif(WINDOWS or not shutil.which("bash") or not shutil.which("curl"), reason="needs bash and curl")
def test_piped_install_sh(remote, tmp_path):
    home, env, _ = remote
    env = without_pyyaml(tmp_path, env)  # as on a fresh host: the bootstraps need no PyYAML
    env["SKILLS_INSTALLER_URL"] = (ROOT / "scripts/install_skills.py").as_uri()
    piped = tmp_path / "pipe.sh"  # stands in for `curl -fsSL .../install.sh | bash -s -- ARGS`
    piped.write_text(f'exec bash -s -- "$@" < {shlex.quote(str(ROOT / "install.sh"))}\n')
    planted = plant_modules(tmp_path / "caller")  # the directory the hook or the user runs it from
    check_contract(home, env, ["bash", str(piped)], cwd=tmp_path / "caller")
    assert not planted.exists(), "the installer runs isolated (-I): the caller's directory is not on sys.path"
    missing = subprocess.run(["bash", str(piped)], env={**env, "SKILLS_PYTHON": "no-such-python"}, capture_output=True)
    assert missing.returncode == 1 and b"Python 3.11+ is required" in missing.stderr
    old = tmp_path / "old-python"  # stands in for a python3 older than 3.11
    put(old, "#!/bin/sh\nexit 1\n")
    old.chmod(0o755)
    older = subprocess.run(["bash", str(piped)], env={**env, "SKILLS_PYTHON": str(old)}, capture_output=True)
    assert older.returncode == 1 and b"Python 3.11+ is required" in older.stderr


@pytest.mark.skipif(WINDOWS or not shutil.which("bash") or not shutil.which("curl"), reason="needs bash and curl")
def test_piped_install_sh_runs_an_installer_of_any_size_and_passes_its_exit_status(remote, tmp_path):
    """curl | bash keeps the download in memory and gives it to Python on standard input, which has
    no size limit; the installer reads nothing from it, and its exit status is the bootstrap's."""
    home, env, _ = remote
    served = tmp_path / "served/install_skills.py"  # three times what one argument may hold
    put(served, (ROOT / "scripts/install_skills.py").read_text() + "# padding\n" * (3 * MAX_ARG_STRLEN // 10))
    assert served.stat().st_size > 3 * MAX_ARG_STRLEN
    env["SKILLS_INSTALLER_URL"] = served.as_uri()
    piped = tmp_path / "pipe.sh"
    piped.write_text(f'exec bash -s -- "$@" < {shlex.quote(str(ROOT / "install.sh"))}\n')
    # From standard input __file__ is "<stdin>", a name relative to the caller's folder: a library
    # clone planted around the caller must not be taken for the installer's own.
    planted = tmp_path / "planted/library"
    put(planted / ".git" / installer.MARKER, "not a clone\n")
    (planted / "scripts").mkdir()
    before = snapshot(planted.parent)
    check_contract(home, env, ["bash", str(piped)], cwd=planted / "scripts")
    assert snapshot(planted.parent) == before and (data_dir(home) / installer.CLONE).is_dir()
    bad = subprocess.run(["bash", str(piped)], env={**env, "SKILLS_BRANCH": "a..b"}, capture_output=True, text=True)
    assert bad.returncode == 1 and "Invalid SKILLS_BRANCH" in bad.stderr
    _, _, upstream = remote
    for i in range(installer.MASS_REMOVAL_MINIMUM):
        upstream.skill(f"extra-{i:02d}")
    upstream.commit("more skills")
    assert subprocess.run(["bash", str(piped)], env=env, capture_output=True).returncode == 0
    shutil.rmtree(upstream.work / "skills")
    upstream.skill("alpha")
    upstream.commit("most skills removed")
    held = subprocess.run(["bash", str(piped)], env=env, capture_output=True, text=True)
    assert held.returncode == installer.NEEDS_PERSON and "Refusing to remove" in held.stderr, held.stderr


@NEEDS_PWSH
def test_downloaded_install_ps1(remote, tmp_path, served_installer):
    home, env, _ = remote
    env = without_pyyaml(tmp_path, env)
    env["SKILLS_INSTALLER_URL"] = served_installer
    alone = tmp_path / "download/install.ps1"  # no checkout next to it: download mode
    alone.parent.mkdir()
    shutil.copyfile(ROOT / "install.ps1", alone)
    temporary = tmp_path / "temporary"  # where install.ps1 saves the downloaded installer
    planted = plant_modules(temporary)
    env.update(TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary))
    check_contract(home, env, [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(alone)], cwd=temporary)
    assert not planted.exists(), "the installer runs isolated (-I): its download folder is not on sys.path"
    if not WINDOWS:
        old = tmp_path / "old-python"  # stands in for a python older than 3.11
        put(old, "#!/bin/sh\nexit 1\n")
        old.chmod(0o755)
        older = subprocess.run(
            [pwsh(), "-NoProfile", "-File", str(alone)], env={**env, "SKILLS_PYTHON": str(old)}, capture_output=True
        )
        assert older.returncode == 1 and b"Python 3.11+ is required" in older.stderr
    unreachable = {**env, "SKILLS_INSTALLER_URL": served_installer.replace("install_skills.py", "missing.py")}
    failed = subprocess.run(
        [pwsh(), "-NoProfile", "-File", str(alone)], env=unreachable, capture_output=True, text=True
    )
    assert failed.returncode == 1 and "could not download the installer" in failed.stderr


@NEEDS_PWSH
def test_install_ps1_from_a_checkout_uses_the_adjacent_installer(remote, tmp_path):
    home, env, _ = remote
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    shutil.copyfile(ROOT / "install.ps1", checkout / "install.ps1")
    shutil.copytree(tmp_path / "upstream/skills", checkout / "skills")
    planted = plant_modules(checkout / "scripts")
    command = [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(checkout / "install.ps1")]
    args = ["--claude-only", "--selection", "beta", "--manual="]  # nothing hidden besides
    result = subprocess.run([*command, *args], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not planted.exists(), "-P: the installer's own folder is not on sys.path"
    assert sorted(os.listdir(home / ".claude/skills")) == ["beta"]
    assert not (data_dir(home) / installer.CLONE).exists(), "a checkout install needs no library clone"


@pytest.mark.skipif(WINDOWS or not shutil.which("bash"), reason="install.sh is the POSIX bootstrap")
def test_install_sh_from_a_checkout_keeps_the_script_folder_off_sys_path(remote, tmp_path):
    home, env, _ = remote
    checkout = tmp_path / "checkout"
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    shutil.copyfile(ROOT / "install.sh", checkout / "install.sh")
    shutil.copytree(tmp_path / "upstream/skills", checkout / "skills")
    planted = plant_modules(checkout / "scripts")
    args = ["--claude-only", "--selection", "beta", "--manual="]
    result = subprocess.run(["bash", str(checkout / "install.sh"), *args], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert sorted(os.listdir(home / ".claude/skills")) == ["beta"]
    assert not planted.exists(), "-P: the installer's own folder is not on sys.path"
