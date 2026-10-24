"""Temporary HOME contract tests: no live client configuration is ever touched."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import install_skills as installer

ROOT = Path(__file__).resolve().parents[1]
POSIX_MODES = pytest.mark.skipif(os.name == "nt", reason="native Windows has no POSIX permission bits")


def can_symlink(tmp_path):
    try:
        (tmp_path / "symlink-probe").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        return False
    (tmp_path / "symlink-probe").unlink()
    return True


def snapshot(root):
    """Every entry's mtime, size and mode: an unchanged run must not rewrite anything."""
    return {str(p): (p.lstat().st_mtime_ns, p.lstat().st_size, p.lstat().st_mode) for p in sorted(root.rglob("*"))}


def skill(root, skill_id, name=None, body="body", description=None):
    p = root / skill_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "SKILL.md").write_text(
        f"---\nname: {name or skill_id}\ndescription: {description or ('Use ' + skill_id)}\n---\n{body}\n"
    )
    (p / "helper.txt").write_text("support file\n")
    return p


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "repo/skills"
    skill(source, "alpha")
    skill(source, "beta")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData/Local"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    for key in list(os.environ):
        if key.startswith("SKILLS_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SKILLS_PYTHON", sys.executable)
    return home, source


def run(source, *args):
    return installer.main(["--source", str(source), *args])


def state_dir(home):
    return home / ("AppData/Local" if os.name == "nt" else ".local/share") / "awesome-skills"


def state(home, client="codex"):
    return json.loads((state_dir(home) / f"{client}.json").read_text())


def backups(home):
    return sorted((state_dir(home) / "backups").iterdir())


def listed(capsys, source, *args):
    capsys.readouterr()
    run(source, "--list", *args)
    return json.loads(capsys.readouterr().out)


def test_first_install_and_no_argument_updater(sandbox, capsys):
    home, source = sandbox
    run(source)
    codex = home / ".codex/skills"
    claude = home / ".claude/skills"
    assert sorted(p.name for p in codex.iterdir()) == [installer.ROUTER]
    assert sorted(p.name for p in claude.iterdir()) == ["alpha", "beta"]
    run(source, "--codex-only", "--enable", "alpha")
    before, times = installer.fingerprint(home), snapshot(home)
    capsys.readouterr()
    run(source)  # consumer updater: no selection/client arguments
    assert capsys.readouterr().out == "Already current; selection preserved.\n"
    assert installer.fingerprint(home) == before
    assert snapshot(home) == times
    assert state(home)["selection"] == ["@library", "alpha"]
    assert state(home, "claude")["selection"] == ["@all"]
    assert state(home, "claude")["managed"]["beta"]["origins"]
    assert state(home, "claude")["managed"]["beta"]["tree"] == installer.tree_id(
        installer.local_listing(source / "beta")
    )
    assert not (home / ".cache").exists()


def test_unselected_legacy_copies_are_never_adopted_or_removed(sandbox, capsys):
    # An unmanaged directory identical to a library skill is not ours to remove.
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    legacy = {name: installer.fingerprint(codex / name) for name in ("alpha", "beta")}
    run(source, "--codex-only")
    assert {name: installer.fingerprint(codex / name) for name in ("alpha", "beta")} == legacy
    assert set(state(home)["managed"]) == {installer.ROUTER}
    plan = json.loads(capsys.readouterr().out.split("Recovery backup:")[0])
    assert {"entry": "alpha", "reason": "not installed by awesome-skills"} in plan["clients"][0]["preserved"]
    run(source, "--restore", str(backups(home)[-1]))
    assert sorted(os.listdir(codex)) == ["alpha", "beta"]
    assert not (state_dir(home) / "codex.json").exists()


def test_user_edit_extra_file_mode_and_unknown_are_preserved(sandbox):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    (codex / "alpha/helper.txt").write_text("user modified support file")
    (codex / "beta/extra.txt").write_text("user added file")
    unknown = skill(codex, "unowned")
    old = {p.name: installer.fingerprint(p) for p in codex.iterdir()}
    run(source, "--codex-only")
    assert all(installer.fingerprint(codex / k) == h for k, h in old.items())
    assert installer.fingerprint(unknown) == old["unowned"]


@POSIX_MODES
def test_permission_change_prevents_legacy_adoption(sandbox):
    home, source = sandbox
    target = home / ".codex/skills/alpha"
    target.parent.mkdir(parents=True)
    shutil.copytree(source / "alpha", target)
    mode = (target / "helper.txt").stat().st_mode & 0o777
    (target / "helper.txt").chmod(0o640 if mode == 0o600 else 0o600)  # differs from the source under any umask
    before = installer.fingerprint(target)
    run(source, "--codex-only")
    assert installer.fingerprint(target) == before


def test_symlinks_hidden_renamed_copies_and_agents_protected(sandbox, tmp_path):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    codex = home / ".codex/skills"
    codex.mkdir(parents=True)
    (codex / "alpha").symlink_to(source / "alpha", target_is_directory=True)
    (codex / "first-party").symlink_to(source / "beta", target_is_directory=True)
    skill(codex / ".system", "bundled")
    shutil.copytree(source / "beta", codex / "different-directory")
    skill(home / ".agents/skills", "agents-only")
    (home / ".agents/config.json").write_text("user config")
    assert all(installer.protected(codex / name) for name in ["alpha", "first-party", ".system"])
    assert not installer.protected(codex / "different-directory")  # kept as unowned, not by name
    agents = installer.fingerprint(home / ".agents")
    old = {p.name: installer.fingerprint(p) for p in codex.iterdir()}
    run(source, "--codex-only", "--delete")
    assert all(installer.fingerprint(codex / k) == h for k, h in old.items())
    assert installer.fingerprint(home / ".agents") == agents


def test_modified_managed_copy_survives_updates_and_deselection(sandbox):
    home, source = sandbox
    run(source, "--codex-only", "--enable", "alpha")
    alpha = home / ".codex/skills/alpha"
    (alpha / "SKILL.md").write_text((alpha / "SKILL.md").read_text() + "user edit")
    before = installer.fingerprint(alpha)
    run(source)
    run(source)
    run(source, "--codex-only", "--disable", "alpha")
    run(source)
    assert installer.fingerprint(alpha) == before
    assert "alpha" not in state(home)["selection"]


def test_claude_existing_user_edit_does_not_block_codex_fix(sandbox):
    home, source = sandbox
    target = home / ".claude/skills/alpha"
    skill(target.parent, "alpha", body="user modified")
    before = installer.fingerprint(target)
    run(source)
    run(source)
    assert installer.fingerprint(target) == before
    assert (home / ".codex/skills" / installer.ROUTER / "SKILL.md").exists()


def test_client_selections_are_independent(sandbox):
    home, source = sandbox
    run(source)
    codex_before = installer.fingerprint(home / ".codex")
    run(source, "--claude-only", "--selection", "beta")
    assert installer.fingerprint(home / ".codex") == codex_before
    assert not (home / ".claude/skills/alpha").exists()
    claude_before = installer.fingerprint(home / ".claude")
    run(source, "--codex-only", "--selection", "alpha")
    assert installer.fingerprint(home / ".claude") == claude_before
    run(source)
    assert state(home)["selection"] == ["alpha"]
    assert state(home, "claude")["selection"] == ["beta"]


def test_update_adds_only_new_claude_skill_and_preserves_codex_choice(sandbox):
    home, source = sandbox
    run(source)
    skill(source, "gamma")
    (source / "alpha/helper.txt").write_text("upstream update")
    run(source)
    assert (home / ".claude/skills/gamma").exists()
    assert not (home / ".codex/skills/gamma").exists()
    assert state(home)["selection"] == ["@library"]
    assert (home / ".claude/skills/alpha/helper.txt").read_text() == "upstream update"


def test_new_library_skill_manifest_is_accepted_by_later_runs(sandbox):
    # Ownership never depends on a name: what one run records, later runs and restore accept.
    home, source = sandbox
    run(source)
    skill(source, "late-upstream")
    run(source)
    assert "late-upstream" in state(home, "claude")["managed"]
    before = installer.fingerprint(home)
    run(source)
    assert installer.fingerprint(home) == before
    run(source, "--claude-only", "--disable", "late-upstream")
    assert not (home / ".claude/skills/late-upstream").exists()
    run(source, "--restore", str(backups(home)[-1]))
    assert (home / ".claude/skills/late-upstream").exists()


def test_identical_frontmatter_names_deduplicate_with_provenance(sandbox, capsys):
    home, source = sandbox
    shutil.copytree(source / "alpha", source / "alias")
    run(source, "--codex-only", "--selection", "alpha,alias")
    assert len(list((home / ".codex/skills").iterdir())) == 1
    info = next(iter(state(home)["managed"].values()))
    assert info["source_ids"] == ["alias", "alpha"]
    assert "origins" in info
    index = listed(capsys, source)
    assert index["skills"]["alias"]["origins"]
    assert index["skills"]["alias"]["tree"] == index["skills"]["alpha"]["tree"]


def test_different_same_names_require_explicit_variant(sandbox, capsys):
    home, source = sandbox
    skill(source, "variant", name="alpha", body="different content")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="name conflicts"):
        run(source, "--codex-only", "--selection", "alpha,variant")
    assert installer.fingerprint(home) == before
    run(source, "--codex-only", "--selection", "variant")
    assert (home / ".codex/skills/variant").exists()
    assert listed(capsys, source)["conflicts"] == {"alpha": ["alpha", "variant"]}


def test_claude_full_preserves_variants_and_reports_conflicts(sandbox, capsys):
    home, source = sandbox
    skill(source, "variant", name="alpha", body="different content")
    run(source)
    report = capsys.readouterr().out
    assert '"conflicts": {' in report and '"variant"' in report
    assert (home / ".claude/skills/alpha").exists()
    assert (home / ".claude/skills/variant").exists()
    assert not (home / ".codex/skills/alpha").exists()


def test_external_same_name_collision_fails_before_mutation(sandbox):
    home, source = sandbox
    skill(home / ".codex/skills", "user-alpha", name="alpha", body="custom")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="name conflict"):
        run(source, "--codex-only", "--enable", "alpha")
    assert installer.fingerprint(home) == before


def test_deselect_and_restore(sandbox):
    home, source = sandbox
    run(source, "--codex-only", "--enable", "alpha")
    run(source, "--codex-only", "--disable", "alpha")
    assert not (home / ".codex/skills/alpha").exists()
    recovery = backups(home)[-1]
    run(source, "--restore", str(recovery))
    assert (home / ".codex/skills/alpha").exists()
    assert "alpha" in state(home)["selection"]


@pytest.mark.parametrize("args", [(), ("--codex-only", "--enable", "alpha"), ("--claude-only", "--delete")])
def test_dry_run_zero_writes_and_no_mkdir(sandbox, args):
    home, source = sandbox
    before = installer.fingerprint(home)
    run(source, *args, "--dry-run")
    assert installer.fingerprint(home) == before
    assert not (home / ".codex").exists()
    assert not (home / ".cache").exists()
    assert not (home / ".local").exists()


def test_dry_run_existing_migration_and_restore_zero_writes(sandbox):
    home, source = sandbox
    shutil.copytree(source, home / ".codex/skills")
    before = installer.fingerprint(home)
    run(source, "--codex-only", "--dry-run")
    assert installer.fingerprint(home) == before
    run(source, "--codex-only")
    before = installer.fingerprint(home)
    run(source, "--restore", str(backups(home)[-1]), "--dry-run")
    assert installer.fingerprint(home) == before


def test_restore_refuses_later_user_modification(sandbox):
    home, source = sandbox
    run(source, "--codex-only", "--enable", "alpha")
    backup = backups(home)[-1]
    (home / ".codex/skills/alpha/helper.txt").write_text("edit after installation")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="overwrite changes"):
        run(source, "--restore", str(backup))
    assert installer.fingerprint(home) == before


def test_local_router_points_at_running_helper_and_source(sandbox):
    home, source = sandbox
    run(source, "--codex-only")
    body = (home / ".codex/skills" / installer.ROUTER / "SKILL.md").read_text()
    assert str(ROOT / "scripts/install_skills.py") in body
    assert f"--source {source}" in body.replace("'", "").replace('"', "")
    assert not (home / ".cache").exists()


@pytest.mark.skipif(os.name == "nt", reason="install.sh is the POSIX bootstrap; install.ps1 is covered separately")
def test_local_shell_updater_preserves_selection_without_arguments(sandbox):
    home, source = sandbox
    clone = source.parent
    shutil.copytree(ROOT / "scripts", clone / "scripts")
    shutil.copy2(ROOT / "install.sh", clone / "install.sh")
    first = subprocess.run(
        ["bash", str(clone / "install.sh"), "--codex-only", "--enable", "alpha"], capture_output=True
    )
    assert first.returncode == 0, first.stderr
    rerun = subprocess.run(["bash", str(clone / "install.sh")], capture_output=True)
    assert rerun.returncode == 0, rerun.stderr
    assert state(home)["selection"] == ["@library", "alpha"]
    assert not (home / ".codex/skills/beta").exists()


STORAGE = pytest.mark.parametrize("variable", ["SKILLS_DATA_DIR", "SKILLS_STATE_DIR", "SKILLS_CACHE_DIR"])


@STORAGE
def test_reject_symlink_destination_and_discovered_storage(sandbox, monkeypatch, tmp_path, variable):
    home, source = sandbox
    (home / ".codex").mkdir()
    if can_symlink(tmp_path):
        (home / ".codex/skills").symlink_to(source, target_is_directory=True)
        with pytest.raises(installer.InstallError, match="symlink"):
            run(source, "--codex-only")
        (home / ".codex/skills").unlink()
    monkeypatch.setenv(variable, str(home / ".codex/skills/cache"))
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")


def test_selection_changes_require_explicit_client(sandbox):
    _, source = sandbox
    with pytest.raises(SystemExit):
        run(source, "--enable", "alpha")


def test_modified_managed_copy_not_pruned_using_historical_dedup_hash(sandbox):
    home, source = sandbox
    run(source, "--codex-only", "--enable", "alpha")
    codex = home / ".codex/skills"
    (codex / "alpha/helper.txt").write_text("user edit")
    shutil.copytree(source / "alpha", codex / "user-alpha")
    before = installer.fingerprint(codex / "alpha")
    run(source, "--codex-only")
    assert installer.fingerprint(codex / "alpha") == before
    assert (codex / "user-alpha").exists()


def test_unmanaged_copy_with_identical_external_is_left_in_place(sandbox):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    shutil.copytree(source / "alpha", codex / "user-alpha")
    run(source, "--codex-only", "--enable", "alpha")
    assert (codex / "alpha").exists() and (codex / "user-alpha").exists()
    assert "alpha" not in state(home)["managed"]


def test_managed_copy_with_identical_external_is_removed(sandbox):
    home, source = sandbox
    codex = home / ".codex/skills"
    run(source, "--codex-only", "--enable", "alpha")
    shutil.copytree(source / "alpha", codex / "user-alpha")
    run(source, "--codex-only")
    assert not (codex / "alpha").exists() and (codex / "user-alpha").exists()
    assert "alpha" not in state(home)["managed"]


def test_generated_router_name_conflict_is_not_silently_overwritten(sandbox):
    home, source = sandbox
    skill(source, "other-router", name=installer.ROUTER)
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="name conflicts"):
        run(source, "--codex-only", "--enable", "other-router")
    assert installer.fingerprint(home) == before


def test_agents_name_conflict_is_read_only(sandbox):
    home, source = sandbox
    skill(home / ".agents/skills", "user-alpha", name="alpha", body="different")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="name conflict"):
        run(source, "--codex-only", "--enable", "alpha")
    assert installer.fingerprint(home) == before


def test_overlapping_client_destinations_are_rejected(sandbox, monkeypatch):
    home, source = sandbox
    monkeypatch.setenv("SKILLS_CLAUDE_DEST", str(home / ".codex/skills"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source)
    assert installer.fingerprint(home) == before


def test_failed_preparation_skips_only_that_entry_and_exits_nonzero(sandbox, monkeypatch, capsys):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    before = installer.fingerprint(codex)
    original = installer.write_tree

    def fail(entries, target):
        if "prepared" in target.parts:
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("partial copy")
            raise OSError("simulated storage failure")
        return original(entries, target)

    monkeypatch.setattr(installer, "write_tree", fail)
    assert run(source, "--codex-only") == 1
    assert "simulated storage failure" in capsys.readouterr().err
    assert installer.fingerprint(codex) == before
    assert not [
        f for f in backups(home)[-1].rglob("*") if f.is_file() and f.name != "restore.json"
    ], "partial copy left"
    monkeypatch.setattr(installer, "write_tree", original)
    assert run(source) == 0
    assert (codex / installer.ROUTER / "SKILL.md").is_file()


def test_one_failing_skill_does_not_block_the_others(sandbox, monkeypatch, capsys):
    home, source = sandbox
    original = installer.DirLibrary.materialize

    def fail_alpha(self, skill_id, target):
        if skill_id == "alpha":
            raise OSError("simulated unwritable path")
        original(self, skill_id, target)

    monkeypatch.setattr(installer.DirLibrary, "materialize", fail_alpha)
    assert run(source) == 1
    err = capsys.readouterr().err
    assert "claude:alpha" in err and "simulated unwritable path" in err
    claude = home / ".claude/skills"
    assert sorted(os.listdir(claude)) == ["beta"]
    assert set(state(home, "claude")["managed"]) == {"beta"}
    assert (home / ".codex/skills" / installer.ROUTER).is_dir()
    monkeypatch.setattr(installer.DirLibrary, "materialize", original)
    assert run(source) == 0
    assert sorted(os.listdir(claude)) == ["alpha", "beta"]


@STORAGE
def test_storage_dotdot_cannot_bypass_discovery_separation(sandbox, monkeypatch, variable):
    home, source = sandbox
    (home / "unused").mkdir()
    monkeypatch.setenv(variable, str(home / "unused/../.codex/skills/full-cache"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_single_client_cannot_target_other_clients_saved_destination(sandbox, monkeypatch):
    home, source = sandbox
    run(source)
    before = installer.fingerprint(home / ".claude")
    monkeypatch.setenv("SKILLS_CODEX_DEST", str(home / ".claude/skills"))
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source, "--codex-only")
    assert installer.fingerprint(home / ".claude") == before


def test_custom_destination_persists_for_no_argument_updater(sandbox, monkeypatch):
    home, source = sandbox
    dest = home / "custom-codex/skills"
    monkeypatch.setenv("SKILLS_CODEX_DEST", str(dest))
    run(source, "--codex-only", "--enable", "alpha")
    monkeypatch.delenv("SKILLS_CODEX_DEST")
    run(source)
    assert state(home)["destination"] == str(installer.native(dest))
    assert (dest / "alpha").exists()
    assert not (home / ".codex/skills").exists()


def test_reserved_router_directory_id_requires_explicit_choice(sandbox):
    home, source = sandbox
    skill(source, installer.ROUTER, name="different-frontmatter-name")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="reserved library entry"):
        run(source, "--codex-only", "--enable", installer.ROUTER)
    assert installer.fingerprint(home) == before


def test_restore_rejects_path_traversal_entry(sandbox):
    home, source = sandbox
    run(source, "--codex-only", "--enable", "alpha")
    backup = backups(home)[-1]
    journal_path = backup / "restore.json"
    journal = json.loads(journal_path.read_text())
    journal["clients"][0]["actions"][0]["entry"] = "../user-config.txt"
    journal_path.write_text(json.dumps(journal))
    unrelated = home / ".codex/user-config.txt"
    unrelated.write_text("configuration")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="Invalid managed entry"):
        run(source, "--restore", str(backup))
    assert installer.fingerprint(home) == before


def test_broken_symlink_state_is_never_replaced(sandbox, tmp_path):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    root = state_dir(home)
    root.mkdir(parents=True)
    (root / "codex.json").symlink_to(home / "missing-state.json")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="symlink state"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_empty_selection_persists(sandbox):
    home, source = sandbox
    run(source, "--codex-only")
    run(source, "--codex-only", "--selection", "")
    run(source)
    assert state(home)["selection"] == []
    assert list((home / ".codex/skills").iterdir()) == []


def test_source_using_router_directory_can_be_selected_without_generated_router(sandbox):
    home, source = sandbox
    skill(source, installer.ROUTER, name="explicit-source-variant")
    run(source, "--codex-only", "--selection", installer.ROUTER)
    assert installer.fingerprint(home / ".codex/skills" / installer.ROUTER) == installer.fingerprint(
        source / installer.ROUTER
    )


def test_cross_filesystem_preflight_preserves_all_live_entries(sandbox, monkeypatch):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    before = installer.fingerprint(codex)
    state_root = installer.native(state_dir(home))
    original = Path.stat

    def other_device(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == state_root:
            fields = list(result)
            fields[2] = result.st_dev + 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", other_device)
    with pytest.raises(installer.InstallError, match="same filesystem"):
        run(source, "--codex-only")
    assert installer.fingerprint(codex) == before
    assert not (home / ".cache").exists()


def test_state_lock_prevents_concurrent_apply(sandbox):
    home, source = sandbox
    state_root = state_dir(home)
    with installer.state_lock(state_root), pytest.raises(installer.InstallError, match="Another"):
        run(source, "--codex-only")
    assert not (home / ".codex").exists()


def test_installation_does_not_require_git(sandbox, monkeypatch):
    home, source = sandbox
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    run(source, "--codex-only")
    assert (home / ".codex/skills" / installer.ROUTER).exists()


@STORAGE
@pytest.mark.parametrize("relative", ["workspace/.agents/skills/full", "workspace/.codex/skills/full"])
def test_storage_cannot_move_overload_into_project_discovery(sandbox, monkeypatch, relative, variable):
    home, source = sandbox
    monkeypatch.setenv(variable, str(home / relative))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


@STORAGE
def test_storage_cannot_move_overload_into_custom_codex_home(sandbox, monkeypatch, variable):
    home, source = sandbox
    monkeypatch.setenv("CODEX_HOME", str(home / "custom-codex"))
    monkeypatch.setenv(variable, str(home / "custom-codex/skills/full"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_single_client_cannot_target_symlinked_claude_collection(sandbox, monkeypatch, tmp_path):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    actual = home / "shared-claude"
    shutil.copytree(source, actual / "skills")
    (home / ".claude").symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("SKILLS_CODEX_DEST", str(actual / "skills"))
    before = installer.fingerprint(actual)
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source, "--codex-only")
    assert installer.fingerprint(actual) == before


@STORAGE
def test_storage_cannot_target_symlinked_global_discovery(sandbox, monkeypatch, tmp_path, variable):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    actual = home / "shared-claude"
    actual.mkdir()
    (home / ".claude").symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv(variable, str(actual / "skills/full-cache"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_claude_modified_alias_conflict_does_not_abort_no_argument_updater(sandbox):
    home, source = sandbox
    shutil.copytree(source / "alpha", source / "alias")
    shutil.copytree(source, home / ".claude/skills")
    alpha = home / ".claude/skills/alpha"
    (alpha / "helper.txt").write_text("user modified Claude skill")
    before = installer.fingerprint(alpha)
    run(source, "--codex-only")
    codex_before = installer.fingerprint(home / ".codex")
    run(source)
    run(source)
    assert installer.fingerprint(alpha) == before
    assert (home / ".claude/skills/alias").exists()
    assert installer.fingerprint(home / ".codex") == codex_before


# Stands in for SIGKILL on every platform: the process ends inside apply, no finally runs.
KILLED_INSIDE_APPLY = """
import os, sys
sys.path.insert(0, sys.argv[1])
from scripts import install_skills as installer
original, moves = installer.move, []
def move(source, target):
    original(source, target)
    moves.append(target)
    if len(moves) == int(sys.argv[2]):
        os._exit(137)
installer.move = move
installer.main(sys.argv[3:])
"""


def killed_inside_apply(source, after_moves, *args):
    command = [sys.executable, "-B", "-c", KILLED_INSIDE_APPLY, str(ROOT), str(after_moves), "--source", str(source)]
    result = subprocess.run([*command, *args], capture_output=True, text=True)
    assert result.returncode == 137, result.stderr


def revise(source):
    for skill_id in ("alpha", "beta"):
        (source / skill_id / "helper.txt").write_text(f"{skill_id} revised\n")


def test_update_killed_mid_apply_is_undone_then_completed(sandbox, capsys):
    home, source = sandbox
    run(source)
    revise(source)
    killed_inside_apply(source, 3)  # alpha replaced, beta moved out, manifest not written
    claude = home / ".claude/skills"
    assert not (claude / "beta").exists()
    assert installer.interrupted_transaction(installer.native(state_dir(home))) is not None
    capsys.readouterr()
    assert run(source) == 0
    assert "Recovered an interrupted update" in capsys.readouterr().out
    assert all((claude / s / "helper.txt").read_text() == f"{s} revised\n" for s in ("alpha", "beta"))
    assert installer.interrupted_transaction(installer.native(state_dir(home))) is None
    assert run(source) == 0
    assert capsys.readouterr().out == "Already current; selection preserved.\n"


def test_interrupted_update_with_a_later_user_edit_needs_a_person(sandbox):
    home, source = sandbox
    run(source)
    revise(source)
    killed_inside_apply(source, 3)
    alpha = home / ".claude/skills/alpha"
    (alpha / "helper.txt").write_text("edited after the crash\n")
    before = installer.fingerprint(home / ".claude")
    with pytest.raises(installer.PersonNeeded, match="could not be undone automatically.*--restore"):
        run(source)
    assert installer.fingerprint(home / ".claude") == before
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--source", str(source)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == installer.NEEDS_PERSON, result.stderr


def test_exception_mid_apply_rolls_back_at_once(sandbox, monkeypatch):
    home, source = sandbox
    run(source)
    claude = home / ".claude/skills"
    before, record = installer.fingerprint(claude), state(home, "claude")
    revise(source)
    original, calls = installer.move, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 3:
            raise OSError("simulated rename failure")
        original(src, dst)

    monkeypatch.setattr(installer, "move", flaky)
    with pytest.raises(OSError, match="simulated rename failure"):
        run(source)
    assert installer.fingerprint(claude) == before and state(home, "claude") == record
    monkeypatch.setattr(installer, "move", original)
    assert run(source) == 0
    assert (claude / "beta/helper.txt").read_text() == "beta revised\n"


def test_old_backups_are_pruned_to_the_newest_few(sandbox, monkeypatch):
    home, source = sandbox
    monkeypatch.setenv("SKILLS_KEEP_BACKUPS", "2")
    run(source)
    for _ in range(2):
        run(source, "--codex-only", "--enable", "alpha")
        run(source, "--codex-only", "--disable", "alpha")
    kept = backups(home)
    assert len(kept) == 2
    run(source, "--restore", str(kept[-1]))
    assert (home / ".codex/skills/alpha").exists()


def test_atomic_json_leaves_no_temporary_file_on_failure(tmp_path, monkeypatch):
    def refuse(*_):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(installer.os, "replace", refuse)
    with pytest.raises(OSError, match="simulated"):
        installer.atomic_json(tmp_path / "state.json", {"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_update_that_would_remove_most_managed_skills_is_refused(sandbox):
    home, source = sandbox
    for i in range(23):
        skill(source, f"extra-{i:02d}")
    run(source)
    for i in range(23):
        shutil.rmtree(source / f"extra-{i:02d}")
    claude = home / ".claude/skills"
    before = installer.fingerprint(claude)
    with pytest.raises(installer.PersonNeeded, match="Refusing to remove 23 of 25 managed claude skills.*--allow"):
        run(source)
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--source", str(source)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == installer.NEEDS_PERSON, result.stderr
    assert installer.fingerprint(claude) == before
    assert run(source, "--allow-mass-removal") == 0
    assert sorted(os.listdir(claude)) == ["alpha", "beta"]


def test_explicit_selection_change_is_not_a_mass_removal(sandbox):
    home, source = sandbox
    for i in range(23):
        skill(source, f"extra-{i:02d}")
    run(source)
    assert run(source, "--claude-only", "--selection", "alpha") == 0
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha"]


@pytest.mark.skipif(os.name == "nt", reason="these names cannot be created on Windows at all")
def test_unportable_local_entries_are_skipped_with_a_warning(sandbox, capsys):
    home, source = sandbox
    skill(source, "colon")
    (source / "colon/a:b.txt").write_text("not a Windows name\n")
    skill(source, "aux")
    assert run(source) == 0
    err = capsys.readouterr().err
    assert "skipping library entry colon" in err and "skipping library entry aux" in err
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha", "beta"]


def without_flock(monkeypatch):
    def unsupported(fd):
        raise OSError(errno.ENOLCK, "No locks available")  # as on an NFS home without lockd

    monkeypatch.setattr(installer, "kernel_lock", unsupported)


def lock_file(home):
    return installer.native(state_dir(home)) / ".lock.excl"


def hold_lock_file(home, started):
    lock = lock_file(home)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(json.dumps({"token": "other-run", "started": started}).encode())
    return lock


def test_without_flock_an_exclusive_lock_file_takes_its_place(sandbox, monkeypatch):
    home, source = sandbox
    without_flock(monkeypatch)
    assert run(source) == 0
    assert not lock_file(home).exists()
    hold_lock_file(home, time.time())
    with pytest.raises(installer.LockBusy, match="Another awesome-skills installer is running"):
        run(source)
    hold_lock_file(home, time.time() - installer.STALE_LOCK_SECONDS - 60)
    assert run(source) == 0, "a lock older than any run is stale"
    assert not lock_file(home).exists() and not list(lock_file(home).parent.glob(".lock.excl.stale-*"))


def test_an_unreadable_old_lock_file_is_stale_by_its_age(sandbox, monkeypatch):
    home, source = sandbox
    without_flock(monkeypatch)
    lock = hold_lock_file(home, 0)
    lock.write_bytes(b"{partial")  # its run died while writing it
    old = time.time() - installer.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    assert run(source) == 0
    lock.write_bytes(b"{partial")
    with pytest.raises(installer.LockBusy):
        run(source)  # the same content written just now is a live lock


def test_takeover_never_keeps_a_lock_another_run_just_took(sandbox, monkeypatch):
    home, source = sandbox
    without_flock(monkeypatch)
    lock = hold_lock_file(home, time.time() - installer.STALE_LOCK_SECONDS - 60)
    fresh = json.dumps({"token": "contender", "started": time.time()}).encode()
    original = os.rename

    def contender_first(src, dst):
        if Path(src) == lock:  # between our read and our rename, a contender took the lock over
            lock.unlink()
            lock.write_bytes(fresh)
        return original(src, dst)

    monkeypatch.setattr(installer.os, "rename", contender_first)
    with pytest.raises(installer.LockBusy):
        run(source)
    assert lock.read_bytes() == fresh, "the contender's lock is put back"
    assert not list(lock.parent.glob(".lock.excl.stale-*"))
    assert not (home / ".claude").exists()


def test_a_lock_that_vanishes_during_takeover_is_retried(sandbox, monkeypatch):
    home, source = sandbox
    without_flock(monkeypatch)
    lock = hold_lock_file(home, time.time() - installer.STALE_LOCK_SECONDS - 60)
    original = os.rename

    def released(src, dst):
        if Path(src) == lock:
            lock.unlink()  # its owner (or another contender) removed it first
        return original(src, dst)

    monkeypatch.setattr(installer.os, "rename", released)
    assert run(source) == 0
    assert not lock.exists()


def test_a_state_directory_that_cannot_be_locked_fails_with_advice(sandbox, monkeypatch):
    _, source = sandbox
    without_flock(monkeypatch)
    original = os.open

    def refuse(path, flags, *args, **kwargs):
        if str(path).endswith(".lock.excl"):
            raise PermissionError(errno.EACCES, "Permission denied")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(installer.os, "open", refuse)
    with pytest.raises(installer.InstallError, match="set SKILLS_STATE_DIR and SKILLS_DATA_DIR"):
        run(source)


def test_backups_are_ordered_by_their_clock_independent_stamp(sandbox):
    home, source = sandbox
    run(source)
    root = installer.native(state_dir(home)) / "backups"
    journal = (installer.backup_dirs(installer.native(state_dir(home)))[-1] / "restore.json").read_text()
    # Local wall-clock names that run backwards across a daylight-saving change:
    later = root / "20261101T013000-02000000000000000002-bbbbbbbb"
    earlier = root / "20261101T015959-02000000000000000001-aaaaaaaa"
    for path, status in ((earlier, "complete"), (later, "applying")):
        path.mkdir()
        (path / "restore.json").write_text(journal.replace('"status": "complete"', f'"status": "{status}"'))
    ordered = installer.backup_dirs(installer.native(state_dir(home)))
    assert ordered[-2:] == [installer.native(earlier), installer.native(later)]
    assert installer.interrupted_transaction(installer.native(state_dir(home))) == installer.native(later)
    (later / "restore.json").write_text(journal)
    (earlier / "restore.json").write_text(journal.replace('"status": "complete"', '"status": "applying"'))
    found = installer.interrupted_transaction(installer.native(state_dir(home)))
    assert found == installer.native(earlier), "every kept journal is checked, not only the newest"


def test_a_local_tree_may_still_contain_links(sandbox, tmp_path):
    home, source = sandbox
    if not can_symlink(tmp_path):
        pytest.skip("symlinks unavailable")
    linked = skill(source, "linked")
    (linked / "helper-link").symlink_to("helper.txt")
    assert run(source) == 0
    installed = home / ".claude/skills/linked/helper-link"
    assert installer.is_link(installed) and os.readlink(installed) == "helper.txt"
    assert "linked" in state(home, "claude")["managed"]
