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
import threading
import time

import pytest

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
    assert sorted(os.listdir(claude)) == ["alpha", "beta"]
    assert (claude / "alpha/nested/deep/data.txt").read_bytes() == b"alpha data\n"
    trees = upstream.trees()
    assert manifest(home, "claude")["managed"]["alpha"]["tree"] == trees["alpha"]
    # The installer's own git tree hashing agrees with git.
    assert installer.tree_id(installer.local_listing(claude / "beta")) == trees["beta"]
    router = (home / ".codex/skills" / installer.ROUTER / "SKILL.md").read_text()
    assert str(repo / "scripts" / "install_skills.py") in router
    assert sorted(os.listdir(home / ".codex/skills")) == [installer.ROUTER]


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
    beta, codex = snapshot(claude / "beta"), snapshot(home / ".codex")
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
    assert snapshot(home / ".codex") == codex
    assert manifest(home, "claude")["managed"]["alpha"]["tree"] == upstream.trees()["alpha"]


def test_only_selected_skills_are_downloaded(remote):
    home, upstream = remote
    run("--claude-only", "--selection", "alpha")
    run("--codex-only")
    repo = clone(home)
    assert upstream.blobs("beta") <= missing_objects(repo)
    assert not upstream.blobs("alpha") & missing_objects(repo)
    run("--codex-only", "--enable", "beta")
    assert not upstream.blobs("beta") & missing_objects(repo)
    assert (home / ".codex/skills/beta/helper.txt").read_bytes() == b"beta support\n"
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
        ("claude", claude, managed, ["@all"]),
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
    assert router["tree"] and str(clone(home)) in (home / ".codex/skills" / installer.ROUTER / "SKILL.md").read_text()
    cache = home / ".cache/awesome-skills"
    assert not legacy.exists()
    assert (cache / "notes.txt").is_file() and (cache / "libraries/keep-me").is_dir()


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
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha", "beta", "gamma"]
    assert manifest(home, "claude")["managed"]["gamma"]["name"] == "gamma"
    # A user's own skill is matched by its frontmatter name without PyYAML, too.
    put(home / ".agents/skills/mine/SKILL.md", "---\nname: 'gamma'\ndescription: mine\n---\n")
    conflict = subprocess.run([*helper, "--codex-only", "--enable", "gamma"], capture_output=True, text=True, env=env)
    assert conflict.returncode == 1 and "Frontmatter name conflict" in conflict.stderr, conflict.stderr
    router = [sys.executable, "-B", str(clone(home) / "scripts/install_skills.py"), "--list", "--search", "gamma"]
    listed = subprocess.run(router, capture_output=True, text=True, env=env)
    assert listed.returncode == 0, listed.stderr
    assert list(json.loads(listed.stdout)["skills"]) == ["gamma"]


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
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
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
    assert (home / ".codex/skills/beta/SKILL.md").is_file()


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
    run("--claude-only", "--disable", "gamma")
    assert not installer.native(home / ".claude/skills/gamma").exists()


def test_disable_and_restore_after_a_git_update(remote):
    home, _ = remote
    run()
    run("--claude-only", "--disable", "beta")
    assert not (home / ".claude/skills/beta").exists()
    backup = sorted((data_dir(home) / "backups").iterdir())[-1]
    run("--restore", str(backup))
    assert (home / ".claude/skills/beta/helper.txt").read_bytes() == b"beta support\n"
    assert manifest(home, "claude")["selection"] == ["@all"]


@pytest.mark.skipif(WINDOWS, reason="native Windows stores no executable bit")
def test_executable_bits_follow_the_tree(remote):
    home, upstream = remote
    put(upstream.work / "skills/alpha/run.sh", "#!/bin/sh\n")
    (upstream.work / "skills/alpha/run.sh").chmod(0o755)
    upstream.commit("add script")
    run()
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
    assert sorted(os.listdir(home / ".claude/skills")) == ["alpha", "beta"]
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
