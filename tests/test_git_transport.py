"""Git transport contract tests: a bare repository over file:// is the remote, HOME is temporary."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
import yaml

from scripts import install_skills as installer
from tests.gitfixtures import (
    ROOT,
    WINDOWS,
    Upstream,
    data_dir,
    git,
    isolate,
    missing_objects,
    object_types,
    packed_objects,
    put,
    snapshot,
    without_pyyaml,
)
from tests.test_install import codex_copy, hidden_from_claude

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


@pytest.fixture
def remote(tmp_path, monkeypatch):
    home = isolate(monkeypatch, tmp_path)
    upstream = Upstream(tmp_path)
    monkeypatch.setenv("SKILLS_REPOSITORY_URL", upstream.url)
    previous = os.umask(0o022)
    yield home, upstream
    os.umask(previous)


def run(*args):
    return installer.main(["--remote", *args])


def clone(home):
    return data_dir(home) / installer.CLONE


def manifest(home, client):
    return json.loads((data_dir(home) / f"{client}.json").read_text())


def subprocess_env(**extra):
    return {**os.environ, "SKILLS_PYTHON": sys.executable, **extra}


def test_first_install_is_a_blobless_sparse_clone(remote):
    home, upstream = remote
    run()
    repo = clone(home)
    assert (repo / ".git" / installer.MARKER).is_file()
    assert git("-C", str(repo), "config", "remote.origin.promisor").strip() == "true"
    assert git("-C", str(repo), "config", "remote.origin.partialclonefilter").strip() == "blob:none"
    assert not (repo / "skills").exists(), "skill content is checked out only while installing"
    assert (repo / "scripts/install_skills.py").is_file() and (repo / installer.INDEX).is_file()
    claude = home / ".claude/skills"
    assert sorted(os.listdir(claude)) == ["alpha", installer.ROUTER, "beta"]
    assert (claude / "alpha/nested/deep/data.txt").read_bytes() == b"alpha data\n"
    trees = upstream.trees()
    assert manifest(home, "claude")["managed"]["alpha"]["tree"] == trees["alpha"]
    # The installer's own git tree hashing agrees with git, for a copy shown to the model.
    run("--claude-only", "--enable", "beta")
    assert installer.tree_id(installer.local_listing(claude / "beta")) == trees["beta"]
    launcher = data_dir(home) / "bin/awesome-skills"
    router = (home / ".codex/skills" / installer.ROUTER / "SKILL.md").read_text()
    assert f"{installer.launcher_call(installer.native(data_dir(home)))} search --client codex" in router
    assert str(repo / "scripts" / "install_skills.py") in launcher.read_text()
    assert all(codex_copy(home, s).is_dir() for s in ("alpha", "beta"))


def test_unchanged_update_is_one_fetch_and_no_writes(remote, monkeypatch, capsys):
    home, _ = remote
    run()
    before = snapshot(home)
    calls = []
    original = installer.Git.run

    def spy(self, repo, *args, **kwargs):
        calls.append(args[0])
        return original(self, repo, *args, **kwargs)

    monkeypatch.setattr(installer.Git, "run", spy)
    capsys.readouterr()
    assert run() == 0
    assert capsys.readouterr().out == "Already current; selection preserved.\n"
    assert snapshot(home) == before  # destinations, state and the clone itself
    assert calls.count("fetch") == 1
    assert not {"clone", "checkout", "sparse-checkout", "gc", "remote"} & set(calls)


def test_changed_skill_fetches_only_its_new_blob_and_rewrites_only_it(remote):
    home, upstream = remote
    run()
    repo, claude = clone(home), home / ".claude/skills"
    beta = snapshot(claude / "beta")
    codex = snapshot(codex_copy(home, "beta"))
    packs = packed_objects(repo)
    upstream.skill("alpha", files={"helper.txt": "alpha support, revised\n"})
    upstream.commit("revise alpha")
    run()
    fetched = set().union(*(oids for name, oids in packed_objects(repo).items() if name not in packs))
    kinds = object_types(repo, fetched)
    blobs = {oid for oid, kind in kinds.items() if kind == "blob"}
    assert blobs == {installer.blob_id(b"alpha support, revised\n")}
    assert sorted(kind for kind in kinds.values() if kind != "tree") == ["blob", "commit"]
    changed = {upstream.rev(spec) for spec in ("main^{tree}", "main:skills", "main:skills/alpha")}
    trees = {oid for oid, kind in kinds.items() if kind == "tree"}
    # Only trees on the changed path; git may resend the previous root tree as a delta base.
    assert changed <= trees <= changed | {upstream.rev("main~1^{tree}")}
    assert (claude / "alpha/helper.txt").read_bytes() == b"alpha support, revised\n"
    assert snapshot(claude / "beta") == beta
    assert snapshot(codex_copy(home, "beta")) == codex
    assert (codex_copy(home, "alpha") / "helper.txt").read_bytes() == b"alpha support, revised\n"
    assert (codex_copy(home, "alpha") / installer.POLICY_FILE).is_file(), "still hidden"
    assert manifest(home, "claude")["managed"]["alpha"]["tree"] == upstream.trees()["alpha"]


def test_changed_skill_bodies_are_downloaded_in_one_batch(remote):
    """The weekly update changes many SKILL.md files: planning must not read one (in a blobless
    clone each blob read alone is a fetch), so the run adds the fetch and one download."""
    home, upstream = remote
    ids = ["alpha", "beta", *(f"extra-{i}" for i in range(4))]
    for skill_id in ids[2:]:
        upstream.skill(skill_id)
    upstream.commit("more skills")
    run()
    repo = clone(home)
    packs = set(packed_objects(repo))
    for skill_id in ids:
        upstream.skill(skill_id, body=f"{skill_id} revised")
    upstream.commit("revise every body")
    assert run("--dry-run") == 0
    assert len(set(packed_objects(repo)) - packs) == 1, "a dry run fetches commits and trees, no blob"
    assert run() == 0
    assert len(set(packed_objects(repo)) - packs) == 2, "the new bodies come in one batch"
    for skill_id in ids:
        for copy in (home / ".claude/skills" / skill_id, codex_copy(home, skill_id)):
            assert f"{skill_id} revised" in (copy / "SKILL.md").read_text() and hidden_from_claude(copy)


def test_only_selected_skills_are_downloaded(remote):
    home, upstream = remote
    run("--claude-only", "--selection", "alpha", "--manual", "")
    run("--codex-only", "--manual", "")
    repo = clone(home)
    assert upstream.blobs("beta") <= missing_objects(repo)
    assert not upstream.blobs("alpha") & missing_objects(repo)
    run("--codex-only", "--enable", "beta")
    assert not upstream.blobs("beta") & missing_objects(repo)
    assert (codex_copy(home, "beta") / "helper.txt").read_bytes() == b"beta support\n"
    assert not (home / ".claude/skills/beta").exists()


def test_deleted_managed_copy_is_reinstalled_alone(remote):
    home, _ = remote
    run()
    claude = home / ".claude/skills"
    alpha = snapshot(claude / "alpha")
    shutil.rmtree(claude / "beta")
    run()
    assert (claude / "beta/helper.txt").is_file()
    assert snapshot(claude / "alpha") == alpha


def make_legacy_install(home, upstream):
    """What the tarball installer left behind: manifests without tree ids, GitHub tarball modes, a cache."""
    state, claude, codex = data_dir(home), home / ".claude/skills", home / ".codex/skills"
    cache = home / ".cache/awesome-skills"
    snapshot_dir = cache / "libraries" / ("ab" * 32)
    managed = {}
    for skill_id in ("alpha", "beta"):
        shutil.copytree(upstream.work / "skills" / skill_id, claude / skill_id)
        shutil.copytree(upstream.work / "skills" / skill_id, snapshot_dir / "skills" / skill_id)
        if not WINDOWS:
            for path in [claude / skill_id, *(claude / skill_id).rglob("*")]:
                path.chmod(0o775 if path.is_dir() else 0o664)
        managed[skill_id] = {
            "name": skill_id,
            "description": f"Use {skill_id}",
            "origins": [{"repository": installer.REPOSITORY, "path": f"skills/{skill_id}"}],
            "sha256": installer.fingerprint(claude / skill_id),
            "source_ids": [skill_id],
        }
    for name in ("index.json", "library_sources.json"):
        put(snapshot_dir / name, "{}\n")
    put(snapshot_dir / "install_skills.py", "# old helper\n")
    put(cache / "notes.txt", "user file\n")
    (cache / "libraries/keep-me").mkdir()
    put(codex / installer.ROUTER / "SKILL.md", f"---\nname: {installer.ROUTER}\n---\nUse {snapshot_dir}\n")
    router = {
        "name": installer.ROUTER,
        "sha256": installer.fingerprint(codex / installer.ROUTER),
        "source_ids": ["@library"],
        "origins": [],
    }
    for client, dest, entries, selection in [
        ("claude", claude, managed, ["alpha", "beta"]),
        ("codex", codex, {installer.ROUTER: router}, ["@library"]),
    ]:
        record = {"schema": 1, "client": client, "destination": str(installer.native(dest)), "selection": selection}
        put(state / f"{client}.json", json.dumps(dict(record, managed=entries)))
    return snapshot_dir


def test_tarball_install_is_adopted_without_recopying(remote):
    home, upstream = remote
    legacy = make_legacy_install(home, upstream)
    claude = home / ".claude/skills"
    (claude / "beta/helper.txt").write_text("user edit after the old install\n")
    alpha, beta = snapshot(claude / "alpha"), installer.fingerprint(claude / "beta")
    run()
    assert snapshot(claude / "alpha") == alpha, "identical content is recognized, not copied again"
    assert installer.fingerprint(claude / "beta") == beta, "a user-modified managed copy stays preserved"
    records = manifest(home, "claude")["managed"]
    assert records["alpha"]["tree"] == upstream.trees()["alpha"]
    assert "tree" not in records["beta"]
    router = manifest(home, "codex")["managed"][installer.ROUTER]
    launcher = data_dir(home) / "bin/awesome-skills"
    assert router["tree"] and str(launcher) in (home / ".codex/skills" / installer.ROUTER / "SKILL.md").read_text()
    cache = home / ".cache/awesome-skills"
    assert not legacy.exists()
    assert (cache / "notes.txt").is_file() and (cache / "libraries/keep-me").is_dir()


def test_a_tarball_install_of_all_migrates_to_hidden_copies(remote):
    home, upstream = remote
    make_legacy_install(home, upstream)
    path = data_dir(home) / "claude.json"
    put(path, json.dumps(dict(json.loads(path.read_text()), selection=["@all"])))  # Claude's old default
    claude = home / ".claude/skills"
    (claude / "beta/helper.txt").write_text("user edit after the old install\n")
    beta = installer.fingerprint(claude / "beta")
    assert run() == 0
    assert hidden_from_claude(claude / "alpha") and installer.fingerprint(claude / "beta") == beta
    value = manifest(home, "claude")
    assert (value["selection"], value["manual"]) == (["@library"], ["@all"]) and (claude / installer.ROUTER).is_dir()
    assert "tree" not in value["managed"]["beta"], "the modified copy keeps its tarball record"


# Shapes from the library that a line-based reader gets wrong: a quoted value whose next line
# starts at column 0 with `name:`, a flow mapping spanning lines, an indentless sequence.
SHAPED_SKILL = """---
name: gamma
description: "Spans lines; the next one starts at column 0 and is not a key:
name: still the description"
allowed-tools: [Read, Write]
metadata:
  {
    "openclaw": {"emoji": "x", "name": "nested"},
  }
tags:
- a
- name: nested
---
body
"""


def test_remote_install_needs_only_the_standard_library(remote, tmp_path):
    home, upstream = remote
    put(upstream.work / "skills/gamma/SKILL.md", SHAPED_SKILL)
    upstream.commit("frontmatter shapes")
    env = without_pyyaml(tmp_path, subprocess_env())
    helper = [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--remote"]
    first = subprocess.run(helper, capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha", installer.ROUTER, "beta", "gamma"]
    assert manifest(home, "claude")["managed"]["gamma"]["name"] == "gamma"
    hidden = (home / ".claude/skills/gamma/SKILL.md").read_text()
    assert hidden == f"---\n{installer.HIDDEN_KEY}: true\n" + SHAPED_SKILL[4:], "transformed without PyYAML"
    assert (codex_copy(home, "gamma") / installer.POLICY_FILE).is_file()
    # A user's own skill is matched by its frontmatter name without PyYAML, too.
    put(home / ".agents/skills/mine/SKILL.md", "---\nname: 'gamma'\ndescription: mine\n---\n")
    conflict = subprocess.run([*helper, "--codex-only", "--enable", "gamma"], capture_output=True, text=True, env=env)
    assert conflict.returncode == 1 and "Frontmatter name conflict" in conflict.stderr, conflict.stderr
    router = [sys.executable, "-B", str(clone(home) / "scripts/install_skills.py"), "--list", "--search", "gamma"]
    listed = subprocess.run(router, capture_output=True, text=True, env=env)
    assert listed.returncode == 0, listed.stderr
    assert list(json.loads(listed.stdout)["skills"]) == ["gamma"]


def test_remote_codex_copies_are_renamed_and_hidden_with_the_standard_library(remote, tmp_path):
    """The edits most library skills need (a name that is not the ID, an agents/openai.yaml with or
    without a policy, a nested SKILL.md) run without PyYAML, as on a fresh host."""
    home, upstream = remote
    upstream.skill("delta", name="shared-name")
    upstream.skill("eps", files={installer.POLICY_FILE: "interface:\n  display_name: Eps\n"})
    upstream.skill("zeta", files={installer.POLICY_FILE: "policy:\n  allow_implicit_invocation: true\n"})
    upstream.skill("eta", files={"tools/inner/SKILL.md": "---\nname: inner\ndescription: Nested.\n---\n"})
    upstream.commit("shapes the Codex copies edit")
    env = without_pyyaml(tmp_path, subprocess_env())
    first = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--remote"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert first.returncode == 0, first.stderr
    copies = {s: codex_copy(home, s) for s in ("delta", "eps", "zeta", "eta")}
    copies["eta--tools-inner"] = copies["eta"] / "tools/inner"
    for name, copy in copies.items():
        assert installer.frontmatter_name((copy / "SKILL.md").read_bytes(), name) == name
        assert yaml.safe_load((copy / installer.POLICY_FILE).read_text())["policy"] == {
            "allow_implicit_invocation": False
        }
    assert yaml.safe_load((copies["eps"] / installer.POLICY_FILE).read_text())["interface"] == {"display_name": "Eps"}
    assert (
        hidden_from_claude(home / ".claude/skills/delta")
        and "shared-name" in (home / ".claude/skills/delta/SKILL.md").read_text()
    ), "Claude's copy keeps its name"


def test_remote_claude_copies_named_like_a_claude_code_command_are_renamed(remote, tmp_path):
    """/review would run a personal skill named review: its Claude copy takes its ID as name, without
    PyYAML, and the next run finds it current."""
    home, upstream = remote
    upstream.skill("review--up--0123456789", name="review")
    upstream.commit("a skill named like /review")
    env = without_pyyaml(tmp_path, subprocess_env())
    helper = [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--remote"]
    first = subprocess.run(helper, capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    copy = home / ".claude/skills/review--up--0123456789"
    assert installer.frontmatter_name((copy / "SKILL.md").read_bytes(), "x") == copy.name and hidden_from_claude(copy)
    assert manifest(home, "claude")["managed"][copy.name]["name"] == copy.name
    again = subprocess.run(helper, capture_output=True, text=True, env=env)
    assert again.returncode == 0 and again.stdout == "Already current; selection preserved.\n", again.stdout


def test_a_line_break_claude_code_does_not_see_fails_its_skill_for_both_clients(remote, capsys):
    """The sync rejects `a<U+2028>b: c` in a frontmatter; a library commit that bypassed it still gets
    no copy at all, since Claude Code would drop its frontmatter, disable-model-invocation included."""
    home, upstream = remote
    put(upstream.work / "skills/sneaky/SKILL.md", "---\nname: sneaky\ndescription: Use X\u2028extra: v\n---\nbody\n")
    index = json.loads((upstream.work / installer.INDEX).read_text())
    index["skills"]["sneaky"] = {"name": "sneaky", "description": "Use X"}
    put(upstream.work / installer.INDEX, json.dumps(index))
    upstream.commit("bypassed the sync", index=False)
    capsys.readouterr()
    assert run() == 1
    err = capsys.readouterr().err
    assert "claude:sneaky (Frontmatter at sneaky/SKILL.md holds U+2028" in err, err
    assert "codex:sneaky (Frontmatter at sneaky/SKILL.md holds U+2028" in err, err
    assert not (home / ".claude/skills/sneaky").exists() and not codex_copy(home, "sneaky").exists()
    assert hidden_from_claude(home / ".claude/skills/alpha")


def test_lock_contention_exits_75(remote):
    home, _ = remote
    with installer.state_lock(installer.native(data_dir(home))):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/install_skills.py"), "--remote"],
            capture_output=True,
            text=True,
            env=subprocess_env(),
        )
    assert result.returncode == installer.LOCK_BUSY, result.stderr
    assert "Another awesome-skills installer is running" in result.stderr
    assert not clone(home).exists()


def test_missing_git_fails_before_writing(remote, monkeypatch):
    home, _ = remote
    monkeypatch.setattr(installer, "find_git", lambda: None)
    wanted = re.escape(installer.minimum_git()[1])
    with pytest.raises(installer.InstallError, match=f"git {wanted} or newer is required; git was not found"):
        run()
    assert snapshot(home) == {}


def test_old_git_fails_before_writing(remote, monkeypatch, tmp_path):
    home, _ = remote
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if WINDOWS:
        (bin_dir / "git.bat").write_text("@echo git version 2.20.1.windows.1\r\n")
    else:
        fake = bin_dir / "git"
        fake.write_text("#!/bin/sh\necho 'git version 2.20.1'\n")
        fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    wanted = re.escape(installer.minimum_git()[1])
    with pytest.raises(
        installer.InstallError, match=f"git {wanted} or newer is required; found git version 2\\.20\\.1"
    ):
        run()
    assert snapshot(home) == {}


def test_router_helper_in_the_data_dir_serves_the_clone(remote, tmp_path):
    home, _ = remote
    run()
    helper = clone(home) / "scripts/install_skills.py"
    offline = subprocess_env(SKILLS_REPOSITORY_URL=(tmp_path / "unreachable.git").as_uri())
    listed = subprocess.run(
        [sys.executable, "-B", str(helper), "--list", "--search", "beta"], capture_output=True, text=True, env=offline
    )
    assert listed.returncode == 0, listed.stderr
    assert list(json.loads(listed.stdout)["skills"]) == ["beta"]
    enabled = subprocess.run(
        [sys.executable, "-B", str(helper), "--codex-only", "--enable", "beta"],
        capture_output=True,
        text=True,
        env=subprocess_env(),
    )
    assert enabled.returncode == 0, enabled.stderr
    assert (codex_copy(home, "beta") / "SKILL.md").is_file()


def test_failed_fetch_keeps_the_previous_install(remote, monkeypatch, tmp_path):
    home, _ = remote
    run()
    installed = installer.fingerprint(home / ".claude")
    monkeypatch.setenv("SKILLS_REPOSITORY_URL", (tmp_path / "gone.git").as_uri())
    with pytest.raises(installer.InstallError, match="git fetch failed"):
        run()
    assert installer.fingerprint(home / ".claude") == installed
    assert not list(data_dir(home).glob("library.broken-*")), "an unreachable remote is not a broken clone"


def test_foreign_directory_at_the_clone_path_is_refused(remote):
    home, _ = remote
    put(clone(home) / "notes.txt", "mine\n")
    with pytest.raises(installer.InstallError, match="Not an awesome-skills library clone"):
        run()
    assert (clone(home) / "notes.txt").read_text() == "mine\n"
    assert not (home / ".claude").exists()


def test_interrupted_download_leaves_no_transaction(remote, monkeypatch):
    home, _ = remote
    original = installer.GitLibrary.prepare

    def fail(self, ids):
        raise installer.InstallError("simulated network failure")

    monkeypatch.setattr(installer.GitLibrary, "prepare", fail)
    with pytest.raises(installer.InstallError, match="simulated"):
        run()
    assert not (home / ".claude").exists() and not (data_dir(home) / "backups").exists()
    monkeypatch.setattr(installer.GitLibrary, "prepare", original)
    run()
    assert (home / ".claude/skills/alpha/SKILL.md").is_file()


def test_deep_paths_install_on_every_platform(remote):
    home, upstream = remote
    deep = "/".join(["a-directory-name-long-enough-to-nest"] * 7) + "/file.txt"
    upstream.skill("gamma", files={deep: "deep\n"})
    upstream.commit("deep skill")
    run()
    installed = installer.native(home / ".claude/skills/gamma") / deep
    assert len(str(installed)) > 260
    assert installed.read_bytes() == b"deep\n"
    run("--claude-only", "--manual", "")
    assert not installer.native(home / ".claude/skills/gamma").exists()


def test_disable_and_restore_after_a_git_update(remote):
    home, _ = remote
    run()
    run("--claude-only", "--manual", "alpha")
    assert not (home / ".claude/skills/beta").exists()
    backup = sorted((data_dir(home) / "backups").iterdir())[-1]
    run("--restore", str(backup))
    assert (home / ".claude/skills/beta/helper.txt").read_bytes() == b"beta support\n"
    assert manifest(home, "claude")["selection"] == ["@library"]
    assert manifest(home, "claude")["manual"] == ["@all"]


@pytest.mark.skipif(WINDOWS, reason="native Windows stores no executable bit")
def test_executable_bits_follow_the_tree(remote):
    home, upstream = remote
    put(upstream.work / "skills/alpha/run.sh", "#!/bin/sh\n")
    (upstream.work / "skills/alpha/run.sh").chmod(0o755)
    upstream.commit("add script")
    run("--claude-only", "--enable", "alpha")  # a visible copy is the library tree
    alpha = home / ".claude/skills/alpha"
    assert stat.S_IMODE((alpha / "run.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((alpha / "helper.txt").stat().st_mode) == 0o644
    assert installer.tree_id(installer.local_listing(alpha)) == upstream.trees()["alpha"]


def test_list_and_dry_run_need_an_installed_clone(remote):
    home, _ = remote
    for args in (["--list"], ["--dry-run"]):
        with pytest.raises(installer.InstallError, match="No library clone"):
            run(*args)
    assert snapshot(home) == {}


def test_dry_run_fetches_but_never_moves_the_install(remote, capsys):
    home, upstream = remote
    run()
    repo = clone(home)
    head = git("-C", str(repo), "rev-parse", "HEAD").strip()
    upstream.skill("beta", files={"helper.txt": "beta revised\n"})
    upstream.commit("revise beta")
    untouched = [home / ".claude", home / ".codex", repo / "scripts", repo / installer.INDEX]
    before = [snapshot(p) for p in untouched], snapshot(data_dir(home) / "claude.json")
    capsys.readouterr()
    assert run("--dry-run") == 0
    plan = json.loads(capsys.readouterr().out)
    claude = next(c for c in plan["clients"] if c["client"] == "claude")
    assert [(a["entry"], a["tree"]) for a in claude["actions"]] == [("beta", upstream.trees()["beta"])]
    assert ([snapshot(p) for p in untouched], snapshot(data_dir(home) / "claude.json")) == before
    assert git("-C", str(repo), "rev-parse", "HEAD").strip() == head
    run("--list")
    assert json.loads(capsys.readouterr().out)["revision"] == head  # offline: the last update
    run()
    assert (home / ".claude/skills/beta/helper.txt").read_bytes() == b"beta revised\n"


def test_stale_index_skips_only_the_unindexed_skill(remote, capsys):
    home, upstream = remote
    run()
    upstream.skill("gamma")
    upstream.skill("beta", files={"helper.txt": "beta revised\n"})
    upstream.commit("forgot the index", index=False)
    assert run() == 0
    assert "skipping library entry gamma: no valid entry in library_index.json" in capsys.readouterr().err
    assert not (home / ".claude/skills/gamma").exists()
    assert (home / ".claude/skills/beta/helper.txt").read_bytes() == b"beta revised\n"


def test_unportable_upstream_entries_are_skipped_and_managed_ones_frozen(remote, capsys):
    home, upstream = remote
    run()
    beta = installer.fingerprint(home / ".claude/skills/beta")
    record = manifest(home, "claude")["managed"]["beta"]
    upstream.raw("skills/beta/bad:name.txt", "not a Windows file name\n")
    upstream.raw("skills/Alpha/SKILL.md", "---\nname: Alpha\ndescription: Case twin.\n---\n")
    upstream.raw("skills/nul/SKILL.md", "---\nname: nul\ndescription: Reserved name.\n---\n")
    upstream.commit_index("unportable entries")
    assert run() == 0
    err = capsys.readouterr().err
    assert "skipping library entry beta: no valid entry" not in err
    assert "skipping library entry beta" in err and "not a portable (Windows) file name" in err
    assert "skipping library entry Alpha" in err and "differs only in case from alpha" in err
    assert "skipping library entry alpha" not in err, "the indexed member of a case group is kept"
    assert "skipping library entry nul" in err
    assert installer.fingerprint(home / ".claude/skills/beta") == beta
    assert manifest(home, "claude")["managed"]["beta"] == record, "a skipped managed entry is frozen, not removed"
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha", installer.ROUTER, "beta"]
    with pytest.raises(installer.InstallError, match="Cannot enable"):
        run("--codex-only", "--enable", "beta")


def test_stale_git_locks_and_interrupted_clones_are_cleaned(remote, capsys):
    home, upstream = remote
    run()
    repo = clone(home)
    put(repo / ".git/index.lock", "")
    put(data_dir(home) / f".{installer.CLONE}.tmp-{'0' * 32}" / "partial", "")
    upstream.skill("alpha", files={"helper.txt": "alpha revised\n"})
    upstream.commit("revise alpha")
    assert run() == 0
    assert "removed 1 stale git lock file(s)" in capsys.readouterr().err
    assert not (repo / ".git/index.lock").exists()
    assert not list(data_dir(home).glob(f".{installer.CLONE}.tmp-*"))
    assert (home / ".claude/skills/alpha/helper.txt").read_bytes() == b"alpha revised\n"


def test_a_broken_clone_is_moved_aside_once_and_cloned_again(remote, capsys):
    home, upstream = remote
    run()
    repo = clone(home)
    for attempt in range(2):
        put(repo / ".git/HEAD", "garbage\n")
        upstream.skill("beta", files={"helper.txt": f"beta revision {attempt}\n"})
        upstream.commit(f"revise beta {attempt}")
        assert run() == 0
        assert "moved it to" in capsys.readouterr().err
        assert (home / ".claude/skills/beta/helper.txt").read_bytes() == f"beta revision {attempt}\n".encode()
    assert len(list(data_dir(home).glob(f"{installer.CLONE}.broken-*"))) == 1


def test_inherited_git_environment_never_reaches_another_repository(remote, monkeypatch, tmp_path):
    home, upstream = remote
    other = tmp_path / "other"
    git("init", "-q", str(other))
    put(other / "file.txt", "mine\n")
    git("-C", str(other), "add", "file.txt")
    git("-C", str(other), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "mine")
    before = git("-C", str(other), "for-each-ref"), (other / ".git/index").read_bytes(), snapshot(other)
    attributes = tmp_path / "global-attributes"
    attributes.write_text("* text eol=crlf\n")
    with open(os.environ["GIT_CONFIG_GLOBAL"], "a") as config:
        config.write(f"[core]\n\tautocrlf = true\n\tattributesFile = {attributes.as_posix()}\n")
    with monkeypatch.context() as hook:  # what a git hook or a shell inside another repo exports
        hook.setenv("GIT_DIR", str(other / ".git"))
        hook.setenv("GIT_WORK_TREE", str(other))
        hook.setenv("GIT_INDEX_FILE", str(other / ".git/index"))
        hook.setenv("GIT_OBJECT_DIRECTORY", str(other / ".git/objects"))
        hook.setenv("GIT_CONFIG_COUNT", "1")
        hook.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
        hook.setenv("GIT_CONFIG_VALUE_0", "true")
        assert run() == 0
    assert (git("-C", str(other), "for-each-ref"), (other / ".git/index").read_bytes(), snapshot(other)) == before
    assert (home / ".claude/skills/alpha/nested/deep/data.txt").read_bytes() == b"alpha data\n"


def plant(tmp_path, monkeypatch, url: str, target: str) -> Path:
    """Another user's repository at the top of a shared temporary directory, which git honors where
    the global config trusts every directory (safe.directory=*, as on the owner's lab machine): it
    redirects `url` to `target`, and its core.sshCommand writes a marker. Returns the marker."""
    shared, marker = tmp_path / "shared-tmp", tmp_path / "planted-command-ran"
    git("init", "-q", str(shared))
    git("-C", str(shared), "config", f"url.{target}.insteadOf", url)
    git("-C", str(shared), "config", "core.sshCommand", f"sh -c 'echo ran > \"$0\"; exit 1' {marker.as_posix()}")
    with open(os.environ["GIT_CONFIG_GLOBAL"], "a") as config:
        config.write("[safe]\n\tdirectory = *\n")
    monkeypatch.setattr(tempfile, "tempdir", str(shared))
    for key in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(key, str(shared))
    monkeypatch.setattr(installer, "PRIVATE", [], raising=False)  # this process's private directory
    return marker


@pytest.mark.parametrize("redirect", ["file", "ssh"])
def test_a_repository_planted_in_the_temporary_directory_is_never_read(remote, monkeypatch, tmp_path, redirect):
    """git --version, config, ls-remote and clone need no repository: they run in a private directory
    of the installer's own, so a planted .git can neither redirect the library nor run a command."""
    home, upstream = remote
    evil = Upstream(tmp_path / "evil")
    evil.skill("alpha", body="planted alpha")
    evil.commit("planted")
    target = evil.url if redirect == "file" else "ssh://planted.invalid/library.git"
    marker = plant(tmp_path, monkeypatch, upstream.url, target)
    found = installer.Git()
    assert found.env.get("GIT_SSH_COMMAND") == installer.SSH_COMMAND, "the planted core.sshCommand is not ours"
    assert installer.remote_tip(found, upstream.url, "main") == upstream.rev("main")
    assert run() == 0
    put(clone(home) / ".git/HEAD", "garbage\n")  # healing a damaged clone asks the remote (ls-remote)
    assert run() == 0
    assert not marker.exists()
    for copy in (home / ".claude/skills/alpha", codex_copy(home, "alpha")):
        assert "planted" not in (copy / "SKILL.md").read_text()


def test_only_sha1_libraries_are_supported():
    with pytest.raises(installer.InstallError, match="SHA-1 is required"):
        installer.GitLibrary(None, ROOT, "a" * 64, worktree=False)


@pytest.fixture
def stalling_remote():
    """An HTTP remote on 127.0.0.1 that accepts connections and never answers."""
    server = socket.create_server(("127.0.0.1", 0))
    held = []

    def accept():
        while True:
            try:
                held.append(server.accept()[0])
            except OSError:
                return

    threading.Thread(target=accept, daemon=True).start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}/library.git"
    server.close()
    for connection in held:
        connection.close()


def test_a_stalled_remote_fails_instead_of_holding_the_lock(remote, monkeypatch, stalling_remote):
    home, upstream = remote
    monkeypatch.setenv("GIT_HTTP_LOW_SPEED_TIME", "2")  # instead of the 60 s default
    run()
    monkeypatch.setenv("SKILLS_REPOSITORY_URL", stalling_remote)
    for fresh in (False, True):
        if fresh:
            installer.rmtree(clone(home))  # git marks pack files read-only on Windows
        started = time.monotonic()
        with pytest.raises(installer.GitError, match="too slow"):
            run()
        assert time.monotonic() - started < 60
        assert not list(data_dir(home).glob(f"{installer.CLONE}.broken-*"))
        assert not list(data_dir(home).glob(f".{installer.CLONE}.tmp-*"))
    monkeypatch.setenv("SKILLS_REPOSITORY_URL", upstream.url)
    assert run() == 0, "the lock was released"


def test_ssh_never_prompts_or_waits_forever_unless_configured(remote, monkeypatch):
    assert installer.Git().env["GIT_SSH_COMMAND"] == installer.SSH_COMMAND
    assert "BatchMode=yes" in installer.SSH_COMMAND and "ConnectTimeout=" in installer.SSH_COMMAND
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i fixture-key")
    assert installer.Git().env["GIT_SSH_COMMAND"] == "ssh -i fixture-key"


def test_a_failed_blob_download_is_reported_not_healed(remote, monkeypatch):
    home, upstream = remote
    run()
    installed = installer.fingerprint(home / ".claude")
    upstream.skill("alpha", files={"helper.txt": "alpha revised\n"})
    upstream.commit("revise alpha")
    original = installer.GitLibrary._sparse

    def drop(self, directories):
        if len(directories) > 1:
            raise installer.GitError("git sparse-checkout failed: fatal: early EOF", "fatal: early EOF")
        original(self, directories)

    monkeypatch.setattr(installer.GitLibrary, "_sparse", drop)
    with pytest.raises(installer.GitError, match="early EOF"):
        run()
    assert installer.fingerprint(home / ".claude") == installed
    assert not list(data_dir(home).glob(f"{installer.CLONE}.broken-*"))
    monkeypatch.setattr(installer.GitLibrary, "_sparse", original)
    assert run() == 0
    assert (home / ".claude/skills/alpha/helper.txt").read_bytes() == b"alpha revised\n"


def fail_once(monkeypatch, command: str, stderr: str) -> list:
    original, calls = installer.Git.run, []

    def run_git(self, repo, *args, **kwargs):
        if args and args[0] == command:
            calls.append(args)
            if len(calls) == 1:
                raise installer.GitError(f"git {command} failed: {stderr}", stderr)
        return original(self, repo, *args, **kwargs)

    monkeypatch.setattr(installer.Git, "run", run_git)
    return calls


def test_a_dropped_transfer_is_retried_once(remote, monkeypatch, capsys):
    home, upstream = remote
    run()
    upstream.skill("beta", files={"helper.txt": "beta revised\n"})
    upstream.commit("revise beta")
    calls = fail_once(monkeypatch, "fetch", "fatal: the remote end hung up unexpectedly")
    assert run() == 0
    assert len(calls) == 2 and "retrying once" in capsys.readouterr().err
    assert (home / ".claude/skills/beta/helper.txt").read_bytes() == b"beta revised\n"
    assert not list(data_dir(home).glob(f"{installer.CLONE}.broken-*"))


def test_a_full_disk_is_not_mistaken_for_a_broken_clone(remote, monkeypatch):
    home, upstream = remote
    run()
    upstream.skill("beta", files={"helper.txt": "beta revised\n"})
    upstream.commit("revise beta")
    fail_once(monkeypatch, "checkout", "error: unable to write file README.md: No space left on device")
    with pytest.raises(installer.GitError, match="No space left on device"):
        run()
    assert is_library(clone(home)) and not list(data_dir(home).glob(f"{installer.CLONE}.broken-*"))


def is_library(path):
    return installer.is_library_clone(installer.native(path))


def test_corruption_signatures():
    for stderr in (
        "fatal: not a git repository: '/x/.git'",
        "error: unable to read sha1 file of a",
        "fatal: bad object HEAD",
    ):
        assert installer.corrupted(installer.GitError("git x failed", stderr))
    for stderr in ("fatal: early EOF", "Operation too slow.", "No space left on device", "error: invalid path 'a:b'"):
        assert not installer.corrupted(installer.GitError("git x failed", stderr))


def test_symlinks_from_the_remote_library_are_never_installed(remote, capsys):
    home, upstream = remote
    run()
    beta = installer.fingerprint(home / ".claude/skills/beta")
    upstream.skill("evil")
    upstream.commit_with_links(
        "links out of the skill",
        {
            "skills/evil/key": "../../.ssh/id_rsa",
            "skills/evil/passwd": "/etc/passwd",
            "skills/beta/key": "../../.ssh/id_rsa",
        },
    )
    assert run() == 0
    err = capsys.readouterr().err
    assert "skipping library entry evil" in err and "key: symbolic link" in err
    assert "skipping library entry beta" in err
    claude = home / ".claude/skills"
    assert not (claude / "evil").exists()
    assert installer.fingerprint(claude / "beta") == beta, "an installed copy is frozen, never updated with the link"
    assert not any(installer.is_link(p) for p in installer.native(home).rglob("*") if ".git" not in p.parts)
    assert not (clone(home) / "skills/evil").exists(), "the entry is never checked out"
    with pytest.raises(installer.InstallError, match="Cannot enable"):
        run("--codex-only", "--enable", "evil")


def test_planning_downloads_one_batch_at_most_however_many_folders_it_compares(remote):
    """Planning compares other folders with the copies it would make: a skill named like one (a
    name twin) and a folder named like a library ID. In a blobless clone a library file read alone
    is a fetch of its own, so planning reads none while a folder's other files already differ, and
    gets all the files it still needs in one batch (none without fetching)."""
    home, upstream = remote
    ids = ["alpha", "beta", "gamma", "delta"]
    for skill_id in ids[2:]:
        upstream.skill(skill_id, files={"helper.txt": f"{skill_id} support\n"})
    upstream.commit("more skills")
    run("--claude-only", "--selection", "", "--manual", "")  # the clone holds no skill's files yet
    repo = clone(home)
    assert all(upstream.blobs(skill_id) <= missing_objects(repo) for skill_id in ids)
    put(home / ".claude/skills/mine/SKILL.md", "---\nname: alpha\ndescription: the user's own\n---\n")
    put(home / ".claude/skills/gamma/SKILL.md", "---\nname: gamma\ndescription: the user's own\n---\n")
    put(home / ".agents/skills/theirs/SKILL.md", "---\nname: beta\ndescription: another tool's\n---\n")
    for skill_id in ids:  # another tool's copies of a library skill, under names of their own
        near = home / ".agents/skills" / f"near-{skill_id}"
        shutil.copytree(upstream.work / "skills" / skill_id, near)
        put(near / "SKILL.md", f"---\nname: {skill_id}\ndescription: an older {skill_id}\n---\nolder body\n")
    packs = set(packed_objects(repo))
    assert run("--claude-only", "--manual", "@all", "--dry-run") == 0
    assert run("--codex-only", "--no-fetch", "--dry-run") == 0
    assert set(packed_objects(repo)) == packs, "nothing needed bytes, or nothing may be fetched"
    assert run("--codex-only", "--dry-run") == 0
    assert len(set(packed_objects(repo)) - packs) == 1, "four folders' files came in one batch"
    assert upstream.blobs("beta") & missing_objects(repo), "and only the files a comparison needs"
    assert run() == 0
    assert all(f"near-{skill_id}" in os.listdir(home / ".agents/skills") for skill_id in ids)


def test_a_lost_data_folder_is_adopted_back_in_one_run(remote, capsys, monkeypatch):
    """With the state and the clone gone (one folder when XDG_DATA_HOME is unset), every copy is
    unmanaged and compared with the copy this installer would make. A comparison may need several
    files the fresh blobless clone lacks: a hidden Codex copy reads SKILL.md and agents/openai.yaml,
    a nested SKILL.md one more. All of them come in the one batch, and the plan made again with them
    adopts every identical copy at once."""
    home, upstream = remote
    nested = "---\nname: sub\ndescription: nested\n---\nbody\n"
    files = {"sub/SKILL.md": nested, "agents/openai.yaml": "interface:\n  display_name: Nest\n"}
    upstream.skill("nest", files=files)
    upstream.commit("a skill with a policy file and a nested SKILL.md")
    assert run() == 0
    before = {client: manifest(home, client)["managed"] for client in ("claude", "codex")}
    assert "nest" in before["codex"] and before["codex"]["nest"]["invocation"] == "manual"
    copies = snapshot(home / ".codex") | snapshot(home / ".agents") | snapshot(home / ".claude")
    shutil.rmtree(data_dir(home))
    capsys.readouterr()
    batches, fetch = [], installer.GitLibrary.fetch_wanted
    monkeypatch.setattr(installer.GitLibrary, "fetch_wanted", lambda self: batches.append(fetch(self)) or batches[-1])
    calls, git_run = [], installer.Git.run
    monkeypatch.setattr(
        installer.Git, "run", lambda self, repo, *a, **k: calls.append(a) or git_run(self, repo, *a, **k)
    )
    assert run() == 0
    assert batches == [True, False], "every file the comparisons needed came in one batch"
    [batch] = [a for a in calls if "--stdin" in a and "fetch" in a]
    assert batch[:3] == ("-c", "fetch.negotiationAlgorithm=noop", "fetch"), "sent as git's own lazy fetch, no haves"
    after = {client: manifest(home, client)["managed"] for client in ("claude", "codex")}
    assert {c: sorted(m) for c, m in after.items()} == {c: sorted(m) for c, m in before.items()}
    assert all(after[c][e]["sha256"] == before[c][e]["sha256"] for c in after for e in after[c])
    assert snapshot(home / ".codex") | snapshot(home / ".agents") | snapshot(home / ".claude") == copies
    plan, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert [item["preserved"] for item in plan["clients"]] == [[], []], "every copy adopted, the routers too"
    assert run() == 0
    assert capsys.readouterr().out.strip().endswith("Already current; selection preserved.")


def test_a_folder_with_a_file_no_copy_has_is_rejected_without_fetching(remote, monkeypatch):
    """may_hold judges by stat alone: a folder named like a library ID that holds one of this
    installer's copies plus a file of its own (as another tool might leave) can be no copy of ours,
    so planning fetches none of its library files, on --dry-run or later."""
    home, _ = remote
    assert run("--codex-only") == 0
    alpha = codex_copy(home, "alpha")
    for entry in os.listdir(alpha.parent):
        if entry not in ("alpha", installer.ROUTER):
            shutil.rmtree(alpha.parent / entry)
    for other in (home / ".codex/skills", home / ".agents/skills"):
        for entry in os.listdir(other) if other != alpha.parent and other.is_dir() else []:
            shutil.rmtree(other / entry)
    put(alpha / "notes-of-another-tool.txt", "theirs\n")
    shutil.rmtree(data_dir(home))  # state and clone: the copy is unmanaged, the new clone has no blobs
    assert run("--claude-only", "--selection", "", "--manual", "") == 0
    batches, fetch = [], installer.GitLibrary.fetch_wanted
    monkeypatch.setattr(installer.GitLibrary, "fetch_wanted", lambda self: batches.append(fetch(self)) or batches[-1])
    assert run("--codex-only", "--dry-run") == 0
    assert batches == [False], "nothing was fetched to compare a folder that cannot be a copy"


def test_planning_reads_installed_copies_instead_of_fetching_their_blobs(remote):
    home, upstream = remote
    run("--claude-only", "--selection", "", "--manual", "")
    repo, claude = clone(home), home / ".claude/skills"
    assert upstream.blobs("alpha") <= missing_objects(repo)
    # A tarball install that a v1 git installer recorded as identical: its blobs were never fetched.
    shutil.copytree(upstream.work / "skills/alpha", claude / "alpha")
    record = {"name": "alpha", "tree": upstream.trees()["alpha"], "source_ids": ["alpha"], "origins": []}
    record["sha256"] = installer.fingerprint(claude / "alpha")
    v1 = {"schema": 1, "client": "claude", "destination": str(installer.native(claude)), "selection": ["@all"]}
    put(data_dir(home) / "claude.json", json.dumps(dict(v1, managed={"alpha": record})))
    assert run("--claude-only", "--dry-run", "--no-fetch") == 0
    assert upstream.blobs("alpha") <= missing_objects(repo), "planning the migration fetched nothing"
    assert run("--claude-only") == 0
    assert (claude / "alpha/SKILL.md").read_text().startswith(f"---\n{installer.HIDDEN_KEY}: true\n")


def test_no_fetch_changes_visibility_offline_without_downloading(remote, monkeypatch, tmp_path):
    home, _ = remote
    run()
    repo = clone(home)
    packs = packed_objects(repo)
    monkeypatch.setenv("SKILLS_REPOSITORY_URL", (tmp_path / "unreachable.git").as_uri())
    with pytest.raises(installer.InstallError, match="git fetch failed"):
        run("--codex-only", "--enable", "alpha")
    calls = []
    original = installer.Git.run

    def spy(self, repo, *args, **kwargs):
        calls.append(args[0])
        return original(self, repo, *args, **kwargs)

    monkeypatch.setattr(installer.Git, "run", spy)
    assert run("--codex-only", "--enable", "alpha", "--no-fetch") == 0
    assert "fetch" not in calls
    assert not (codex_copy(home, "alpha") / installer.POLICY_FILE).exists()
    assert (codex_copy(home, "beta") / installer.POLICY_FILE).exists()
    assert run("--claude-only", "--enable", "beta", "--no-fetch") == 0
    assert packed_objects(repo) == packs, "the blobs were already in the clone"
    assert run("--no-fetch", "--dry-run") == 0


def test_git_is_found_only_in_absolute_path_folders(tmp_path, monkeypatch):
    """On Windows a bare `git` is looked up in the current folder first, as an empty PATH entry is on
    POSIX. The routers have the user run the launcher in a session, so from a project folder: a git,
    git.bat or git.cmd there must never run, in the installer or in a local checkout's revision check."""
    real = shutil.which("git")
    project, marker = tmp_path / "project", tmp_path / "planted-git-ran"
    for name in ("git", "git.bat", "git.cmd"):
        script = f'@echo off\r\ntype nul > "{marker}"\r\n' if name != "git" else f"#!/bin/sh\ntouch '{marker}'\n"
        put(project / name, script)
        (project / name).chmod(0o755)
    checkout = tmp_path / "checkout"
    git("init", "-q", str(checkout))
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", os.path.dirname(real)]))
    found = installer.find_git()
    assert found and os.path.isabs(found) and os.path.samefile(os.path.dirname(found), os.path.dirname(real))
    assert installer.Git().exe == found
    assert installer.checkout_git(checkout, "rev-parse", "--git-dir").endswith(".git")
    assert not marker.exists()
    monkeypatch.setenv("PATH", os.pathsep.join(["", "."]))
    assert installer.find_git() is None and installer.checkout_git(checkout, "rev-parse", "--git-dir") == ""
    with pytest.raises(installer.InstallError, match="git was not found on PATH"):
        installer.Git()
    assert not marker.exists()


@pytest.mark.skipif(WINDOWS, reason="simulates Windows' PATHEXT lookup on POSIX")
def test_on_windows_git_is_found_by_its_pathext_suffix(tmp_path, monkeypatch):
    project, tools = tmp_path / "project", tmp_path / "tools"
    for path in (project / "git.EXE", tools / "git.CMD"):
        put(path, "")
        path.chmod(0o755)
    monkeypatch.setattr(installer, "WINDOWS", True)
    monkeypatch.setenv("PATHEXT", os.pathsep.join([".EXE", ".CMD"]))
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tools)]))
    assert installer.find_git() == str(tools / "git.CMD")


@pytest.mark.parametrize("dot", ["empty folder", "empty file"])
def test_a_local_tree_reads_no_repository_above_its_own_broken_git(tmp_path, dot):
    """A --source checkout whose .git is not a repository records no revision and no sparse flag of
    the repository around it (`git -C DIR` would climb to that one)."""
    outer = Upstream(tmp_path).work  # a real repository with commits
    inner = outer / "vendor/checkout"
    put(inner / "skills/solo/SKILL.md", "---\nname: solo\ndescription: Use solo\n---\nbody\n")
    if dot == "empty folder":
        (inner / ".git").mkdir()
    else:
        put(inner / ".git", "")
    assert installer.checkout_git(outer, "rev-parse", "HEAD"), "the outer repository answers"
    assert installer.checkout_git(inner, "rev-parse", "HEAD") == ""
    assert installer.checkout_git(inner, "config", "--bool", "core.sparseCheckout") == ""
