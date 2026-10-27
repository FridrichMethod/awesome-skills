"""The committed library_index.json must describe skills/ exactly as the installer reads it."""

from __future__ import annotations

import re
from pathlib import Path

from scripts import install_skills as installer
from scripts import sync_skills

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_INVALID = re.compile(r'[<>:"|?*\x00-\x1f\\]|[. ]$|^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$', re.IGNORECASE)


def test_committed_index_matches_the_skill_tree():
    expected = installer.index_text(installer.build_index(ROOT / "skills"))
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
    assert installer.build_index(skills)["skills"] == {
        "alpha": {"name": "alpha", "description": "First."},
        "beta": {"name": "beta", "description": "Second."},
    }
    assert index.read_text(encoding="utf-8") == installer.index_text(installer.build_index(skills))


def test_skill_paths_check_out_on_windows():
    """Git on Windows refuses reserved or invalid names and collapses case-only differences."""
    paths = [p.relative_to(ROOT).as_posix() for p in (ROOT / "skills").rglob("*")]
    invalid = [p for p in paths if any(WINDOWS_INVALID.search(part) for part in p.split("/"))]
    assert not invalid, invalid[:20]
    folded = {}
    collisions = [p for p in paths if folded.setdefault(p.lower(), p) != p]
    assert not collisions, collisions[:20]
