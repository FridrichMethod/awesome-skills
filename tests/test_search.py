"""The read-only library search, the launcher that runs it and the installer, and the routers
that call the launcher. Temporary HOME and copies only."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_skills as installer
from tests.test_install import skill

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"
POSIX = pytest.mark.skipif(WINDOWS, reason="runs the POSIX launcher")


@pytest.fixture
def library(tmp_path):
    """A copy of the search helper beside a synthetic index of 70 skills."""
    root = tmp_path / "library"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/search_skills.py", root / "scripts/search_skills.py")
    skills = {
        f"tool-{i:02d}": {"name": f"tool-{i:02d}", "description": f"Generic protein helper {i}."} for i in range(60)
    }
    skills.update(
        {
            "protein": {"name": "protein", "description": "Exact ID."},
            "single-cell-qc": {"name": "scqc", "description": "Quality control of cells."},
            "rna_tools": {"name": "rna-tools", "description": "Single cell RNA analysis. " + "x" * 300},
            "alpha": {"name": "alpha", "description": "Alpha skill."},
            "beta": {"name": "shared", "description": "Beta skill."},
        }
    )
    (root / installer.INDEX).write_text(json.dumps({"schema": 1, "skills": skills}))
    return root


def search(library, *args, env=None):
    command = [sys.executable, "-I", "-B", str(library / "scripts/search_skills.py"), *args]
    return subprocess.run(command, capture_output=True, text=True, env=env)


def test_the_helper_imports_only_the_standard_library():
    tree = ast.parse((ROOT / "scripts/search_skills.py").read_text())
    modules = {
        alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    modules |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules <= set(sys.stdlib_module_names) | {"__future__"}, modules


def test_separators_are_interchangeable_and_every_word_must_match(library):
    found = [
        search(library, *words).stdout.splitlines()[1:]
        for words in (["single", "cell"], ["single-cell"], ["single_cell"])
    ]
    assert found[0] == found[1] == found[2]
    assert [line.split(" ")[0] for line in found[0]] == ["single-cell-qc", "rna_tools"]
    assert search(library, "single", "nothing-like-this").returncode == 1


def test_the_exact_id_ranks_first_and_output_is_bounded(library):
    result = search(library, "protein")
    lines = result.stdout.splitlines()
    assert result.returncode == 0 and lines[0] == "61 match(es) for 'protein'; the best 12:"
    assert lines[1] == "protein - Exact ID."
    assert len(lines) == 14 and lines[-1] == "... 49 more; add a word to narrow the search"
    assert len(search(library, "protein", "--limit", "500").stdout.splitlines()) == 52, "at most 50 matches"
    long = search(library, "rna").stdout.splitlines()[1]
    assert long.endswith("...") and len(long.split(" - ", 1)[1]) == 150


def test_no_match_and_a_missing_index(library):
    result = search(library, "zzz")
    assert result.returncode == 1 and result.stdout == "0 match(es) for 'zzz':\n"
    (library / installer.INDEX).unlink()
    assert search(library, "alpha").returncode == 2


def test_visible_marks_and_codex_paths_come_from_the_state(library, tmp_path):
    state, first, second = tmp_path / "state", tmp_path / "codex", tmp_path / "agents"
    state.mkdir()
    (state / "claude.json").write_text(json.dumps({"selection": ["@all"]}))
    codex = {"selection": ["@library", "beta"], "destination": str(first), "destination2": str(second)}
    codex["managed"] = {"alpha": {"root": 1}}
    (state / "codex.json").write_text(json.dumps(codex))
    skill(second, "alpha")
    skill(first, "beta")
    claude = search(library, "skill", "--client", "claude", "--state", str(state)).stdout.splitlines()
    assert claude[1:] == ["alpha [visible] - Alpha skill.", "beta [visible] - Beta skill."]
    env = {**os.environ, "HOME": str(tmp_path / "empty-home")}
    lines = search(library, "skill", "--client", "codex", "--state", str(state), env=env).stdout.splitlines()
    assert lines[1:] == [
        "alpha - Alpha skill.",
        f"  {second / 'alpha/SKILL.md'}",
        "beta [visible] - Beta skill.",
        f"  {first / 'beta/SKILL.md'}",
    ]


def sandbox_env(tmp_path, **extra) -> tuple[Path, dict]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("SKILLS_") and k not in ("XDG_DATA_HOME", "CODEX_HOME")
    }
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / "AppData/Local"), **extra)
    return home, env


@POSIX
def test_the_launcher_carries_the_install_time_storage_and_dispatches_search(tmp_path):
    checkout = tmp_path / "repo"
    for skill_id in ("alpha", "beta"):
        skill(checkout / "skills", skill_id)
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    index = installer.index_text(installer.build_index(checkout / "skills"))
    (checkout / installer.INDEX).write_text(index)
    custom = tmp_path / "custom-state"
    home, env = sandbox_env(tmp_path, SKILLS_STATE_DIR=str(custom), SKILLS_CODEX_DEST=str(tmp_path / "cx/skills"))
    install = [sys.executable, "-B", str(checkout / "scripts/install_skills.py")]
    assert subprocess.run(install, env=env, capture_output=True).returncode == 0
    launcher = home / ".local/share/awesome-skills/bin/awesome-skills"
    assert os.access(launcher, os.X_OK)
    bare = {"HOME": str(home), "PATH": os.environ["PATH"]}  # what a router's shell may have
    found = subprocess.run(
        [str(launcher), "search", "--client", "codex", "alpha"], env=bare, capture_output=True, text=True
    )
    assert found.returncode == 0, found.stderr
    assert f"  {tmp_path / 'cx/skills/alpha/SKILL.md'}" in found.stdout.splitlines()
    shown = subprocess.run(
        [str(launcher), "--codex-only", "--enable", "beta"], env=bare, capture_output=True, text=True
    )
    assert shown.returncode == 0, shown.stderr
    assert json.loads((custom / "codex.json").read_text())["selection"] == ["@library", "beta"]
    assert not (home / ".local/share/awesome-skills/codex.json").exists(), "no second, divergent state"


def test_routers_differ_per_client_and_quote_for_powershell_on_windows(monkeypatch, tmp_path):
    call = installer.shlex.quote(str(tmp_path / "bin/awesome-skills"))
    claude = installer.router_info("claude", call)["entries"]["SKILL.md"][2].decode()
    codex = installer.router_info("codex", call)["entries"]["SKILL.md"][2].decode()
    head, body = claude.split("\n---\n", 1)
    assert f"allowed-tools: Bash({call} search *)" in head and 'argument-hint: "[what you need]"' in head
    assert installer.HIDDEN_KEY not in head
    assert body.startswith("Request: $ARGUMENTS\n") and "!`" not in claude
    assert f"{call} search --client claude WORDS" in body and "/ID" in body and "SKILL.md" in body
    assert f"{call} search --client codex WORDS" in codex and "$ID" in codex and "argument-hint" not in codex
    assert "/ID" not in codex and "Skill tool" not in codex
    monkeypatch.setattr(installer, "WINDOWS", True)
    data = Path("C:/Users/o'brien/AppData/Local/awesome-skills")
    assert installer.launcher_call(data).startswith("& 'C:") and "o''brien" in installer.launcher_call(data)
    assert (
        "```powershell"
        in installer.router_info("codex", installer.launcher_call(data))["entries"]["SKILL.md"][2].decode()
    )


class FakeLibrary:
    def router_command(self):
        return "C:/lib/scripts/install_skills.py", []


def test_the_windows_launcher_uses_single_quoted_literals(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "WINDOWS", True)
    monkeypatch.setattr(installer.sys, "executable", "C:/Python/py'thon.exe")
    data, state = tmp_path / "da'ta", tmp_path / "state"
    files = installer.launchers(data, state, FakeLibrary())
    ps1 = files[data / "bin/awesome-skills.ps1"]
    assert ps1.startswith("\ufeff# Written by the awesome-skills installer")
    assert "& 'C:/Python/py''thon.exe' -B" in ps1 and "da''ta" in ps1 and "@args" in ps1


PWSH = shutil.which("pwsh")


@pytest.mark.skipif(
    PWSH is None and os.environ.get("AWESOME_SKILLS_REQUIRE_PWSH") != "1", reason="PowerShell 7 (pwsh) unavailable"
)
def test_the_powershell_launcher_runs_the_search_and_the_installer(library, monkeypatch, tmp_path):
    if PWSH is None:
        pytest.fail("pwsh is required (AWESOME_SKILLS_REQUIRE_PWSH=1) but not on PATH")
    shutil.copyfile(ROOT / "scripts/install_skills.py", library / "scripts/install_skills.py")

    class Library:
        def router_command(self):
            return str(library / "scripts/install_skills.py"), []

    monkeypatch.setattr(installer, "WINDOWS", True)
    data = tmp_path / "da'ta"
    path, text = next((p, t) for p, t in installer.launchers(data, tmp_path / "state", Library()).items() if p.suffix)
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode())
    command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(path)]
    found = subprocess.run([*command, "search", "alpha"], capture_output=True, text=True)
    assert found.returncode == 0 and "alpha - Alpha skill." in found.stdout, found.stderr
    assert subprocess.run([*command, "search", "zzz"], capture_output=True).returncode == 1
    usage = subprocess.run([*command, "--help"], capture_output=True, text=True)
    assert usage.returncode == 0 and "--manual" in usage.stdout, usage.stderr
