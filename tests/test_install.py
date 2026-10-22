"""Temporary HOME contract tests: no live client configuration is ever touched."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts import install_skills as installer

ROOT = Path(__file__).resolve().parents[1]


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
    for key in list(os.environ):
        if key.startswith("SKILLS_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("SKILLS_PYTHON", sys.executable)
    return home, source


def run(source, *args):
    return installer.main(["--source", str(source), *args])


def state(home, client="codex"):
    return json.loads((home / f".local/share/awesome-skills/{client}.json").read_text())


def backups(home):
    return sorted((home / ".local/share/awesome-skills/backups").iterdir())


def test_first_install_and_no_argument_updater(sandbox):
    home, source = sandbox
    run(source)
    codex = home / ".codex/skills"
    claude = home / ".claude/skills"
    assert sorted(p.name for p in codex.iterdir()) == [installer.ROUTER]
    assert sorted(p.name for p in claude.iterdir()) == ["alpha", "beta"]
    run(source, "--codex-only", "--enable", "alpha")
    before = installer.fingerprint(home)
    run(source)  # dotfiles updater: no selection/client arguments
    assert installer.fingerprint(home) == before
    assert state(home)["selection"] == ["@library", "alpha"]
    assert state(home, "claude")["selection"] == ["@all"]
    cache = next((home / ".cache/awesome-skills/libraries").iterdir())
    assert (cache / "skills/beta/SKILL.md").exists()
    assert json.loads((cache / "index.json").read_text())["beta"]["origins"]


def test_legacy_migration_exact_content_and_recovery(sandbox):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    before = installer.fingerprint(codex)
    run(source, "--codex-only")
    assert not (codex / "alpha").exists()
    recovery = backups(home)[-1]
    assert installer.fingerprint(recovery / "codex/alpha") == installer.fingerprint(source / "alpha")
    run(source, "--restore", str(recovery))
    assert installer.fingerprint(codex) == before
    assert not (home / ".local/share/awesome-skills/codex.json").exists()


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


def test_permission_change_prevents_legacy_adoption(sandbox):
    home, source = sandbox
    target = home / ".codex/skills/alpha"
    target.parent.mkdir(parents=True)
    shutil.copytree(source / "alpha", target)
    (target / "helper.txt").chmod(0o600)
    before = installer.fingerprint(target)
    run(source, "--codex-only")
    assert installer.fingerprint(target) == before


def test_symlinks_hidden_renamed_copies_and_agents_protected(sandbox):
    home, source = sandbox
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


def test_identical_frontmatter_names_deduplicate_with_provenance(sandbox):
    home, source = sandbox
    shutil.copytree(source / "alpha", source / "alias")
    run(source, "--codex-only", "--selection", "alpha,alias")
    assert len(list((home / ".codex/skills").iterdir())) == 1
    info = next(iter(state(home)["managed"].values()))
    assert info["source_ids"] == ["alias", "alpha"]
    assert "origins" in info
    cache = next((home / ".cache/awesome-skills/libraries").iterdir())
    assert json.loads((cache / "index.json").read_text())["alias"]["origins"]


def test_different_same_names_require_explicit_variant(sandbox):
    home, source = sandbox
    skill(source, "variant", name="alpha", body="different content")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="name conflicts"):
        run(source, "--codex-only", "--selection", "alpha,variant")
    assert installer.fingerprint(home) == before
    run(source, "--codex-only", "--selection", "variant")
    assert (home / ".codex/skills/variant").exists()
    cache = next((home / ".cache/awesome-skills/libraries").iterdir())
    assert (cache / "skills/alpha/SKILL.md").exists()


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


def test_cached_helper_is_self_contained_and_keeps_snapshot(sandbox):
    home, source = sandbox
    run(source, "--codex-only")
    cache_root = home / ".cache/awesome-skills/libraries"
    cache = next(cache_root.iterdir())
    result = subprocess.run(
        [sys.executable, "-B", str(cache / "install_skills.py"), "--codex-only", "--enable", "alpha"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(list(cache_root.iterdir())) == 1
    assert (home / ".codex/skills/alpha").exists()


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


def test_remote_dry_run_archive_is_in_memory(sandbox, monkeypatch):
    home, source = sandbox
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        archive.add(source, arcname="repo-main/skills")
        archive.add(ROOT / "scripts/install_skills.py", arcname="repo-main/scripts/install_skills.py")
    payload = buf.getvalue()
    monkeypatch.setattr(installer, "urlopen", lambda *a, **kw: io.BytesIO(payload))
    before = installer.fingerprint(home)
    installer.main(["--remote", "--codex-only", "--dry-run"])
    assert installer.fingerprint(home) == before
    # Remote bootstrap executes via python -c: __file__ does not exist.
    monkeypatch.delattr(installer, "__file__")
    installer.main(["--remote", "--codex-only", "--dry-run"])
    assert installer.fingerprint(home) == before


def test_reject_symlink_destination_and_discovered_cache(sandbox, monkeypatch):
    home, source = sandbox
    (home / ".codex").mkdir()
    (home / ".codex/skills").symlink_to(source)
    with pytest.raises(installer.InstallError, match="symlink"):
        run(source, "--codex-only")
    (home / ".codex/skills").unlink()
    monkeypatch.setenv("SKILLS_CACHE_DIR", str(home / ".codex/skills/cache"))
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


def test_duplicate_owned_legacy_copy_is_pruned_for_identical_external(sandbox):
    home, source = sandbox
    codex = home / ".codex/skills"
    shutil.copytree(source, codex)
    shutil.copytree(source / "alpha", codex / "user-alpha")
    run(source, "--codex-only", "--enable", "alpha")
    assert not (codex / "alpha").exists()
    assert (codex / "user-alpha").exists()
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


def test_interrupted_preparation_keeps_live_entries_and_is_restorable(sandbox, monkeypatch):
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
    with pytest.raises(OSError, match="storage failure"):
        run(source, "--codex-only")
    assert installer.fingerprint(codex) == before
    monkeypatch.setattr(installer, "write_tree", original)
    run(source, "--restore", str(backups(home)[-1]))
    assert installer.fingerprint(codex) == before


def test_no_argument_update_rebuilds_missing_cache(sandbox):
    home, source = sandbox
    run(source, "--codex-only")
    cache = next((home / ".cache/awesome-skills/libraries").iterdir())
    shutil.rmtree(cache)
    run(source, "--codex-only")
    assert (cache / "skills/alpha/SKILL.md").exists()


def test_cache_dotdot_cannot_bypass_discovery_separation(sandbox, monkeypatch):
    home, source = sandbox
    (home / "unused").mkdir()
    monkeypatch.setenv("SKILLS_CACHE_DIR", str(home / "unused/../.codex/skills/full-cache"))
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
    assert state(home)["destination"] == str(dest)
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


def test_changed_cache_helper_is_rejected(sandbox):
    home, source = sandbox
    run(source, "--codex-only")
    cache = next((home / ".cache/awesome-skills/libraries").iterdir())
    (cache / "install_skills.py").write_text("# edited helper")
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="Cache helper changed"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_helper_code_is_part_of_cache_snapshot(sandbox, tmp_path, monkeypatch):
    _, source = sandbox
    first = installer.Library(source)
    helper = tmp_path / "new-installer.py"
    helper.write_bytes(first.helper + b"\n# new version\n")
    monkeypatch.setattr(installer, "__file__", str(helper))
    second = installer.Library(source)
    assert first.skills == second.skills
    assert first.snapshot != second.snapshot


def test_duplicate_archive_member_is_rejected_before_writes(sandbox, monkeypatch):
    home, source = sandbox
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        archive.add(source, arcname="repo-main/skills")
        archive.add(source / "alpha/SKILL.md", arcname="repo-main/skills/alpha/SKILL.md")
    monkeypatch.setattr(installer, "urlopen", lambda *a, **kw: io.BytesIO(buf.getvalue()))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="Duplicate archive member"):
        installer.main(["--remote", "--codex-only"])
    assert installer.fingerprint(home) == before


def test_broken_symlink_state_is_never_replaced(sandbox):
    home, source = sandbox
    state_dir = home / ".local/share/awesome-skills"
    state_dir.mkdir(parents=True)
    (state_dir / "codex.json").symlink_to(home / "missing-state.json")
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
    state_root = home / ".local/share/awesome-skills"
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
    state_root = home / ".local/share/awesome-skills"
    with installer.state_lock(state_root), pytest.raises(installer.InstallError, match="Another"):
        run(source, "--codex-only")
    assert not (home / ".codex").exists()


def test_installation_does_not_require_git(sandbox, monkeypatch):
    home, source = sandbox
    monkeypatch.setattr(installer.shutil, "which", lambda _: None)
    run(source, "--codex-only")
    assert (home / ".codex/skills" / installer.ROUTER).exists()


@pytest.mark.parametrize("relative", ["workspace/.agents/skills/full", "workspace/.codex/skills/full"])
def test_cache_cannot_move_overload_into_project_discovery(sandbox, monkeypatch, relative):
    home, source = sandbox
    monkeypatch.setenv("SKILLS_CACHE_DIR", str(home / relative))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_cache_cannot_move_overload_into_custom_codex_home(sandbox, monkeypatch):
    home, source = sandbox
    monkeypatch.setenv("CODEX_HOME", str(home / "custom-codex"))
    monkeypatch.setenv("SKILLS_CACHE_DIR", str(home / "custom-codex/skills/full"))
    before = installer.fingerprint(home)
    with pytest.raises(installer.InstallError, match="disjoint"):
        run(source, "--codex-only")
    assert installer.fingerprint(home) == before


def test_single_client_cannot_target_symlinked_claude_collection(sandbox, monkeypatch):
    home, source = sandbox
    actual = home / "shared-claude"
    shutil.copytree(source, actual / "skills")
    (home / ".claude").symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("SKILLS_CODEX_DEST", str(actual / "skills"))
    before = installer.fingerprint(actual)
    with pytest.raises(installer.InstallError, match="destinations overlap"):
        run(source, "--codex-only")
    assert installer.fingerprint(actual) == before


def test_cache_cannot_target_symlinked_global_discovery(sandbox, monkeypatch):
    home, source = sandbox
    actual = home / "shared-claude"
    actual.mkdir()
    (home / ".claude").symlink_to(actual, target_is_directory=True)
    monkeypatch.setenv("SKILLS_CACHE_DIR", str(actual / "skills/full-cache"))
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
