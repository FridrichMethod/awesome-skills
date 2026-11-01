"""The read-only library search. Temporary copies only."""

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
