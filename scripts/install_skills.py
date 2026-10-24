#!/usr/bin/env python3
"""Install independent persistent client selections with conservative ownership.

Remote installs keep the library as a blobless, sparse git clone in the data directory.
An update fetches new commits and trees, then downloads only the blobs of selected skills
whose git tree changed. --dry-run and --list never write to HOME.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 - users may run an older python3
    print("awesome-skills requires Python 3.11 or newer.", file=sys.stderr)
    raise SystemExit(1)

try:
    import fcntl
except ImportError:  # native Windows
    fcntl = None
    import msvcrt

try:
    import yaml
except ImportError:
    print("awesome-skills requires PyYAML; use an existing Python environment or install PyYAML>=6.0.", file=sys.stderr)
    raise SystemExit(1) from None

REPOSITORY = "https://github.com/FridrichMethod/awesome-skills"
REPOSITORY_URL = REPOSITORY + ".git"
SCHEMA = 1
ROUTER = "awesome-skills-library"
INDEX = "library_index.json"
PROVENANCE = "library_sources.json"
CLONE = "library"
MARKER = "awesome-skills-library"  # file in the clone's .git directory
MIN_GIT = (2, 29, 0)
LOCK_BUSY = 75
WINDOWS = os.name == "nt"
LINK_TAGS = {0xA000000C, 0xA0000003}  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (junction)
FILE_MODES = {"100644": 0o644, "100755": 0o755}
DIR_MODE = 0o755
GIT_CONFIG = (
    "core.autocrlf=false",
    "core.eol=lf",
    "core.longpaths=true",
    "core.fsmonitor=false",
    f"core.hooksPath={os.devnull}",
    "gc.autoDetach=false",
    "advice.detachedHead=false",
    "http.lowSpeedLimit=1000",
    "http.lowSpeedTime=60",
)
LEGACY_CACHE_FILES = {"index.json", "install_skills.py", "library_sources.json", "skills"}
LEGACY_SNAPSHOT = re.compile(r"[0-9a-f]{64}")
LEGACY_TEMP = re.compile(r"[0-9a-f]{64}\.tmp-[0-9a-f]{32}")
LEGACY_TEMP_FILE = re.compile(r"(index|library_sources)\.json\.tmp-[0-9a-f]{32}")


class InstallError(Exception):
    pass


class LockBusy(InstallError):
    pass


# --- Paths -----------------------------------------------------------------------------


def native(path: Path) -> Path:
    """Use extended-length paths on Windows so deep skill trees need no registry change."""
    if not WINDOWS:
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    text = os.path.abspath(text)
    return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)


def display(path) -> str:
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    return text[4:] if text.startswith("\\\\?\\") else text


def is_link(path: Path) -> bool:
    """Symlinks, and on Windows also junctions."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in LINK_TAGS


def plain_dir(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISDIR(st.st_mode) and getattr(st, "st_reparse_tag", 0) not in LINK_TAGS


def rmtree(path: Path):
    def writable(function, name, *_):
        os.chmod(name, stat.S_IWRITE)  # git marks pack files read-only on Windows
        function(name)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=writable)


def move(source: Path, target: Path):
    """Rename, retrying briefly on Windows, where scanners hold fresh files open."""
    for attempt in range(6):
        try:
            source.rename(target)
            return
        except PermissionError:
            if not WINDOWS or attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def no_symlink_ancestors(path: Path):
    for p in (path, *path.parents):
        if is_link(p):
            raise InstallError(f"Refusing symlink directory or ancestor: {display(p)}")


def safe_absolute(path: Path) -> Path:
    path = path.expanduser().absolute()
    no_symlink_ancestors(path)
    return native(Path(os.path.abspath(path)))


def overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


# --- Content identity ------------------------------------------------------------------


def digest(entries: dict) -> str:
    """Hash every relative path, type, permission, byte and symlink target."""
    h = hashlib.sha256()
    for path, (kind, mode, data) in sorted(entries.items()):
        h.update(json.dumps([path, kind, mode, len(data)], separators=(",", ":")).encode())
        h.update(b"\0" + data + b"\0")
    return h.hexdigest()


def tree(path: Path) -> dict:
    entries = {}

    def visit(p: Path, rel: str):
        mode = stat.S_IMODE(p.lstat().st_mode)
        if is_link(p):
            entries[rel] = ("link", mode, os.readlink(p).encode())
        elif p.is_dir():
            entries[rel] = ("dir", mode, b"")
            for child in sorted(p.iterdir()):
                visit(child, f"{rel}/{child.name}" if rel else child.name)
        elif p.is_file():
            entries[rel] = ("file", mode, p.read_bytes())
        else:
            raise InstallError(f"Unsupported file type: {display(p)}")

    visit(path, "")
    return entries


def fingerprint(path: Path) -> str | None:
    if not os.path.lexists(path):
        return None
    return digest(tree(path))


def blob_id(data: bytes, algorithm: str = "sha1") -> str:
    h = hashlib.new(algorithm)
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def local_entries(path: Path) -> dict:
    """Every entry below path as relative POSIX path -> (kind, permission bits), from lstat only."""
    out = {}

    def visit(directory: Path, prefix: str):
        for child in directory.iterdir():
            rel, st = prefix + child.name, os.lstat(child)
            if stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in LINK_TAGS:
                kind = "link"
            elif stat.S_ISDIR(st.st_mode):
                kind = "dir"
            elif stat.S_ISREG(st.st_mode):
                kind = "file"
            else:
                raise InstallError(f"Unsupported file type: {display(child)}")
            out[rel] = (kind, stat.S_IMODE(st.st_mode))
            if kind == "dir":
                visit(child, rel + "/")

    visit(path, "")
    return out


def local_listing(path: Path, algorithm: str = "sha1") -> dict:
    """Git's view of a directory: relative POSIX path -> (mode, object id).

    Directories are implicit, so empty ones vanish as they do in git. Native Windows
    cannot store the executable bit; every file reads as 100644 there.
    """
    out = {}
    for rel, (kind, bits) in local_entries(path).items():
        p = path.joinpath(*rel.split("/"))
        if kind == "link":
            out[rel] = ("120000", blob_id(os.fsencode(os.readlink(p)), algorithm))
        elif kind == "file":
            executable = not WINDOWS and bits & stat.S_IXUSR
            out[rel] = ("100755" if executable else "100644", blob_id(p.read_bytes(), algorithm))
    return out


def listing_kinds(listing: dict) -> dict:
    kinds = {}
    for rel, (mode, _) in listing.items():
        parts = rel.split("/")
        for i in range(1, len(parts)):
            kinds["/".join(parts[:i])] = "dir"
        kinds[rel] = "link" if mode == "120000" else "file"
    return kinds


def tree_id(listing: dict, algorithm: str = "sha1") -> str:
    """The git tree object id of a listing, computed without git."""
    root: dict = {}
    for rel, entry in listing.items():
        *parents, name = rel.split("/")
        node = root
        for part in parents:
            node = node.setdefault(part, {})
        node[name] = entry

    def build(node: dict) -> str:
        rows = []
        for name, value in node.items():
            raw = os.fsencode(name)
            if isinstance(value, dict):
                rows.append((raw + b"/", b"40000 " + raw + b"\0" + bytes.fromhex(build(value))))
            else:
                rows.append((raw, value[0].encode() + b" " + raw + b"\0" + bytes.fromhex(value[1])))
        body = b"".join(row for _, row in sorted(rows))
        h = hashlib.new(algorithm)
        h.update(b"tree %d\0" % len(body))
        h.update(body)
        return h.hexdigest()

    return build(root)


def same_files(expected: dict, actual: dict) -> bool:
    if expected.keys() != actual.keys():
        return False
    for rel, (mode, oid) in expected.items():
        actual_mode, actual_oid = actual[rel]
        if oid != actual_oid:
            return False
        if mode != actual_mode and not (WINDOWS and {mode, actual_mode} <= set(FILE_MODES)):
            return False
    return True


def same_tree(expected: dict, path: Path, algorithm: str) -> bool:
    """Same paths, bytes, link targets and executable bits; other permission bits are ignored."""
    if not plain_dir(path):
        return False
    kinds = {rel: kind for rel, kind in listing_kinds(expected).items() if kind != "dir"}
    if {rel: kind for rel, (kind, _) in local_entries(path).items() if kind != "dir"} != kinds:
        return False  # cheap stat-only rejection before reading any bytes
    return same_files(expected, local_listing(path, algorithm))


def exact_tree(expected: dict, path: Path, algorithm: str) -> bool:
    """The whole directory is what this installer writes: no extra entries, canonical modes."""
    if not plain_dir(path):
        return False
    entries = local_entries(path)
    if {rel: kind for rel, (kind, _) in entries.items()} != listing_kinds(expected):
        return False
    if not WINDOWS:
        if stat.S_IMODE(os.lstat(path).st_mode) != DIR_MODE:
            return False
        for rel, (kind, bits) in entries.items():
            if kind == "dir" and bits != DIR_MODE or kind == "file" and bits != FILE_MODES.get(expected[rel][0]):
                return False
    return same_files(expected, local_listing(path, algorithm))


# --- Metadata --------------------------------------------------------------------------


def metadata(data: bytes, label: str) -> dict:
    try:
        lines = data.decode("utf-8").splitlines()
        if lines[0].strip() != "---":
            raise ValueError("missing frontmatter")
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        if not isinstance(fm, dict) or not isinstance(fm.get("name"), str) or not fm["name"].strip():
            raise ValueError("missing string name")
        return fm
    except (ValueError, IndexError, StopIteration, UnicodeError, yaml.YAMLError) as e:
        raise InstallError(f"Invalid frontmatter at {label}: {e}") from e


def skill_ids(skills: Path) -> list[str]:
    return sorted(
        p.name for p in skills.iterdir() if not p.name.startswith(".") and not is_link(p) and (p / "SKILL.md").is_file()
    )


def build_index(skills: Path) -> dict:
    """The committed full-library index: every source ID's frontmatter name and description."""
    index = {}
    for skill_id in skill_ids(skills):
        fm = metadata((skills / skill_id / "SKILL.md").read_bytes(), skill_id)
        index[skill_id] = {"name": fm["name"], "description": fm.get("description", "")}
    return {"schema": SCHEMA, "skills": index}


def index_text(index: dict) -> str:
    return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def origins(provenance: dict, skill_id: str, revision: str) -> list:
    entry = provenance.get(skill_id) if isinstance(provenance, dict) else None
    recorded = entry.get("origins") if isinstance(entry, dict) else None
    return recorded or [
        {
            "repository": REPOSITORY,
            "revision": revision,
            "path": f"skills/{skill_id}",
            "upstream": "not recorded by legacy sync",
        }
    ]


def read_json(path: Path, default: dict) -> dict:
    if is_link(path):
        raise InstallError(f"Refusing symlink state: {display(path)}")
    if not path.exists():
        return default
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise InstallError(f"Expected an object: {display(path)}")
    return value


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temp.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    os.replace(temp, path)


# --- Git -------------------------------------------------------------------------------


class Git:
    def __init__(self):
        wanted = ".".join(map(str, MIN_GIT))
        exe = shutil.which("git")
        if not exe:
            raise InstallError(f"git {wanted} or newer is required; git was not found on PATH")
        self.exe = exe
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_LFS_SKIP_SMUDGE="1")
        self.env["LC_ALL"] = "C"
        found = self.run(None, "--version").decode("utf-8", "replace").strip()
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", found)
        if not match or tuple(int(part or 0) for part in match.groups()) < MIN_GIT:
            raise InstallError(f"git {wanted} or newer is required; found {found or 'an unknown version'}")

    def run(self, repo: Path | None, *args: str, stdin: str = "", check: bool = True) -> bytes:
        command = [self.exe]
        for item in GIT_CONFIG:
            command += ["-c", item]
        if repo is not None:
            command += ["-C", display(repo)]
        result = subprocess.run([*command, *args], input=stdin.encode(), capture_output=True, env=self.env)
        if check and result.returncode:
            lines = [line for line in result.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
            detail = lines[-1].strip() if lines else f"exit status {result.returncode}"
            raise InstallError(f"git {args[0]} failed: {detail}")
        return result.stdout

    def text(self, repo: Path | None, *args: str, check: bool = True) -> str:
        return self.run(repo, *args, check=check).decode("utf-8", "replace").strip()


def is_library_clone(path: Path) -> bool:
    return plain_dir(path) and (path / ".git" / MARKER).is_file()


# --- Libraries -------------------------------------------------------------------------


class Library:
    """The complete library index, plus skill content on demand."""

    kind = ""
    algorithm = "sha1"

    def __init__(self):
        self.skills: dict = {}
        self.revision = "unversioned"

    def listing(self, skill_id: str) -> dict:
        raise NotImplementedError

    def adoptable(self, skill_id: str, path: Path) -> bool:
        raise NotImplementedError

    def materialize(self, skill_id: str, target: Path):
        raise NotImplementedError

    def router_command(self) -> tuple[str, list[str]]:
        raise NotImplementedError

    def describe(self) -> dict:
        raise NotImplementedError

    def prepare(self, ids: list[str]):
        """Make the content of these skills available to materialize()."""

    def release(self):
        """Drop content prepared for this run."""


class DirLibrary(Library):
    """A local skills/ tree, such as a development clone."""

    kind = "directory"

    def __init__(self, source: Path):
        super().__init__()
        if source is None or not source.is_dir():
            raise InstallError(f"Missing source library: {display(source)}")
        self.source = source
        provenance = read_json(source.parent / PROVENANCE, {})
        if shutil.which("git"):
            result = subprocess.run(
                ["git", "-C", display(source.parent), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                self.revision = result.stdout.strip()
        self._listings, self._fingerprints = {}, {}
        for skill_id in skill_ids(source):
            fm = metadata((source / skill_id / "SKILL.md").read_bytes(), skill_id)
            listing = local_listing(source / skill_id)
            self._listings[skill_id] = listing
            self.skills[skill_id] = {
                "name": fm["name"],
                "description": fm.get("description", ""),
                "tree": tree_id(listing),
                "origins": origins(provenance, skill_id, self.revision),
            }

    def listing(self, skill_id):
        return self._listings[skill_id]

    def adoptable(self, skill_id, path):
        # Legacy adoption requires an exact whole-tree hash, never a name alone.
        if skill_id not in self._fingerprints:
            self._fingerprints[skill_id] = fingerprint(self.source / skill_id)
        return fingerprint(path) == self._fingerprints[skill_id]

    def materialize(self, skill_id, target):
        shutil.copytree(self.source / skill_id, target, symlinks=True)

    def router_command(self):
        helper = globals().get("__file__")
        helper = display(Path(helper).resolve()) if helper else "install_skills.py"
        return helper, ["--source", display(self.source)]

    def describe(self):
        return {"kind": self.kind, "path": display(self.source), "revision": self.revision}


class GitLibrary(Library):
    """One commit of the blobless library clone; a worktree is needed only to install."""

    kind = "git"

    def __init__(self, git: Git, repo: Path, commit: str, home: Path, worktree: bool):
        super().__init__()
        self.git, self.repo, self.home, self.worktree, self.revision = git, repo, home, worktree, commit
        self.algorithm = "sha256" if len(commit) == 64 else "sha1"
        self._prepared = False
        trees, files = {}, defaultdict(dict)
        for record in git.run(repo, "ls-tree", "-r", "-t", "-z", commit, "--", "skills").split(b"\0"):
            if not record:
                continue
            meta, _, raw = record.partition(b"\t")
            mode, kind, oid = meta.decode().split(" ")
            parts = raw.decode("utf-8", "surrogateescape").split("/")
            if len(parts) < 2 or parts[0] != "skills" or parts[1].startswith("."):
                continue
            if len(parts) == 2:
                if kind == "tree":
                    trees[parts[1]] = oid
            elif kind == "blob":
                files[parts[1]]["/".join(parts[2:])] = (mode, oid)
            elif kind != "tree":
                raise InstallError(f"Unsupported library entry ({kind}): {'/'.join(parts)}")
        ids = sorted(i for i in trees if "SKILL.md" in files.get(i, {}))
        index = self._json(INDEX, required=True)
        if index.get("schema") != SCHEMA or not isinstance(index.get("skills"), dict):
            raise InstallError(f"Unsupported library index {INDEX} at {commit[:12]}")
        if set(index["skills"]) != set(ids):
            raise InstallError(f"Library index {INDEX} does not match skills/ at {commit[:12]}")
        provenance = self._json(PROVENANCE, required=False)
        for skill_id in ids:
            info = index["skills"][skill_id]
            if not isinstance(info, dict) or not isinstance(info.get("name"), str) or not info["name"].strip():
                raise InstallError(f"Invalid library index entry: {skill_id}")
            self.skills[skill_id] = {
                "name": info["name"],
                "description": info.get("description", ""),
                "tree": trees[skill_id],
                "origins": origins(provenance, skill_id, commit),
            }
        self._files = files

    def _json(self, name: str, required: bool) -> dict:
        raw = self.git.run(self.repo, "cat-file", "blob", f"{self.revision}:{name}", check=required)
        value = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(value, dict):
            raise InstallError(f"Expected an object: {name} at {self.revision[:12]}")
        return value

    def listing(self, skill_id):
        return self._files[skill_id]

    def adoptable(self, skill_id, path):
        return exact_tree(self._files[skill_id], path, self.algorithm)

    def prepare(self, ids):
        if not ids:
            return
        if not self.worktree:
            raise InstallError("Internal error: preparing content from a read-only library")
        self._prepared = True
        self._sparse(["scripts", *(f"skills/{skill_id}" for skill_id in sorted(set(ids)))])

    def release(self):
        if self._prepared:
            self._prepared = False
            self._sparse(["scripts"])

    def _sparse(self, directories: list[str]):
        # Cone mode: git batch-downloads exactly the missing blobs below these directories.
        self.git.run(self.repo, "sparse-checkout", "set", "--stdin", stdin="\n".join(directories) + "\n")

    def materialize(self, skill_id, target):
        source = self.repo / "skills" / skill_id
        if not plain_dir(source):
            raise InstallError(f"Library checkout is missing {skill_id}")
        shutil.copytree(source, target, symlinks=True)
        expected = self._files[skill_id]
        if not WINDOWS:
            for rel, kind in listing_kinds(expected).items():
                if kind != "link":
                    os.chmod(
                        target.joinpath(*rel.split("/")), DIR_MODE if kind == "dir" else FILE_MODES[expected[rel][0]]
                    )
            os.chmod(target, DIR_MODE)
        if not same_tree(expected, target, self.algorithm):
            raise InstallError(f"Checked-out content differs from the library tree: {skill_id}")

    def router_command(self):
        return display(self.home / "scripts" / "install_skills.py"), []

    def describe(self):
        return {"kind": self.kind, "path": display(self.home), "revision": self.revision}


def create_clone(git: Git, data: Path, repo: Path, url: str, branch: str):
    data.mkdir(parents=True, exist_ok=True)
    temp = data / f".{CLONE}.tmp-{uuid.uuid4().hex}"
    try:
        git.run(
            None,
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--no-checkout",
            "--single-branch",
            "--branch",
            branch,
            "--",
            url,
            display(temp),
        )
        (temp / ".git" / MARKER).write_bytes(b"awesome-skills library clone, managed by install_skills.py\n")
        git.run(temp, "sparse-checkout", "init", "--cone")
        git.run(temp, "sparse-checkout", "set", "--stdin", stdin="scripts\n")
        move(temp, repo)
    except BaseException:
        if os.path.lexists(temp):
            rmtree(temp)
        raise


def update_clone(git: Git, data: Path, url: str, branch: str) -> tuple[GitLibrary, bool]:
    """Fetch new commits and trees, and move the clone to the branch tip (writes only if it moved)."""
    repo = data / CLONE
    created = not os.path.lexists(repo)
    if created:
        create_clone(git, data, repo, url, branch)
    elif not is_library_clone(repo):
        raise InstallError(f"Not an awesome-skills library clone: {display(repo)}; move it away and rerun")
    if git.text(repo, "config", "--get", "remote.origin.url", check=False) != url:
        git.run(repo, "remote", "set-url", "origin", url)
    ref = f"refs/remotes/origin/{branch}"
    if not created:
        git.run(
            repo,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--no-auto-maintenance",
            "origin",
            f"+refs/heads/{branch}:{ref}",
        )
    commit = git.text(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    moved = created or git.text(repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False) != commit
    if moved:
        git.run(repo, "checkout", "--quiet", "--force", "--detach", commit)
        git.run(repo, "update-ref", "-d", f"refs/heads/{branch}", check=False)
    return GitLibrary(git, repo, commit, repo, worktree=True), moved


@contextmanager
def open_library(git: Git | None, source: Path | None, data: Path, url: str, branch: str, mode: str):
    """mode: "apply" updates the clone (lock held); "list" and "dry-run" never write to HOME."""
    if git is None:
        yield DirLibrary(source)
        return
    home = data / CLONE
    if mode == "apply":
        library, moved = update_clone(git, data, url, branch)
        try:
            yield library
        finally:
            try:
                library.release()
            except InstallError as exc:
                print(f"awesome-skills: warning: {exc}", file=sys.stderr)
        if moved:
            git.run(home, "gc", "--auto", "--quiet", check=False)
        return
    if is_library_clone(home):
        head = git.text(home, "rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
        if head and (mode == "list" or remote_tip(git, url, branch) == head):
            yield GitLibrary(git, home, head, home, worktree=False)
            return
    # No current clone: read the tip from a throwaway shallow, blobless clone.
    temporary = Path(tempfile.mkdtemp(prefix="awesome-skills-"))
    try:
        clone = native(temporary) / CLONE
        git.run(
            None,
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--no-checkout",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            "--",
            url,
            display(clone),
        )
        yield GitLibrary(git, clone, git.text(clone, "rev-parse", "--verify", "HEAD^{commit}"), home, worktree=False)
    finally:
        rmtree(temporary)


def remote_tip(git: Git, url: str, branch: str) -> str:
    line = git.text(None, "ls-remote", "--exit-code", url, f"refs/heads/{branch}")
    return line.split()[0] if line else ""


# --- Router ----------------------------------------------------------------------------


def router_info(library: Library) -> dict:
    helper, extra = library.router_command()
    python = sys.executable
    if WINDOWS:

        def quote(value: str) -> str:
            return '"' + value.replace("`", "``").replace('"', '`"') + '"'

        fence, call = "powershell", f"& {quote(python)} -B {quote(helper)}"
    else:
        quote = shlex.quote
        fence, call = "bash", f"{quote(python)} -B {quote(helper)}"
    call += "".join(" " + quote(arg) for arg in extra)
    body = f"""---
name: {ROUTER}
description: Search the complete awesome-skills library and enable only the skills needed for a task, with source provenance.
---

The full library index is kept outside automatic discovery. Search it (IDs,
frontmatter names, descriptions, tree ids, and origins):

```{fence}
{call} --list --search protein
```

Enable a source ID for Codex, persist it across updates, then restart the session:

```{fence}
{call} --codex-only --enable SOURCE_ID
```

Enabling installs the skill into the Codex skills directory at once. Read its
`SKILL.md` there directly when a session restart is inconvenient, and use its
relative supporting files from that same directory. Do not invent provenance
or silently choose between different same-name variants. `--disable SOURCE_ID`
reversibly removes an unmodified managed copy. `--dry-run` previews all actions
without writing. `--list` reports conflicts. Selection changes require a client flag.
"""
    entries = {"": ("dir", 0o755, b""), "SKILL.md": ("file", 0o644, body.encode())}
    listing = {"SKILL.md": ("100644", blob_id(body.encode(), library.algorithm))}
    return {"entries": entries, "listing": listing, "tree": tree_id(listing, library.algorithm)}


def write_tree(entries: dict, target: Path):
    for rel, (kind, mode, data) in sorted(entries.items()):
        p = target / rel if rel else target
        if kind == "dir":
            p.mkdir(parents=True, exist_ok=True)
        elif kind == "file":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            p.chmod(mode)
        else:
            raise InstallError(f"Unsupported generated entry: {rel}")
    for rel, (kind, mode, _) in sorted(entries.items(), reverse=True):
        if kind == "dir":
            (target / rel if rel else target).chmod(mode)


# --- Planning --------------------------------------------------------------------------


def conflict_groups(skills: dict) -> dict:
    by_name = defaultdict(list)
    for skill_id, info in skills.items():
        by_name[info["name"]].append(skill_id)
    return {name: ids for name, ids in sorted(by_name.items()) if len({skills[i]["tree"] for i in ids}) > 1}


def protected(path: Path) -> bool:
    return path.name.startswith(".") or is_link(path)


def valid_entry(entry: str):
    if not isinstance(entry, str) or not entry or entry.startswith(".") or "/" in entry or "\\" in entry:
        raise InstallError(f"Invalid managed entry: {entry!r}")


def valid_hash(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise InstallError(f"Invalid fingerprint: {value!r}")


def valid_tree(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value)):
        raise InstallError(f"Invalid tree id: {value!r}")


def validate_state(value: dict, client: str):
    if not value:
        return
    if value.get("schema") != SCHEMA or value.get("client") != client:
        raise InstallError(f"Unsupported or invalid state: {client}")
    if not isinstance(value.get("destination"), str) or not Path(value["destination"]).is_absolute():
        raise InstallError(f"Invalid state destination: {client}")
    if not isinstance(value.get("selection"), list) or not all(isinstance(i, str) for i in value["selection"]):
        raise InstallError(f"Invalid state selection: {client}")
    if not isinstance(value.get("managed"), dict):
        raise InstallError(f"Invalid ownership manifest: {client}")
    for entry, info in value["managed"].items():
        valid_entry(entry)
        if not isinstance(info, dict) or info.get("sha256") is None:
            raise InstallError(f"Invalid ownership record: {client}:{entry}")
        valid_hash(info["sha256"])
        valid_tree(info.get("tree"))


def selection(args, client: str, old: dict, library: Library) -> list[str]:
    ids = old.get("selection", ["@library"] if client == "codex" else ["@all"])
    if args.selection is not None:
        ids = [v for v in args.selection.split(",") if v]
    ids = set(library.skills) | (set(ids) - {"@all"}) if "@all" in ids and args.disable else set(ids)
    ids.update(args.enable)
    unknown_disable = set(args.disable) - set(library.skills) - set(ids) - {"@library", "@all"}
    if unknown_disable:
        raise InstallError(f"Unknown source IDs to disable: {sorted(unknown_disable)}")
    ids.difference_update(args.disable)
    unknown = ids - set(library.skills) - {"@library", "@all"}
    if unknown:
        raise InstallError(f"Unknown source IDs: {sorted(unknown)} (use --list --search)")
    return sorted(ids)


def desired_entries(client: str, ids: list[str], library: Library, router: dict) -> tuple[dict, dict]:
    selected = set(library.skills) if "@all" in ids else set(ids) - {"@library"}
    if "@library" in ids and ROUTER in selected:
        raise InstallError(f"Source ID collides with reserved library entry: {ROUTER}")
    selected_info = {i: library.skills[i] for i in selected}
    if "@library" in ids:
        selected_info["@library"] = {"name": ROUTER, "tree": router["tree"]}
    conflicts = conflict_groups(selected_info)
    if conflicts and client == "codex":
        raise InstallError(
            f"Codex selection has different-content frontmatter name conflicts: {json.dumps(conflicts)}. "
            "Select one explicit source ID per name; all variants remain in the library."
        )
    # Preserve Claude's full paths. Codex deduplicates identical trees and records aliases.
    desired, seen = {}, {}
    for skill_id in sorted(selected):
        info = dict(library.skills[skill_id], source_ids=[skill_id])
        key = (info["name"], info["tree"])
        if client == "codex" and key in seen:
            desired[seen[key]]["source_ids"].append(skill_id)
        else:
            seen[key] = skill_id
            desired[skill_id] = info
    if "@library" in ids:
        desired[ROUTER] = {
            "name": ROUTER,
            "tree": router["tree"],
            "source_ids": ["@library"],
            "origins": [{"repository": REPOSITORY, "path": "scripts/install_skills.py"}],
        }
    return desired, conflicts


def expected_listing(want: dict, library: Library, router: dict) -> dict:
    return router["listing"] if want["source_ids"] == ["@library"] else library.listing(want["source_ids"][0])


def kept_entry(entry: str, reason: str = "protected, modified, or unproven ownership") -> dict:
    return {"entry": entry, "reason": reason}


def plan_entries(client, dest, managed, desired, library, router) -> tuple[list, list, dict]:
    actions, kept, new_managed = [], [], {}
    existing = {p.name for p in dest.iterdir()} if dest.exists() else set()
    for entry in sorted(existing | set(desired) | set(managed)):
        target, want, rec = dest / entry, desired.get(entry), managed.get(entry)
        present = entry in existing
        if want and rec and rec.get("tree") == want["tree"] and present and plain_dir(target):
            # Unchanged since this installer recorded it: a cheap existence check, no hashing.
            new_managed[entry] = dict(want, sha256=rec["sha256"])
            continue
        if present and not want and not rec and entry not in library.skills:
            kept.append(kept_entry(entry))  # unknown entries are never hashed or claimed
            continue
        current = fingerprint(target) if present else None
        owned = False
        if current is not None and not protected(target):
            if rec:
                owned = current == rec["sha256"]
            elif entry in library.skills:
                owned = library.adoptable(entry, target)
        if current is not None and not owned:
            kept.append(kept_entry(entry))
            if rec:
                # Retain the last installed fingerprint so future updates keep
                # recognizing the edited copy, including after deselection.
                new_managed[entry] = rec
            if want and not rec and client == "codex":
                if want["source_ids"] != ["@library"] or not same_tree(router["listing"], target, library.algorithm):
                    raise InstallError(f"Cannot install {client}:{entry}: preserved destination differs: {target}")
            continue
        if want:
            if current is not None and same_tree(expected_listing(want, library, router), target, library.algorithm):
                new_managed[entry] = dict(want, sha256=current)  # identical content: record, do not copy
            else:
                new_managed[entry] = dict(want, sha256=None)  # filled in once the copy is prepared
                actions.append(
                    {
                        "entry": entry,
                        "before": current,
                        "after": None,
                        "source": want["source_ids"][0],
                        "tree": want["tree"],
                    }
                )
        elif owned:
            actions.append({"entry": entry, "before": current, "after": None})
    return actions, kept, new_managed


def external_skills(client: str, dest: Path, kept: list, home: Path) -> dict:
    """Preserved skills, even symlinks, and for Codex ~/.agents/skills, by frontmatter name."""
    paths = {item["entry"]: dest / item["entry"] for item in kept}
    if client == "codex":
        agents = home / ".agents/skills"
        if agents.is_dir() and agents != dest:
            paths.update({f".agents/{p.name}": p for p in agents.iterdir()})
    external = {}
    for entry, directory in paths.items():
        p = directory / "SKILL.md"
        if p.is_file():
            try:
                external[entry] = {"name": metadata(p.read_bytes(), display(p))["name"], "path": directory}
            except InstallError:
                pass
    return external


def external_conflicts(external: dict, algorithm: str) -> dict:
    by_name = defaultdict(list)
    for entry, ext in external.items():
        by_name[ext["name"]].append(entry)
    groups = {}
    for name, entries in sorted(by_name.items()):
        if len(entries) > 1:
            trees = {tree_id(local_listing(external[e]["path"], algorithm), algorithm) for e in entries}
            if len(trees) > 1:
                groups[name] = entries
    return groups


def plan_client(client, dest, old, ids, library, router, home) -> dict:
    managed = old.get("managed", {}) if old.get("destination") == str(dest) else {}
    desired, conflicts = desired_entries(client, ids, library, router)
    actions, kept, new_managed = plan_entries(client, dest, managed, desired, library, router)
    external = external_skills(client, dest, kept, home)
    preserved = {item["entry"] for item in kept}
    for entry, info in list(new_managed.items()):
        if entry in preserved:
            continue  # The recorded hash is historical for a modified managed copy.
        for other, ext in external.items():
            if other == entry or ext["name"] != info["name"]:
                continue
            if not same_tree(expected_listing(info, library, router), ext["path"], library.algorithm):
                if client == "codex":
                    raise InstallError(
                        f"Frontmatter name conflict with preserved {display(ext['path'])}: {info['name']} ({entry})"
                    )
                conflicts[info["name"]] = sorted(
                    set(conflicts.get(info["name"], [])) | {entry, f"external:{display(ext['path'])}"}
                )
                continue
            if client == "codex":
                target, rec = dest / entry, managed.get(entry)
                current = fingerprint(target)
                owned = current is not None and not protected(target)
                owned = owned and (current == rec["sha256"] if rec else library.adoptable(entry, target))
                if current is not None and not owned:
                    # A modified copy found through the unchanged-entry shortcut stays preserved.
                    if rec:
                        new_managed[entry] = rec
                    else:
                        new_managed.pop(entry)
                    kept.append(kept_entry(entry))
                    break
                new_managed.pop(entry, None)
                actions = [a for a in actions if a["entry"] != entry]
                if current is not None:
                    actions.append({"entry": entry, "before": current, "after": None})
                kept.append(kept_entry(entry, f"identical external name at {other}; not claimed"))
                break
    new = {"schema": SCHEMA, "client": client, "destination": str(dest), "selection": ids, "managed": new_managed}
    return {
        "client": client,
        "destination": str(dest),
        "actions": actions,
        "preserved": kept,
        "conflicts": conflicts,
        "external_conflicts": external_conflicts(external, library.algorithm),
        "state": new,
        "previous_state": old,
    }


# --- Locking, applying and restoring ---------------------------------------------------


@contextmanager
def state_lock(directory: Path):
    """An exclusive, non-blocking lock owned by this installer (flock, or msvcrt on Windows)."""
    path = directory / ".lock"
    no_symlink_ancestors(path)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o644)
    try:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if isinstance(exc, BlockingIOError) or exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise LockBusy(f"Another awesome-skills installer is running (lock: {display(path)})") from exc
            raise
        try:
            yield
        finally:
            if fcntl is None:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def journal_status(path: Path):
    """Read a journal's status without parsing megabytes of saved state each run."""
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 256))
            tail = stream.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return None
    match = re.search(r'"status": "(\w+)"\s*\}\s*$', tail)
    return match.group(1) if match else read_json(path, {}).get("status")


def preflight(plans: list, state: Path):
    for p in plans:
        if read_json(state / f"{p['client']}.json", {}) != p["previous_state"]:
            raise InstallError(f"Selection changed since planning: {p['client']}")
        for action in p["actions"]:
            target = Path(p["destination"]) / action["entry"]
            no_symlink_ancestors(target)
            if fingerprint(target) != action["before"]:
                raise InstallError(f"Destination changed since planning: {display(target)}")
            ancestor = target.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            if ancestor.stat().st_dev != state.stat().st_dev:
                raise InstallError(
                    f"Recovery state and destination must be on the same filesystem: {display(state)}, {display(target)}"
                )


def apply_plans(plans: list, state: Path, library: Library, router: dict) -> Path | None:
    """Apply verified plans as one recoverable transaction. The caller holds the lock."""
    preflight(plans, state)
    changed = [p for p in plans if p["actions"] or read_json(state / f"{p['client']}.json", {}) != p["state"]]
    if not changed:
        return None
    backups = state / "backups"
    no_symlink_ancestors(backups)
    if backups.exists():
        for saved in backups.iterdir():
            if journal_status(saved / "restore.json") == "applying":
                raise InstallError(f"Incomplete transaction; restore it first with --restore {display(saved)}")
    # Download first: a failed transfer leaves no transaction behind.
    library.prepare([a["source"] for p in changed for a in p["actions"] if a.get("source") not in (None, "@library")])
    backup = backups / (time.strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns():020d}-" + uuid.uuid4().hex[:8])
    no_symlink_ancestors(backup)
    backup.mkdir(parents=True)
    journal = {"schema": SCHEMA, "state_dir": str(state), "status": "preparing", "clients": []}
    for p in changed:
        statefile = state / f"{p['client']}.json"
        journal["clients"].append(
            {
                "client": p["client"],
                "destination": p["destination"],
                "old_state": read_json(statefile, {}) if statefile.exists() else None,
                "new_state": None,
                "actions": p["actions"],
            }
        )
    atomic_json(backup / "restore.json", journal)
    prepare_copies(changed, backup, library, router)
    for item, p in zip(journal["clients"], changed, strict=True):
        validate_state(p["state"], p["client"])
        item["new_state"], item["actions"] = p["state"], p["actions"]
    journal["status"] = "applying"
    atomic_json(backup / "restore.json", journal)
    for p in changed:
        dest = Path(p["destination"])
        for action in p["actions"]:
            entry, target = action["entry"], dest / action["entry"]
            if fingerprint(target) != action["before"] or is_link(target):
                raise InstallError(f"Destination changed since planning: {target}; recovery journal: {backup}")
            if action["before"] is not None:
                saved = backup / p["client"] / entry
                saved.parent.mkdir(parents=True, exist_ok=True)
                move(target, saved)
            if action["after"] is not None:
                dest.mkdir(parents=True, exist_ok=True)
                move(backup / "prepared" / p["client"] / entry, target)
        atomic_json(state / f"{p['client']}.json", p["state"])
    journal["status"] = "complete"
    atomic_json(backup / "restore.json", journal)
    return backup


def prepare_copies(changed: list, backup: Path, library: Library, router: dict):
    """Fully prepare and verify replacements before any live entry moves."""
    try:
        for p in changed:
            for action in p["actions"]:
                if action.get("source") is None:
                    continue
                entry = action["entry"]
                prepared = backup / "prepared" / p["client"] / entry
                prepared.parent.mkdir(parents=True, exist_ok=True)
                if action["source"] == "@library":
                    write_tree(router["entries"], prepared)
                    expected = router["listing"]
                else:
                    library.materialize(action["source"], prepared)
                    expected = library.listing(action["source"])
                if not same_tree(expected, prepared, library.algorithm):
                    raise InstallError(f"Prepared copy changed: {display(prepared)}; recovery journal: {backup}")
                action["after"] = fingerprint(prepared)
                p["state"]["managed"][entry]["sha256"] = action["after"]
    except BaseException:
        if (backup / "prepared").exists():
            try:
                rmtree(backup / "prepared")
            except OSError:
                pass
        raise


def restore(backup: Path, state: Path, dry_run: bool):
    no_symlink_ancestors(backup)
    if backup.parent != state / "backups":
        raise InstallError(f"Recovery backup must belong to this state directory: {display(state)}")
    journal = read_json(backup / "restore.json", {})
    if (
        journal.get("schema") != SCHEMA
        or journal.get("state_dir") != str(state)
        or journal.get("status") not in {"complete", "applying", "preparing"}
        or not isinstance(journal.get("clients"), list)
    ):
        raise InstallError(f"Invalid or already restored journal: {display(backup)}")
    if journal["status"] == "preparing":
        # Interrupted before any live entry or manifest moved: nothing to put back.
        print(json.dumps({"restore": display(backup), "targets": []}, indent=2))
        if not dry_run:
            journal["status"] = "restored"
            atomic_json(backup / "restore.json", journal)
        return
    operations = restore_operations(backup, state, journal)
    print(json.dumps({"restore": display(backup), "targets": [display(t) for t, _, _ in operations]}, indent=2))
    if dry_run:
        return
    for target, saved, current in reversed(operations):
        if current is not None:
            redo = backup / "replaced-on-restore" / (target.name + "-" + uuid.uuid4().hex[:8])
            redo.parent.mkdir(parents=True, exist_ok=True)
            move(target, redo)
        if saved.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            move(saved, target)
    for client in journal["clients"]:
        path = state / f"{client['client']}.json"
        if client["old_state"] is None:
            path.unlink(missing_ok=True)
        else:
            atomic_json(path, client["old_state"])
    journal["status"] = "restored"
    atomic_json(backup / "restore.json", journal)


def restore_operations(backup: Path, state: Path, journal: dict) -> list:
    operations = []
    seen_clients = set()
    for client in journal["clients"]:
        name = client.get("client")
        if name not in {"claude", "codex"} or name in seen_clients:
            raise InstallError(f"Invalid recovery client: {name}")
        seen_clients.add(name)
        validate_state(client.get("new_state") or {}, name)
        validate_state(client.get("old_state") or {}, name)
        if not client.get("new_state") or client.get("destination") != client["new_state"]["destination"]:
            raise InstallError("Recovery destination does not match the client manifest")
        dest = safe_absolute(Path(client["destination"]))
        if str(dest) != client["destination"]:
            raise InstallError("Recovery destination must be canonical and absolute")
        current_state = read_json(state / f"{client['client']}.json", {})
        if current_state not in [client["new_state"], client["old_state"] or {}]:
            raise InstallError(f"Client selection changed after this transaction: {client['client']}")
        for action in client["actions"]:
            valid_entry(action.get("entry"))
            valid_hash(action.get("before"))
            valid_hash(action.get("after"))
            valid_tree(action.get("tree"))
            if action.get("before") == action.get("after"):
                raise InstallError("Invalid recovery action")
            if action["after"] is not None and action["after"] != client["new_state"]["managed"].get(
                action["entry"], {}
            ).get("sha256"):
                raise InstallError("Recovery fingerprint does not match the ownership manifest")
            target = dest / action["entry"]
            saved = backup / client["client"] / action["entry"]
            no_symlink_ancestors(saved)
            if target.exists() and (not target.is_dir() or not (target / "SKILL.md").is_file()):
                raise InstallError(f"Recovery target is not a skill directory: {display(target)}")
            current = fingerprint(target)
            if current == action["before"] and not saved.exists():
                continue
            if current not in [action["after"], None] or is_link(target):
                raise InstallError(f"Refusing to overwrite changes during restore: {display(target)}")
            if action["before"] is not None and fingerprint(saved) != action["before"]:
                raise InstallError(f"Missing or changed recovery copy: {display(saved)}")
            operations.append((target, saved, current))
    return operations


# --- Legacy tarball-installer cache ----------------------------------------------------


def legacy_caches(cache_root: Path) -> list[Path]:
    """Snapshot directories the tarball installer created, recognized by name and exact layout."""
    libraries = cache_root / "libraries"
    if not plain_dir(cache_root) or not plain_dir(libraries):
        return []
    found = []
    for child in sorted(libraries.iterdir()):
        if not plain_dir(child):
            continue
        names = set(os.listdir(child))
        if LEGACY_SNAPSHOT.fullmatch(child.name) and names == LEGACY_CACHE_FILES:
            found.append(child)
        elif LEGACY_TEMP.fullmatch(child.name) and all(
            n in LEGACY_CACHE_FILES or LEGACY_TEMP_FILE.fullmatch(n) for n in names
        ):
            found.append(child)
    return found


def remove_legacy_caches(cache_root: Path) -> list[Path]:
    removed = []
    for path in legacy_caches(cache_root):
        rmtree(path)
        removed.append(path)
    if removed:
        for directory in (cache_root / "libraries", cache_root):
            try:
                directory.rmdir()  # only when nothing else is left
            except OSError:
                break
    return removed


def migrated(state: Path) -> bool:
    """No managed router still comes from the tarball installer, whose router pointed into its cache."""
    for client in ("claude", "codex"):
        managed = read_json(state / f"{client}.json", {}).get("managed", {})
        if any(info.get("source_ids") == ["@library"] and "tree" not in info for info in managed.values()):
            return False
    return True


# --- Command line ----------------------------------------------------------------------


def default_data(home: Path) -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "awesome-skills"
    if WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        return Path(local if local else home / "AppData/Local") / "awesome-skills"
    return home / ".local/share/awesome-skills"


def outside_discovery(path: Path) -> Path:
    if any(
        a in {".agents", ".codex", ".claude"} and b == "skills"
        for a, b in zip(path.parts, path.parts[1:], strict=False)
    ):
        raise InstallError(f"Storage must be disjoint from project/global discovery: {display(path)}")
    return path


def storage_path(variable: str, default: Path) -> Path:
    return outside_discovery(safe_absolute(Path(os.environ.get(variable) or default)))


def resolve_clients(args, home: Path, storage: list[Path], source: Path | None) -> list[tuple]:
    clients = []
    for client in ["codex"] if args.codex_only else ["claude"] if args.claude_only else ["claude", "codex"]:
        state = storage[0]
        old = read_json(state / f"{client}.json", {})
        validate_state(old, client)
        dest = safe_absolute(
            Path(
                os.environ.get(f"SKILLS_{client.upper()}_DEST", old.get("destination", str(home / f".{client}/skills")))
            )
        )
        if dest == home / ".agents" or home / ".agents" in dest.parents:
            raise InstallError(f"This installer does not own ~/.agents: {display(dest)}")
        other = "claude" if client == "codex" else "codex"
        other_state = read_json(state / f"{other}.json", {})
        validate_state(other_state, other)
        other_roots = {Path(os.environ.get(f"SKILLS_{other.upper()}_DEST", str(home / f".{other}/skills")))}
        if other_state.get("destination"):
            other_roots.add(Path(other_state["destination"]))
        for root in other_roots:
            if overlap(dest, native(root.expanduser().resolve())):
                raise InstallError(f"Client destinations overlap: {display(dest)}, {display(root)}")
        codex_root = native(Path(os.path.abspath(Path(os.environ.get("CODEX_HOME", str(home / ".codex")))))) / "skills"
        for root in [home / ".codex/skills", home / ".claude/skills", home / ".agents", codex_root, dest]:
            root = native(root.resolve())
            for path in storage:
                if overlap(path, root):
                    raise InstallError(
                        f"Storage and discovery roots must be disjoint: {display(path)}, {display(root)}"
                    )
        if source is not None and overlap(source, dest):
            raise InstallError(f"Source and destination overlap: {display(source)}, {display(dest)}")
        clients.append((client, dest, old))
    return clients


def make_plans(args, clients: list, library: Library, home: Path) -> tuple[list, dict]:
    router = router_info(library)
    plans = [
        plan_client(client, dest, old, selection(args, client, old, library), library, router, home)
        for client, dest, old in clients
    ]
    if len(plans) == 2:
        a, b = (Path(p["destination"]) for p in plans)
        if overlap(a, b):
            raise InstallError(f"Client destinations overlap: {display(a)}, {display(b)}")
    return plans, router


def report(dry_run: bool, library: Library, plans: list, legacy: list[Path]) -> dict:
    clients = [
        {k: v for k, v in p.items() if k not in {"state", "previous_state"}} | {"selection": p["state"]["selection"]}
        for p in plans
    ]
    return {
        "dry_run": dry_run,
        "library_entries": len(library.skills),
        "library": library.describe(),
        "legacy_cache_cleanup": [display(p) for p in legacy],
        "clients": clients,
    }


def emit(value: dict):
    utf8 = (sys.stdout.encoding or "").lower().replace("-", "") == "utf8"
    print(json.dumps(value, indent=2, ensure_ascii=not utf8))


def guard_source(source: Path, data: Path):
    """A local source must be a complete tree, never the sparse library clone."""
    if overlap(source, data) or is_library_clone(source.parent):
        raise InstallError(f"Refusing the managed library clone as a local source: {display(source)}")
    sparse = source.parent / ".git" / "info" / "sparse-checkout"
    if sparse.is_file() and shutil.which("git"):
        result = subprocess.run(
            ["git", "-C", display(source.parent), "config", "--bool", "core.sparseCheckout"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if result.stdout.strip() == "true":
            raise InstallError(f"Refusing a sparse checkout as a local source: {display(source)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    clients = parser.add_mutually_exclusive_group()
    clients.add_argument("--codex-only", action="store_true")
    clients.add_argument("--claude-only", action="store_true")
    parser.add_argument("--source", type=Path, help="local skills directory (default: adjacent library)")
    parser.add_argument("--remote", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--selection", help="replace ONE client's selection with comma-separated IDs; empty disables all"
    )
    parser.add_argument("--enable", action="append", default=[], metavar="ID")
    parser.add_argument("--disable", action="append", default=[], metavar="ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true", help="list full-library metadata and name conflicts")
    parser.add_argument("--search", default="", help="filter --list by ID, name, description or origin")
    parser.add_argument("--restore", type=Path, help="restore a backup, refusing later modifications")
    parser.add_argument("--delete", action="store_true", help="deprecated: prune only verified managed deselections")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.selection is not None or args.enable or args.disable) and not (args.codex_only or args.claude_only):
        parser.error("selection changes require --codex-only or --claude-only")
    home = native(Path.home())
    data_default = default_data(home)
    state = storage_path("SKILLS_STATE_DIR", data_default if WINDOWS else home / ".local/share/awesome-skills")
    legacy_cache = storage_path("SKILLS_CACHE_DIR", home / ".cache/awesome-skills")
    remote, source = args.remote, None
    helper = globals().get("__file__")
    clone = native(Path(helper).resolve().parent.parent) if helper else None
    if args.source is None and clone is not None and is_library_clone(clone):
        # The helper inside the library clone (the router's command) serves that clone.
        remote, data = True, outside_discovery(safe_absolute(clone.parent))
    else:
        data = storage_path("SKILLS_DATA_DIR", data_default)
    if args.restore:
        target = safe_absolute(args.restore)
        if args.dry_run:
            restore(target, state, True)
        else:
            with state_lock(state):
                restore(target, state, False)
        return 0
    if not remote:
        adjacent = Path(helper).resolve().parent if helper else Path.cwd()
        default = adjacent / "skills" if (adjacent / "skills").exists() else adjacent.parent / "skills"
        source = native((args.source or default).resolve())
        guard_source(source, data)
    url = os.environ.get("SKILLS_REPOSITORY_URL") or REPOSITORY_URL
    branch = os.environ.get("SKILLS_BRANCH") or "main"
    if not re.fullmatch(r"[A-Za-z0-9._][A-Za-z0-9._/-]*", branch) or ".." in branch:
        raise InstallError(f"Invalid SKILLS_BRANCH: {branch!r}")
    git = Git() if remote else None  # a missing or old git fails before anything is written
    if args.list:
        with open_library(git, source, data, url, branch, "list") as library:
            matches = {i: s for i, s in library.skills.items() if args.search.lower() in json.dumps([i, s]).lower()}
            emit({"revision": library.revision, "skills": matches, "conflicts": conflict_groups(matches)})
        return 0
    clients = resolve_clients(args, home, [state, data, legacy_cache], source)
    if args.dry_run:
        with open_library(git, source, data, url, branch, "dry-run") as library:
            plans, _ = make_plans(args, clients, library, home)
            emit(report(True, library, plans, legacy_caches(legacy_cache)))
        return 0
    with ExitStack() as stack:
        if remote:
            # The clone is shared state too: fetch, plan and apply under one lock.
            stack.enter_context(state_lock(state))
            if data != state:
                stack.enter_context(state_lock(data))
            clients = resolve_clients(args, home, [state, data, legacy_cache], source)
        library = stack.enter_context(open_library(git, source, data, url, branch, "apply"))
        plans, router = make_plans(args, clients, library, home)
        if not remote:
            stack.enter_context(state_lock(state))  # a planning error leaves HOME untouched
        backup = apply_plans(plans, state, library, router)
        removed = remove_legacy_caches(legacy_cache) if migrated(state) else []
    if backup:
        emit(report(False, library, plans, removed))
        print(f"Recovery backup: {display(backup)}")
    else:
        print("Already current; selection preserved.")
    if removed:
        print(f"Removed {len(removed)} legacy cache snapshot(s) under {display(legacy_cache)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LockBusy as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(LOCK_BUSY) from None
    except (InstallError, OSError, ValueError) as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("awesome-skills: interrupted", file=sys.stderr)
        raise SystemExit(130) from None
