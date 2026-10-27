"""A local upstream served over file:// and an isolated HOME; no network, no live home."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import install_skills as installer

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def git(*args: str, stdin: bytes | None = None) -> str:
    command = ["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "-c", "init.defaultBranch=main"]
    result = subprocess.run([*command, *args], input=stdin, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout.decode()


def put(path: Path, text: str):
    path = installer.native(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


def data_dir(home: Path) -> Path:
    return home / ("AppData/Local" if WINDOWS else ".local/share") / "awesome-skills"


def without_pyyaml(root: Path, env: dict) -> dict:
    """env for a child Python that cannot import PyYAML, as on a fresh host: a failing `yaml`
    module comes first on PYTHONPATH. Checked here, so a test never passes by accident."""
    shim = root / "no-pyyaml"
    put(shim / "yaml.py", 'raise ImportError("PyYAML is hidden from this test")\n')
    env = {**env, "PYTHONPATH": os.pathsep.join(filter(None, [str(shim), env.get("PYTHONPATH")]))}
    probe = subprocess.run(
        [env.get("SKILLS_PYTHON", sys.executable), "-c", "import yaml"], env=env, capture_output=True
    )
    assert probe.returncode != 0 and b"PyYAML is hidden" in probe.stderr, probe.stderr
    return env


def snapshot(root: Path) -> dict:
    """Every entry's mtime, size and mode: an unchanged run must not rewrite anything."""
    root = installer.native(root)
    if not root.exists():
        return {}
    return {str(p): (p.lstat().st_mtime_ns, p.lstat().st_size, p.lstat().st_mode) for p in sorted(root.rglob("*"))}


def isolate(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    for key in list(os.environ):
        if key.startswith(("SKILLS_", "GIT_")):
            monkeypatch.delenv(key)
    for key in ("XDG_DATA_HOME", "CODEX_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData/Local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    return home


class Upstream:
    """A working repository and the bare repository the installer fetches from."""

    def __init__(self, root: Path):
        self.work, self.bare = root / "upstream", root / "remote.git"
        git("init", "-q", str(self.work))
        for key, value in [
            ("user.name", "fixture"),
            ("user.email", "fixture@example.invalid"),
            ("commit.gpgsign", "false"),
        ]:
            git("-C", str(self.work), "config", key, value)
        (self.work / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/install_skills.py", self.work / "scripts/install_skills.py")
        put(self.work / installer.PROVENANCE, "{}\n")
        self.skill("alpha", files={"helper.txt": "alpha support\n", "nested/deep/data.txt": "alpha data\n"})
        self.skill("beta", files={"helper.txt": "beta support\n"})
        self.commit("initial", push=False)
        git("clone", "-q", "--bare", str(self.work), str(self.bare))
        git("-C", str(self.bare), "config", "uploadpack.allowFilter", "true")
        git("-C", str(self.bare), "config", "uploadpack.allowAnySHA1InWant", "true")
        git("-C", str(self.work), "remote", "add", "origin", str(self.bare))
        self.url = self.bare.as_uri()

    def skill(self, skill_id: str, files: dict | None = None, name: str | None = None, body: str = "body"):
        root = self.work / "skills" / skill_id
        put(root / "SKILL.md", f"---\nname: {name or skill_id}\ndescription: Use {skill_id}\n---\n{body}\n")
        for rel, text in (files or {}).items():
            put(root / rel, text)

    def commit(self, message: str = "update", push: bool = True, index: bool = True):
        if index:
            put(self.work / installer.INDEX, installer.index_text(installer.build_index(self.work / "skills")))
        git("-C", str(self.work), "add", "-A")
        git("-C", str(self.work), "commit", "-q", "-m", message)
        if push:
            git("-C", str(self.work), "push", "-q", "origin", "HEAD:main")

    def raw(self, path: str, text: str):
        """Stage a path the filesystem may not allow (Windows-invalid or case twin), via the index only."""
        blob = git("-C", str(self.work), "hash-object", "-w", "--stdin", stdin=text.encode()).strip()
        unchecked = ["-c", "core.protectNTFS=false", "-c", "core.protectHFS=false", "-c", "core.ignoreCase=false"]
        git("-C", str(self.work), *unchecked, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")

    def commit_with_links(self, message: str, links: dict):
        """Commit the worktree plus symlink entries (path -> target) staged through the index only,
        so the test needs no symlink support on the host."""
        put(self.work / installer.INDEX, installer.index_text(installer.build_index(self.work / "skills")))
        git("-C", str(self.work), "add", "-A")
        for path, target in links.items():
            blob = git("-C", str(self.work), "hash-object", "-w", "--stdin", stdin=target.encode()).strip()
            git("-C", str(self.work), "update-index", "--add", "--cacheinfo", f"120000,{blob},{path}")
        self.commit_index(message)

    def commit_index(self, message: str):
        git("-C", str(self.work), "commit", "-q", "-m", message)
        git("-C", str(self.work), "push", "-q", "origin", "HEAD:main")

    def rev(self, spec: str) -> str:
        return git("-C", str(self.bare), "rev-parse", spec).strip()

    def trees(self) -> dict:
        out = git("-C", str(self.bare), "ls-tree", "main", "skills/")
        return {line.split("\t")[1].split("/")[1]: line.split()[2] for line in out.splitlines()}

    def blobs(self, skill_id: str) -> set:
        out = git("-C", str(self.bare), "ls-tree", "-r", "main", f"skills/{skill_id}/")
        return {line.split()[2] for line in out.splitlines()}


def packed_objects(repo: Path) -> dict:
    """Pack name -> object ids, read from the pack indexes (no object access, no lazy fetch)."""
    packs = {}
    for idx in (repo / ".git/objects/pack").glob("*.idx"):
        lines = git("show-index", stdin=idx.read_bytes()).splitlines()
        packs[idx.name] = {line.split()[1] for line in lines}
    return packs


def object_types(repo: Path, oids: set) -> dict:
    out = git("-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objecttype)", stdin="\n".join(oids).encode())
    return dict(line.split() for line in out.splitlines())


def missing_objects(repo: Path) -> set:
    out = git("-C", str(repo), "rev-list", "--objects", "--missing=print", "HEAD")
    return {line[1:] for line in out.splitlines() if line.startswith("?")}
