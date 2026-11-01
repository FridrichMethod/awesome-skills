"""Visible and hidden installs: what each client shows the model, the Codex roots and their limit,
and the one-time migration of states written before hidden installs. Temporary HOME only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_skills as installer
from tests.gitfixtures import snapshot
from tests.test_install import can_symlink, codex_copy, hidden_from_claude, hidden_from_codex, skill, state_dir

ROOT = Path(__file__).resolve().parents[1]
ROUTER = installer.ROUTER


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    previous = os.umask(0o022)  # canonical modes, so exact copies can be adopted
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "repo/skills"
    for skill_id in ("alpha", "beta"):
        skill(source, skill_id)
    for key in list(os.environ):
        if key.startswith("SKILLS_"):
            monkeypatch.delenv(key)
    for key in ("XDG_DATA_HOME", "CODEX_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData/Local"))
    yield home, source
    os.umask(previous)


def run(source, *args):
    return installer.main(["--source", str(source), *args])


def state(home, client):
    return json.loads((state_dir(home) / f"{client}.json").read_text())


def plan(capsys) -> dict:
    return json.loads(capsys.readouterr().out.split("Recovery backup:")[0])


def name_of(path: Path) -> str:
    return installer.frontmatter_name((path / "SKILL.md").read_bytes(), str(path))


# --- Visible and hidden ------------------------------------------------------------------


def test_enable_and_disable_change_only_what_the_model_sees(sandbox, capsys):
    home, source = sandbox
    run(source)
    claude = home / ".claude/skills"
    beta = installer.fingerprint(claude / "beta")
    capsys.readouterr()
    run(source, "--claude-only", "--enable", "alpha")
    assert [a["entry"] for a in plan(capsys)["clients"][0]["actions"]] == ["alpha"]
    assert not hidden_from_claude(claude / "alpha") and installer.fingerprint(claude / "beta") == beta
    assert state(home, "claude")["managed"]["alpha"]["invocation"] == "auto"
    run(source, "--claude-only", "--disable", "alpha")
    assert hidden_from_claude(claude / "alpha"), "a deselected skill stays installed, hidden"
    assert state(home, "claude")["selection"] == ["@library"]


def test_the_manual_set_decides_what_else_is_installed(sandbox):
    home, source = sandbox
    run(source)
    claude = home / ".claude/skills"
    run(source, "--claude-only", "--manual", "beta")
    assert sorted(os.listdir(claude)) == [ROUTER, "beta"] and hidden_from_claude(claude / "beta")
    run(source)
    assert state(home, "claude")["manual"] == ["beta"], "kept by later runs without flags"
    run(source, "--claude-only", "--manual", "")
    assert sorted(os.listdir(claude)) == [ROUTER]
    run(source, "--claude-only", "--manual", "@all")
    assert sorted(os.listdir(claude)) == ["alpha", ROUTER, "beta"]
    with pytest.raises(SystemExit):
        run(source, "--manual", "")  # selection changes need a client
    with pytest.raises(installer.InstallError, match="Unknown source IDs"):
        run(source, "--claude-only", "--manual", "missing")


def test_a_user_edit_to_a_hidden_copy_survives_toggles_and_updates(sandbox):
    home, source = sandbox
    run(source)
    alpha = home / ".claude/skills/alpha"
    (alpha / "helper.txt").write_text("user edit\n")
    edited, record = installer.fingerprint(alpha), state(home, "claude")["managed"]["alpha"]["sha256"]
    run(source, "--claude-only", "--enable", "alpha")
    run(source, "--claude-only", "--disable", "alpha")
    (source / "alpha/helper.txt").write_text("upstream change\n")
    run(source)
    assert installer.fingerprint(alpha) == edited
    assert state(home, "claude")["managed"]["alpha"]["sha256"] == record


def test_a_local_policy_file_that_cannot_take_the_key_fails_its_skill(sandbox, capsys):
    home, source = sandbox
    gamma = skill(source, "gamma")  # a --source tree, which the sync never checked
    (gamma / "agents").mkdir()
    (gamma / "agents/openai.yaml").write_text("interface:\n  display_name: Gamma\n...\n")
    capsys.readouterr()
    assert run(source, "--codex-only") == 1, "not installed as if hidden while Codex would list it"
    err = capsys.readouterr().err
    assert "codex:gamma (Cannot hide gamma/SKILL.md: agents/openai.yaml is not one block mapping at column 0)" in err
    assert not codex_copy(home, "gamma").exists() and hidden_from_codex(codex_copy(home, "alpha"))


# Local shapes the line-by-line edits take but whose copies would not read as hidden: an explicit or
# escaped key later turns the inserted `true` back to false; Claude Code ignores frontmatter with a
# column-0 continuation line (PyYAML does not) or with `---` before its closing line (Claude ends it
# there); the policy block lands inside a quoted string.
LOCAL_SHAPES = {
    "explicit-key": ("---\nname: gamma\ndescription: g\n? disable-model-invocation\n: false\n---\n", None),
    "escaped-key": ('---\nname: gamma\ndescription: g\n"disable\\x2dmodel-invocation": false\n---\n', None),
    "column-0-line": ('---\nname: gamma\ndescription: "Spans lines,\nthe next at column 0"\n---\n', None),
    "dashes-in-a-value": ('---\nname: gamma\ndescription: "Format: split notes on --- lines"\n---\n', None),
    "policy-in-a-string": (
        "---\nname: gamma\ndescription: g\n---\n",
        'interface:\n  prompt: "Draft a\npolicy:\n  plan"\n',
    ),
}


@pytest.mark.parametrize("skill_md, policy", LOCAL_SHAPES.values(), ids=list(LOCAL_SHAPES))
def test_a_local_skill_the_sync_would_reject_gets_no_edited_copy(sandbox, capsys, skill_md, policy):
    home, source = sandbox
    gamma = source / "gamma"  # a --source tree, which the sync never checked
    gamma.mkdir()
    (gamma / "SKILL.md").write_text(skill_md)
    if policy:
        (gamma / "agents").mkdir()
        (gamma / "agents/openai.yaml").write_text(policy)
    capsys.readouterr()
    assert run(source) == 1
    err = capsys.readouterr().err
    assert "claude:gamma (Cannot install gamma: " in err and "codex:gamma (Cannot " in err
    assert not (home / ".claude/skills/gamma").exists() and not codex_copy(home, "gamma").exists()
    assert hidden_from_claude(home / ".claude/skills/alpha") and hidden_from_codex(codex_copy(home, "alpha"))
    assert run(source, "--claude-only", "--selection", "@library,gamma") == 0, "a visible Claude copy is not edited"
    assert (home / ".claude/skills/gamma/SKILL.md").read_text() == skill_md


def test_an_upstream_change_is_installed_still_hidden(sandbox):
    home, source = sandbox
    run(source)
    (source / "alpha/helper.txt").write_text("upstream change\n")
    run(source)
    for copy in (home / ".claude/skills/alpha", codex_copy(home, "alpha")):
        assert (copy / "helper.txt").read_text() == "upstream change\n"
    assert hidden_from_claude(home / ".claude/skills/alpha") and hidden_from_codex(codex_copy(home, "alpha"))


def test_an_upstream_change_that_leaves_the_copies_as_they_are_moves_nothing(sandbox, capsys):
    """A changed tree is copied again without being compared first; a copy that comes out the
    same (the change was in a dropped plugin folder) is recorded, and the transaction restores."""
    home, source = sandbox
    (source / "alpha/.claude-plugin").mkdir()
    (source / "alpha/.claude-plugin/plugin.json").write_text("{}\n")
    run(source)
    copies = [home / ".claude/skills/alpha", codex_copy(home, "alpha")]
    before = [snapshot(copy) for copy in copies]
    records = {client: state(home, client) for client in ("claude", "codex")}
    (source / "alpha/.claude-plugin/plugin.json").write_text('{"version": "2"}\n')
    capsys.readouterr()
    assert run(source) == 0
    assert all(not client["actions"] and not client["failed"] for client in plan(capsys)["clients"])
    assert [snapshot(copy) for copy in copies] == before
    tree = installer.tree_id(installer.local_listing(source / "alpha"))
    assert all(state(home, client)["managed"]["alpha"]["tree"] == tree for client in records)
    assert run(source) == 0 and "Already current" in capsys.readouterr().out
    backup = sorted((state_dir(home) / "backups").iterdir())[-1]
    assert installer.main(["--restore", str(backup)]) == 0
    assert {client: state(home, client) for client in records} == records


def test_exact_client_copies_are_adopted_and_raw_trees_only_when_named(sandbox, capsys):
    home, source = sandbox
    run(source)
    for client in ("claude", "codex"):
        (state_dir(home) / f"{client}.json").unlink()
    claude = home / ".claude/skills"
    shutil.rmtree(claude / "beta")
    shutil.copytree(source / "beta", claude / "beta")  # the library tree, which any tool may copy
    alpha, beta = installer.fingerprint(claude / "alpha"), installer.fingerprint(claude / "beta")
    capsys.readouterr()
    run(source, "--claude-only")
    claude_plan = plan(capsys)["clients"][0]
    assert not claude_plan["actions"], "the exact hidden alpha is recorded, and @all names no raw tree"
    assert {"entry": "beta", "reason": "protected, modified, or unproven ownership"} in claude_plan["preserved"]
    assert installer.fingerprint(claude / "alpha") == alpha and installer.fingerprint(claude / "beta") == beta
    assert set(state(home, "claude")["managed"]) == {"alpha"}, "an unmanaged router folder stays unclaimed"
    run(source, "--claude-only", "--manual", "alpha,beta")
    actions = [a["entry"] for a in plan(capsys)["clients"][0]["actions"]]
    assert actions == ["beta"], "a raw tree whose ID is named is claimed and copied again"
    assert hidden_from_claude(claude / "beta") and set(state(home, "claude")["managed"]) == {"alpha", "beta"}


def test_only_this_installers_copies_are_claimed_in_the_shared_agents_root(sandbox, capsys):
    home, source = sandbox
    run(source, "--codex-only")
    second = home / ".agents/skills"
    assert installer.placement("beta") and hidden_from_codex(second / "beta")
    (state_dir(home) / "codex.json").unlink()
    run(source, "--codex-only")
    assert "beta" in state(home, "codex")["managed"], "an exact hidden Codex copy is this installer's"
    shutil.rmtree(second / "beta")
    shutil.copytree(source / "beta", second / "beta")  # as `npx skills` would leave it
    (state_dir(home) / "codex.json").unlink()
    raw = installer.fingerprint(second / "beta")
    capsys.readouterr()
    run(source, "--codex-only")
    assert installer.fingerprint(second / "beta") == raw and "beta" not in state(home, "codex")["managed"]
    assert any(item["entry"] == "beta" and item.get("root") == 1 for item in plan(capsys)["clients"][0]["preserved"])
    with pytest.raises(installer.InstallError, match="preserved destination differs"):
        run(source, "--codex-only", "--manual", "beta")
    assert installer.fingerprint(second / "beta") == raw


def test_a_new_form_of_the_copies_reaches_installs_whose_tree_is_unchanged(sandbox, monkeypatch, capsys):
    home, source = sandbox
    run(source)
    assert state(home, "claude")["managed"]["alpha"]["form"] == installer.FORM
    original = installer.copy_edits

    def revised(client, skill_id, invocation, listing, read):  # a later fix of the transforms
        edits = original(client, skill_id, invocation, listing, read)
        return dict(edits, **{"NOTICE.txt": b"revised\n"}) if skill_id == "alpha" else edits

    monkeypatch.setattr(installer, "copy_edits", revised)
    run(source)
    assert not (home / ".claude/skills/alpha/NOTICE.txt").exists(), "the same form keeps the unchanged shortcut"
    monkeypatch.setattr(installer, "FORM", installer.FORM + 1)
    capsys.readouterr()
    run(source)
    assert [a["entry"] for c in plan(capsys)["clients"] for a in c["actions"]] == ["alpha", "alpha"]
    assert all((copy / "NOTICE.txt").is_file() for copy in (home / ".claude/skills/alpha", codex_copy(home, "alpha")))
    assert state(home, "codex")["managed"]["beta"]["form"] == installer.FORM, "recorded, not copied again"


def test_state_versions_and_records_are_validated():
    v1 = {"schema": 1, "client": "codex", "destination": "/x", "selection": ["@library"], "managed": {}}
    installer.validate_state(v1, "codex")
    v2 = dict(v1, manual=["@all"], selection_version=2, destination2="/y")
    v2["managed"] = {"a": {"sha256": "0" * 64, "invocation": "manual", "root": 1}}
    installer.validate_state(v2, "codex")
    for bad in (
        dict(v2, manual="@all"),
        dict(v2, selection_version=3),
        dict(v2, managed={"a": {"sha256": "0" * 64, "invocation": "hidden"}}),
        dict(v1, managed={"a": {"sha256": "0" * 64, "root": 1}}),
    ):
        with pytest.raises(installer.InstallError):
            installer.validate_state(bad, "codex")


# --- Codex roots ---------------------------------------------------------------------------


def test_codex_copies_split_between_two_roots_by_a_stable_hash(sandbox, monkeypatch):
    home, source = sandbox
    skill(source, "delta", name="shared-name")
    second = home / "custom-agents/skills"
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(second))
    run(source, "--codex-only")
    first = home / ".codex/skills"
    roots = {s: second if installer.placement(s) else first for s in ("alpha", "beta", "delta")}
    assert set(roots.values()) == {first, second}, "the fixture covers both roots"
    assert sorted(os.listdir(first)) == sorted([ROUTER, *(s for s, r in roots.items() if r == first)])
    assert sorted(os.listdir(second)) == sorted(s for s, r in roots.items() if r == second)
    assert all(name_of(r / s) == s and hidden_from_codex(r / s) for s, r in roots.items())
    record = state(home, "codex")
    assert record["destination2"] == str(installer.native(second))
    assert all(record["managed"][s].get("root", 0) == installer.placement(s) for s in roots)
    monkeypatch.delenv("SKILLS_CODEX_DEST2")
    before = installer.fingerprint(home)
    run(source, "--codex-only")
    assert installer.fingerprint(home) == before, "the saved second root is kept"


def test_codex_finds_its_second_root_however_home_is_spelled(sandbox, monkeypatch, capsys):
    home, source = sandbox
    monkeypatch.setenv("HOME", str(home / "../home"))
    skill(source, "delta")
    run(source, "--codex-only")
    second = [s for s in ("alpha", "beta", "delta") if installer.placement(s)]
    assert second and all((home / ".agents/skills" / s).is_dir() for s in second)
    capsys.readouterr()
    assert run(source, "--codex-only") == 0
    assert capsys.readouterr().out == "Already current; selection preserved.\n", "its own copies are not foreign"


def test_a_linked_second_codex_root_is_never_written_and_blocks_no_update(sandbox, tmp_path, monkeypatch, capsys):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    ids = ["alpha", "beta", *(f"extra-{i}" for i in range(6))]
    for skill_id in ids[2:]:
        skill(source, skill_id)
    shared = home / "shared-skills"  # ~/.agents/skills shared with other tools through a link
    skill(shared, "mine", body="the user's own")
    (home / ".agents").mkdir()
    (home / ".agents/skills").symlink_to(shared, target_is_directory=True)
    outside = installer.fingerprint(shared)
    capsys.readouterr()
    assert run(source) == 0
    assert "Refusing symlink directory or ancestor" in capsys.readouterr().err
    assert installer.fingerprint(shared) == outside
    assert all(hidden_from_claude(home / ".claude/skills" / s) for s in ids), "Claude is updated as usual"
    first, second = home / ".codex/skills", [s for s in ids if installer.placement(s)]
    assert second and sorted(os.listdir(first)) == sorted([ROUTER, *(s for s in ids if s not in second)])
    assert "destination2" not in state(home, "codex")
    assert run(source, "--codex-only", "--enable", second[0]) == 0, "a skill asked for by name goes to the first root"
    assert name_of(first / second[0]) == second[0] and not hidden_from_codex(first / second[0])
    assert installer.fingerprint(shared) == outside
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(home / ".agents/skills"))
    with pytest.raises(installer.InstallError, match="symlink"):
        run(source, "--codex-only")


@pytest.mark.parametrize("link", [".agents/skills", ".agents"])
def test_a_second_codex_root_linked_into_claudes_is_refused_while_both_clients_install(sandbox, tmp_path, link):
    """Codex reads ~/.agents/skills, so through such a link it would list every hidden Claude copy
    (it ignores disable-model-invocation) and find most names twice ($ID would load neither)."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    claude = home / ".claude/skills"  # shared with other tools: ~/.agents/skills leads into it
    skill(claude, "mine", body="the user's own Claude skill")
    (home / link).parent.mkdir(parents=True, exist_ok=True)
    (home / link).symlink_to(claude if link.endswith("skills") else claude.parent, target_is_directory=True)
    refused = "leads into Claude's skills"
    before = installer.fingerprint(home)
    for args in ([], ["--dry-run"]):
        with pytest.raises(installer.PersonNeeded, match=refused):
            run(source, *args)
    assert installer.fingerprint(home) == before, "nothing written"
    assert run(source, "--codex-only") == 0, "Claude's folder holds no copy of this installer's yet"
    assert sorted(os.listdir(home / ".codex/skills")) == sorted(
        [ROUTER, *(s for s in ("alpha", "beta") if not installer.placement(s))]
    )
    with pytest.raises(installer.PersonNeeded, match=refused):
        run(source, "--claude-only")  # Codex, installed, would read these copies
    assert sorted(os.listdir(claude)) == ["mine"]
    shutil.rmtree(state_dir(home))
    shutil.rmtree(home / ".codex/skills")
    assert run(source, "--claude-only") == 0 and hidden_from_claude(claude / "alpha")
    with pytest.raises(installer.PersonNeeded, match=refused):
        run(source, "--codex-only")
    assert not (home / ".codex/skills").exists()
    (home / link).unlink()  # the way out: a folder of Codex's own
    assert run(source) == 0 and hidden_from_codex(codex_copy(home, "alpha"))


def test_copies_in_a_second_root_that_became_a_link_stay_owned(sandbox, tmp_path, monkeypatch, capsys):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    for i in range(6):
        skill(source, f"extra-{i}")
    run(source)
    second, shared = home / ".agents/skills", home / "shared-skills"
    placed = sorted(os.listdir(second))
    assert placed and set(placed) <= set(state(home, "codex")["managed"])
    second.rename(shared)  # shared with other tools from now on
    second.symlink_to(shared, target_is_directory=True)
    before, copies = state(home, "codex"), installer.fingerprint(shared)
    capsys.readouterr()
    assert run(source) == 0
    assert "Codex's copies there are left as they are (see SKILLS_CODEX_DEST2)" in capsys.readouterr().err
    assert state(home, "codex") == before, "still owned, not forgotten"
    assert installer.fingerprint(shared) == copies
    assert run(source, "--codex-only", "--enable", "alpha") == 0, "a visibility change still works"
    assert state(home, "codex")["managed"].keys() == before["managed"].keys()
    skill(source, placed[0], body="changed upstream")
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(shared))  # the README's way to update them again
    assert run(source, "--codex-only") == 0
    assert "changed upstream" in (shared / placed[0] / "SKILL.md").read_text() and hidden_from_codex(shared / placed[0])
    value = state(home, "codex")
    assert value["destination2"] == str(installer.native(shared)) and set(placed) <= set(value["managed"])


def test_a_visible_copy_another_tool_left_in_the_shared_root_is_never_claimed(sandbox, capsys):
    home, source = sandbox
    second = home / ".agents/skills"
    assert installer.placement("beta"), "beta belongs in the second root"
    shutil.copytree(source / "beta", second / "beta")  # identical to beta's visible Codex copy
    raw = installer.fingerprint(second / "beta")
    assert installer.DirLibrary(source).derived("codex", "beta", "auto")[1] == {}, "nothing tells it apart"
    capsys.readouterr()
    assert run(source, "--codex-only", "--manual", "", "--selection", "@library,beta") == 0
    assert "beta" not in state(home, "codex")["managed"] and installer.fingerprint(second / "beta") == raw
    assert any(item["entry"] == "beta" and item.get("root") == 1 for item in plan(capsys)["clients"][0]["preserved"])
    with pytest.raises(installer.InstallError, match="preserved destination differs"):
        run(source, "--codex-only", "--selection", "@library", "--manual", "beta")
    assert installer.fingerprint(second / "beta") == raw, "never rewritten as a hidden copy"


def test_codex_copies_drop_plugin_folders_and_neutralize_nested_skills(sandbox):
    home, source = sandbox
    gamma = skill(source, "gamma")
    (gamma / ".claude-plugin").mkdir()
    (gamma / ".claude-plugin/plugin.json").write_text("{}\n")
    skill(gamma / "tools", "inner", name="beta")  # a nested SKILL.md that would shadow beta
    run(source)
    codex, claude = codex_copy(home, "gamma"), home / ".claude/skills/gamma"
    assert not (codex / ".claude-plugin").exists() and not (claude / ".claude-plugin").exists()
    assert name_of(codex / "tools/inner") == "gamma--tools-inner" and hidden_from_codex(codex / "tools/inner")
    assert name_of(claude / "tools/inner") == "beta", "Claude reads only top-level skills"


def test_a_foreign_codex_skill_keeps_its_name(sandbox, capsys):
    home, source = sandbox
    skill(home / ".agents/skills", "mine", name="alpha", body="the user's own")
    capsys.readouterr()
    run(source, "--codex-only")
    codex = plan(capsys)["clients"][0]
    assert not codex_copy(home, "alpha").exists(), "two skills named alpha would make $alpha inject neither"
    assert any(item["entry"] == "alpha" and "is taken by" in item["reason"] for item in codex["preserved"])
    assert (home / ".agents/skills/mine/SKILL.md").read_text().endswith("the user's own\n")
    with pytest.raises(installer.InstallError, match="Frontmatter name conflict"):
        run(source, "--codex-only", "--enable", "alpha")


def test_skills_in_agents_count_as_other_tools_when_codex_writes_elsewhere(sandbox, monkeypatch, capsys):
    """Codex reads ~/.agents/skills whether or not it is a root of this install, also when this
    run installs Claude first."""
    home, source = sandbox
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(home / "second"))
    skill(home / ".agents/skills", "mine", name="alpha", body="the user's own")
    capsys.readouterr()
    assert run(source) == 0
    codex = next(client for client in plan(capsys)["clients"] if client["client"] == "codex")
    assert any(item["entry"] == "alpha" and "is taken by" in item["reason"] for item in codex["preserved"])
    assert "alpha" not in state(home, "codex")["managed"] and hidden_from_claude(home / ".claude/skills/alpha")


def test_a_bundled_codex_skill_name_is_never_installed_for_codex(sandbox):
    home, source = sandbox
    skill(source, "skill-creator")  # a --source tree the weekly sync never produces
    run(source)
    assert hidden_from_claude(home / ".claude/skills/skill-creator"), "Claude has no such bundled skill"
    assert not codex_copy(home, "skill-creator").exists() and "skill-creator" not in state(home, "codex")["managed"]
    with pytest.raises(installer.InstallError, match="collides with reserved library entry: skill-creator"):
        run(source, "--codex-only", "--enable", "skill-creator")


def test_a_codex_root_that_would_overflow_is_refused_before_writing(sandbox, monkeypatch, capsys):
    home, source = sandbox
    first = [s for s in ("alpha", "beta") if not installer.placement(s)]
    monkeypatch.setattr(installer, "ROOT_CAP", 1 + len(first))  # the router and the library fit, one more does not
    skill(home / ".codex/skills", "foreign")
    before = installer.fingerprint(home)
    with pytest.raises(installer.PersonNeeded, match=rf"Refusing to fill .*\.codex.skills with {2 + len(first)} skill"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
    assert run(source, "--codex-only", "--dry-run") == 0
    assert "Refusing to fill" in capsys.readouterr().err
    assert run(source, "--codex-only", "--manual", "") == 0, "fewer skills fit"


def test_an_overflowing_codex_root_holds_back_codex_alone(sandbox, monkeypatch):
    home, source = sandbox
    first = [s for s in ("alpha", "beta") if not installer.placement(s)]
    monkeypatch.setattr(installer, "ROOT_CAP", 1 + len(first))
    skill(home / ".codex/skills", "foreign")  # say, many skills another tool put there
    codex = installer.fingerprint(home / ".codex/skills")
    with pytest.raises(installer.PersonNeeded, match=r"Refusing to fill .*\(--codex-only --manual\)"):
        run(source)
    assert installer.fingerprint(home / ".codex/skills") == codex and not (state_dir(home) / "codex.json").exists()
    assert all(hidden_from_claude(home / ".claude/skills" / s) for s in ("alpha", "beta")), "Claude still updates"


def test_a_mass_removal_holds_back_only_its_client(sandbox):
    home, source = sandbox
    for i in range(23):
        skill(source, f"extra-{i:02d}")
    run(source)
    run(source, "--codex-only", "--manual", "alpha")
    for i in range(23):
        shutil.rmtree(source / f"extra-{i:02d}")  # a broken library, as far as Claude can tell
    skill(source, "alpha", body="changed upstream")
    claude = installer.fingerprint(home / ".claude/skills")
    with pytest.raises(installer.PersonNeeded, match="Refusing to remove 23 of 26 managed claude skills"):
        run(source)
    assert installer.fingerprint(home / ".claude/skills") == claude
    assert "changed upstream" in (codex_copy(home, "alpha") / "SKILL.md").read_text(), "Codex still updates"


def test_the_shared_second_codex_root_is_capped_too(sandbox, monkeypatch):
    home, source = sandbox
    second = [s for s in ("alpha", "beta") if installer.placement(s)]
    monkeypatch.setattr(installer, "ROOT_CAP", 1 + len(second))  # one foreign skill fits, two do not
    for name in ("foreign-one", "foreign-two"):  # other tools' skills in ~/.agents/skills
        skill(home / ".agents/skills", name)
    before = installer.fingerprint(home)
    with pytest.raises(
        installer.PersonNeeded, match=rf"Refusing to fill .*\.agents.skills with {2 + len(second)} skill"
    ):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
    shutil.rmtree(home / ".agents/skills/foreign-two")
    assert run(source, "--codex-only") == 0


# --- Migration -------------------------------------------------------------------------------


def make_v1(home, source, client, selection):
    """An install as the installer before hidden installs left it: one root per client holding the
    library trees as they are, and v1 records (no manual, destination2, root or invocation)."""
    dest = home / (".claude/skills" if client == "claude" else ".codex/skills")
    ids = installer.skill_ids(source) if "@all" in selection else [i for i in selection if i[0] != "@"]
    managed = {}
    for skill_id in ids:
        shutil.copytree(source / skill_id, dest / skill_id)
        tree = installer.tree_id(installer.local_listing(source / skill_id))
        managed[skill_id] = {"name": skill_id, "tree": tree, "source_ids": [skill_id], "origins": []}
    if "@library" in selection:
        skill(dest, ROUTER, body="the v1 router, which ran install_skills.py --list")
        tree = installer.tree_id(installer.local_listing(dest / ROUTER))
        managed[ROUTER] = {"name": ROUTER, "tree": tree, "source_ids": ["@library"], "origins": []}
    for entry, record in managed.items():
        record["sha256"] = installer.fingerprint(dest / entry)
    value = {"schema": 1, "client": client, "destination": str(installer.native(dest)), "selection": selection}
    state_dir(home).mkdir(parents=True, exist_ok=True)
    (state_dir(home) / f"{client}.json").write_text(json.dumps(dict(value, managed=managed)))


def test_claude_all_migrates_once_to_the_router_with_the_library_hidden(sandbox, monkeypatch, capsys):
    home, source = sandbox
    for i in range(25):
        skill(source, f"extra-{i:02d}")
    make_v1(home, source, "claude", ["@all"])
    claude = home / ".claude/skills"
    assert not hidden_from_claude(claude / "alpha")
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source) == 0, "no mass removal: the migration removes nothing"
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Migrated claude: @all -> visible @library, 27 hidden; undo: --claude-only --selection @all"
    assert out[1].startswith("Updated codex: ") and out[2].startswith("Recovery backup: ")
    assert all(hidden_from_claude(claude / s) for s in os.listdir(claude) if s != ROUTER)
    value = state(home, "claude")
    assert (value["selection"], value["manual"], value["selection_version"]) == (["@library"], ["@all"], 2)
    marks = json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]
    assert marks["claude"]["backup"] == out[2].split(": ", 1)[1]
    journal = json.loads((Path(marks["claude"]["backup"]) / "restore.json").read_text())
    assert journal["migration"] == installer.MIGRATION
    capsys.readouterr()
    assert run(source) == 0
    assert capsys.readouterr().out == "Already current; selection preserved.\n"
    run(source, "--claude-only", "--selection", "@all")
    run(source)
    assert not any(hidden_from_claude(claude / s) for s in os.listdir(claude))


def test_a_claude_v1_list_of_most_of_the_library_migrates_like_all(sandbox, monkeypatch, capsys):
    home, source = sandbox
    for i in range(100):
        skill(source, f"extra-{i:03d}")
    every = installer.skill_ids(source)
    kept = [s for s in every if s != "beta"]  # how v1 stored @all after `--claude-only --disable beta`
    make_v1(home, source, "codex", kept[:100])
    make_v1(home, source, "claude", kept)
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source, "--claude-only") == 0
    out = capsys.readouterr().out.splitlines()
    backup = out[1].split(": ", 1)[1]
    undo = f"--claude-only --restore {backup}"
    assert out[0] == f"Migrated claude: {len(kept)} IDs -> visible @library, {len(every)} hidden; undo: {undo}"
    value = state(home, "claude")
    assert (value["selection"], value["manual"]) == (["@library"], ["@all"]), "the model's listing cannot overflow"
    assert all(hidden_from_claude(home / ".claude/skills" / s) for s in every)
    run(source, "--claude-only", "--restore", backup)
    run(source, "--claude-only")
    assert (state(home, "claude")["selection"], state(home, "claude")["manual"]) == (kept, []), "undone for good"
    capsys.readouterr()
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 1)  # the two hidden copies
    run(source, "--codex-only")
    assert state(home, "codex")["selection"] == kept[:100], "Codex lists stay visible, as specified"
    assert capsys.readouterr().out.startswith(
        "Migrated codex: 100 IDs -> visible 100 IDs, 2 hidden; undo: --codex-only --manual ''"
    )


def test_the_printed_claude_undo_leaves_the_codex_migration_of_the_same_run(sandbox, monkeypatch, capsys):
    home, source = sandbox
    for i in range(100):
        skill(source, f"extra-{i:03d}")
    kept = [s for s in installer.skill_ids(source) if s != "beta"]
    make_v1(home, source, "claude", kept)
    make_v1(home, source, "codex", ["@library", "alpha"])
    codex_v1 = state(home, "codex")
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source) == 0, "one transaction migrates both clients"
    out = capsys.readouterr().out.splitlines()
    backup = out[2].split(": ", 1)[1]
    assert out[0].endswith(f"undo: --claude-only --restore {backup}")
    assert out[1].startswith("Migrated codex: ") and out[1].endswith("undo: --codex-only --manual ''")
    codex = state(home, "codex")
    assert run(source, "--claude-only", "--restore", backup) == 0
    assert state(home, "claude")["selection"] == kept and "selection_version" not in state(home, "claude")
    assert state(home, "codex") == codex, "the Codex migration stays"
    marks = json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]
    assert marks["claude"]["undone"] and "undone" not in marks["codex"]
    assert run(source) == 0
    assert (state(home, "claude")["selection"], state(home, "claude")["manual"]) == (kept, [])
    assert state(home, "codex") == codex
    with pytest.raises(installer.InstallError, match="Nothing claude left to restore"):
        run(source, "--claude-only", "--restore", backup)
    assert run(source, "--restore", backup) == 0, "the rest of the transaction"
    assert state(home, "codex") == codex_v1
    with pytest.raises(installer.InstallError, match="already restored"):
        run(source, "--restore", backup)


def test_other_v1_selections_stay_visible_with_the_rest_hidden(sandbox, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["alpha"])
    make_v1(home, source, "codex", ["@library", "beta"])
    alpha = installer.fingerprint(home / ".claude/skills/alpha")
    capsys.readouterr()
    run(source)
    clients = {c["client"]: c for c in plan(capsys)["clients"]}
    assert clients["claude"]["migration"] == {"from": ["alpha"], "selection": ["alpha"], "manual": ["@all"]}
    assert [a["entry"] for a in clients["claude"]["actions"]] == ["beta"], "alpha is recorded, not copied"
    assert installer.fingerprint(home / ".claude/skills/alpha") == alpha
    assert hidden_from_claude(home / ".claude/skills/beta")
    beta = home / ".codex/skills/beta"  # a v1 copy, recorded where it is although its hash says root 1
    assert installer.placement("beta") and beta.is_dir() and not hidden_from_codex(beta)
    assert not (home / ".agents/skills/beta").exists() and "root" not in state(home, "codex")["managed"]["beta"]
    assert (
        hidden_from_codex(codex_copy(home, "alpha"))
        and "the v1 router" not in (beta.parent / ROUTER / "SKILL.md").read_text()
    )
    assert state(home, "codex")["selection"] == ["@library", "beta"]


def test_a_v1_codex_copy_keeps_its_root_through_the_migration_even_when_edited(sandbox, capsys):
    home, source = sandbox
    skill(source, "gamma")
    make_v1(home, source, "codex", ["@library", "beta", "gamma"])
    codex = home / ".codex/skills"
    (codex / "gamma/helper.txt").write_text("user edit\n")
    edited, record = installer.fingerprint(codex / "gamma"), json.loads((state_dir(home) / "codex.json").read_text())
    assert installer.placement("beta") and installer.placement("gamma"), "both would go to ~/.agents/skills if new"
    capsys.readouterr()
    assert run(source, "--codex-only") == 0
    codex_plan = plan(capsys)["clients"][0]
    assert sorted(a["entry"] for a in codex_plan["actions"]) == ["alpha", ROUTER], "beta is recorded, gamma kept"
    assert installer.fingerprint(codex / "gamma") == edited and not (home / ".agents/skills/gamma").exists()
    assert state(home, "codex")["managed"]["gamma"] == record["managed"]["gamma"], "the edited copy keeps its record"
    assert not (home / ".agents/skills/beta").exists() and name_of(codex / "beta") == "beta"
    capsys.readouterr()
    assert run(source, "--codex-only") == 0
    assert capsys.readouterr().out == "Already current; selection preserved.\n"


def test_saved_ids_that_left_the_library_are_dropped_with_a_warning(sandbox, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["alpha", "beta"])
    make_v1(home, source, "codex", ["@library", "beta"])
    shutil.rmtree(source / "beta")  # renamed or removed upstream, as skill-creator was
    capsys.readouterr()
    assert run(source) == 0, "neither client is blocked"
    err = capsys.readouterr().err
    for client in ("claude", "codex"):
        assert f"{client}: dropping saved IDs that left the library (see --list --search): beta" in err
    assert state(home, "claude")["selection"] == ["alpha"] and state(home, "codex")["selection"] == ["@library"]
    run(source, "--claude-only", "--manual", "alpha")
    shutil.rmtree(source / "alpha")
    assert run(source, "--claude-only") == 0
    assert (state(home, "claude")["selection"], state(home, "claude")["manual"]) == ([], [])
    with pytest.raises(installer.InstallError, match="Unknown source IDs"):
        run(source, "--claude-only", "--enable", "alpha")


def test_a_dry_run_reports_the_migration_and_writes_nothing(sandbox, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["@all"])
    before = installer.fingerprint(home)
    capsys.readouterr()
    run(source, "--claude-only", "--dry-run")
    claude = json.loads(capsys.readouterr().out)["clients"][0]
    assert claude["migration"] == {"from": ["@all"], "selection": ["@library"], "manual": ["@all"]}
    assert installer.fingerprint(home) == before


def test_restoring_the_migration_is_a_lasting_opt_out(sandbox, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["@all"])
    v1 = state(home, "claude")
    run(source, "--claude-only")
    backup = Path(
        json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]["claude"]["backup"]
    )
    run(source, "--restore", str(backup))
    assert state(home, "claude") == v1
    marks = json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]
    assert marks["claude"]["undone"]
    claude = home / ".claude/skills"
    copies = installer.fingerprint(claude)
    capsys.readouterr()
    run(source, "--claude-only")
    assert "migration" not in plan(capsys)["clients"][0]
    value = state(home, "claude")
    assert (value["selection"], value["manual"], value["selection_version"]) == (["@all"], [], 2)
    assert installer.fingerprint(claude) == copies and not hidden_from_claude(claude / "alpha")


KILLED_INSIDE_APPLY = """
import os, sys
sys.path.insert(0, sys.argv[1])
from scripts import install_skills as installer
original, moves = installer.move, []
def move(source, target):
    original(source, target)
    moves.append(target)
    if len(moves) == 2:
        os._exit(137)
installer.move = move
installer.main(sys.argv[2:])
"""


def test_an_interrupted_migration_is_recovered_and_redone(sandbox, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["@all"])
    v1 = state(home, "claude")
    command = [sys.executable, "-B", "-c", KILLED_INSIDE_APPLY, str(ROOT), "--source", str(source), "--claude-only"]
    assert subprocess.run(command, capture_output=True).returncode == 137
    assert not (state_dir(home) / installer.MIGRATIONS).exists(), "marked only once the journal is complete"
    capsys.readouterr()
    assert run(source, "--claude-only") == 0
    out = capsys.readouterr().out
    assert "Recovered an interrupted update" in out and '"migration"' in out
    assert state(home, "claude")["selection"] == ["@library"] and v1["selection"] == ["@all"]
    assert json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]["claude"]


def test_a_codex_transaction_beside_a_frozen_second_root_restores_and_recovers(sandbox, tmp_path, capsys):
    """Once ~/.agents/skills became a link, a Codex journal names one root while its new state keeps
    the frozen second one: --restore and the next run's recovery must still accept it."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    for i in range(6):
        skill(source, f"extra-{i}")
    run(source)
    second, shared = home / ".agents/skills", home / "shared-skills"
    second.rename(shared)
    second.symlink_to(shared, target_is_directory=True)
    managed = state(home, "codex")["managed"]
    first = next(s for s in sorted(managed) if s != ROUTER and not managed[s].get("root"))
    copy = home / ".codex/skills" / first
    skill(source, first, body="changed upstream")
    assert run(source, "--codex-only") == 0 and "changed upstream" in (copy / "SKILL.md").read_text()
    backup = sorted((state_dir(home) / "backups").iterdir())[-1]
    (item,) = json.loads((backup / "restore.json").read_text())["clients"]
    assert "destination2" not in item and "destination2" in item["new_state"], "the shape this test is about"
    assert installer.main(["--restore", str(backup)]) == 0
    assert "changed upstream" not in (copy / "SKILL.md").read_text()
    command = [sys.executable, "-B", "-c", KILLED_INSIDE_APPLY, str(ROOT), "--source", str(source), "--codex-only"]
    assert subprocess.run(command, capture_output=True).returncode == 137
    capsys.readouterr()
    assert run(source) == 0
    assert "Recovered an interrupted update" in capsys.readouterr().out
    assert "changed upstream" in (copy / "SKILL.md").read_text() and hidden_from_codex(copy)
    assert set(state(home, "codex")["managed"]) == set(managed), "the frozen copies are still owned"


def test_a_saved_destination_of_the_other_client_still_counts_when_overridden(sandbox, monkeypatch):
    home, source = sandbox
    run(source, "--claude-only")
    monkeypatch.setenv("SKILLS_CLAUDE_DEST", str(home / "elsewhere/skills"))
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(home / ".claude/skills"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
