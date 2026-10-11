"""Content conflicts must remain reviewable, with observed source provenance."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import sync_skills as ss


def skill(parent: Path, directory: str, name: str = "shared", body: str = "body") -> Path:
    root = parent / directory
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f'---\nname: "{name}"\ndescription: Useful description.\n---\n{body}\n')
    return root


def origin(repository: str = "https://example.test/one.git", path: str = "skills/example", revision: str = "a") -> dict:
    return {"repository": repository, "path": path, "revision": revision, "current": True}


def library(tmp_path: Path) -> ss.LibrarySources:
    destination = tmp_path / "library"
    destination.mkdir(exist_ok=True)
    return ss.LibrarySources(destination, tmp_path / "library_sources.json")


def reload(index: ss.LibrarySources) -> ss.LibrarySources:
    index.save()
    return ss.LibrarySources(index.skills_dest, index.metadata_path)


def test_new_copy_records_actual_repository_revision_and_path(tmp_path: Path) -> None:
    index = library(tmp_path)
    source = skill(tmp_path / "incoming", "different-directory", "loader-name")
    source_origin = origin()
    skill_id, action = index.install(source, "one", source_origin)
    assert (skill_id, action) == ("different-directory", "new")
    index = reload(index)
    entry = index.entries[skill_id]
    assert entry["name"] == "loader-name"
    assert entry["digest"] == ss.skill_tree_digest(source)
    assert entry["origins"] == [source_origin]


def test_distinct_frontmatter_name_conflict_preserves_both_contents(tmp_path: Path, capsys) -> None:
    index = library(tmp_path)
    first = skill(tmp_path / "one", "one-dir", body="first content")
    second = skill(tmp_path / "two", "two-dir", body="second content")
    first_id, _ = index.install(first, "one", origin())
    second_id, _ = index.install(second, "two", origin("https://example.test/two.git"))
    assert second_id.startswith("two-dir--two--")
    assert ss.skill_tree_digest(index.skills_dest / first_id) == ss.skill_tree_digest(first)
    assert ss.skill_tree_digest(index.skills_dest / second_id) == ss.skill_tree_digest(second)
    assert ss.skill_frontmatter_name(index.skills_dest / second_id) == "shared"
    index = reload(index)
    assert index.entries[first_id]["conflicts"] == sorted([first_id, second_id])
    assert "NAME CONFLICT 'shared'" in capsys.readouterr().err


def test_deduplication_keeps_all_origins_and_is_idempotent(tmp_path: Path) -> None:
    index = library(tmp_path)
    first = skill(tmp_path / "one", "one-dir")
    second = skill(tmp_path / "two", "two-dir")
    first_id, _ = index.install(first, "one", origin())
    assert index.install(second, "two", origin("https://example.test/two.git")) == (first_id, "deduplicated")
    index = reload(index)
    snapshot = index.metadata_path.read_bytes()
    assert index.install(second, "two", origin("https://example.test/two.git")) == (first_id, "deduplicated")
    index.save()
    assert index.metadata_path.read_bytes() == snapshot
    assert len(index.entries[first_id]["origins"]) == 2
    assert len(list(index.skills_dest.iterdir())) == 1


def test_whole_tree_differs_even_when_skill_md_is_identical(tmp_path: Path) -> None:
    index = library(tmp_path)
    first = skill(tmp_path / "one", "example")
    second = skill(tmp_path / "two", "example")
    (first / "helper.py").write_text("old helper")
    (second / "helper.py").write_text("new helper")
    first_id, _ = index.install(first, "one", origin())
    second_id, action = index.install(second, "two", origin("https://example.test/two.git"))
    assert first_id != second_id and action == "new"
    assert "shared" in index.conflicts()


def test_upstream_can_update_its_own_unmodified_copy(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(tmp_path / "old", "example", body="old")
    new = skill(tmp_path / "new", "example", body="new")
    skill_id, _ = index.install(old, "one", origin())
    index = reload(index)
    assert index.install(new, "one", origin(revision="b")) == (skill_id, "updated")
    assert len(list(index.skills_dest.iterdir())) == 1
    assert index.entries[skill_id]["origins"][0]["revision"] == "b"


def test_distinct_paths_in_one_repository_do_not_override_each_other(tmp_path: Path) -> None:
    index = library(tmp_path)
    first = skill(tmp_path / "one", "example", body="path one")
    second = skill(tmp_path / "two", "example", body="path two")
    first_id, _ = index.install(first, "one", origin(path="one/example"))
    second_id, _ = index.install(second, "one", origin(path="two/example"))
    index = reload(index)
    updated = skill(tmp_path / "new", "example", body="updated path one")
    assert index.install(updated, "one", origin(path="one/example", revision="b")) == (first_id, "updated")
    assert ss.skill_tree_digest(index.skills_dest / second_id) == ss.skill_tree_digest(second)


def test_legacy_directory_has_no_invented_upstream_and_is_not_replaced(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(index.skills_dest, "example", body="legacy")
    before = ss.skill_tree_digest(old)
    index = ss.LibrarySources(index.skills_dest, index.metadata_path)
    incoming = skill(tmp_path / "incoming", "example", body="upstream")
    skill_id, _ = index.install(incoming, "one", origin())
    assert skill_id != "example"
    assert ss.skill_tree_digest(old) == before
    index = reload(index)
    legacy = index.entries["example"]["origins"][0]
    assert legacy["kind"] == "legacy"
    assert "repository" not in legacy and "revision" not in legacy


def test_identical_legacy_copy_can_deduplicate_but_remains_protected(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(index.skills_dest, "example")
    index = ss.LibrarySources(index.skills_dest, index.metadata_path)
    identical = skill(tmp_path / "incoming", "example")
    assert index.install(identical, "one", origin()) == ("example", "deduplicated")
    index = reload(index)
    new = skill(tmp_path / "new", "example", body="new version")
    assert index.install(new, "one", origin(revision="b"))[0] != "example"
    assert ss.skill_tree_digest(old) == ss.skill_tree_digest(identical)


def test_locally_modified_support_file_is_not_overwritten(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(tmp_path / "old", "example")
    skill_id, _ = index.install(old, "one", origin())
    (index.skills_dest / skill_id / "user.py").write_text("local change")
    index = reload(index)
    new = skill(tmp_path / "new", "example", body="new version")
    assert index.install(new, "one", origin(revision="b"))[0] != skill_id
    assert (index.skills_dest / skill_id / "user.py").read_text() == "local change"
    assert index.entries[skill_id]["locally_modified"] is True


def test_shared_copy_is_preserved_when_one_source_advances(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(tmp_path / "old", "example")
    skill_id, _ = index.install(old, "one", origin())
    index.install(old, "two", origin("https://example.test/two.git"))
    index = reload(index)
    new = skill(tmp_path / "new", "example", body="new version")
    new_id, action = index.install(new, "one", origin(revision="b"))
    assert action == "new" and new_id != skill_id
    origins = index.entries[skill_id]["origins"]
    assert origins[0]["current"] is False
    assert origins[1]["current"] is True
    assert ss.skill_tree_digest(index.skills_dest / skill_id) == ss.skill_tree_digest(old)


def test_edit_after_initial_scan_is_rechecked_before_replacement(tmp_path: Path) -> None:
    index = library(tmp_path)
    old = skill(tmp_path / "old", "example")
    skill_id, _ = index.install(old, "one", origin())
    index = reload(index)
    (index.skills_dest / skill_id / "late-edit.txt").write_text("edited while sync ran")
    new = skill(tmp_path / "new", "example", body="new version")
    assert index.install(new, "one", origin(revision="b"))[0] != skill_id
    assert (index.skills_dest / skill_id / "late-edit.txt").read_text() == "edited while sync ran"


def test_symlink_and_unknown_directory_are_not_replaced(tmp_path: Path) -> None:
    index = library(tmp_path)
    external = skill(tmp_path / "external", "first-party")
    (index.skills_dest / "example").symlink_to(external, target_is_directory=True)
    (index.skills_dest / "unknown").mkdir()
    (index.skills_dest / "unknown" / "user.txt").write_text("owned by user")
    index = ss.LibrarySources(index.skills_dest, index.metadata_path)
    one = skill(tmp_path / "one", "example")
    two = skill(tmp_path / "two", "unknown", name="different")
    assert index.install(one, "one", origin())[0] != "example"
    assert index.install(two, "two", origin(path="skills/unknown"))[0] != "unknown"
    assert (index.skills_dest / "example").is_symlink()
    assert (index.skills_dest / "unknown" / "user.txt").read_text() == "owned by user"


def test_tree_digest_includes_paths_empty_directories_and_executable_bits(tmp_path: Path) -> None:
    root = skill(tmp_path, "example")
    baseline = ss.skill_tree_digest(root)
    (root / "empty").mkdir()
    assert ss.skill_tree_digest(root) != baseline
    baseline = ss.skill_tree_digest(root)
    os.chmod(root / "SKILL.md", 0o755)
    assert ss.skill_tree_digest(root) != baseline


def test_bad_manifest_fails_closed(tmp_path: Path) -> None:
    metadata = tmp_path / "library_sources.json"
    metadata.write_text(json.dumps({"../escape": {"origins": []}}))
    with pytest.raises(ValueError, match="Invalid library provenance"):
        ss.LibrarySources(tmp_path / "library", metadata)


def test_sync_pipeline_filters_and_sanitizes_before_comparing(tmp_path: Path, monkeypatch) -> None:
    index = library(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()

    def clone(_url: str, destination: Path) -> bool:
        root = skill(destination, "example")
        (root / "SKILL.md").write_text("---\nname: shared\ndescription: words: need quoting\n---\nbody\n")
        (root / ".gitattributes").write_text("*.bin filter=lfs")
        (root / "vector.bin").write_text("LFS pointer fixture")
        (root / "repo" / "dataset").mkdir(parents=True)
        (root / "repo" / "dataset" / "blob.txt").write_text("do not copy")
        return True

    monkeypatch.setattr(ss, "shallow_clone", clone)
    monkeypatch.setattr(ss, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="fixture-revision\n"))
    stats: dict = {}
    ss.sync_upstream("https://example.test/one.git", "one", "fixture", staging, stats, index)
    destination = index.skills_dest / "example"
    assert not (destination / ".gitattributes").exists()
    assert not (destination / "vector.bin").exists()
    assert not (destination / "repo" / "dataset").exists()
    assert 'description: "words: need quoting"' in (destination / "SKILL.md").read_text()
    assert index.entries["example"]["origins"][0]["revision"] == "fixture-revision"
    assert stats["one"]["frontmatter_normalized"] == 1
