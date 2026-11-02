"""Visible and hidden installs: what each client shows the model, the Codex roots and their limit,
and the one-time migration of states written before hidden installs. Temporary HOME only."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import install_skills as installer
from tests.gitfixtures import snapshot
from tests.test_install import can_symlink, codex_copy, hidden_from_claude, hidden_from_codex, skill, state_dir

ROOT = Path(__file__).resolve().parents[1]
ROUTER = installer.ROUTER
SECOND = f".agents/skills/{installer.AGENTS_FOLDER}"  # Codex's second root, below where other tools look


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
    """The JSON plan a run printed first (a "Recovery backup:" line follows when its backup keeps copies)."""
    return json.JSONDecoder().raw_decode(capsys.readouterr().out)[0]


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


def test_disable_from_a_visible_all_shows_the_rest(sandbox):
    """The printed migration undo makes Claude's visible set @all again; --disable then lists the
    rest of the library, as v1 did."""
    home, source = sandbox
    run(source)
    assert run(source, "--claude-only", "--selection", "@all") == 0
    claude = home / ".claude/skills"
    assert not hidden_from_claude(claude / "alpha") and not hidden_from_claude(claude / "beta")
    assert run(source, "--claude-only", "--disable", "alpha") == 0
    assert state(home, "claude")["selection"] == ["beta"]
    assert hidden_from_claude(claude / "alpha") and not hidden_from_claude(claude / "beta")
    assert not (claude / ROUTER).exists()


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
    "recursive-alias": ("---\nname: gamma\ndescription: g\n---\n", "interface: &x\n  self: *x\n"),
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
    assert set(state(home, "claude")["managed"]) == {"alpha", installer.ROUTER}, "the exact router is ours too"
    run(source, "--claude-only", "--manual", "alpha,beta")
    actions = [a["entry"] for a in plan(capsys)["clients"][0]["actions"]]
    assert actions == ["beta"], "a raw tree whose ID is named is claimed and copied again"
    assert hidden_from_claude(claude / "beta")
    assert set(state(home, "claude")["managed"]) == {"alpha", "beta", installer.ROUTER}


def test_only_this_installers_copies_are_claimed_in_the_shared_agents_root(sandbox, capsys):
    home, source = sandbox
    run(source, "--codex-only")
    second = home / SECOND
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

    def revised(client, skill_id, invocation, listing, read, rename=False):  # a later fix of the transforms
        edits = original(client, skill_id, invocation, listing, read, rename)
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


def test_state_versions_and_records_are_validated(tmp_path):
    first, second = str(tmp_path / "x"), str(tmp_path / "y")  # "/x" has no drive, so is relative on Windows
    v1 = {"schema": 1, "client": "codex", "destination": first, "selection": ["@library"], "managed": {}}
    installer.validate_state(v1, "codex")
    v2 = dict(v1, manual=["@all"], selection_version=2, destination2=second)
    v2["managed"] = {"a": {"sha256": "0" * 64, "invocation": "manual", "root": 1}}
    installer.validate_state(v2, "codex")
    for bad in (
        dict(v2, manual="@all"),
        dict(v2, selection_version=3),
        dict(v2, managed={"a": {"sha256": "0" * 64, "invocation": "hidden"}}),
        dict(v1, managed={"a": {"sha256": "0" * 64, "root": 1}}),
        dict(v2, destination2="y"),
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


def test_no_codex_copy_lies_where_other_tools_list_skills(sandbox):
    """Gemini CLI reads ~/.agents/skills/SKILL.md and ~/.agents/skills/*/SKILL.md only (0.63's glob),
    and lists every skill there to its model, which neither hiding key stops; Codex walks six levels
    deep. So Codex's second half sits one folder deeper, where only Codex finds it."""
    home, source = sandbox
    for i in range(6):
        skill(source, f"extra-{i}")
    run(source)
    agents = home / ".agents/skills"
    assert not list(agents.glob("SKILL.md")) and not list(agents.glob("*/SKILL.md"))
    managed = state(home, "codex")["managed"]
    second = [entry for entry, record in managed.items() if record.get("root") == 1]
    assert second and all((agents / installer.AGENTS_FOLDER / entry / "SKILL.md").is_file() for entry in second)
    assert state(home, "codex")["destination2"] == str(installer.native(agents / installer.AGENTS_FOLDER))


def test_codex_finds_its_second_root_however_home_is_spelled(sandbox, monkeypatch, capsys):
    home, source = sandbox
    monkeypatch.setenv("HOME", str(home / "../home"))
    skill(source, "delta")
    run(source, "--codex-only")
    second = [s for s in ("alpha", "beta", "delta") if installer.placement(s)]
    assert second and all((home / SECOND / s).is_dir() for s in second)
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


def test_a_second_root_linked_into_codexs_first_names_the_fix_that_works(sandbox, tmp_path, capsys):
    """~/.agents/skills linked to ~/.codex/skills: Codex reads one folder twice and finds only the copies
    of the first root. SKILLS_CODEX_DEST2 cannot help there (both roots would overlap, or the variable
    would name a link): the warning names the fix that does."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    (home / ".codex/skills").mkdir(parents=True)
    (home / ".agents").mkdir()
    # A relative link, as `ln -s ../.codex/skills` makes, in this host's separator: Windows does not
    # resolve a link whose stored target holds forward slashes.
    (home / ".agents/skills").symlink_to(Path("..", ".codex", "skills"), target_is_directory=True)
    capsys.readouterr()
    assert run(source, "--codex-only") == 0
    err = capsys.readouterr().err
    assert "replace the link with a folder of its own: Codex finds only the copies in" in err, err
    assert "SKILLS_CODEX_DEST2" not in err


INTO_CLAUDE = "leads into Claude's skills"
NO_CODEX = ["--codex-only", "--selection", "", "--manual", ""]  # the remedies that keep the link
SEEN_ONLY = ["--claude-only", "--manual", ""]


def link_agents_into(home, link: str, target: Path):
    """~/.agents/skills (or ~/.agents) made a link into Claude's skills folder (or its parent)."""
    (home / link).parent.mkdir(parents=True, exist_ok=True)
    (home / link).symlink_to(target if link.endswith("skills") else target.parent, target_is_directory=True)


@pytest.mark.parametrize("link", [".agents/skills", ".agents"])
def test_a_second_codex_root_linked_into_claudes_holds_back_codex_and_hidden_claude_copies(
    sandbox, tmp_path, capsys, link
):
    """Codex reads ~/.agents/skills, so through a link into Claude's skills it would list every Claude
    copy, hidden ones included (it ignores disable-model-invocation), and find most names twice ($ID
    would load neither). Neither client fills that folder then: Codex installs nothing, Claude no
    hidden copy, and the run exits 3 naming the remedies, each of which works on its own."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    claude = home / ".claude/skills"
    skill(claude, "mine", body="the user's own Claude skill")
    link_agents_into(home, link, claude)
    capsys.readouterr()
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE) as held:
        run(source)
    assert "Replace the link with a folder" in str(held.value) and " ".join(NO_CODEX[:2]) in str(held.value)
    assert "--codex-only --selection '' --manual ''" in str(held.value) and "--claude-only --manual ''" in str(
        held.value
    )
    assert sorted(os.listdir(claude)) == ["mine"] and not (home / ".codex/skills").exists()
    assert "SKILLS_CODEX_DEST2" not in capsys.readouterr().err, "no advice that would not help here"
    for args in ([], ["--claude-only"]):  # --codex-only alone is fine while Claude has no copy there
        before = installer.fingerprint(home)
        with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE):
            run(source, *args)
        assert installer.fingerprint(home) == before, f"nothing written for {args}"
    assert run(source, "--dry-run") == 0
    assert run(source, *SEEN_ONLY) == 0 and sorted(os.listdir(claude)) == sorted(["mine", ROUTER])
    before = installer.fingerprint(home)
    with pytest.raises(installer.PersonNeeded, match="Codex is left as it is"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before, "now Claude's router is there: Codex alone writes nothing"
    assert run(source, "--claude-only", "--enable", "alpha") == 0 and not hidden_from_claude(claude / "alpha")
    assert run(source, "--claude-only", "--selection", "", "--manual", "") == 0, "an uninstall is never held"
    assert sorted(os.listdir(claude)) == ["mine"]


@pytest.mark.parametrize(
    "where, above",
    [
        (".agents/skills/shared", False),
        (".codex/skills/shared", False),
        (".agents/skills", False),
        (".agents/skills/shared", True),
        (".codex/skills/shared", True),
    ],
    ids=["in-agents", "in-codex", "root", "above-in-agents", "above-in-codex"],
)
def test_a_folder_codex_reads_that_leads_into_claudes_gets_no_hidden_claude_copy(sandbox, tmp_path, where, above):
    """Codex follows links in the folders it reads. Through one onto Claude's skills folder or above it
    (the folder itself, or a link in a real ~/.agents/skills or ~/.codex/skills; Codex walks several
    levels) it would list every Claude copy, which carries no Codex policy, and with the whole library
    hidden that is the overflow this design prevents. So Claude writes no hidden copy there and Codex
    nothing: nothing is written at all."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    claude = home / ".claude/skills"
    skill(claude, "mine", body="the user's own Claude skill")
    (home / where).parent.mkdir(parents=True, exist_ok=True)
    (home / where).symlink_to(claude.parent if above else claude, target_is_directory=True)
    before = installer.fingerprint(home)
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE) as held:
        run(source)
    assert "--claude-only --manual ''" in str(held.value) and " ".join(NO_CODEX[:2]) in str(held.value)
    assert installer.fingerprint(home) == before, "neither client wrote anything"
    assert sorted(os.listdir(claude)) == ["mine"]


def test_a_link_to_one_claude_skill_holds_nothing_back(sandbox, tmp_path):
    """A link that shares one skill of the user's own with Codex shows Codex that skill alone."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    mine = skill(home / ".claude/skills", "mine", body="the user's own Claude skill")
    (home / ".agents/skills").mkdir(parents=True)
    (home / ".agents/skills/mine").symlink_to(mine, target_is_directory=True)
    assert run(source) == 0
    assert hidden_from_claude(home / ".claude/skills/alpha") and hidden_from_codex(codex_copy(home, "alpha"))


def test_the_ways_out_that_keep_the_link(sandbox, tmp_path, capsys):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    claude = home / ".claude/skills"
    link_agents_into(home, ".agents/skills", claude)
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE):
        run(source)
    assert run(source, *SEEN_ONLY) == 0
    with pytest.raises(installer.PersonNeeded, match="Codex is left as it is"):
        run(source)
    assert run(source, *NO_CODEX) == 0
    capsys.readouterr()
    assert run(source) == 0, "the no-argument update is not held any more"
    assert capsys.readouterr().out == "Already current; selection preserved.\n"
    assert not (home / ".codex/skills").exists() and os.listdir(claude) == [ROUTER]


def test_a_v1_host_with_the_link_is_left_as_it_is_until_a_person_decides(sandbox, tmp_path, capsys):
    """A v1 install of both clients' defaults (Claude @all, visible; Codex @library, its router managed
    in ~/.codex/skills) that origin/main updated with the link. Codex already lists every Claude copy;
    the migration would keep that and is not made until a person decides."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    for i in range(25):
        skill(source, f"extra-{i:02d}")
    make_v1(home, source, "claude", ["@all"])
    make_v1(home, source, "codex", ["@library"])
    claude, codex = home / ".claude/skills", home / ".codex/skills"
    link_agents_into(home, ".agents/skills", claude)
    v1, before = {c: state(home, c) for c in ("claude", "codex")}, installer.fingerprint(home)
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE) as held:
        run(source)
    assert installer.fingerprint(home) == before and {c: state(home, c) for c in v1} == v1
    # `--manual ''` would migrate Claude to the router alone and remove the library it lists now.
    assert "keep Claude's copies as they are, all listed to the model: --claude-only --selection @all --manual ''" in (
        str(held.value)
    )
    assert "--claude-only --manual ''" not in str(held.value)
    copies = sorted(os.listdir(claude))
    assert run(source, "--claude-only", "--selection", "@all", "--manual", "") == 0
    assert sorted(os.listdir(claude)) == copies and not any(hidden_from_claude(claude / s) for s in copies)
    assert (state(home, "claude")["selection"], state(home, "claude")["manual"]) == (["@all"], [])
    assert run(source, *NO_CODEX) == 0 and not os.listdir(codex), "the v1 Codex router is removed"
    assert run(source) == 0
    backup = Path(
        json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]["claude"]["backup"]
    )
    assert run(source, "--claude-only", "--restore", str(backup)) == 0, "--restore is never held"
    assert state(home, "claude") == v1["claude"]


def test_the_claude_way_out_that_keeps_the_link_says_what_it_removes(sandbox, tmp_path):
    """Once Claude has hidden copies, the link makes Codex list them; `--manual ''` removes them."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    assert run(source, "--claude-only") == 0 and hidden_from_claude(home / ".claude/skills/alpha")
    link_agents_into(home, ".agents/skills", home / ".claude/skills")
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE) as held:
        run(source)
    assert "keep Claude to the skills the model sees, which removes its 2 hidden copies: --claude-only --manual ''" in (
        str(held.value)
    )
    assert run(source, *SEEN_ONLY) == 0 and os.listdir(home / ".claude/skills") == [ROUTER]


def test_replacing_the_link_with_a_folder_lets_codex_install(sandbox, tmp_path):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    link_agents_into(home, ".agents/skills", home / ".claude/skills")
    with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE):
        run(source)
    (home / ".agents/skills").unlink()
    (home / ".agents/skills").mkdir()  # a folder of Codex's own
    assert run(source) == 0
    assert all(hidden_from_codex(codex_copy(home, s)) for s in ("alpha", "beta"))
    assert all(hidden_from_claude(home / ".claude/skills" / s) for s in ("alpha", "beta"))
    assert {installer.placement(s) for s in state(home, "codex")["managed"] if s != ROUTER} == {0, 1}


def test_codex_alone_installs_while_claude_has_no_copy_of_this_installer_there(sandbox, tmp_path):
    """--codex-only while Claude's folder, which the link leads into, holds only the user's own skills:
    Codex sees them as other tools' skills, and nothing of this installer's is listed twice."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    claude = home / ".claude/skills"
    skill(claude, "mine", body="the user's own Claude skill")
    link_agents_into(home, ".agents/skills", claude)
    assert run(source, "--codex-only") == 0
    assert sorted(os.listdir(home / ".codex/skills")) == sorted(
        [ROUTER, *(s for s in ("alpha", "beta") if not installer.placement(s))]
    )
    assert sorted(os.listdir(claude)) == ["mine"]


def test_only_claudes_own_root_counts_for_the_link(sandbox, tmp_path, monkeypatch):
    """Claude installed at a custom root, which the state saves: ~/.agents/skills leading into
    ~/.claude/skills (only the user's own skill there) holds nothing back, while a link into the
    saved root holds Codex back even when Claude is not part of the run."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    custom = home / "claude-config/skills"
    monkeypatch.setenv("SKILLS_CLAUDE_DEST", str(custom))
    assert run(source, "--claude-only") == 0
    monkeypatch.delenv("SKILLS_CLAUDE_DEST")
    skill(home / ".claude/skills", "mine")
    link_agents_into(home, ".agents/skills", home / ".claude/skills")
    assert run(source) == 0 and hidden_from_codex(codex_copy(home, "alpha"))
    (home / ".agents/skills").unlink()
    link_agents_into(home, ".agents/skills", custom)
    before = installer.fingerprint(home / ".codex")
    for args in ([], ["--codex-only"], ["--codex-only", "--enable", "alpha"]):
        with pytest.raises(installer.PersonNeeded, match=INTO_CLAUDE):
            run(source, *args)
    assert installer.fingerprint(home / ".codex") == before


def test_copies_in_a_second_root_that_became_a_link_stay_owned(sandbox, tmp_path, monkeypatch, capsys):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    for i in range(6):
        skill(source, f"extra-{i}")
    run(source)
    agents, shared = home / ".agents/skills", home / "shared-skills"
    second = agents / installer.AGENTS_FOLDER
    placed = sorted(os.listdir(second))
    assert placed and set(placed) <= set(state(home, "codex")["managed"])
    agents.rename(shared)  # shared with other tools from now on
    agents.symlink_to(shared, target_is_directory=True)
    before, copies = state(home, "codex"), installer.fingerprint(shared)
    capsys.readouterr()
    assert run(source) == 0
    there = installer.display(installer.native((shared / installer.AGENTS_FOLDER).resolve()))  # no \\?\ shown
    fix = f"(set SKILLS_CODEX_DEST2={there} to write them"
    assert f"Codex's copies there are left as they are {fix}" in capsys.readouterr().err
    assert state(home, "codex") == before, "still owned, not forgotten"
    assert installer.fingerprint(shared) == copies
    assert run(source, "--codex-only", "--enable", "alpha") == 0, "a visibility change still works"
    assert state(home, "codex")["managed"].keys() == before["managed"].keys()
    skill(source, placed[0], body="changed upstream")
    target = shared / installer.AGENTS_FOLDER
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(target))  # the README's way to update them again
    assert run(source, "--codex-only") == 0
    assert "changed upstream" in (target / placed[0] / "SKILL.md").read_text() and hidden_from_codex(target / placed[0])
    value = state(home, "codex")
    assert value["destination2"] == str(installer.native(target)) and set(placed) <= set(value["managed"])


@pytest.mark.parametrize("where", [".agents/skills", SECOND])
def test_a_visible_copy_another_tool_left_in_the_shared_root_is_never_claimed(sandbox, capsys, where):
    """Another tool's copy of a library tree in ~/.agents/skills (or, oddly, in this installer's own
    folder there) is never claimed or rewritten: Codex reads it already, so none of ours joins it."""
    home, source = sandbox
    theirs = home / where / "beta"
    assert installer.placement("beta"), "beta belongs in the second root"
    shutil.copytree(source / "beta", theirs)  # identical to beta's visible Codex copy
    raw = installer.fingerprint(theirs)
    assert installer.DirLibrary(source).derived("codex", "beta", "auto")[1] == {}, "nothing tells it apart"
    capsys.readouterr()
    assert run(source, "--codex-only", "--manual", "", "--selection", "@library,beta") == 0
    assert "beta" not in state(home, "codex")["managed"] and installer.fingerprint(theirs) == raw
    assert any(item["entry"] == "beta" and item.get("root") == 1 for item in plan(capsys)["clients"][0]["preserved"])
    expected = "preserved destination differs" if where == SECOND else "Frontmatter name conflict"
    with pytest.raises(installer.InstallError, match=expected):
        run(source, "--codex-only", "--selection", "@library", "--manual", "beta")
    assert installer.fingerprint(theirs) == raw, "never rewritten as a hidden copy"


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


def test_a_visible_codex_copy_gives_a_nested_skill_the_policy_in_its_own_file(sandbox):
    """A visible copy reads its top-level SKILL.md alone, but each nested one's agents/openai.yaml too."""
    home, source = sandbox
    nest = skill(source, "nest")
    skill(nest, "sub")
    (nest / "sub/agents").mkdir()
    (nest / "sub/agents/openai.yaml").write_text("interface:\n  display_name: Sub\n")
    assert run(source, "--codex-only", "--selection", "nest", "--manual", "") == 0
    copy = codex_copy(home, "nest")
    assert not hidden_from_codex(copy) and name_of(copy) == "nest"
    assert (copy / "sub/agents/openai.yaml").read_text() == (
        "interface:\n  display_name: Sub\npolicy:\n  allow_implicit_invocation: false\n"
    )


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


def test_a_claude_copy_named_like_a_claude_code_command_is_named_after_its_id(sandbox, capsys):
    """Claude Code also resolves /NAME through a personal skill's frontmatter name, so a library skill
    `name: review` under any ID would take over /review, its allowed-tools and !`...` lines included.
    Its Claude copy, hidden or visible, is named after its ID; any other name stays an alias."""
    home, source = sandbox
    skill(source, "review--up--0123456789", name="review")
    skill(source, "planner", name="Plan")
    skill(source, "delta", name="shared-name")
    assert run(source) == 0
    claude = home / ".claude/skills"
    assert (claude / "review--up--0123456789/SKILL.md").read_text() == (
        f'---\n{installer.HIDDEN_KEY}: true\nname: "review--up--0123456789"\n'
        "description: Use review--up--0123456789\n---\nbody\n"
    )
    assert name_of(claude / "planner") == "planner" and hidden_from_claude(claude / "planner")
    assert state(home, "claude")["managed"]["planner"]["name"] == "planner"
    assert name_of(claude / "delta") == "shared-name" and hidden_from_claude(claude / "delta")
    assert run(source, "--claude-only", "--enable", "planner") == 0
    assert name_of(claude / "planner") == "planner" and not hidden_from_claude(claude / "planner")
    capsys.readouterr()
    assert run(source) == 0 and capsys.readouterr().out == "Already current; selection preserved.\n"


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
    """Codex walks ~/.agents/skills breadth first: the folder itself, its folders (other tools' skills
    and this installer's), then theirs, where the copies are. Every folder it reaches first counts."""
    home, source = sandbox
    second = [s for s in ("alpha", "beta") if installer.placement(s)]
    monkeypatch.setattr(installer, "ROOT_CAP", 4 + len(second))  # one foreign skill fits, two do not
    for name in ("foreign-one", "foreign-two"):  # other tools' skills in ~/.agents/skills
        (skill(home / ".agents/skills", name) / "references").mkdir()
    before = installer.fingerprint(home)
    message = rf"Refusing to fill .*{installer.AGENTS_FOLDER} with {len(second)} skill folders and 6 other folders"
    with pytest.raises(installer.PersonNeeded, match=message):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
    shutil.rmtree(home / ".agents/skills/foreign-two")
    assert run(source, "--codex-only") == 0


def test_the_cap_counts_other_tools_folders_through_a_linked_agents_folder(sandbox, tmp_path, monkeypatch):
    """With ~/.agents/skills a link and SKILLS_CODEX_DEST2 set inside its target, as the warning says,
    Codex still walks ~/.agents/skills first, so its folders count as they do in a real folder."""
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    second = [s for s in ("alpha", "beta") if installer.placement(s)]
    monkeypatch.setattr(installer, "ROOT_CAP", 4 + len(second))
    shared = home / "shared-skills"
    for name in ("foreign-one", "foreign-two"):
        (skill(shared, name) / "references").mkdir()
    (home / ".agents").mkdir()
    (home / ".agents/skills").symlink_to(shared, target_is_directory=True)
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(shared / installer.AGENTS_FOLDER))
    before = installer.fingerprint(home)
    message = rf"Refusing to fill .*{installer.AGENTS_FOLDER} with {len(second)} skill folders and 6 other folders"
    with pytest.raises(installer.PersonNeeded, match=message):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
    shutil.rmtree(shared / "foreign-two")
    assert run(source, "--codex-only") == 0
    assert run(source, "--codex-only") == 0, "the second root itself, reached through the link, is no other folder"


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
    assert run(source, *undo_of(out[0])) == 0
    run(source)
    assert visible(home, "claude") == installer.skill_ids(source), "the v1 visible set: every skill, no router"


def test_the_migration_line_names_the_copies_it_removes(sandbox, monkeypatch, capsys):
    """A v1 copy whose ID left the library (the sync renamed skill-creator, say) is removed with the
    migration: /skill-creator then stops working, so the one-line summary says so."""
    home, source = sandbox
    for skill_id in ("renamed-upstream", *(f"extra-{i:02d}" for i in range(25))):
        skill(source, skill_id)
    make_v1(home, source, "claude", ["@all"])
    shutil.rmtree(source / "renamed-upstream")
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source, "--claude-only") == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("Migrated claude: @all -> visible @library, 27 hidden, 1 removed (renamed-upstream);"), line
    assert not (home / ".claude/skills/renamed-upstream").exists()


def test_restoring_the_migration_after_a_later_update_names_what_to_restore_first(sandbox):
    home, source = sandbox
    make_v1(home, source, "claude", ["@all"])
    assert run(source, "--claude-only") == 0
    migration = Path(
        json.loads((state_dir(home) / installer.MIGRATIONS).read_text())[installer.MIGRATION]["claude"]["backup"]
    )
    skill(source, "alpha", body="changed upstream")  # the next weekly update
    assert run(source, "--claude-only") == 0
    later = installer.backup_dirs(installer.native(state_dir(home)))[-1]
    assert later != installer.native(migration)
    with pytest.raises(installer.InstallError, match="restore the later transactions first, newest first") as error:
        run(source, "--restore", str(migration), "--dry-run")
    assert installer.display(later) in str(error.value)
    assert run(source, "--restore", str(later)) == 0 and run(source, "--restore", str(migration)) == 0
    assert state(home, "claude")["selection"] == ["@all"] and not hidden_from_claude(home / ".claude/skills/alpha")


def test_the_restore_order_names_each_later_claude_transaction_newest_first(sandbox):
    """Only the later transactions that still hold a part of this client's, newest first: not one of
    the other client's alone, not one already restored, not the refused transaction itself."""
    home, source = sandbox
    make_v1(home, source, "claude", ["@all"])
    assert run(source, "--claude-only") == 0
    backups = lambda: installer.backup_dirs(installer.native(state_dir(home)))  # noqa: E731
    [migration] = backups()
    skill(source, "alpha", body="changed upstream")
    assert run(source, "--claude-only") == 0
    assert run(source, "--codex-only") == 0, "Codex's first install: no part of Claude's"
    skill(source, "beta", body="changed upstream")
    assert run(source, "--claude-only") == 0
    first, codex, last = backups()[1:]
    with pytest.raises(installer.InstallError) as error:
        run(source, "--restore", str(migration), "--dry-run")
    assert str(error.value).endswith(f"newest first: {installer.display(last)}, {installer.display(first)}")
    assert run(source, "--claude-only", "--restore", str(last)) == 0
    with pytest.raises(installer.InstallError) as error:
        run(source, "--restore", str(migration), "--dry-run")
    assert str(error.value).endswith(f"newest first: {installer.display(first)}"), "a restored one is done"
    assert run(source, "--restore", str(first)) == 0 and run(source, "--claude-only", "--restore", str(migration)) == 0
    assert state(home, "claude")["selection"] == ["@all"]


def visible(home, client) -> list[str]:
    """The installed copies the model sees (the router among them)."""
    if client == "claude":
        return sorted(p.name for p in (home / ".claude/skills").iterdir() if not hidden_from_claude(p))
    roots = [home / ".codex/skills", home / SECOND]
    return sorted(p.name for r in roots if r.is_dir() for p in r.iterdir() if not hidden_from_codex(p))


def undo_of(line: str) -> list[str]:
    """The printed undo, as arguments: never a --restore, which needs a backup."""
    command = line.split("; undo: ", 1)[1]
    assert "--restore" not in command, line
    return shlex.split(command)


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
    undo = "--claude-only --selection @all --disable beta"
    assert out[0] == f"Migrated claude: {len(kept)} IDs -> visible @library, {len(every)} hidden; undo: {undo}"
    value = state(home, "claude")
    assert (value["selection"], value["manual"]) == (["@library"], ["@all"]), "the model's listing cannot overflow"
    assert all(hidden_from_claude(home / ".claude/skills" / s) for s in every)
    assert run(source, *undo_of(out[0])) == 0
    assert visible(home, "claude") == kept and state(home, "claude")["selection"] == kept, "the v1 visible set"
    run(source, "--claude-only")
    assert visible(home, "claude") == kept, "a v2 state: the migration never runs again"
    capsys.readouterr()
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 1)  # the two hidden copies
    run(source, "--codex-only")
    assert state(home, "codex")["selection"] == kept[:100], "Codex lists stay visible, as specified"
    line = capsys.readouterr().out.splitlines()[0]
    assert line == "Migrated codex: 100 IDs -> visible 100 IDs, 2 hidden; undo: --codex-only --manual ''"
    assert run(source, *undo_of(line)) == 0
    copies = [p for root in (home / ".codex/skills", home / SECOND) if root.is_dir() for p in root.iterdir()]
    assert visible(home, "codex") == kept[:100] and len(copies) == 100, "the v1 visible set, and nothing hidden"


@pytest.mark.parametrize("left_out", [3, 98])
def test_the_printed_undo_of_a_long_claude_list_is_the_shorter_selection_command(
    sandbox, monkeypatch, capsys, left_out
):
    """@all less what v1 left out, or the list itself when that is shorter; IDs that left the library
    since are not named, and a router v1 listed stays listed."""
    home, source = sandbox
    for i in range(98 + left_out):
        skill(source, f"extra-{i:03d}")
    every = installer.skill_ids(source)
    v1 = ["@library", "gone-upstream", *every[left_out:]]
    make_v1(home, source, "claude", [i for i in v1 if i != "gone-upstream"])
    value = state(home, "claude")
    (state_dir(home) / "claude.json").write_text(json.dumps(dict(value, selection=v1)))
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source, "--claude-only") == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith(f"Migrated claude: {len(v1)} IDs -> visible @library, {len(every)} hidden; undo: ")
    args = undo_of(line)
    shorter = "--disable" in args
    assert shorter == (left_out == 3) and "gone-upstream" not in line
    assert run(source, *args) == 0
    assert visible(home, "claude") == sorted([ROUTER, *every[left_out:]]), "the v1 visible set"


def test_the_printed_undo_keeps_a_v1_id_the_library_now_skips():
    """A skipped entry is frozen, not gone: --selection accepts it, so the undo names it."""
    library = SimpleNamespace(skills={"alpha": {}, "beta": {}, "gamma": {}}, skipped={"frozen": "invalid on Windows"})
    assert installer.migration_undo(["alpha", "frozen", "gone"], library) == "--selection alpha,frozen"


def test_the_printed_claude_undo_leaves_the_codex_migration_of_the_same_run(sandbox, monkeypatch, capsys):
    home, source = sandbox
    for i in range(100):
        skill(source, f"extra-{i:03d}")
    kept = [s for s in installer.skill_ids(source) if s != "beta"]
    make_v1(home, source, "claude", kept)
    make_v1(home, source, "codex", ["@library", "alpha"])
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source) == 0, "one transaction migrates both clients"
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("undo: --claude-only --selection @all --disable beta")
    assert out[1].startswith("Migrated codex: ") and out[1].endswith("undo: --codex-only --manual ''")
    codex = state(home, "codex")
    assert run(source, *undo_of(out[0])) == 0
    assert visible(home, "claude") == kept and state(home, "codex") == codex, "the Codex migration stays"


def test_a_kept_migration_backup_restores_one_client_at_a_time(sandbox, monkeypatch, capsys):
    """A migration from a local tree keeps its backup: --restore of one client's part is a lasting
    opt-out for it alone, recorded as undone in migrations.json, and the rest restores later."""
    home, source = sandbox
    for i in range(100):
        skill(source, f"extra-{i:03d}")
    kept = [s for s in installer.skill_ids(source) if s != "beta"]
    make_v1(home, source, "claude", kept)
    make_v1(home, source, "codex", ["@library", "alpha"])
    codex_v1 = state(home, "codex")
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 5)
    capsys.readouterr()
    assert run(source) == 0
    out = capsys.readouterr().out.splitlines()
    backup = out[2].split("Recovery backup: ", 1)[1]
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


def test_saved_ids_that_left_the_library_are_dropped_with_a_warning(sandbox, monkeypatch, capsys):
    home, source = sandbox
    make_v1(home, source, "claude", ["alpha", "beta"])
    make_v1(home, source, "codex", ["@library", "beta"])
    shutil.rmtree(source / "beta")  # renamed or removed upstream, as skill-creator was
    capsys.readouterr()
    assert run(source, "--dry-run") == 0
    migrations = {c["client"]: c["migration"] for c in json.loads(capsys.readouterr().out)["clients"]}
    assert migrations["codex"] == {"from": ["@library", "beta"], "selection": ["@library"], "manual": ["@all"]}
    assert migrations["claude"]["selection"] == ["alpha"], "the migration reports what stays visible"
    monkeypatch.setattr(installer, "SUMMARY_ACTIONS", 0)
    assert run(source) == 0, "neither client is blocked"
    out, err = capsys.readouterr()
    assert (
        "Migrated codex: @library,beta -> visible @library, 1 hidden, 1 removed (beta); undo: --codex-only --manual ''"
        in (out)
    )
    assert (
        "Migrated claude: alpha,beta -> visible alpha, 0 hidden, 1 removed (beta); undo: --claude-only --manual ''"
        in (out)
    )
    for client in ("claude", "codex"):
        assert err.count(f"{client}: dropping saved IDs that left the library (see --list --search): beta") == 1
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
