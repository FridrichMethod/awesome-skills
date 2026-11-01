"""The weekly sync must never commit what the installer would skip on some platform."""

from __future__ import annotations

import os
import shutil
import subprocess
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


def test_a_skill_whose_name_remote_installs_cannot_verify_is_rejected(pipeline, capsys):
    library, _, builders = pipeline

    def upstream(dest: Path):
        write_skill(dest / "skills/good")
        anchored = dest / "skills/anchored"
        anchored.mkdir(parents=True)
        # PyYAML reads the name; the standard-library reader refuses frontmatter with anchors.
        (anchored / "SKILL.md").write_text(
            "---\nname: anchored\ndescription: Fixture skill.\nmetadata:\n  base: &defaults {a: 1}\n---\nbody\n"
        )

    builders.append(upstream)
    assert sync(pipeline)["rejected"] == 1
    err = capsys.readouterr().err
    assert sorted(p.name for p in library.skills_dest.iterdir()) == ["good"]
    assert "REJECTED skills/anchored: remote installs cannot read the frontmatter name without PyYAML" in err
    assert "anchor, tag or alias" in err


def test_library_problems_report_a_name_read_differently_without_pyyaml(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    write_skill(skills / "good")
    write_skill(skills / "other")
    reader = ss._installer()
    real = reader.frontmatter_name
    monkeypatch.setattr(
        reader, "frontmatter_name", lambda data, label: "renamed" if label == "other" else real(data, label)
    )
    assert ss.library_problems(skills) == ["other: frontmatter name 'other' reads as 'renamed' without PyYAML"]


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
    assert set(ss.build_index(skills)["skills"]) == {"good"}
    assert (tmp_path / installer.INDEX).read_text(encoding="utf-8") == ss.index_text(ss.build_index(skills))


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


@pytest.mark.skipif(os.name == "nt", reason="the sync runs on Linux; creating links needs privileges on Windows")
def test_an_upstream_link_is_followed_only_to_a_file_of_its_own_checkout(pipeline, tmp_path, capsys):
    """A link out of the upstream checkout, as to the runner's .git/config, must never become the
    bytes of a library file that the weekly job commits and pushes."""
    library, _, builders = pipeline
    secret = tmp_path / "runner/work/awesome-skills/.git/config"
    secret.parent.mkdir(parents=True)
    secret.write_text('[http]\n\textraheader = "AUTHORIZATION: basic SECRET"\n')

    def upstream(dest: Path):
        write_skill(dest / "skills/leak")
        (dest / "skills/leak/notes.txt").symlink_to(secret)
        write_skill(dest / "skills/linked-skill-md")
        (dest / "skills/linked-skill-md/SKILL.md").unlink()
        (dest / "skills/linked-skill-md/SKILL.md").symlink_to(secret)
        write_skill(dest / "skills/own-git")
        (dest / ".git").mkdir()
        (dest / ".git/config").write_text("[remote]\n\turl = SECRET\n")
        (dest / "skills/own-git/config").symlink_to("../../.git/config")
        write_skill(dest / "skills/shared-license", extra={"../../shared/LICENSE": "MIT\n"})
        (dest / "skills/shared-license/LICENSE").symlink_to("../../shared/LICENSE")

    builders.append(upstream)
    stats = sync(pipeline)
    err = capsys.readouterr().err
    assert sorted(p.name for p in library.skills_dest.iterdir()) == ["shared-license"]
    license_file = library.skills_dest / "shared-license/LICENSE"
    assert not license_file.is_symlink() and license_file.read_text() == "MIT\n", "a file of the checkout is copied"
    assert stats["rejected"] == 3 and "REJECTED skills/leak: notes.txt: symbolic link" in err
    assert "SKILL.md: symbolic link" in err and "config: symbolic link" in err
    assert "SECRET" not in err and secret.read_text().count("SECRET") == 1


def test_portability_rules():
    assert installer.name_problem("aux.md") and installer.name_problem("x.") and installer.name_problem("a:b")
    assert not installer.name_problem("console.md")
    assert installer.path_problems(["Docs/a.md", "docs/b.md"]) == ["docs: differs only in case from Docs"]
    problems = installer.skill_problems("ok", {"SKILL.md": "file", "lib": "link", "vendor": "submodule"})
    assert problems == ["lib: symbolic link", "vendor: submodule"]
    assert installer.case_collisions(["Pdb", "pdb"], {"pdb"}) == {"Pdb": "differs only in case from pdb"}
    assert set(installer.case_collisions(["Pdb", "pdb"])) == {"Pdb", "pdb"}


def test_column_zero_frontmatter_is_indented_not_rejected(pipeline):
    library, _, builders = pipeline

    def upstream(dest: Path):
        root = dest / "skills/folded"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text('---\nname: folded\ndescription: "One.\n\nTwo: three."\n---\nbody\n')

    builders.append(upstream)
    assert sync(pipeline)["rejected"] == 0
    text = (library.skills_dest / "folded/SKILL.md").read_text()
    assert text == '---\nname: folded\ndescription: "One.\n\n  Two: three."\n---\nbody\n'
    assert ss.build_index(library.skills_dest)["skills"]["folded"] == {
        "name": "folded",
        "description": "One.\nTwo: three.",
    }


def test_frontmatter_claude_code_cannot_parse_is_a_problem(tmp_path):
    """The sanitizer fixes this shape before the check runs; the library check still catches
    content that bypassed it."""
    root = write_skill(tmp_path / "raw")
    (root / "SKILL.md").write_text('---\nname: raw\ndescription: "One\nTwo"\n---\n')
    assert ss.candidate_problems(root, "raw") == [
        "frontmatter has a multi-line quoted scalar or flow collection with a line not indented past its key, "
        "which Claude Code cannot parse"
    ]
    assert ss.library_problems(tmp_path) == [f"raw: {ss.candidate_problems(root, 'raw')[0]}"]


def test_a_value_holding_three_dashes_is_rejected_after_sanitizing(pipeline, capsys):
    """Claude Code ends the frontmatter at the first `---` anywhere, then cannot parse the rest and
    drops every field, disable-model-invocation included; the sanitizer quotes this description."""
    library, _, builders = pipeline

    def upstream(dest: Path):
        write_skill(dest / "skills/good")
        dashed = dest / "skills/dashed"
        dashed.mkdir(parents=True)
        (dashed / "SKILL.md").write_text(
            "---\nname: dashed\ndescription: Format: split notes on --- lines, then summarize each part\n---\n"
        )

    builders.append(upstream)
    assert sync(pipeline)["rejected"] == 1
    assert sorted(p.name for p in library.skills_dest.iterdir()) == ["good"]
    assert "REJECTED skills/dashed: frontmatter holds `---` before its closing line" in capsys.readouterr().err


def test_reserved_codex_system_names_get_a_source_qualified_id(pipeline):
    library, _, builders = pipeline
    builders.append(
        lambda dest: [write_skill(dest / f"skills/{name}") for name in ("skill-creator", "Imagegen", "fine")]
    )
    assert sync(pipeline)["new"] == 3
    names = sorted(p.name for p in library.skills_dest.iterdir())
    assert names[0] == "Imagegen--one--" + names[0].rsplit("--", 1)[1]
    assert names[1] == "fine" and names[2].startswith("skill-creator--one--")
    assert ss.library_problems(library.skills_dest) == []


def test_a_reserved_library_id_breaks_the_rules(tmp_path):
    write_skill(tmp_path / "openai-docs")
    write_skill(tmp_path / "docs")
    write_skill(tmp_path / "security-review")
    assert ss.library_problems(tmp_path) == [
        "openai-docs: reserved for a bundled Codex system skill",
        "security-review: reserved for a Claude Code command or bundled skill",
    ]


def test_claude_code_command_names_get_a_source_qualified_id(pipeline):
    """With such an ID the library copy would take over Claude Code's own /init or /claude-api."""
    library, _, builders = pipeline
    builders.append(lambda dest: [write_skill(dest / f"skills/{name}") for name in ("init", "Claude-API", "fine")])
    assert sync(pipeline)["new"] == 3
    names = sorted(p.name for p in library.skills_dest.iterdir())
    assert names[0].startswith("Claude-API--one--") and names[1] == "fine" and names[2].startswith("init--one--")
    assert ss.library_problems(library.skills_dest) == []


def test_reserved_library_ids_move_to_their_variant_with_provenance(tmp_path):
    skills = tmp_path / "skills"
    write_skill(skills / "review-agent", extra={"notes.md": "kept\n"})
    write_skill(skills / "legacy-only")
    library = ss.LibrarySources(skills, tmp_path / "library_sources.json")
    url = ss.UPSTREAMS[0][0]
    library.entries["review-agent"]["origins"].append({"repository": url, "path": "x/review-agent", "current": True})
    digest = library.entries["review-agent"]["digest"]
    library.save()
    library = ss.LibrarySources(skills, tmp_path / "library_sources.json")
    [(old, new)] = library.release_reserved()
    assert old == "review-agent" and new.startswith(f"review-agent--{ss.UPSTREAMS[0][1]}--")
    library.save()
    assert sorted(p.name for p in skills.iterdir()) == ["legacy-only", new]
    assert (skills / new / "notes.md").read_text() == "kept\n"
    entries = ss.LibrarySources(skills, tmp_path / "library_sources.json").entries
    assert "review-agent" not in entries and entries[new]["digest"] == digest
    assert not entries[new].get("locally_modified")
    assert [o.get("repository") for o in entries[new]["origins"]] == [None, url]
    assert ss.LibrarySources(skills, tmp_path / "library_sources.json").release_reserved() == []


def test_a_variant_id_fits_a_codex_name(tmp_path):
    library = ss.LibrarySources(tmp_path / "skills", tmp_path / "library_sources.json")
    origin = {"repository": ss.UPSTREAMS[0][0], "path": "skills/x"}
    base = "spatial-transcriptomics-deconvolution-cell2location"  # 51 characters, a real base ID
    long = library._variant_id(base, "academic-humanizer", origin)
    assert len(long) <= ss.VARIANT_ID_MAX and installer.CODEX_NAME.fullmatch(long)
    assert long.startswith(base[:20]) and long.endswith(library._variant_id("x", "academic-humanizer", origin)[1:])
    library.entries[long] = {"origins": []}
    taken = library._variant_id(base, "academic-humanizer", origin)
    assert taken == f"{long}-2" and len(taken) <= 64
    short = library._variant_id("pdb", "gdm-science", origin)
    assert short.startswith("pdb--gdm-science--") and len(short) == len("pdb--gdm-science--") + 10, "unchanged"


def library_paths(monkeypatch, tmp_path: Path) -> Path:
    skills = tmp_path / "skills"
    for name, value in [
        ("SKILLS_DEST", skills),
        ("LIBRARY_SOURCES_PATH", tmp_path / "library_sources.json"),
        ("LIBRARY_INDEX_PATH", tmp_path / installer.INDEX),
    ]:
        monkeypatch.setattr(ss, name, value)
    return skills


def test_sanitize_only_keeps_the_library_records_in_step(tmp_path, monkeypatch):
    skills = library_paths(monkeypatch, tmp_path)
    for skill_id in ("folded", "edited"):
        root = write_skill(skills / skill_id)
        (root / "SKILL.md").write_text(f'---\nname: {skill_id}\ndescription: "One\nTwo"\n---\n')
    ss.LibrarySources(skills, tmp_path / "library_sources.json").save()
    (skills / "edited/extra.md").write_text("a local edit\n")  # recorded digest no longer matches
    assert ss.sanitize_only(skills) == 0
    assert (skills / "folded/SKILL.md").read_text() == '---\nname: folded\ndescription: "One\n  Two"\n---\n'
    library = ss.LibrarySources(skills, tmp_path / "library_sources.json")
    assert library.entries["folded"]["digest"] == ss.skill_tree_digest(skills / "folded")
    assert not library.entries["folded"].get("locally_modified")
    assert library.entries["edited"]["locally_modified"] is True
    assert library.entries["edited"]["digest"] != ss.skill_tree_digest(skills / "edited")
    assert ss.library_problems(skills) == []
    index = installer.read_json(tmp_path / installer.INDEX, {})["skills"]
    assert sorted(index) == ["edited", "folded"]
    snapshot = (tmp_path / "library_sources.json").read_bytes()
    assert ss.sanitize_only(skills) == 0
    assert (tmp_path / "library_sources.json").read_bytes() == snapshot


def test_sanitize_only_moves_reserved_ids(tmp_path, monkeypatch, capsys):
    skills = library_paths(monkeypatch, tmp_path)
    write_skill(skills / "skill-installer")
    ss.LibrarySources(skills, tmp_path / "library_sources.json").save()
    assert ss.sanitize_only(skills) == 0
    [moved] = [p.name for p in skills.iterdir()]
    assert moved.startswith("skill-installer--legacy--")
    assert f"moved: skills/skill-installer -> skills/{moved}" in capsys.readouterr().out
    assert sorted(installer.read_json(tmp_path / installer.INDEX, {})["skills"]) == [moved]
    assert sorted(ss.LibrarySources(skills, tmp_path / "library_sources.json").entries) == [moved]


@pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")
def test_git_reads_no_repository_above_the_folder_it_runs_in(tmp_path, monkeypatch):
    """The sync's git commands run with discovery stopped above their folder: a temporary directory
    may hold another user's .git, whose configuration git would otherwise honor."""
    commit = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x"]
    planted, staging = tmp_path / "shared", tmp_path / "shared/staging"
    subprocess.run(["git", "init", "-q", str(planted)], check=True)
    subprocess.run(["git", "-C", str(planted), *commit], check=True)
    (staging / "one").mkdir(parents=True)  # a clone that left no repository
    assert ss.run(["git", "rev-parse", "HEAD"], cwd=staging / "one", check=False).returncode != 0
    calls = []
    monkeypatch.setattr(ss.subprocess, "run", lambda command, **options: calls.append(options) or SimpleNamespace())
    assert ss.shallow_clone("https://example.test/one.git", staging / "two")
    assert calls[0]["cwd"] == staging, "the clone runs in the private staging folder"
    assert calls[0]["env"]["GIT_CEILING_DIRECTORIES"] == str(planted.resolve())
