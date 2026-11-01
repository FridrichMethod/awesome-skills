"""The committed library_index.json must describe skills/ exactly as the installer reads it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from scripts import install_skills as installer
from scripts import sync_skills

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_INVALID = re.compile(r'[<>:"|?*\x00-\x1f\\]|[. ]$|^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$', re.IGNORECASE)


def test_committed_index_matches_the_skill_tree():
    expected = sync_skills.index_text(sync_skills.build_index(ROOT / "skills"))
    actual = (ROOT / installer.INDEX).read_text(encoding="utf-8")
    assert actual == expected, "regenerate it: python scripts/sync_skills.py --index-only"


def test_every_library_name_reads_the_same_without_pyyaml():
    """A remote install checks each copy's name with the standard-library reader against the index."""
    index = installer.read_json(ROOT / installer.INDEX, {})["skills"]
    names = {}
    for skill_id in installer.skill_ids(ROOT / "skills"):
        try:
            names[skill_id] = installer.frontmatter_name(
                (ROOT / "skills" / skill_id / "SKILL.md").read_bytes(), skill_id
            )
        except installer.InstallError as error:
            names[skill_id] = str(error)
    differing = {skill_id: name for skill_id, name in names.items() if name != index[skill_id]["name"]}
    assert not differing, list(differing.items())[:20]


def test_sync_writes_the_index_only_when_it_changes(tmp_path):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha/SKILL.md").write_text("---\nname: alpha\ndescription: First.\n---\n")
    (skills / ".hidden").mkdir()
    index = tmp_path / installer.INDEX
    assert sync_skills.write_library_index(skills, index)
    first = index.stat().st_mtime_ns
    assert not sync_skills.write_library_index(skills, index)
    assert index.stat().st_mtime_ns == first
    (skills / "beta").mkdir()
    (skills / "beta/SKILL.md").write_text("---\nname: beta\ndescription: Second.\n---\n")
    assert sync_skills.write_library_index(skills, index)
    assert sync_skills.build_index(skills)["skills"] == {
        "alpha": {"name": "alpha", "description": "First."},
        "beta": {"name": "beta", "description": "Second."},
    }
    assert index.read_text(encoding="utf-8") == sync_skills.index_text(sync_skills.build_index(skills))


def test_skill_paths_check_out_on_windows():
    """Git on Windows refuses reserved or invalid names and collapses case-only differences."""
    paths = [p.relative_to(ROOT).as_posix() for p in (ROOT / "skills").rglob("*")]
    invalid = [p for p in paths if any(WINDOWS_INVALID.search(part) for part in p.split("/"))]
    assert not invalid, invalid[:20]
    folded = {}
    collisions = [p for p in paths if folded.setdefault(p.lower(), p) != p]
    assert not collisions, collisions[:20]


def test_committed_library_passes_the_sync_rules():
    """What the weekly sync would refuse to commit: portability, name parity, frontmatter Claude
    Code cannot parse, skills the installer could not hide, and reserved IDs."""
    assert sync_skills.library_problems(ROOT / "skills") == []


def test_committed_provenance_digests_match_the_skill_tree():
    """A recorded digest that drifted from its tree would mark the copy locally modified, and the
    next sync would add a duplicate variant instead of updating or deduplicating it."""
    provenance = json.loads((ROOT / installer.PROVENANCE).read_text(encoding="utf-8"))
    ids = installer.skill_ids(ROOT / "skills")
    assert sorted(provenance) == ids
    drifted = [
        skill_id
        for skill_id in ids
        if not provenance[skill_id].get("locally_modified")
        and provenance[skill_id]["digest"] != sync_skills.skill_tree_digest(ROOT / "skills" / skill_id)
    ]
    assert not drifted, drifted[:20]


def flush_quoted_lines(text: str) -> str:
    """The shape canonicalization B repairs: every line of a multi-line quoted scalar at column 0."""
    lines = text.split("\n")
    for token in yaml.scan(text):
        if isinstance(token, yaml.ScalarToken) and token.style in ('"', "'"):
            for row in range(token.start_mark.line + 1, token.end_mark.line + 1):
                lines[row] = lines[row].lstrip(" ")
    return "\n".join(lines)


def test_canonicalization_b_reads_every_library_frontmatter_the_same():
    """For every SKILL.md: PyYAML's whole frontmatter and the standard-library name stay the same
    when B repairs the column-0 form of each multi-line quoted scalar, and B leaves no line that
    Claude Code would reject."""
    checked = 0
    for skill_id in installer.skill_ids(ROOT / "skills"):
        text = installer.frontmatter((ROOT / "skills" / skill_id / "SKILL.md").read_bytes(), skill_id)
        assert sync_skills._indent_flow_lines(text) == text, skill_id
        flush = flush_quoted_lines(text)
        if flush == text:
            continue
        checked += 1
        repaired = sync_skills._indent_flow_lines(flush)
        assert sync_skills._shallow_flow_lines(repaired) == [], skill_id
        for variant in (flush, repaired):
            assert yaml.safe_load(variant) == yaml.safe_load(text), skill_id
            assert installer.NameReader(variant).read() == installer.NameReader(text).read(), skill_id
    assert checked >= 30  # the 29 repaired files and math-olympiad
