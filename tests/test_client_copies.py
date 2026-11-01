"""The per-client form of an installed copy: plugin folders dropped, hidden copies flagged, Codex
names set to the ID. Pure functions of the library tree, checked here and on the live library."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import install_skills as installer
from scripts import sync_skills as ss

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = installer.HIDDEN_KEY


def frontmatter(data: bytes) -> dict:
    return yaml.safe_load(installer.frontmatter(data, "fixture"))


def tree(files: dict) -> tuple[dict, callable]:
    """A listing (rel -> (mode, oid)) and a reader for a skill given as rel -> text."""
    data = {rel: text.encode() for rel, text in files.items()}
    listing = {rel: ("100644", installer.blob_id(raw)) for rel, raw in data.items()}
    return listing, data.__getitem__


def edits(client, invocation, files, skill_id="alpha"):
    listing, read = tree(files)
    return installer.copy_edits(client, skill_id, invocation, listing, read)


SKILL = "---\nname: shared-name\ndescription: First.\n---\nbody\n"


def test_a_visible_claude_copy_is_the_library_tree():
    assert edits("claude", "auto", {"SKILL.md": SKILL, "sub/SKILL.md": SKILL}) == {}


def test_a_hidden_claude_copy_carries_the_key_only_in_its_top_level_skill():
    out = edits("claude", "manual", {"SKILL.md": SKILL, "sub/SKILL.md": SKILL})
    assert list(out) == ["SKILL.md"]
    assert frontmatter(out["SKILL.md"]) == {HIDDEN: True, "name": "shared-name", "description": "First."}


def test_a_visible_codex_copy_is_named_after_its_id():
    out = edits("codex", "auto", {"SKILL.md": SKILL})
    assert out == {"SKILL.md": b'---\nname: "alpha"\ndescription: First.\n---\nbody\n'}
    assert edits("codex", "auto", {"SKILL.md": SKILL.replace("shared-name", "alpha")}) == {}


@pytest.mark.parametrize(
    "line", ["name: 'shared-name'", 'name: "shared-name"  # upstream', '"name": shared-name', "name : shared-name"]
)
def test_every_one_line_spelling_of_the_name_is_replaced(line):
    data = f"---\n{line}\ndescription: First.\n---\n".encode()
    out = installer.renamed_skill_md(data, "alpha", "alpha")
    assert out == b'---\nname: "alpha"\ndescription: First.\n---\n'


def test_a_missing_name_is_added_and_bom_and_crlf_stay():
    out = installer.renamed_skill_md(b"\xef\xbb\xbf---\r\ndescription: First.\r\n---\r\n", "alpha", "alpha")
    assert out == b'\xef\xbb\xbf---\r\nname: "alpha"\r\ndescription: First.\r\n---\r\n'


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"---\nname: >\n  shared\ndescription: x\n---\n", "not a one-line top-level key"),
        (b"---\nname: a\nname: b\n---\n", "more than one top-level name"),
        (b"no frontmatter\n", "missing frontmatter"),
    ],
)
def test_names_that_cannot_be_replaced_line_by_line_are_refused(data, reason):
    with pytest.raises(installer.InstallError, match=reason):
        installer.renamed_skill_md(data, "alpha", "alpha")


def test_a_nested_skill_gets_a_unique_name_and_stays_out_of_the_codex_catalog():
    out = edits("codex", "auto", {"SKILL.md": SKILL, "tools/sub dir/SKILL.md": SKILL})
    assert frontmatter(out["tools/sub dir/SKILL.md"])["name"] == "alpha--tools-sub-dir"
    assert yaml.safe_load(out["tools/sub dir/agents/openai.yaml"]) == {"policy": {"allow_implicit_invocation": False}}
    assert "agents/openai.yaml" not in out, "a visible top-level copy keeps its policy"


def test_long_nested_names_are_shortened_with_a_hash():
    name = installer.nested_name("a" * 60, "deep/er/SKILL.md")
    assert len(name) == 64 and name.startswith("a" * 53 + "-")
    assert name != installer.nested_name("a" * 60, "deep/est/SKILL.md")


def test_a_hidden_codex_copy_gets_the_policy_the_name_and_the_claude_key():
    files = {"SKILL.md": SKILL, "agents/openai.yaml": "interface:\n  display_name: A\n"}
    out = edits("codex", "manual", files)
    assert frontmatter(out["SKILL.md"]) == {HIDDEN: True, "name": "alpha", "description": "First."}
    assert yaml.safe_load(out["agents/openai.yaml"]) == {
        "interface": {"display_name": "A"},
        "policy": {"allow_implicit_invocation": False},
    }


def test_a_policy_shape_the_installer_cannot_edit_fails_the_skill():
    with pytest.raises(installer.InstallError, match="not a block-style mapping"):
        edits("codex", "manual", {"SKILL.md": SKILL, "agents/openai.yaml": "policy: true\n"})


def test_plugin_folders_are_dropped_from_every_copy(tmp_path):
    files = {"SKILL.md": SKILL, ".claude-plugin/plugin.json": "{}", "x/.codex-plugin/p.json": "{}", "y.txt": "y"}
    listing, read = tree(files)
    for client in ("claude", "codex"):
        found = installer.copy_edits(client, "alpha", "auto", listing, read)
        assert sorted(installer.derived_listing(listing, found)) == ["SKILL.md", "y.txt"]
    target = tmp_path / "alpha"
    for rel, text in files.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text)
    (target / ".cursor-plugin").mkdir()  # an empty one too
    changed = installer.copy_edits("codex", "alpha", "manual", listing, read)
    installer.apply_edits(target, changed)
    assert installer.same_tree(installer.derived_listing(listing, changed), target)
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*")) == [
        "SKILL.md",
        "agents",
        "agents/openai.yaml",
        "x",
        "y.txt",
    ]


@pytest.mark.parametrize("skill_id", ["a" * 65, "with.dot"])
def test_a_codex_copy_needs_an_id_codex_loads_and_mentions(tmp_path, skill_id):
    """Codex refuses a name over 64 characters; `$NAME` stops at any other character."""
    with pytest.raises(installer.InstallError, match="Codex cannot name a skill"):
        edits("codex", "auto", {"SKILL.md": SKILL}, skill_id=skill_id)
    assert list(edits("claude", "manual", {"SKILL.md": SKILL}, skill_id=skill_id)) == ["SKILL.md"]
    (tmp_path / skill_id).mkdir()
    (tmp_path / skill_id / "SKILL.md").write_text(SKILL)
    assert any("Codex cannot name a skill" in p for p in ss.candidate_problems(tmp_path / skill_id, skill_id))
    assert edits("codex", "auto", {"SKILL.md": SKILL}, skill_id="a" * 64), "64 characters are fine"


def test_the_sync_rejects_a_skill_whose_codex_copy_cannot_be_named(tmp_path):
    root = tmp_path / "alpha"
    (root / "sub").mkdir(parents=True)
    (root / "SKILL.md").write_text(SKILL)
    (root / "sub/SKILL.md").write_text("---\nname: >\n  folded\ndescription: x\n---\n")
    problems = ss.candidate_problems(root, "alpha")
    assert any("Cannot rename alpha/sub/SKILL.md" in p for p in problems), problems
    (root / "sub/SKILL.md").write_text("---\nname: plain\ndescription: x\n---\n")
    assert ss.candidate_problems(root, "alpha") == []


def test_every_transform_of_the_live_library_reads_as_before_plus_its_change():
    """PyYAML parity of every client copy of every committed skill: only the edited keys change."""
    skills = ROOT / "skills"
    differing = []
    for skill_id in installer.skill_ids(skills):
        directory = skills / skill_id
        listing = installer.local_listing(directory)
        for client, invocation in (("claude", "manual"), ("codex", "auto"), ("codex", "manual")):
            found = installer.copy_edits(
                client, skill_id, invocation, listing, lambda rel, d=directory: (d / rel).read_bytes()
            )
            for rel, data in found.items():
                before = (directory / rel).read_bytes() if rel in listing else None
                if rel.endswith("SKILL.md"):
                    expected = frontmatter(before)
                    if client == "codex":
                        expected["name"] = skill_id if rel == "SKILL.md" else installer.nested_name(skill_id, rel)
                        assert installer.frontmatter_name(data, rel) == expected["name"]
                    if invocation == "manual" and rel == "SKILL.md":
                        expected[HIDDEN] = True
                    actual = frontmatter(data)
                else:
                    expected = yaml.safe_load(before) if before else {}
                    expected["policy"] = {**expected.get("policy", {}), "allow_implicit_invocation": False}
                    actual = yaml.safe_load(data)
                if actual != expected:
                    differing.append((skill_id, client, invocation, rel))
    assert not differing, differing[:20]
