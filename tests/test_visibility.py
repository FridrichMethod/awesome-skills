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


def test_an_upstream_change_is_installed_still_hidden(sandbox):
    home, source = sandbox
    run(source)
    (source / "alpha/helper.txt").write_text("upstream change\n")
    run(source)
    for copy in (home / ".claude/skills/alpha", codex_copy(home, "alpha")):
        assert (copy / "helper.txt").read_text() == "upstream change\n"
    assert hidden_from_claude(home / ".claude/skills/alpha") and hidden_from_codex(codex_copy(home, "alpha"))


def test_exact_client_copies_are_adopted_and_raw_trees_copied_again(sandbox, capsys):
    home, source = sandbox
    run(source)
    for client in ("claude", "codex"):
        (state_dir(home) / f"{client}.json").unlink()
    claude = home / ".claude/skills"
    shutil.rmtree(claude / "beta")
    shutil.copytree(source / "beta", claude / "beta")  # the library tree, not the hidden copy
    alpha = installer.fingerprint(claude / "alpha")
    capsys.readouterr()
    run(source, "--claude-only")
    actions = [a["entry"] for a in plan(capsys)["clients"][0]["actions"]]
    assert actions == ["beta"], "the exact hidden alpha is recorded, the raw beta copied again"
    assert installer.fingerprint(claude / "alpha") == alpha and hidden_from_claude(claude / "beta")
    assert set(state(home, "claude")["managed"]) == {"alpha", "beta"}


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


# --- Migration -------------------------------------------------------------------------------


def make_v1(home, source, client, selection, manual=""):
    """An install as the installer before hidden installs left it: v1 state, plain copies."""
    run(source, f"--{client}-only", "--selection", ",".join(selection), "--manual", manual)
    path = state_dir(home) / f"{client}.json"
    value = json.loads(path.read_text())
    for key in ("manual", "selection_version"):
        value.pop(key)
    for record in value["managed"].values():
        record.pop("invocation")
    path.write_text(json.dumps(value))


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
    assert codex_copy(home, "beta").is_dir() and not hidden_from_codex(codex_copy(home, "beta"))
    assert hidden_from_codex(codex_copy(home, "alpha"))
    assert state(home, "codex")["selection"] == ["@library", "beta"]


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


def test_a_saved_destination_of_the_other_client_still_counts_when_overridden(sandbox, monkeypatch):
    home, source = sandbox
    run(source, "--claude-only")
    monkeypatch.setenv("SKILLS_CLAUDE_DEST", str(home / "elsewhere/skills"))
    monkeypatch.setenv("SKILLS_CODEX_DEST2", str(home / ".claude/skills"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before
