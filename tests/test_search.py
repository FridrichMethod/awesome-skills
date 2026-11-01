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
from scripts import sync_skills
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


def test_the_exact_id_outranks_skills_that_mention_it_more_often(library):
    index = json.loads((library / installer.INDEX).read_text())
    index["skills"].update(
        {
            "pdb": {"name": "pdb", "description": "Protein Data Bank."},
            "bio-pdb-structure-navigation": {"name": "bio-pdb-navigation", "description": "Read pdb files, pdb tools."},
        }
    )
    (library / installer.INDEX).write_text(json.dumps(index))
    assert [line.split(" ")[0] for line in search(library, "pdb").stdout.splitlines()[1:]] == [
        "pdb",
        "bio-pdb-structure-navigation",
    ]


def test_a_codex_path_comes_from_the_recorded_root_or_says_it_is_missing(library, tmp_path):
    """A foreign folder of the same name in the other root is never the path the router reads, and
    a skill with no Codex copy says so instead of naming a path."""
    state, first, second = tmp_path / "state", tmp_path / "codex", tmp_path / "agents"
    state.mkdir()
    codex = {"selection": ["@library"], "destination": str(first), "destination2": str(second)}
    (state / "codex.json").write_text(json.dumps(dict(codex, managed={"alpha": {"root": 1}})))
    skill(first, "alpha", body="another tool's alpha")
    skill(second, "alpha")
    env = {**os.environ, "HOME": str(tmp_path / "empty-home")}
    env.pop("CODEX_HOME", None)
    lines = search(library, "skill", "--client", "codex", "--state", str(state), env=env).stdout.splitlines()
    assert lines[1:] == [
        "alpha - Alpha skill.",
        f"  {second / 'alpha/SKILL.md'}",
        "beta - Beta skill.",
        "  (not installed for Codex)",
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
    index = sync_skills.index_text(sync_skills.build_index(checkout / "skills"))
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
    marker = tmp_path / "planted-module-ran"  # the installer's own folder is not on its sys.path (-P)
    (checkout / "scripts/json.py").write_text(f"open({str(marker)!r}, 'w').close()\nraise SystemExit(97)\n")
    shown = subprocess.run(
        [str(launcher), "--codex-only", "--enable", "beta"], env=bare, capture_output=True, text=True
    )
    assert shown.returncode == 0, shown.stderr
    assert not marker.exists()
    assert json.loads((custom / "codex.json").read_text())["selection"] == ["@library", "beta"]
    assert not (home / ".local/share/awesome-skills/codex.json").exists(), "no second, divergent state"


@POSIX
def test_the_launcher_keeps_working_when_the_second_codex_root_becomes_a_link(tmp_path):
    checkout = tmp_path / "repo"
    for skill_id in ("alpha", "beta", *(f"extra-{i}" for i in range(6))):
        skill(checkout / "skills", skill_id)
    shutil.copytree(ROOT / "scripts", checkout / "scripts")
    home, env = sandbox_env(tmp_path)
    assert subprocess.run([sys.executable, "-B", str(checkout / "scripts/install_skills.py")], env=env).returncode == 0
    launcher = home / ".local/share/awesome-skills/bin/awesome-skills"
    assert "SKILLS_CODEX_DEST" not in launcher.read_text(), "the state saves the destinations"
    second, shared = home / ".agents/skills", home / "shared-skills"
    assert any(second.iterdir())
    second.rename(shared)  # shared with other tools from now on
    second.symlink_to(shared, target_is_directory=True)
    bare = {"HOME": str(home), "PATH": os.environ["PATH"]}
    for args in (["--codex-only", "--enable", "alpha", "--no-fetch"], []):  # what the routers and updates run
        result = subprocess.run([str(launcher), *args], env=bare, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "Codex's copies there are left as they are" in result.stderr


def router(client, data):
    return installer.router_info(client, data)["entries"]["SKILL.md"][2].decode()


def test_routers_differ_per_client_and_quote_for_powershell_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "WINDOWS", False)  # the POSIX forms first, on every platform
    call = installer.shlex.quote(str(tmp_path / "bin/awesome-skills"))
    claude, codex = router("claude", tmp_path), router("codex", tmp_path)
    head, body = claude.split("\n---\n", 1)
    assert f"allowed-tools: Bash({call} search *)" in head and 'argument-hint: "[what you need]"' in head
    assert installer.HIDDEN_KEY not in head
    assert body.startswith("Request: $ARGUMENTS\n") and "!`" not in claude
    assert f"{call} search --client claude WORDS" in body and "/ID" in body and "SKILL.md" in body
    assert f"{call} search --client codex WORDS" in codex and "$ID" in codex and "argument-hint" not in codex
    assert "/ID" not in codex and "Skill tool" not in codex
    monkeypatch.setattr(installer, "WINDOWS", True)
    data = Path("C:/Users/o'brien/AppData/Local/awesome-skills")
    ps = installer.launcher_call(data)
    assert ps.startswith("& 'C:") and "o''brien" in ps
    codex = router("codex", data)  # Codex runs commands in PowerShell on Windows
    assert f"```powershell\n   {ps} search --client codex WORDS\n   ```" in codex and "```bash" not in codex
    # Claude's Bash tool is Git Bash, which runs the sh launcher; without Git Bash it has PowerShell.
    sh = installer.shlex.quote("C:/Users/o'brien/AppData/Local/awesome-skills/bin/awesome-skills")
    claude = router("claude", data)
    assert (
        f"```bash\n   {sh} search --client claude WORDS\n   ```\n\n   or\n\n   ```powershell\n   {ps} search" in claude
    )
    assert f"\nallowed-tools: Bash({sh} search *) PowerShell({ps} search *)\n" in claude


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
    assert "& 'C:/Python/py''thon.exe' -P -B" in ps1 and "da''ta" in ps1 and "@args" in ps1
    assert "& 'C:/Python/py''thon.exe' -I -B" in ps1, "the search runs isolated"


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
    data = tmp_path / "O\u2019Brien's da\u2018ta"  # PowerShell ends a single-quoted string at either mark
    path, text = next((p, t) for p, t in installer.launchers(data, tmp_path / "state", Library()).items() if p.suffix)
    path.parent.mkdir(parents=True)
    path.write_bytes(text.encode())
    command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(path)]
    found = subprocess.run([*command, "search", "alpha"], capture_output=True, text=True)
    assert found.returncode == 0 and "alpha - Alpha skill." in found.stdout, found.stderr
    assert subprocess.run([*command, "search", "zzz"], capture_output=True).returncode == 1
    usage = subprocess.run([*command, "--help"], capture_output=True, text=True)
    assert usage.returncode == 0 and "--manual" in usage.stdout, usage.stderr


@pytest.mark.skipif(
    PWSH is None and os.environ.get("AWESOME_SKILLS_REQUIRE_PWSH") != "1", reason="PowerShell 7 (pwsh) unavailable"
)
def test_a_powershell_literal_keeps_every_single_quote_mark(tmp_path):
    """PowerShell also ends a single-quoted string at U+2018, U+2019, U+201A and U+201B: a path such
    as C:\\Users\\O\u2019Brien must stay one literal, and the rest of it never runs as code."""
    if PWSH is None:
        pytest.fail("pwsh is required (AWESOME_SKILLS_REQUIRE_PWSH=1) but not on PATH")
    values = ["O\u2019Brien", "a\u2019+(Write-Output INJECTED)+\u2019b", "\u2018x\u201ay\u201bz'", '$(1+1) `n "q"']
    script = tmp_path / "literals.ps1"
    script.write_bytes(("\ufeff" + "".join(f"Write-Output {installer.ps_quote(v)}\n" for v in values)).encode())
    out = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(script)], capture_output=True)
    assert out.returncode == 0 and out.stdout.decode().splitlines() == values, out.stderr.decode()
