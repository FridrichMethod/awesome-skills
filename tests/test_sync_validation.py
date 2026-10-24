"""The weekly sync must never commit what the installer would skip on some platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install_skills as installer
from scripts import sync_skills as ss

CASE_SENSITIVE = sys.platform.startswith("linux")


def write_skill(root: Path, name: str | None = None, extra: dict | None = None) -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: {name or root.name}\ndescription: Fixture skill.\n---\nbody\n")
    for rel, text in (extra or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """sync_upstream over a fake upstream; returns (library, staging, stats, build-upstream hook)."""
    destination = tmp_path / "library"
    destination.mkdir()
    library = ss.LibrarySources(destination, tmp_path / "library_sources.json")
    staging = tmp_path / "staging"
    staging.mkdir()
    builders = []
    monkeypatch.setattr(ss, "shallow_clone", lambda _url, dest: [build(dest) for build in builders] or True)
    monkeypatch.setattr(ss, "run", lambda *_a, **_k: SimpleNamespace(stdout="fixture-revision\n"))
    return library, staging, builders


def sync(pipeline) -> dict:
    library, staging, _ = pipeline
    stats: dict = {}
    ss.sync_upstream("https://example.test/one.git", "one", "fixture", staging, stats, library)
    return stats["one"]


def test_unportable_or_unreadable_upstream_skills_are_rejected_and_the_rest_synced(pipeline, capsys):
    library, _, builders = pipeline

    def upstream(dest: Path):
        write_skill(dest / "skills/good")
        write_skill(dest / "skills/submodules", extra={".gitmodules": "[submodule]\n"})
        write_skill(dest / "skills/no-name", name="''")
        if os.name != "nt":
            write_skill(dest / "skills/aux")
            write_skill(dest / "skills/colon", extra={"a:b.txt": "x\n"})
            write_skill(dest / "skills/dot.")
        if CASE_SENSITIVE:
            write_skill(dest / "skills/twins", extra={"Read.md": "a\n", "read.md": "b\n"})

    builders.append(upstream)
    stats = sync(pipeline)
    err = capsys.readouterr().err
    expected = 2 + (3 if os.name != "nt" else 0) + (1 if CASE_SENSITIVE else 0)
    assert stats["rejected"] == expected
    assert sorted(p.name for p in library.skills_dest.iterdir()) == ["good"]
    assert "REJECTED skills/submodules" in err and ".gitmodules: git metadata file" in err
    assert "REJECTED skills/no-name" in err and "Invalid frontmatter" in err
    if os.name != "nt":
        assert "REJECTED skills/aux" in err and "REJECTED skills/colon" in err and "REJECTED skills/dot." in err
    if CASE_SENSITIVE:
        assert "differs only in case" in err


def test_case_only_id_collision_becomes_a_source_qualified_variant(pipeline):
    library, _, builders = pipeline
    write_skill(library.skills_dest / "pdb", name="pdb")
    library = ss.LibrarySources(library.skills_dest, library.metadata_path)
    builders.append(lambda dest: write_skill(dest / "skills/PDB", name="pdb-upper"))
    stats: dict = {}
    staging = pipeline[1]
    ss.sync_upstream("https://example.test/one.git", "one", "fixture", staging, stats, library)
    names = sorted(p.name for p in library.skills_dest.iterdir())
    assert names[0] == "PDB--one--" + names[0].split("--")[2] and names[1] == "pdb"
    assert not installer.case_collisions(names)


def test_sync_exits_3_after_writing_the_valid_rest(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    skills.mkdir()
    for name, value in [
        ("SKILLS_DEST", skills),
        ("LIBRARY_SOURCES_PATH", tmp_path / "library_sources.json"),
        ("LIBRARY_INDEX_PATH", tmp_path / installer.INDEX),
        ("README_PATH", tmp_path / "README.md"),
        ("UPSTREAMS", [("https://example.test/one.git", "one", "fixture")]),
    ]:
        monkeypatch.setattr(ss, name, value)

    def upstream(_url, dest: Path):
        write_skill(dest / "skills/good")
        write_skill(dest / "skills/bad", extra={".gitmodules": "[submodule]\n"})
        return True

    monkeypatch.setattr(ss, "shallow_clone", upstream)
    monkeypatch.setattr(ss, "run", lambda *_a, **_k: SimpleNamespace(stdout="fixture-revision\n"))
    assert ss.main([]) == ss.REJECTED_EXIT
    assert sorted(p.name for p in skills.iterdir()) == ["good"]
    assert set(installer.build_index(skills)["skills"]) == {"good"}
    assert (tmp_path / installer.INDEX).read_text(encoding="utf-8") == installer.index_text(
        installer.build_index(skills)
    )


def test_sync_fails_without_writing_the_index_when_the_tree_breaks_the_rules(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"
    write_skill(skills / "legacy", extra={".gitmodules": "[submodule]\n"})  # predates the rules
    for name, value in [
        ("SKILLS_DEST", skills),
        ("LIBRARY_SOURCES_PATH", tmp_path / "library_sources.json"),
        ("LIBRARY_INDEX_PATH", tmp_path / installer.INDEX),
        ("README_PATH", tmp_path / "README.md"),
        ("UPSTREAMS", []),
    ]:
        monkeypatch.setattr(ss, name, value)
    assert ss.main([]) == 1
    assert "::error::skills/legacy: .gitmodules: git metadata file" in capsys.readouterr().err
    assert not (tmp_path / installer.INDEX).exists()


def test_index_regeneration_failure_is_loud(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"
    write_skill(skills / "good")
    for name, value in [
        ("SKILLS_DEST", skills),
        ("LIBRARY_SOURCES_PATH", tmp_path / "library_sources.json"),
        ("LIBRARY_INDEX_PATH", tmp_path / installer.INDEX),
        ("README_PATH", tmp_path / "README.md"),
        ("UPSTREAMS", []),
    ]:
        monkeypatch.setattr(ss, name, value)

    def broken(*_args, **_kwargs):
        raise ss._installer().InstallError("simulated unreadable frontmatter")

    monkeypatch.setattr(ss, "write_library_index", broken)
    assert ss.main([]) == 1
    assert (
        "::error::Could not regenerate library_index.json: simulated unreadable frontmatter" in capsys.readouterr().err
    )


def test_portability_rules():
    assert installer.name_problem("aux.md") and installer.name_problem("x.") and installer.name_problem("a:b")
    assert not installer.name_problem("console.md")
    assert installer.path_problems(["Docs/a.md", "docs/b.md"]) == ["docs: differs only in case from Docs"]
    problems = installer.skill_problems("ok", {"SKILL.md": "file", "lib": "link", "vendor": "submodule"})
    assert problems == ["lib: symbolic link", "vendor: submodule"]
    assert installer.case_collisions(["Pdb", "pdb"], {"pdb"}) == {"Pdb": "differs only in case from pdb"}
    assert set(installer.case_collisions(["Pdb", "pdb"])) == {"Pdb", "pdb"}
