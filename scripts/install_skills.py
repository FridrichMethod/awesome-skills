#!/usr/bin/env python3
"""Install the skill library for Claude Code and Codex: every skill runs by hand, the model sees
only each client's selection (by default the router). Remote installs keep a blobless sparse
git clone and need only the standard library; PyYAML reads a checkout's skills in full."""

from __future__ import annotations

import argparse
import bisect
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

REPOSITORY = "https://github.com/FridrichMethod/awesome-skills"
REPOSITORY_URL = REPOSITORY + ".git"
SCHEMA = 1
# v2 states: `selection` is what the model sees, `manual` what is installed hidden besides, and
# records carry `invocation` (SCHEMA also gates the index and journals, so it stays 1).
SELECTION_VERSION = 2
MIGRATION, MIGRATIONS = "selection-v2", "migrations.json"
SHORTCUT = ("tree", "invocation", "name", "root")  # an unchanged record and copy is not rehashed
ROOT_CAP = 1990  # Codex walks at most 2,000 directories per skills root, top-level folders first
SUMMARY_ACTIONS = 100  # a larger plan prints one line per client instead of its JSON
LAUNCHER = "awesome-skills"
ROUTER = "awesome-skills-library"
INDEX = "library_index.json"
PROVENANCE = "library_sources.json"
CLONE = "library"
MARKER = "awesome-skills-library"  # file in the clone's .git directory
MIN_GIT = (2, 29, 0)
# A sparse index keeps every directory outside the cone as one entry, so git on Windows
# never checks (and refuses) a Windows-invalid path deep inside a skill nobody selected.
SPARSE_INDEX_GIT = (2, 37, 0)
LOCK_BUSY = 75
NEEDS_PERSON = 3  # an interrupted update or a mass removal needs a person's decision
KEEP_BACKUPS = 5
STALE_LOCK_SECONDS = 6 * 3600  # a fallback lock this old is stale: far above the longest run
LOCK_UNSUPPORTED = {errno.ENOLCK, errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)}
# A stalled connection never holds the lock: HTTP below 1000 B/s for 60 s aborts
# (GIT_HTTP_LOW_SPEED_* override), and unconfigured ssh never prompts or waits on a silent peer.
SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
MASS_REMOVAL_SHARE, MASS_REMOVAL_MINIMUM = 0.5, 20
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
    f"core.attributesFile={os.devnull}",
    "gc.autoDetach=false",
    "advice.detachedHead=false",
    "http.lowSpeedLimit=1000",
    "http.lowSpeedTime=60",
)
# Inherited GIT_* variables (a hook's GIT_DIR, injected GIT_CONFIG_COUNT, ...) are dropped but
# for ssh, proxy, TLS, config-file selection and the low-speed overrides.
GIT_ENV_KEEP = frozenset(
    "GIT_SSH GIT_SSH_COMMAND GIT_SSH_VARIANT GIT_PROXY_COMMAND GIT_SSL_CAINFO GIT_SSL_CAPATH GIT_SSL_CERT "
    "GIT_SSL_KEY GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_CONFIG_NOSYSTEM GIT_HTTP_LOW_SPEED_LIMIT "
    "GIT_HTTP_LOW_SPEED_TIME".split()
)
# Only these mean the clone is damaged; anything else (a dropped link, a full disk) is retried
# or reported, never answered by re-cloning.
CORRUPTION = (
    *("not a git repository", "bad object", "invalid object", "unable to read", "corrupt", "could not parse"),
    *("needed a single revision", "bad revision", "unknown revision", "bad index"),
)
WINDOWS_INVALID = re.compile(r'[<>:"|?*\x00-\x1f\\]|[. ]$|^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$', re.IGNORECASE)
GIT_METADATA_FILES = {".gitattributes", ".gitmodules"}
LEGACY_CACHE_FILES = {"index.json", "install_skills.py", "library_sources.json", "skills"}
LEGACY_SNAPSHOT = re.compile(r"[0-9a-f]{64}")
LEGACY_TEMP = re.compile(r"[0-9a-f]{64}\.tmp-[0-9a-f]{32}")
LEGACY_TEMP_FILE = re.compile(r"(index|library_sources)\.json\.tmp-[0-9a-f]{32}")


class InstallError(Exception):
    pass


class LockBusy(InstallError):
    pass


class GitError(InstallError):
    """A git command failed."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


class PersonNeeded(InstallError):
    """Exit 3: an interrupted update cannot be undone, or an update would remove most skills."""


def corrupted(error: GitError) -> bool:
    text = (getattr(error, "stderr", "") or str(error)).lower()
    return any(signature in text for signature in CORRUPTION)


def warn(message: str):
    print(f"awesome-skills: warning: {message}", file=sys.stderr)


# --- Paths


def native(path: Path) -> Path:
    """Extended-length paths on Windows: deep skill trees need no registry change."""
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


def name_problem(name: str) -> str | None:
    if not name or name in {".", ".."} or "/" in name:
        return "invalid name"
    return "not a portable (Windows) file name" if WINDOWS_INVALID.search(name) else None


def path_problems(paths) -> list[str]:
    """Paths git cannot check out everywhere: Windows-invalid names and case-only collisions."""
    every = set()
    for rel in paths:
        parts = rel.split("/")
        every.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    problems, seen = [], {}
    for rel in sorted(every):
        reason = name_problem(rel.rsplit("/", 1)[-1])
        if reason:
            problems.append(f"{rel}: {reason}")
        other = seen.setdefault(rel.casefold(), rel)
        if other != rel:
            problems.append(f"{rel}: differs only in case from {other}")
    return problems


def skill_problems(skill_id: str, kinds: dict) -> list[str]:
    """Why a skill (relative path -> "file", "link", ...) cannot be installed on every platform."""
    reason = "hidden" if skill_id.startswith(".") else name_problem(skill_id)
    problems = [f"{skill_id}: {reason}"] if reason else []
    for rel, kind in sorted(kinds.items()):
        if kind != "file":
            problems.append(f"{rel}: {'symbolic link' if kind == 'link' else kind}")
        if rel.rsplit("/", 1)[-1] in GIT_METADATA_FILES:
            problems.append(f"{rel}: git metadata file")
    return problems + path_problems(kinds)


def case_collisions(ids, preferred=frozenset()) -> dict:
    """IDs that differ only in case cannot coexist on Windows or macOS. When exactly one of a
    group is preferred (it has a valid index entry), only the others are reported."""
    groups = defaultdict(list)
    for skill_id in ids:
        groups[skill_id.casefold()].append(skill_id)
    found = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        keep = [i for i in group if i in preferred]
        for skill_id in [i for i in group if i != keep[0]] if len(keep) == 1 else group:
            found[skill_id] = f"differs only in case from {', '.join(o for o in group if o != skill_id)}"
    return found


# --- Content identity


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


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


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


def local_listing(path: Path) -> dict:
    """Git's view of a directory: relative POSIX path -> (mode, object id). Directories are
    implicit (empty ones vanish); native Windows has no executable bit, every file is 100644."""
    out = {}
    for rel, (kind, bits) in local_entries(path).items():
        p = path.joinpath(*rel.split("/"))
        if kind == "link":
            out[rel] = ("120000", blob_id(os.fsencode(os.readlink(p))))
        elif kind == "file":
            executable = not WINDOWS and bits & stat.S_IXUSR
            out[rel] = ("100755" if executable else "100644", blob_id(p.read_bytes()))
    return out


def listing_kinds(listing: dict) -> dict:
    kinds = {}
    for rel, (mode, _) in listing.items():
        parts = rel.split("/")
        for i in range(1, len(parts)):
            kinds["/".join(parts[:i])] = "dir"
        kinds[rel] = "link" if mode == "120000" else "file"
    return kinds


def tree_id(listing: dict) -> str:
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
        return hashlib.sha1(b"tree %d\0" % len(body) + body).hexdigest()

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


def same_tree(expected: dict, path: Path) -> bool:
    """Same paths, bytes, link targets and executable bits; other permission bits are ignored."""
    if not plain_dir(path):
        return False
    kinds = {rel: kind for rel, kind in listing_kinds(expected).items() if kind != "dir"}
    if {rel: kind for rel, (kind, _) in local_entries(path).items() if kind != "dir"} != kinds:
        return False  # cheap stat-only rejection before reading any bytes
    return same_files(expected, local_listing(path))


def exact_tree(expected: dict, path: Path) -> bool:
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
    return same_files(expected, local_listing(path))


# --- Metadata

# A remote install reads only the top-level `name` of SKILL.md, with NameReader (the rest comes
# from library_index.json); the sync rejects a skill it cannot read exactly as PyYAML does.
NON_PRINTABLE = re.compile(r"[^\t\n\r\x20-\x7e\x85\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
DOCUMENT_MARKER = re.compile(r"(?:---|\.\.\.)(?:[ \t]|$)")
BLOCK_HEADER = re.compile(r"[|>](?:[+-]([1-9])?|([1-9])[+-]?)?(?: +(?:#.*)?)?")
ESCAPES = {
    **{"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"},
    **{"e": "\x1b", " ": " ", '"': '"', "\\": "\\", "/": "/", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"},
}
HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
# PyYAML's implicit resolvers (yaml/resolver.py) for plain scalars that do not load as str.
NOT_STRINGS = [
    (
        re.compile(
            r"""^(?:yes|Yes|YES|no|No|NO
                    |true|True|TRUE|false|False|FALSE
                    |on|On|ON|off|Off|OFF)$""",
            re.X,
        ),
        "yYnNtTfFoO",
    ),
    (
        re.compile(
            r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?
                    |\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?
                    |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*
                    |[-+]?\.(?:inf|Inf|INF)
                    |\.(?:nan|NaN|NAN))$""",
            re.X,
        ),
        "-+0123456789.",
    ),
    (
        re.compile(
            r"""^(?:[-+]?0b[0-1_]+
                    |[-+]?0[0-7_]+
                    |[-+]?(?:0|[1-9][0-9_]*)
                    |[-+]?0x[0-9a-fA-F_]+
                    |[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$""",
            re.X,
        ),
        "-+0123456789",
    ),
    (re.compile(r"^(?:<<)$"), "<"),
    (re.compile(r"""^(?: ~ |null|Null|NULL | )$""", re.X), "~nN"),
    (
        re.compile(
            r"""^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]
                    |[0-9][0-9][0-9][0-9] -[0-9][0-9]? -[0-9][0-9]?
                     (?:[Tt]|[ \t]+)[0-9][0-9]?
                     :[0-9][0-9] :[0-9][0-9] (?:\.[0-9]*)?
                     (?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$""",
            re.X,
        ),
        "0123456789",
    ),
    (re.compile(r"^(?:=)$"), "="),
]


def pyyaml():
    """PyYAML, needed only to parse whole frontmatter: installs from a checkout, and the sync."""
    try:
        import yaml
    except ImportError:
        raise InstallError(
            f"Installing from a checkout or --source reads every SKILL.md with PyYAML, which "
            f"{display(sys.executable)} cannot import; install PyYAML>=6.0 there or set SKILLS_PYTHON to a "
            "Python that has it. A remote install needs only the standard library."
        ) from None
    return yaml


def frontmatter(data: bytes, label: str) -> str:
    """The text between the first two `---` lines: what PyYAML and NameReader both read."""
    try:
        lines = data.decode("utf-8").splitlines()
        if lines[0].strip() != "---":
            raise ValueError("missing frontmatter")
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except (ValueError, IndexError, StopIteration) as e:
        raise InstallError(f"Invalid frontmatter at {label}: {e}") from e
    return "\n".join(lines[1:end])


def metadata(data: bytes, label: str) -> dict:
    """The whole frontmatter, parsed by PyYAML."""
    yaml = pyyaml()
    text = frontmatter(data, label)
    try:
        fm = yaml.safe_load(text)
        if not isinstance(fm, dict) or not isinstance(fm.get("name"), str) or not fm["name"].strip():
            raise ValueError("missing string name")
        return fm
    except (ValueError, yaml.YAMLError) as e:
        raise InstallError(f"Invalid frontmatter at {label}: {e}") from e


def frontmatter_name(data: bytes, label: str) -> str:
    """The frontmatter's top-level name as PyYAML would load it, read with the standard library."""
    try:
        return NameReader(frontmatter(data, label)).read()
    except ValueError as e:
        raise InstallError(f"Unreadable frontmatter name at {label}: {e}") from e


def skip_spaces(line: str, k: int) -> int:
    while k < len(line) and line[k] == " ":
        k += 1
    if line[k : k + 1] == "\t":
        raise ValueError("tab outside a quoted scalar")
    return k


def plain_start(ch: str, after: str) -> bool:
    """Whether a plain scalar may start here in block context (PyYAML's check_plain)."""
    return ch not in " \t-?:,[]{}#&*!|>'\"%@`" or (ch in "-?:" and after not in ("", " ", "\t"))


def plain_scalar(line: str, k: int, flow: bool = False) -> tuple[int, int]:
    """PyYAML's plain scalar from line[k] on: (end of its text, index of what stops it on this line)."""
    stops = ",?[]{}" if flow else ""
    end = k
    while True:
        j = k
        while j < len(line) and line[j] not in " \t" + stops:
            if line[j] == ":" and line[j + 1 : j + 2] in ("", " ", "\t", *stops.replace("?", "")):
                break
            j += 1
        if j == k:
            break
        end = k = j
        while k < len(line) and line[k] == " ":
            k += 1
        if k == end or k == len(line) or line[k] == "#":
            break
    if line[k : k + 1] == "\t":
        raise ValueError("tab outside a quoted scalar")
    return end, k


def escape(text: str, k: int) -> tuple[str, int]:
    """The double-quoted escape at text[k] (a backslash): its value and the index after it."""
    code = text[k + 1 : k + 2]
    if code in ESCAPES:
        return ESCAPES[code], k + 2
    if code == "\n":
        return "", k + 2  # an escaped line break
    digits = text[k + 2 : k + 2 + HEX_ESCAPES.get(code, 0)]
    if code not in HEX_ESCAPES or len(digits) != HEX_ESCAPES[code] or not HEX_DIGITS.issuperset(digits):
        raise ValueError(f"invalid escape in a double-quoted scalar: \\{code}")
    return chr(int(digits, 16)), k + 2 + len(digits)


def unquote(token: str) -> str:
    """The value of a one-line quoted scalar, quotes included in token."""
    if token[0] == "'":
        return token[1:-1].replace("''", "'")
    chars, k = [], 1
    while k < len(token) - 1:
        if token[k] == "\\":
            char, k = escape(token, k)
        else:
            char, k = token[k], k + 1
        chars.append(char)
    return "".join(chars)


class NameReader:
    """The top-level name of frontmatter text exactly as yaml.safe_load reads it, or ValueError.
    A column-0 line can belong to a quoted scalar or flow collection above it, so every multi-line
    value is followed. Block structure is checked as PyYAML does; flow grammar (`[a: b: c]`) is not."""

    def __init__(self, text: str):
        self.text, self.lines = text, text.split("\n")
        self.starts = [0]
        for line in self.lines[:-1]:
            self.starts.append(self.starts[-1] + len(line) + 1)
        self.stack = []  # open block collections: [column, "map" or "seq", value pending, indentless]
        self.plain = None  # (least column, is the name) of a plain scalar that may continue
        self.names = []

    def read(self) -> str:
        if NON_PRINTABLE.search(self.text):
            raise ValueError("non-printable character")
        if any(DOCUMENT_MARKER.match(line) for line in self.lines):
            raise ValueError("document marker")
        i = 0
        while i < len(self.lines):
            i = self.line(i)
        if not self.names:
            raise ValueError("no top-level name")
        if not self.names[0].strip():
            raise ValueError("empty name")
        return self.names[0]

    def line(self, i: int) -> int:
        line = self.lines[i]
        col = len(line) - len(line.lstrip(" "))
        if col == len(line):
            return i + 1
        if line[col] == "\t":
            raise ValueError("tab outside a quoted scalar")
        if self.plain:
            if line[col] != "#" and col >= self.plain[0]:  # the plain scalar continues here
                if self.plain[1]:
                    raise ValueError("multi-line name")
                stop = plain_scalar(line, col)[1]
                if stop < len(line) and line[stop] == ":":
                    raise ValueError("mapping value inside a plain scalar")
                if stop < len(line):
                    self.plain = None  # a comment ends it
                return i + 1
            self.plain = None
        return i + 1 if line[col] == "#" else self.structure(i, col)

    def structure(self, i: int, col: int) -> int:
        line = self.lines[i]
        while self.stack and self.stack[-1][0] > col:
            self.stack.pop()
        pos = col
        while line.startswith("-", pos) and line[pos + 1 : pos + 2] in ("", " "):
            self.enter(pos, "seq")
            pos = skip_spaces(line, pos + 1)
        if pos == len(line) or line[pos] == "#":
            return i + 1  # an empty entry; its value may follow on later lines
        return self.node(i, pos)

    def indent(self) -> int:
        """PyYAML's current block indentation (an indentless sequence shares its mapping's)."""
        return self.stack[-1][0] if self.stack else -1

    def enter(self, col: int, kind: str):
        """Add a key ("map") or a `- ` entry ("seq") at col to its block collection, or open one
        as the pending value of the key or entry above, as PyYAML's parser allows."""
        top = self.stack[-1] if self.stack else None
        if top and top[0] == col and top[1] == "seq" and top[3] and kind == "map":
            self.stack.pop()  # a key at its mapping's column ends an indentless sequence
            top = self.stack[-1]
        if top is None:
            if col or kind == "seq":
                raise ValueError("frontmatter does not start with a top-level key")
        elif top[0] == col and top[1] == kind:
            top[2] = True
            return
        elif not top[2] or top[0] > col or top[0] == col and kind == "map":
            raise ValueError(f"unexpected {'key' if kind == 'map' else 'sequence entry'} at column {col}")
        if top:
            top[2] = False
        self.stack.append([col, kind, True, top is not None and top[0] == col])

    def scalar(self, col: int):
        """A value node starting a line or following `- `: the pending value above it."""
        top = self.stack[-1] if self.stack else None
        if top is None or top[0] >= col or not top[2]:
            raise ValueError(f"unexpected value at column {col}")
        top[2] = False

    def node(self, i: int, pos: int) -> int:
        """A node at the start of a line or after `- `: a key with its value, or a value."""
        line, colon, key = self.lines[i], -1, ""
        if line[pos] in "'\"":
            row, end = self.quoted(i, pos)
            if row == i:
                colon, key = skip_spaces(line, end), unquote(line[pos:end])
        elif plain_start(line[pos], line[pos + 1 : pos + 2]):
            end, colon = plain_scalar(line, pos)
            key = line[pos:end]
        if line[colon : colon + 1] == ":" and line[colon + 1 : colon + 2] in ("", " ", "\t"):
            return self.key(i, pos, colon, key)
        self.scalar(pos)
        return self.value(i, pos, False)

    def key(self, i: int, pos: int, colon: int, key: str) -> int:
        if colon - pos > 1024:
            raise ValueError("key longer than 1024 characters")
        if key == "<<":
            raise ValueError("merge key")
        self.enter(pos, "map")
        line, is_name = self.lines[i], len(self.stack) == 1 and key == "name"
        if is_name and self.names:
            raise ValueError("duplicate top-level name")
        p = skip_spaces(line, colon + 1)
        if p == len(line) or line[p] == "#":
            if is_name:
                raise ValueError("empty name")
            return i + 1
        self.stack[-1][2] = False
        return self.value(i, p, is_name)

    def value(self, i: int, p: int, is_name: bool) -> int:
        line = self.lines[i]
        ch, after = line[p], line[p + 1 : p + 2]
        if ch in "&!*":
            raise ValueError("anchor, tag or alias")
        if ch in "'\"":
            row, end = self.quoted(i, p)
            if is_name:
                if row != i:
                    raise ValueError("multi-line name")
                self.names.append(unquote(line[p:end]))
            return self.end_of_node(row, end)
        if is_name and not plain_start(ch, after):
            raise ValueError("name is not a plain or quoted scalar")
        if ch in "[{":
            return self.end_of_node(*self.flow(i, p))
        if ch in "|>":
            return self.block(i, p)
        if not plain_start(ch, after):
            raise ValueError(f"unexpected {ch!r}")
        end, stop = plain_scalar(line, p)
        if stop < len(line) and line[stop] == ":":
            raise ValueError("mapping value inside a plain scalar")
        text = line[p:end]
        if text in ("=", "<<"):
            raise ValueError(f"{text!r} does not load")  # SafeLoader has no constructor for these
        if is_name:
            if any(text[0] in first and pattern.match(text) for pattern, first in NOT_STRINGS):
                raise ValueError(f"name {text!r} does not load as a string")
            self.names.append(text)
        if stop == len(line):
            self.plain = (self.indent() + 1, is_name)
        return i + 1

    def end_of_node(self, row: int, end: int) -> int:
        line = self.lines[row]
        k = skip_spaces(line, end)
        if k < len(line) and line[k] != "#":
            raise ValueError(f"unexpected {line[k]!r} after a value")
        return row + 1

    def quoted(self, i: int, pos: int) -> tuple[int, int]:
        """(row, column) just past the quoted scalar that opens at row i, column pos."""
        text, k = self.text, self.starts[i] + pos
        quote = text[k]
        k += 1
        while k < len(text):
            if text[k] == quote:
                if quote == "'" and text.startswith("'", k + 1):
                    k += 2
                    continue
                row = bisect.bisect_right(self.starts, k) - 1
                return row, k + 1 - self.starts[row]
            k = escape(text, k)[1] if quote == '"' and text[k] == "\\" else k + 1
        raise ValueError("unterminated quoted scalar")

    def flow(self, i: int, k: int) -> tuple[int, int]:
        """(row, column) just past the flow collection that opens at row i, column k. Inside it
        PyYAML ignores indentation, and a plain scalar that reaches the end of a line goes on
        with the next one unless that starts with a comment."""
        depth, plain = 0, False
        while i < len(self.lines):
            line = self.lines[i]
            if plain:
                k = skip_spaces(line, 0)
                if k < len(line) and line[k] != "#":
                    k = plain_scalar(line, k, flow=True)[1]
                plain = k == len(line)
            while k < len(line) and not plain:
                ch = line[k]
                if ch == "#":
                    break  # a comment to the end of the line
                if ch in "'\"":
                    i, k = self.quoted(i, k)
                    line = self.lines[i]
                    continue
                if ch in "[{]}":
                    depth += 1 if ch in "[{" else -1
                    if not depth:
                        return i, k + 1
                elif ch not in " ,?:":  # in flow context, ? and : are always indicators
                    if ch in "\t&!*|>%@`" or (ch == "-" and line[k + 1 : k + 2] in ("", " ")):
                        raise ValueError(f"unexpected {ch!r} in a flow collection")
                    k = plain_scalar(line, k, flow=True)[1]
                    plain = k == len(line)
                    continue
                k += 1
            i, k = i + 1, 0
        raise ValueError("unterminated flow collection")

    def block(self, i: int, p: int) -> int:
        """The row after a block scalar whose header is at row i, column p (PyYAML's indentation)."""
        lines = self.lines
        header = BLOCK_HEADER.fullmatch(lines[i], p)
        if not header:
            raise ValueError("invalid block scalar header")
        indent, step, j = max(self.indent() + 1, 1), header.group(1) or header.group(2), i + 1
        if step:
            indent += int(step) - 1
        else:  # the widest leading blank line or the first content line sets it
            while j < len(lines) and not lines[j].strip(" "):
                indent, j = max(indent, len(lines[j])), j + 1
            if j < len(lines):
                indent = max(indent, len(lines[j]) - len(lines[j].lstrip(" ")))
        j = i + 1
        while j < len(lines) and (not lines[j].strip(" ") or len(lines[j]) - len(lines[j].lstrip(" ")) >= indent):
            j += 1
        return j


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


# --- Hidden copies

# Codex's bundled system skills (codex-cli 0.165): the sync gives a library skill with such an
# ID a source-qualified one, since a plain `$ID` would be ambiguous.
CODEX_SYSTEM_SKILLS = frozenset({"imagegen", "openai-docs", "review-agent", "skill-creator", "skill-installer"})
# A hidden skill still runs on /ID and $ID: Claude Code leaves one whose frontmatter sets
# disable-model-invocation out of the model's listing (the last duplicate key wins, so every
# top-level line of it is replaced), Codex one whose agents/openai.yaml sets
# policy.allow_implicit_invocation false. The sync rejects skills these line edits cannot hide.
HIDDEN_KEY = "disable-model-invocation"
HIDDEN_KEY_LINE = re.compile(r"""(["']?)disable-model-invocation\1[ \t]*:""")
HIDDEN_PLAIN_LINE = re.compile(r"disable-model-invocation:[ \t]+(?:true|True|TRUE|false|False|FALSE)[ \t]*(?:#.*)?")
POLICY_FILE = "agents/openai.yaml"
POLICY_KEY_LINE = re.compile(r"""(["']?)policy\1[ \t]*:""")
POLICY_BLOCK_LINE = re.compile(r"policy:[ \t]*(?:#.*)?")
IMPLICIT_KEY_LINE = re.compile(r"""(["']?)allow_implicit_invocation\1[ \t]*:""")
IMPLICIT_ONE_LINE = re.compile(r"allow_implicit_invocation:[ \t]+[^ \t#].*")
IMPLICIT_FALSE_LINE = re.compile(r"allow_implicit_invocation:[ \t]+false[ \t]*(?:#.*)?")
UTF8_BOM = b"\xef\xbb\xbf"


def split_text(data: bytes, label: str) -> tuple[bytes, list[str], str]:
    """(BOM, lines split at LF with any CR kept, the CR to end a new line with) of UTF-8 bytes."""
    bom = UTF8_BOM if data.startswith(UTF8_BOM) else b""
    try:
        lines = data[len(bom) :].decode("utf-8").split("\n")
    except UnicodeDecodeError as e:
        raise InstallError(f"Cannot hide {label}: not UTF-8 ({e})") from e
    return bom, lines, "\r" if lines[0].endswith("\r") else ""


def frontmatter_end(lines: list[str], label: str) -> int:
    """The index of the `---` line that closes the frontmatter opening the file."""
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r").strip() == "---"), None)
    if lines[0].rstrip("\r").strip() != "---" or end is None:
        raise InstallError(f"Invalid frontmatter at {label}: missing frontmatter")
    return end


def hidden_skill_md(data: bytes, label: str) -> bytes:
    """SKILL.md with every top-level disable-model-invocation line replaced by one `true` line
    right after the opening `---`; BOM and line endings stay. A line of the key that is not a
    plain one-line boolean raises InstallError."""
    bom, lines, cr = split_text(data, label)
    end = frontmatter_end(lines, label)
    kept = []
    for line in lines[1:end]:
        if not HIDDEN_KEY_LINE.match(line):
            kept.append(line)
        elif not HIDDEN_PLAIN_LINE.fullmatch(line.rstrip("\r")):
            raise InstallError(f"Cannot hide {label}: top-level {HIDDEN_KEY} is not a plain one-line true or false")
    out = [lines[0], f"{HIDDEN_KEY}: true{cr}", *kept, *lines[end:]]
    return bom + "\n".join(out).encode("utf-8")


def hidden_policy(data: bytes | None, label: str) -> bytes:
    """agents/openai.yaml with policy.allow_implicit_invocation false: the file or a `policy:`
    block is added if missing, else the key is set inside the block-style mapping. BOM and line
    endings stay; any other shape raises InstallError."""
    if data is None:
        return b"policy:\n  allow_implicit_invocation: false\n"
    bom, lines, cr = split_text(data, label)
    text = [line.rstrip("\r") for line in lines]

    def refuse(reason: str) -> InstallError:
        return InstallError(f"Cannot hide {label}: {POLICY_FILE} {reason}")

    found = [i for i, line in enumerate(text) if POLICY_KEY_LINE.match(line)]
    if len(found) > 1:
        raise refuse("has more than one top-level policy key")
    if not found:
        tail = f"{cr}\n" if lines[-1] else ""
        block = f"{tail}policy:{cr}\n  allow_implicit_invocation: false{cr}\n"
        return bom + ("\n".join(lines) + block).encode("utf-8")
    p = found[0]
    if not POLICY_BLOCK_LINE.fullmatch(text[p]):
        raise refuse("has a policy that is not a block-style mapping")
    end = next((j for j in range(p + 1, len(text)) if text[j][:1] not in ("", " ", "#")), len(text))
    entries = [j for j in range(p + 1, end) if text[j].strip() and not text[j].lstrip(" ").startswith("#")]
    if not entries or text[entries[0]].lstrip(" ").startswith("-"):
        raise refuse("has a policy that is not a block-style mapping")
    indent = len(text[entries[0]]) - len(text[entries[0]].lstrip(" "))
    children = [j for j in entries if len(text[j]) - len(text[j].lstrip(" ")) <= indent]
    keys = [j for j in children if IMPLICIT_KEY_LINE.match(text[j], indent)]
    if len(keys) > 1:
        raise refuse("sets policy.allow_implicit_invocation more than once")
    line = " " * indent + f"allow_implicit_invocation: false{cr}"
    if not keys:
        lines.insert(p + 1, line)
        return bom + "\n".join(lines).encode("utf-8")
    k = keys[0]
    following = next((j for j in children if j > k), end)
    if not IMPLICIT_ONE_LINE.fullmatch(text[k], indent) or any(j in entries for j in range(k + 1, following)):
        raise refuse("has a policy.allow_implicit_invocation that is not a plain one-line value")
    if IMPLICIT_FALSE_LINE.fullmatch(text[k], indent):
        return data
    lines[k] = line
    return bom + "\n".join(lines).encode("utf-8")


# --- Client copies

# A copy depends only on the library tree, the client and the visibility. Plugin manifest
# folders go (Claude lists their commands; Codex names the skill `plugin:ID`). Codex matches $NAME
# against the frontmatter name, which 500+ skills share, so each Codex copy is named after its
# ID and a nested SKILL.md gets a unique name and the policy. Hidden Codex copies also get the
# Claude key, for Cursor.
PLUGIN_DIRS = frozenset({".claude-plugin", ".codex-plugin", ".cursor-plugin"})
NAME_KEY_LINE = re.compile(r"""(["']?)name\1[ \t]*:(?=[ \t\r]|$)""")


def plugin_path(rel: str) -> bool:
    return any(part in PLUGIN_DIRS for part in rel.split("/"))


def renamed_skill_md(data: bytes, name: str, label: str) -> bytes:
    """SKILL.md whose one top-level name line (added if missing) is `name: "NAME"`; the result
    must read as NAME without PyYAML, or InstallError is raised."""

    def reads_as_name(text: bytes) -> bool:
        try:
            return frontmatter_name(text, label) == name
        except InstallError:
            return False

    bom, lines, cr = split_text(data, label)
    if reads_as_name(data[len(bom) :]):
        return data
    found = [i for i in range(1, frontmatter_end(lines, label)) if NAME_KEY_LINE.match(lines[i])]
    if len(found) > 1:
        raise InstallError(f"Cannot rename {label}: more than one top-level name")
    line = f"name: {json.dumps(name)}{cr}"
    if found:
        lines[found[0]] = line
    else:
        lines.insert(1, line)
    out = "\n".join(lines).encode("utf-8")
    if not reads_as_name(out):
        raise InstallError(f"Cannot rename {label}: its name is not a one-line top-level key")
    return bom + out


def nested_name(skill_id: str, rel: str) -> str:
    """The Codex name of a SKILL.md below the top level: ID--sub-path, at most 64 characters."""
    name = f"{skill_id}--" + re.sub(r"[^A-Za-z0-9_-]+", "-", rel.rsplit("/", 1)[0])
    return name if len(name) <= 64 else name[:53] + "-" + hashlib.sha256(name.encode()).hexdigest()[:10]


def copy_edits(client: str, skill_id: str, invocation: str, listing: dict, read) -> dict:
    """rel -> bytes the client's copy replaces or adds; read(rel) gives the library's bytes. A
    local tree may link: an edit of a link, or below a linked folder, would write outside the copy."""
    edits, hide = {}, invocation == "manual"
    if client == "claude" and not hide:
        return edits  # read nothing
    for rel in sorted(listing):
        top = rel == "SKILL.md"
        if rel.rsplit("/", 1)[-1] != "SKILL.md" or plugin_path(rel) or client == "claude" and not top:
            continue
        label = f"{skill_id}/{rel}"
        data = original = read(rel)
        if top and hide:
            data = hidden_skill_md(data, label)
        if client == "codex":
            data = renamed_skill_md(data, skill_id if top else nested_name(skill_id, rel), label)
            policy = rel[: -len("SKILL.md")] + POLICY_FILE
            old = read(policy) if (hide or not top) and policy in listing else None
            new = hidden_policy(old, label) if hide or not top else None
            if new != old:
                edits[policy] = new
        if data != original:
            edits[rel] = data
    for rel in edits:
        parts = rel.split("/")
        if any(listing.get("/".join(parts[:i]), "0")[0] == "120000" for i in range(1, len(parts) + 1)):
            raise InstallError(f"Cannot edit {skill_id}/{rel}: it is or lies below a symbolic link")
    return edits


def derived_listing(listing: dict, edits: dict) -> dict:
    """The git listing of a client's copy: plugin manifest folders dropped, edits applied."""
    out = {rel: entry for rel, entry in listing.items() if not plugin_path(rel)}
    out.update({rel: (listing.get(rel, ("100644",))[0], blob_id(data)) for rel, data in edits.items()})
    return out


def apply_edits(target: Path, edits: dict):
    """Turn a verified copy of the library tree into the client's copy (see derived_listing)."""
    for root, dirs, _ in os.walk(target):
        for name in [d for d in dirs if d in PLUGIN_DIRS]:
            path = Path(root) / name
            path.unlink() if is_link(path) else rmtree(path)
            dirs.remove(name)
    for rel, data in sorted(edits.items()):
        path = target.joinpath(*rel.split("/"))
        if is_link(path) or any(map(is_link, path.parents[: rel.count("/")])):
            raise InstallError(f"Refusing to write through a link: {display(path)}")
        fresh = not path.exists()
        if not path.parent.exists():
            path.parent.mkdir(parents=True)
            if not WINDOWS:
                path.parent.chmod(DIR_MODE)
        path.write_bytes(data)
        if fresh and not WINDOWS:
            path.chmod(FILE_MODES["100644"])


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
    atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def atomic_write(path: Path, data: bytes, mode: int | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temp.write_bytes(data)
        if mode is not None and not WINDOWS:
            temp.chmod(mode)
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# --- Git


def git_env() -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_") or key in GIT_ENV_KEEP}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_LFS_SKIP_SMUDGE="1", GIT_ATTR_NOSYSTEM="1")
    env["LC_ALL"] = "C"
    return env


def minimum_git() -> tuple[tuple, str]:
    version = SPARSE_INDEX_GIT if WINDOWS else MIN_GIT
    return version, ".".join(map(str, version)) + (" (on Windows)" if WINDOWS else "")


class Git:
    def __init__(self):
        minimum, wanted = minimum_git()
        exe = shutil.which("git")
        if not exe:
            raise InstallError(f"git {wanted} or newer is required; git was not found on PATH")
        self.exe, self.env = exe, git_env()
        found = self.text(None, "--version")
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", found)
        self.version = tuple(int(part or 0) for part in match.groups()) if match else (0, 0, 0)
        if self.version < minimum:
            raise InstallError(f"git {wanted} or newer is required; found {found or 'an unknown version'}")
        if not {"GIT_SSH", "GIT_SSH_COMMAND"} & set(self.env) and not self.text(
            None, "config", "--get", "core.sshCommand", check=False
        ):
            self.env["GIT_SSH_COMMAND"] = SSH_COMMAND

    def command(self, repo: Path | None, *args: str) -> list[str]:
        command = [self.exe]
        for item in GIT_CONFIG:
            command += ["-c", item]
        if repo is not None:
            # Never discover a repository: a broken clone must fail, not fall back to an enclosing one.
            command += ["-C", display(repo), f"--git-dir={display(repo / '.git')}", f"--work-tree={display(repo)}"]
        return [*command, *args]

    def run(self, repo: Path | None, *args: str, stdin: str = "", check: bool = True) -> bytes:
        result = subprocess.run(
            self.command(repo, *args),
            input=stdin.encode(),
            capture_output=True,
            env=self.env,
            cwd=tempfile.gettempdir() if repo is None else None,
        )
        if check and result.returncode:
            lines = [line for line in result.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
            detail = lines[-1].strip() if lines else f"exit status {result.returncode}"
            raise GitError(f"git {args[0]} failed: {detail}", "\n".join(lines))
        return result.stdout

    def text(self, repo: Path | None, *args: str, check: bool = True) -> str:
        return self.run(repo, *args, check=check).decode("utf-8", "replace").strip()


def valid_index_entry(info) -> bool:
    return isinstance(info, dict) and isinstance(info.get("name"), str) and bool(info["name"].strip())


def is_library_clone(path: Path) -> bool:
    return plain_dir(path) and (path / ".git" / MARKER).is_file()


# --- Libraries


class Library:
    """The complete library index, plus skill content on demand."""

    kind = ""

    def __init__(self):
        self.skills: dict = {}
        self.skipped: dict = {}  # source ID -> why it cannot be installed here
        self.revision = "unversioned"
        self._derived: dict = {}

    def screen(self, ids: list[str], kinds: dict, indexed: set | None = None, links: bool = False) -> list[str]:
        """The IDs installable on every platform; the others are skipped with a warning."""
        colliding = case_collisions(ids, indexed or frozenset())
        accepted = []
        for skill_id in ids:
            problems = [
                p for p in skill_problems(skill_id, kinds[skill_id]) if not (links and p.endswith(": symbolic link"))
            ]
            if skill_id in colliding:
                problems.insert(0, colliding[skill_id])
            if indexed is not None and skill_id not in indexed:
                problems.insert(0, f"no valid entry in {INDEX}")
            if problems:
                self.skipped[skill_id] = "; ".join(problems[:3])
                warn(f"skipping library entry {skill_id}: {self.skipped[skill_id]}")
            else:
                accepted.append(skill_id)
        return accepted

    def listing(self, skill_id: str) -> dict:
        raise NotImplementedError

    def read(self, skill_id: str, rel: str) -> bytes:
        raise NotImplementedError

    def derived(self, client: str, skill_id: str, invocation: str, local: Path | None = None) -> tuple[dict, dict]:
        """(listing, edits) of a client's copy (see copy_edits); InstallError if it cannot be made.
        A file of `local`, an installed copy, holding the library's bytes is read there: in a
        blobless clone each blob read alone is a fetch of its own."""
        key = (client, skill_id, invocation)
        if key not in self._derived:
            listing = self.listing(skill_id)

            def read(rel):
                p = local and local.joinpath(*rel.split("/"))
                if p and not is_link(p) and p.is_file() and blob_id(data := p.read_bytes()) == listing[rel][1]:
                    return data
                return self.read(skill_id, rel)

            edits = copy_edits(client, skill_id, invocation, listing, read)
            self._derived[key] = derived_listing(listing, edits), edits
        return self._derived[key]

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

    def skill_name(self, data: bytes, label: str) -> str:
        """A prepared copy's frontmatter name, read the way this library read its own names."""
        return frontmatter_name(data, label)


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
                env=git_env(),
            )
            if result.returncode == 0:
                self.revision = result.stdout.strip()
        self._fingerprints = {}
        ids = skill_ids(source)
        self._listings = {skill_id: local_listing(source / skill_id) for skill_id in ids}
        kinds = {
            i: {rel: "link" if m == "120000" else "file" for rel, (m, _) in self._listings[i].items()} for i in ids
        }
        for skill_id in self.screen(ids, kinds, links=True):  # a local tree may link
            listing = self._listings[skill_id]
            fm = metadata((source / skill_id / "SKILL.md").read_bytes(), skill_id)
            self.skills[skill_id] = {
                "name": fm["name"],
                "description": fm.get("description", ""),
                "tree": tree_id(listing),
                "origins": origins(provenance, skill_id, self.revision),
            }

    def listing(self, skill_id):
        return self._listings[skill_id]

    def read(self, skill_id, rel):
        return (self.source / skill_id).joinpath(*rel.split("/")).read_bytes()

    def adoptable(self, skill_id, path):
        # Legacy adoption requires an exact whole-tree hash, never a name alone.
        if skill_id not in self._fingerprints:
            self._fingerprints[skill_id] = fingerprint(self.source / skill_id)
        return fingerprint(path) == self._fingerprints[skill_id]

    def materialize(self, skill_id, target):
        shutil.copytree(self.source / skill_id, target, symlinks=True)

    def skill_name(self, data, label):
        return metadata(data, label)["name"]  # a local tree's names come from PyYAML

    def router_command(self):
        helper = globals().get("__file__")
        helper = display(Path(helper).resolve()) if helper else "install_skills.py"
        return helper, ["--source", display(self.source)]

    def describe(self):
        return {"kind": self.kind, "path": display(self.source), "revision": self.revision}


class GitLibrary(Library):
    """One commit of the blobless library clone; a worktree is needed only to install."""

    kind = "git"

    def __init__(self, git: Git, repo: Path, commit: str, worktree: bool):
        super().__init__()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise InstallError(f"Unsupported library object format at {display(repo)} (SHA-1 is required)")
        self.git, self.repo, self.worktree, self.revision = git, repo, worktree, commit
        self._prepared, self._cat = False, None
        trees, files, kinds = {}, defaultdict(dict), defaultdict(dict)
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
            elif kind != "tree":
                rel = "/".join(parts[2:])
                files[parts[1]][rel] = (mode, oid)
                if mode in FILE_MODES:
                    kinds[parts[1]][rel] = "file"
                else:
                    kinds[parts[1]][rel] = {"120000": "link", "160000": "submodule"}.get(mode, f"mode {mode}")
        index = self._json(INDEX, required=True)
        if index.get("schema") != SCHEMA or not isinstance(index.get("skills"), dict):
            raise InstallError(f"Unsupported library index {INDEX} at {commit[:12]}")
        provenance = self._json(PROVENANCE, required=False)
        ids = sorted(i for i in trees if "SKILL.md" in files.get(i, {}))
        indexed = {i for i in ids if valid_index_entry(index["skills"].get(i))}
        for skill_id in self.screen(ids, kinds, indexed):
            info = index["skills"][skill_id]
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

    def read(self, skill_id, rel):
        """A file's bytes from one long-lived `git cat-file --batch` (a missing blob is fetched)."""
        oid = self._files[skill_id][rel][1]
        if self._cat is None:
            self._cat = subprocess.Popen(
                self.git.command(self.repo, "cat-file", "--batch"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self.git.env,
            )
        self._cat.stdin.write(oid.encode() + b"\n")
        self._cat.stdin.flush()
        header = self._cat.stdout.readline().split()
        if header[1:2] != [b"blob"]:
            raise InstallError(f"Library object {oid} ({skill_id}/{rel}) is not available")
        return self._cat.stdout.read(int(header[2]) + 1)[:-1]

    def adoptable(self, skill_id, path):
        return exact_tree(self._files[skill_id], path)

    def prepare(self, ids):
        if not ids:
            return
        if not self.worktree:
            raise InstallError("Internal error: preparing content from a read-only library")
        self._prepared = True
        self._sparse(["scripts", *(f"skills/{skill_id}" for skill_id in sorted(set(ids)))])

    def release(self):
        if self._cat is not None:
            self._cat.stdin.close()
            self._cat.wait()
            self._cat = None
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
        if not same_tree(expected, target):
            raise InstallError(f"Checked-out content differs from the library tree: {skill_id}")

    def router_command(self):
        return display(self.repo / "scripts" / "install_skills.py"), []

    def describe(self):
        return {"kind": self.kind, "path": display(self.repo), "revision": self.revision}


def retried(action):
    """A failed transfer that is not corruption (a dropped or stalled link) is retried once."""
    try:
        return action()
    except GitError as exc:
        if corrupted(exc):
            raise
        warn(f"{exc}; retrying once")
        time.sleep(1)
        return action()


def create_clone(git: Git, data: Path, url: str, branch: str):
    """Clone into a temporary sibling, check out only scripts/ and root files, then rename into place."""
    data.mkdir(parents=True, exist_ok=True)
    temp, repo = data / f".{CLONE}.tmp-{uuid.uuid4().hex}", data / CLONE

    def clone():
        if os.path.lexists(temp):
            rmtree(temp)
        args = ["--filter=blob:none", "--no-checkout", "--single-branch", "--branch", branch, "--", url]
        git.run(None, "clone", "--quiet", *args, display(temp))

    try:
        retried(clone)
        (temp / ".git" / MARKER).write_bytes(b"awesome-skills library clone, managed by install_skills.py\n")
        index = ["--sparse-index"] if git.version >= SPARSE_INDEX_GIT else []
        git.run(temp, "sparse-checkout", "init", "--cone", *index)
        git.run(temp, "sparse-checkout", "set", "--stdin", stdin="scripts\n")
        tip = git.text(temp, "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}")
        git.run(temp, "checkout", "--quiet", "--force", "--detach", tip)
        git.run(temp, "update-ref", "-d", f"refs/heads/{branch}", check=False)
        move(temp, repo)
    except BaseException:
        if os.path.lexists(temp):
            rmtree(temp)
        raise
    for older in sorted(data.glob(f"{CLONE}.broken-*"))[:-1]:  # only now that a clone works again
        if plain_dir(older):
            rmtree(older)


def sweep_clone_leftovers(data: Path):
    """Under the lock nothing else uses the clone: drop interrupted clones and stale git locks."""
    if plain_dir(data):
        for leftover in data.glob(f".{CLONE}.tmp-*"):
            if plain_dir(leftover):
                rmtree(leftover)
    git_dir = data / CLONE / ".git"
    if is_library_clone(data / CLONE):
        stale = [*git_dir.glob("*.lock"), *git_dir.glob("info/*.lock"), *(git_dir / "refs").rglob("*.lock")]
        for lock in stale:
            lock.unlink(missing_ok=True)
        if stale:
            warn(f"removed {len(stale)} stale git lock file(s) in {display(git_dir)}")


def heal_clone(git: Git, data: Path, url: str, branch: str, error: GitError) -> bool:
    """A corrupted clone is moved aside and cloned again once, if the remote is reachable."""
    if not corrupted(error):
        return False
    try:
        remote_tip(git, url, branch)
    except GitError:
        return False  # a fresh clone would not get through either
    broken = data / f"{CLONE}.broken-{time.time_ns():020d}"
    move(data / CLONE, broken)
    warn(f"library clone is damaged ({error}); moved it to {display(broken)} and cloning again")
    create_clone(git, data, url, branch)
    return True


def refresh_clone(git: Git, data: Path, url: str, branch: str, checkout: bool) -> tuple[GitLibrary, bool]:
    repo = data / CLONE
    if git.text(repo, "config", "--get", "remote.origin.url", check=False) != url:
        git.run(repo, "remote", "set-url", "origin", url)
    ref = f"refs/remotes/origin/{branch}"
    fetch = [
        "--quiet",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-auto-maintenance",
        "origin",
        f"+refs/heads/{branch}:{ref}",
    ]
    retried(lambda: git.run(repo, "fetch", *fetch))
    tip = git.text(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    moved = git.text(repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False) != tip
    if moved and checkout:
        git.run(repo, "checkout", "--quiet", "--force", "--detach", tip)
    return GitLibrary(git, repo, tip, worktree=checkout), moved


def update_clone(git: Git, data: Path, url: str, branch: str) -> tuple[GitLibrary, bool]:
    """Fetch new commits and trees and check out the tip (writes only if it moved). Lock held."""
    repo = data / CLONE
    sweep_clone_leftovers(data)
    if not os.path.lexists(repo):
        create_clone(git, data, url, branch)
        return refresh_clone(git, data, url, branch, checkout=True)[0], True
    if not is_library_clone(repo):
        raise InstallError(f"Not an awesome-skills library clone: {display(repo)}; move it away and rerun")
    try:
        return refresh_clone(git, data, url, branch, checkout=True)
    except GitError as exc:
        if not heal_clone(git, data, url, branch, exc):
            raise
        return refresh_clone(git, data, url, branch, checkout=True)[0], True


def existing_clone(data: Path) -> Path:
    repo = data / CLONE
    if not is_library_clone(repo):
        raise InstallError(
            f"No library clone at {display(repo)} yet; install once first (or use a local checkout's install.sh)"
        )
    return repo


@contextmanager
def open_library(git: Git | None, source: Path | None, data: Path, url: str, branch: str, mode: str, fetch: bool):
    """Mode "apply" updates and checks out the clone, "dry-run" only fetches into it; without
    fetch both plan against its checkout. Lock held."""
    if git is None:
        yield DirLibrary(source)
        return
    moved = False
    if mode == "dry-run" or not fetch:
        repo = existing_clone(data)
        sweep_clone_leftovers(data)
    if not fetch:
        head = git.text(repo, "rev-parse", "--verify", "HEAD^{commit}")
        library = GitLibrary(git, repo, head, worktree=mode == "apply")
    elif mode == "dry-run":
        library = refresh_clone(git, data, url, branch, checkout=False)[0]
    else:
        library, moved = update_clone(git, data, url, branch)
    try:
        yield library
    finally:
        try:
            library.release()
        except InstallError as exc:
            warn(str(exc))
    if moved:
        git.run(data / CLONE, "gc", "--auto", "--quiet", check=False)


def listed_library(git: Git | None, source: Path | None, data: Path) -> Library:
    """--list reads the clone at its last update, offline (missing objects may be fetched lazily)."""
    if git is None:
        return DirLibrary(source)
    repo = existing_clone(data)
    return GitLibrary(git, repo, git.text(repo, "rev-parse", "--verify", "HEAD^{commit}"), worktree=False)


def remote_tip(git: Git, url: str, branch: str) -> str:
    ref = f"refs/heads/{branch}"
    for line in git.text(None, "ls-remote", "--exit-code", url, ref).splitlines():
        oid, _, name = line.partition("\t")
        if name == ref:
            return oid
    return ""


# --- Router and launcher


def launcher_path(data: Path, suffix: str = "") -> Path:
    return data / "bin" / (LAUNCHER + suffix)


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def launcher_call(data: Path) -> str:
    """How a router runs the launcher: a single-quoted PowerShell literal on Windows."""
    if WINDOWS:
        return "& " + ps_quote(display(launcher_path(data, ".ps1")))
    return shlex.quote(display(launcher_path(data)))


def launchers(data: Path, state: Path, library: Library) -> dict:
    """Path -> text of the launchers: this install's installer with its storage, saved
    destinations and remote unless set, or (`search ...`) the read-only search."""
    helper, extra = library.router_command()
    search, python = str(Path(helper).with_name("search_skills.py")), sys.executable
    env = {"SKILLS_STATE_DIR": display(state), "SKILLS_DATA_DIR": display(data)}
    for client in ("claude", "codex"):
        saved = read_json(state / f"{client}.json", {})
        for key, variable in (("destination", ""), ("destination2", "2")):
            if saved.get(key):
                env[f"SKILLS_{client.upper()}_DEST{variable}"] = display(saved[key])
    env.update({key: os.environ[key] for key in ("SKILLS_REPOSITORY_URL", "SKILLS_BRANCH") if os.environ.get(key)})
    note = "# Written by the awesome-skills installer on every run; edits are overwritten."
    q = shlex.quote
    sh = ["#!/bin/sh", note, *(f"{k}=${{{k}:-{q(v)}}}\nexport {k}" for k, v in sorted(env.items()))]
    sh.append(
        f'if [ "${{1-}}" = search ]; then\n    shift\n    exec {q(python)} -I -B {q(search)} --state "$SKILLS_STATE_DIR" "$@"\nfi'
    )
    sh.append(f'exec {q(python)} -B {" ".join(map(q, [helper, *extra]))} "$@"')
    files = {launcher_path(data): "\n".join(sh) + "\n"}
    if WINDOWS:
        p = ps_quote
        ps = [note, *(f"if (-not $env:{k}) {{ $env:{k} = {p(v)} }}" for k, v in sorted(env.items()))]
        ps.append(
            f"if ($args.Count -and $args[0] -eq 'search') {{\n    & {p(python)} -I -B {p(search)} --state $env:SKILLS_STATE_DIR @($args | Select-Object -Skip 1)"
        )
        ps.append(
            f"}} else {{\n    & {p(python)} -B {' '.join(map(p, [helper, *extra]))} @args\n}}\nexit $LASTEXITCODE"
        )
        files[launcher_path(data, ".ps1")] = "\ufeff" + "\n".join(ps) + "\n"  # a BOM: Windows PowerShell reads UTF-8
    return files


def write_launchers(data: Path, state: Path, library: Library):
    for path, text in launchers(data, state, library).items():
        no_symlink_ancestors(path)
        if not path.is_file() or path.read_bytes() != text.encode():
            atomic_write(path, text.encode(), 0o755)


def router_info(client: str, call: str) -> dict:
    """The router skill for one client: search the library through the launcher, then use a skill."""
    fence, claude = "powershell" if WINDOWS else "bash", client == "claude"
    owner = "Claude Code but hidden from your skill list" if claude else "Codex but not listed here"
    head = (
        f"---\nname: {ROUTER}\ndescription: Find the right skill among the awesome-skills library, installed for "
        f"{owner} (biology, chemistry, protein design, ML, data, software, writing). Use when no listed skill fits "
        "the task or the user asks which skill to use.\n"
    )
    search = f"""1. Search offline with 1-3 distinctive words (all must match; '-', '_' and spaces are the
   same). It prints at most 12 matches{", each with its SKILL.md path" * (not claude)}; exit status 1 means none:

   ```{fence}
   {call} search --client {client} WORDS
   ```

"""
    show = f"the user runs `{call} --{client}-only --enable ID --no-fetch`"
    if claude:
        body = f"""{head}argument-hint: "[what you need]"
allowed-tools: Bash({call} search *)
---
Request: $ARGUMENTS

Most library skills are hidden from you, and the Skill tool refuses them. If the request is
empty, ask the user what they need.

{search}2. Reply with the 1-5 best IDs the search printed, one line each on why; never guess one.
3. Invoke an ID marked [visible] with the Skill tool. For any other, ask the user to start their
   next message with /ID and the task; do not open its SKILL.md or do its work yourself.
4. To list an ID in every session, {show}; do not run it unasked.
"""
    else:
        body = f"""{head}---
Most library skills are not listed here; all of them are installed and usable.

{search}2. Say in one line which ID you use and why; never guess an ID or a path.
3. Read that SKILL.md completely at the printed path and follow it, resolving relative paths
   from its directory. Tell the user that typing $ID loads it directly.
4. Nothing needs enabling or downloading. To list an ID in every session, {show}.
"""
    entries = {"": ("dir", 0o755, b""), "SKILL.md": ("file", 0o644, body.encode())}
    listing = {"SKILL.md": ("100644", blob_id(body.encode()))}
    return {"entries": entries, "listing": listing, "tree": tree_id(listing)}


def write_tree(entries: dict, target: Path):
    """Write the generated router: relative path -> (kind, mode, bytes), its folder first."""
    for rel, (kind, mode, data) in sorted(entries.items()):
        path = target / rel if rel else target
        path.mkdir(parents=True, exist_ok=True) if kind == "dir" else path.write_bytes(data)
        path.chmod(mode)


# --- Planning


def conflict_groups(skills: dict) -> dict:
    by_name = defaultdict(list)
    for skill_id, info in skills.items():
        by_name[info["name"]].append(skill_id)
    return {name: sorted(ids) for name, ids in sorted(by_name.items()) if len({skills[i]["tree"] for i in ids}) > 1}


def protected(path: Path) -> bool:
    return path.name.startswith(".") or is_link(path)


def valid_entry(entry: str):
    if not isinstance(entry, str) or not entry or entry.startswith(".") or "/" in entry or "\\" in entry:
        raise InstallError(f"Invalid managed entry: {entry!r}")


def valid_hash(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise InstallError(f"Invalid fingerprint: {value!r}")


def valid_tree(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value)):
        raise InstallError(f"Invalid tree id: {value!r}")


def validate_state(value: dict, client: str):
    if not value:
        return
    if value.get("schema") != SCHEMA or value.get("client") != client:
        raise InstallError(f"Unsupported or invalid state: {client}")
    if value.get("selection_version", SELECTION_VERSION) != SELECTION_VERSION:
        raise InstallError(f"Unsupported state selection version: {client}")
    roots = [value.get("destination"), *([value["destination2"]] if "destination2" in value else [])]
    if not all(isinstance(root, str) and Path(root).is_absolute() for root in roots):
        raise InstallError(f"Invalid state destination: {client}")
    for key in ("selection", *(["manual"] if "manual" in value else [])):
        if not isinstance(value.get(key), list) or not all(isinstance(i, str) for i in value[key]):
            raise InstallError(f"Invalid state {key}: {client}")
    if not isinstance(value.get("managed"), dict):
        raise InstallError(f"Invalid ownership manifest: {client}")
    for entry, info in value["managed"].items():  # v1 records have no invocation
        valid_entry(entry)
        if not isinstance(info, dict) or info.get("sha256") is None or info.get("root", 0) not in range(len(roots)):
            raise InstallError(f"Invalid ownership record: {client}:{entry}")
        if info.get("invocation", "auto") not in ("auto", "manual"):
            raise InstallError(f"Invalid ownership record: {client}:{entry}")
        valid_hash(info["sha256"])
        valid_tree(info.get("tree"))


def selection(args, client: str, old: dict, library: Library) -> list[str]:
    """The skills shown to the model: IDs, @library (the router) or @all."""
    known = set(library.skills) | set(library.skipped)
    blocked = sorted(set(args.enable) & set(library.skipped))
    if blocked:
        raise InstallError(f"Cannot enable {blocked}: {'; '.join(library.skipped[i] for i in blocked)}")
    ids = set(stored(old, "selection", client, known) if args.selection is None else args.selection.split(",")) - {""}
    if "@all" in ids and args.disable:
        ids = set(library.skills) | ids - {"@all"}
    ids.update(args.enable)
    unknown_disable = set(args.disable) - known - set(ids) - {"@library", "@all"}
    if unknown_disable:
        raise InstallError(f"Unknown source IDs to disable: {sorted(unknown_disable)}")
    ids.difference_update(args.disable)
    unknown = ids - known - {"@library", "@all"}
    if unknown:
        raise InstallError(f"Unknown source IDs: {sorted(unknown)} (use --list --search)")
    return sorted(ids)


def manual_set(args, client: str, old: dict, library: Library) -> list[str]:
    """The skills installed but hidden from the model, unless shown: @all, IDs, or none."""
    known = set(library.skills) | set(library.skipped)
    ids = set(stored(old, "manual", client, known) if args.manual is None else args.manual.split(",")) - {""}
    unknown = ids - known - {"@all"}
    if unknown:
        raise InstallError(f"Unknown source IDs: {sorted(unknown)} (use --list --search)")
    return sorted(ids)


def stored(old: dict, key: str, client: str, known: set) -> list[str]:
    """A saved set without the IDs the library no longer has (renamed or removed upstream)."""
    ids = old.get(key, ["@library"] if key == "selection" else ["@all"])
    gone = sorted(set(ids) - known - {"@all", "@library"})
    if gone:
        warn(f"{client}: dropping saved IDs that left the library (see --list --search): {', '.join(gone)}")
    return [i for i in ids if i not in gone]


def desired_entries(client: str, visible: list, manual: list, library: Library, router: dict) -> tuple:
    """(entry -> record, name conflicts, entries asked for by name) of one client's install."""
    reserved = ({ROUTER} if "@library" in visible else set()) | (CODEX_SYSTEM_SKILLS if client == "codex" else set())
    named = (set(visible) | set(manual)) - {"@all", "@library"}
    clashes = sorted(i for i in named if i.casefold() in reserved)
    if clashes:
        raise InstallError(f"Source ID collides with reserved library entry: {', '.join(clashes)}")
    every = {i for i in library.skills if i.casefold() not in reserved}
    installed = every if "@all" in visible or "@all" in manual else named & set(library.skills)
    shown = every if "@all" in visible else set(visible)
    desired = {}
    for skill_id in sorted(installed):
        info = dict(library.skills[skill_id], source_ids=[skill_id])
        info["invocation"] = "auto" if skill_id in shown else "manual"
        if client == "codex":
            info["name"] = skill_id  # every Codex copy is renamed to its ID, so names never collide
        desired[skill_id] = info
    if "@library" in visible:
        origin = {"repository": REPOSITORY, "path": "scripts/install_skills.py"}
        desired[ROUTER] = {"name": ROUTER, "tree": router["tree"], "source_ids": ["@library"], "origins": [origin]}
        desired[ROUTER]["invocation"] = "auto"
        named.add(ROUTER)
    # Claude keeps every variant: same-name skills differ only in their /name alias.
    return desired, conflict_groups(desired) if client == "claude" else {}, named


def placement(skill_id: str) -> int:
    """The Codex root of a new copy: sha256(ID) mod 2."""
    return int.from_bytes(hashlib.sha256(skill_id.encode()).digest(), "big") % 2


def matches(client: str, want: dict, library: Library, router: dict, path: Path) -> bool:
    """The directory holds the client's copy (paths, bytes, links and executable bits)."""
    try:
        if want["source_ids"] == ["@library"]:
            return same_tree(router["listing"], path)
        return same_tree(library.derived(client, want["source_ids"][0], want["invocation"], path)[0], path)
    except InstallError:
        return False  # the copy cannot be made; preparing it reports why


def adoptable(client: str, want: dict, library: Library, path: Path) -> bool:
    """An unmanaged directory is claimed only as an exact client copy, or as an exact library tree
    (which is then copied again in the client's form)."""
    skill_id = want["source_ids"][0]
    if skill_id not in library.skills:
        return False
    try:
        if exact_tree(library.derived(client, skill_id, want["invocation"], path)[0], path):
            return True
    except InstallError:
        pass
    return library.adoptable(skill_id, path)


def kept_entry(entry: str, reason: str = "protected, modified, or unproven ownership", **where) -> dict:
    return {"entry": entry, "reason": reason, **where}


def roots_of(item: dict) -> list[Path]:
    """A client's skills roots in a plan or journal: Codex has a second one."""
    return [Path(item[key]) for key in ("destination", "destination2") if item.get(key)]


def target_of(item: dict, action: dict) -> Path:
    return roots_of(item)[action.get("root", 0)] / action["entry"]


def slot(client: str, action: dict) -> str:
    """The backup directory of an action's root."""
    return client + ("2" if action.get("root") else "")


def plan_entries(client, roots, managed, desired, library, router, named) -> tuple[list, list, dict]:
    actions, kept, new_managed = [], [], {}
    for index, dest in enumerate(roots):
        where = {"root": index} if index else {}
        wanted = {e: w for e, w in desired.items() if w.get("root", 0) == index}
        records = {e: r for e, r in managed.items() if r.get("root", 0) == index}
        existing = {p.name for p in dest.iterdir()} if dest.exists() else set()
        for entry in sorted(existing | set(wanted) | set(records)):
            target, want, rec = dest / entry, wanted.get(entry), records.get(entry)
            present = entry in existing
            if want and rec and present and plain_dir(target) and all(rec.get(k) == want.get(k) for k in SHORTCUT):
                # Unchanged since this installer recorded it: a cheap existence check, no hashing.
                new_managed[entry] = dict(want, sha256=rec["sha256"])
                continue
            if rec and entry in library.skipped:
                new_managed[entry] = rec  # frozen: never updated or removed while the entry is skipped
                kept.append(kept_entry(entry, f"library entry skipped: {library.skipped[entry]}", **where))
                continue
            if present and not want and not rec:
                # Never hashed, claimed or removed, even when identical to a library skill.
                kept.append(kept_entry(entry, "not installed by awesome-skills", **where))
                continue
            current = fingerprint(target) if present else None
            owned = False
            if current is not None and not protected(target):
                owned = current == rec["sha256"] if rec else bool(want) and adoptable(client, want, library, target)
            if current is not None and not owned:
                kept.append(kept_entry(entry, **where))
                if rec:
                    # Retain the last installed fingerprint so future updates keep
                    # recognizing the edited copy, including after deselection.
                    new_managed[entry] = rec
                if want and not rec and client == "codex" and entry in named:
                    if not matches(client, want, library, router, target):
                        raise InstallError(f"Cannot install {client}:{entry}: preserved destination differs: {target}")
                continue
            if want:
                if current is not None and matches(client, want, library, router, target):
                    new_managed[entry] = dict(want, sha256=current)  # identical content: record, do not copy
                else:
                    new_managed[entry] = dict(want, sha256=None)  # filled in once the copy is prepared
                    source = {"source": want["source_ids"][0], "tree": want["tree"]}
                    actions.append({"entry": entry, "before": current, "after": None, **source, **where})
            elif owned:
                actions.append({"entry": entry, "before": current, "after": None, **where})
    return actions, kept, new_managed


def external_skills(client: str, roots: list, kept: list, home: Path) -> dict:
    """Path -> frontmatter name of preserved skills (even symlinks), and for Codex of everything
    in ~/.agents/skills unless that is one of its roots."""
    paths = [roots[item.get("root", 0)] / item["entry"] for item in kept]
    agents = home / ".agents/skills"
    if client == "codex" and agents.is_dir() and not any(r.is_dir() and os.path.samefile(r, agents) for r in roots):
        paths += list(agents.iterdir())
    external = {}
    for directory in paths:
        p = directory / "SKILL.md"
        if p.is_file():
            try:
                external[directory] = frontmatter_name(p.read_bytes(), display(p))
            except InstallError:
                pass
    return external


def external_conflicts(external: dict) -> dict:
    by_name = defaultdict(list)
    for path, name in external.items():
        by_name[name].append(path)
    groups = {}
    for name, paths in sorted(by_name.items()):
        if len(paths) > 1 and len({tree_id(local_listing(p)) for p in paths}) > 1:
            groups[name] = sorted(map(display, paths))
    return groups


def unclaim(plan: dict, entry: str, info: dict, managed: dict, reason: str):
    """Leave a Codex name to a preserved skill (two make `$name` inject neither): our unmodified
    copy goes, a modified one stays."""
    where = {"root": 1} if info.get("root") else {}
    target, rec = roots_of(plan)[info.get("root", 0)] / entry, managed.get(entry)
    current = fingerprint(target)
    plan["actions"] = [a for a in plan["actions"] if a["entry"] != entry]
    plan["state"]["managed"].pop(entry, None)
    if current is not None and rec and current == rec["sha256"] and not protected(target):
        plan["actions"].append({"entry": entry, "before": current, "after": None, **where})
    elif current is not None and rec:
        plan["state"]["managed"][entry] = rec  # a modified copy found through the shortcut stays preserved
    plan["preserved"].append(kept_entry(entry, reason, **where))


def plan_client(client, roots, old, base, visible, manual, library, router, home) -> dict:
    """Plan one client from its state `base` (old, or the migrated form of old)."""
    keys = ("destination", "destination2")
    managed = {
        entry: rec
        for entry, rec in base.get("managed", {}).items()
        if rec.get("root", 0) < len(roots) and base.get(keys[rec.get("root", 0)]) == str(roots[rec.get("root", 0)])
    }
    desired, conflicts, named = desired_entries(client, visible, manual, library, router)
    for entry, want in list(desired.items()):  # a managed copy keeps its root; a new Codex copy goes by its ID
        rec = managed.get(entry)
        if rec.get("root") if rec else client == "codex" and entry != ROUTER and placement(entry):
            if len(roots) > 1:
                want["root"] = 1
            elif entry not in named:
                del desired[entry]  # no usable second root (see resolve_clients)
    actions, kept, new_managed = plan_entries(client, roots, managed, desired, library, router, named)
    new = {"schema": SCHEMA, "client": client, "destination": str(roots[0]), "selection": visible, "manual": manual}
    plan = {"client": client, "destination": str(roots[0])}
    if len(roots) > 1:
        new["destination2"] = plan["destination2"] = str(roots[1])
    new.update(selection_version=SELECTION_VERSION, managed=new_managed)
    external = external_skills(client, roots, kept, home)
    plan.update(actions=actions, preserved=kept, conflicts=conflicts, external_conflicts=external_conflicts(external))
    plan.update(failed=[], state=new, previous_state=old, managed_before=managed, router=router)
    preserved = {roots[item.get("root", 0)] / item["entry"] for item in kept}
    for entry, info in list(new_managed.items()):
        target = roots[info.get("root", 0)] / entry
        if target in preserved:
            continue  # The recorded hash is historical for a modified managed copy.
        for path, name in external.items():
            if path == target or name != info["name"]:
                continue
            identical = matches(client, info, library, router, path)
            if client == "claude":
                if not identical:
                    conflicts[name] = sorted(set(conflicts.get(name, [])) | {entry, f"external:{display(path)}"})
                continue
            if not identical and entry in named:
                raise InstallError(f"Frontmatter name conflict with preserved {display(path)}: {name} ({entry})")
            unclaim(plan, entry, info, managed, f"name {name!r} is taken by {display(path)}; not claimed")
            break
    return plan


def mass_removal(args, plans: list) -> str | None:
    """A no-argument update that would remove most managed skills is refused unless asked for."""
    if args.allow_mass_removal or args.selection is not None or args.manual is not None or args.enable or args.disable:
        return None
    for p in plans:
        before, after = p["managed_before"], p["state"]["managed"]
        removing = [a for a in p["actions"] if a.get("source") is None and a["entry"] not in after]
        if len(removing) >= MASS_REMOVAL_MINIMUM and len(removing) > MASS_REMOVAL_SHARE * len(before):
            return (
                f"Refusing to remove {len(removing)} of {len(before)} managed {p['client']} skills in one update; "
                "rerun with --allow-mass-removal if that is intended"
            )
    return None


def overflow(plans: list) -> str | None:
    """A Codex root holding more than ROOT_CAP top-level folders (any owner) could lose skills."""
    for p in plans:
        for index, root in enumerate(roots_of(p) if p["client"] == "codex" else []):
            names = {n for n in os.listdir(root) if not n.startswith(".")} if root.is_dir() else set()
            for action in (a for a in p["actions"] if a.get("root", 0) == index):
                if action.get("source"):
                    names.add(action["entry"])
                else:
                    names.discard(action["entry"])
            if len(names) > ROOT_CAP:
                return (
                    f"Refusing to fill {display(root)} with {len(names)} skill folders: Codex finds at most "
                    f"about 2,000 per root (limit {ROOT_CAP}); remove skills there or install fewer (--manual)"
                )
    return None


# --- Locking, applying and restoring


def kernel_lock(fd: int):
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def kernel_unlock(fd: int):
    if fcntl is None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def state_lock(directory: Path):
    """An exclusive, non-blocking lock (flock, or msvcrt on Windows); where flock does not
    work (some NFS or Lustre homes), exclusive_file_lock takes its place."""
    path = directory / ".lock"
    no_symlink_ancestors(path)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o644)
    try:
        try:
            kernel_lock(fd)
        except OSError as exc:
            if isinstance(exc, BlockingIOError) or exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise LockBusy(f"Another awesome-skills installer is running (lock: {display(path)})") from exc
            if exc.errno not in LOCK_UNSUPPORTED:
                raise
            with exclusive_file_lock(directory, exc):
                yield
            return
        try:
            yield
        finally:
            kernel_unlock(fd)
    finally:
        os.close(fd)


def lock_age(content: bytes, path: Path) -> float:
    try:
        started = float(json.loads(content.decode("utf-8"))["started"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        started = os.lstat(path).st_mtime  # written partly by a run that died at once
    return time.time() - started


def busy(lock: Path) -> LockBusy:
    return LockBusy(f"Another awesome-skills installer is running (lock: {display(lock)})")


@contextmanager
def exclusive_file_lock(directory: Path, reason: OSError):
    """An O_EXCL file holding a random token and start time, stale only by age, taken over by
    an atomic rename after which the moved file must be exactly the one judged stale."""
    lock = directory / ".lock.excl"
    mine = json.dumps({"token": uuid.uuid4().hex, "started": time.time()}).encode()
    for _ in range(3):
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            try:
                judged = lock.read_bytes()
                if lock_age(judged, lock) <= STALE_LOCK_SECONDS:
                    raise busy(lock) from None
                aside = directory / f".lock.excl.stale-{uuid.uuid4().hex}"
                os.rename(lock, aside)
            except FileNotFoundError:
                continue  # released or taken over meanwhile: look again
            if aside.read_bytes() != judged:
                try:  # a contender's fresh lock was moved: put it back, it is theirs
                    os.link(aside, lock)
                except OSError:
                    pass
                aside.unlink(missing_ok=True)
                raise busy(lock) from None
            aside.unlink(missing_ok=True)
            continue
        except OSError as exc:
            raise InstallError(
                f"Cannot lock {display(directory)}: flock is unsupported there ({reason.strerror}) and an "
                f"exclusive lock file failed ({exc.strerror}); set SKILLS_STATE_DIR and SKILLS_DATA_DIR "
                "to a directory on a local filesystem"
            ) from exc
        try:
            os.write(fd, mine)
        finally:
            os.close(fd)
        break
    else:
        raise busy(lock)
    try:
        yield
    finally:
        try:
            if lock.read_bytes() == mine:
                lock.unlink()
        except OSError as exc:
            warn(f"could not remove the lock {display(lock)}: {exc}")


def backup_order(path: Path) -> int:
    """Names carry time.time_ns(); time zones and daylight saving cannot reorder them."""
    match = re.search(r"-(\d{20})-", path.name)
    return int(match.group(1)) if match else os.lstat(path).st_mtime_ns


def backup_dirs(state: Path) -> list[Path]:
    backups = state / "backups"
    no_symlink_ancestors(backups)
    return sorted((p for p in backups.iterdir() if plain_dir(p)), key=backup_order) if plain_dir(backups) else []


def interrupted_transaction(state: Path, keep: int = KEEP_BACKUPS) -> Path | None:
    """The newest unfinished transaction among the kept ones (every run recovers it first)."""
    for saved in reversed(backup_dirs(state)[-keep:] if keep else backup_dirs(state)):
        if read_json(saved / "restore.json", {}).get("status") == "applying":
            return saved
    return None


def recover(state: Path, keep: int = KEEP_BACKUPS) -> Path | None:
    """Undo an update that was killed mid-apply, so the run can start from the previous install."""
    stale = interrupted_transaction(state, keep)
    if stale is None:
        return None
    try:
        restore(stale, state, dry_run=False, quiet=True)
    except InstallError as exc:
        raise PersonNeeded(
            f"An interrupted update could not be undone automatically: {exc}. "
            f"Resolve it, then run --restore {display(stale)}"
        ) from exc
    print(f"Recovered an interrupted update: {display(stale)}")
    return stale


def prune_backups(state: Path, keep: int):
    """Keep the newest finished transactions; never touch one that is still applying."""
    if keep <= 0:
        return
    for saved in backup_dirs(state)[:-keep]:
        if read_json(saved / "restore.json", {}).get("status") in {"complete", "restored", "preparing", None}:
            rmtree(saved)


def preflight(plans: list, state: Path):
    for p in plans:
        if read_json(state / f"{p['client']}.json", {}) != p["previous_state"]:
            raise InstallError(f"Selection changed since planning: {p['client']}")
        for action in p["actions"]:
            target = target_of(p, action)
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


def apply_plans(plans: list, state: Path, library: Library, keep: int = KEEP_BACKUPS) -> Path | None:
    """Apply verified plans as one recoverable transaction. The caller holds the lock."""
    preflight(plans, state)
    changed = [p for p in plans if p["actions"] or read_json(state / f"{p['client']}.json", {}) != p["state"]]
    if not changed:
        return None
    pending = interrupted_transaction(state, keep)
    if pending:
        raise InstallError(f"Incomplete transaction; restore it first with --restore {display(pending)}")
    # Download first: a failed transfer leaves no transaction behind.
    library.prepare([a["source"] for p in changed for a in p["actions"] if a.get("source") not in (None, "@library")])
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.time_ns():020d}-" + uuid.uuid4().hex[:8]
    backup = state / "backups" / stamp
    no_symlink_ancestors(backup)
    backup.mkdir(parents=True)
    journal = {"schema": SCHEMA, "state_dir": str(state), "status": "preparing", "clients": []}
    if any("migration" in p for p in changed):
        journal["migration"] = MIGRATION  # a --restore of this transaction undoes the migration for good
    for p in changed:
        statefile = state / f"{p['client']}.json"
        item = {k: p[k] for k in ("client", "destination", "destination2") if k in p}
        item.update(old_state=read_json(statefile, {}) if statefile.exists() else None, new_state=None)
        journal["clients"].append(dict(item, actions=p["actions"], **({"migrated": True} if "migration" in p else {})))
    atomic_json(backup / "restore.json", journal)
    prepare_copies(changed, backup, library)
    for item, p in zip(journal["clients"], changed, strict=True):
        validate_state(p["state"], p["client"])
        item["new_state"], item["actions"] = p["state"], p["actions"]
    journal["status"] = "applying"
    atomic_json(backup / "restore.json", journal)
    try:
        move_live_entries(changed, state, backup)
    except BaseException:
        try:
            restore(backup, state, dry_run=False, quiet=True)  # put the previous install back now
        except InstallError as exc:
            warn(f"automatic rollback failed ({exc}); the next run retries it")
        raise
    journal["status"] = "complete"
    atomic_json(backup / "restore.json", journal)
    return backup


def move_live_entries(changed: list, state: Path, backup: Path):
    for p in changed:
        for action in p["actions"]:
            entry, target, where = action["entry"], target_of(p, action), slot(p["client"], action)
            if fingerprint(target) != action["before"] or is_link(target):
                raise InstallError(f"Destination changed since planning: {target}; recovery journal: {backup}")
            if action["before"] is not None:
                saved = backup / where / entry
                saved.parent.mkdir(parents=True, exist_ok=True)
                move(target, saved)
            if action["after"] is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                move(backup / "prepared" / where / entry, target)
        atomic_json(state / f"{p['client']}.json", p["state"])


def prepare_copies(changed: list, backup: Path, library: Library):
    """Prepare and verify replacements before any live entry moves. A skill that fails is
    reported and skipped (its copy and record stay); the others proceed."""
    try:
        for p in changed:
            for action in list(p["actions"]):
                if action.get("source") is not None:
                    prepare_one(p, action, backup, library)
    except BaseException:
        if (backup / "prepared").exists():
            try:
                rmtree(backup / "prepared")
            except OSError:
                pass
        raise


def prepare_one(p: dict, action: dict, backup: Path, library: Library):
    """Copy the library tree, turn it into the client's copy, and verify both steps."""
    entry, want = action["entry"], p["state"]["managed"][action["entry"]]
    prepared = backup / "prepared" / slot(p["client"], action) / entry
    try:
        prepared.parent.mkdir(parents=True, exist_ok=True)
        if action["source"] == "@library":
            write_tree(p["router"]["entries"], prepared)
            expected = p["router"]["listing"]
        else:
            library.materialize(action["source"], prepared)
            expected, edits = library.derived(p["client"], action["source"], want["invocation"])
            apply_edits(prepared, edits)
        if not same_tree(expected, prepared):
            raise InstallError(f"Prepared copy changed: {display(prepared)}")
        name = library.skill_name((prepared / "SKILL.md").read_bytes(), entry)
        if name != want["name"]:
            raise InstallError(f"Frontmatter name {name!r} differs from {INDEX}")
    except (InstallError, OSError) as exc:
        if os.path.lexists(prepared):
            rmtree(prepared)
        p["actions"].remove(action)
        previous = p["managed_before"].get(entry)
        if previous:
            p["state"]["managed"][entry] = previous
        else:
            p["state"]["managed"].pop(entry, None)
        p["failed"].append({"entry": entry, "source": action["source"], "error": str(exc)})
        return
    action["after"] = fingerprint(prepared)
    p["state"]["managed"][entry]["sha256"] = action["after"]


def restore(backup: Path, state: Path, dry_run: bool, quiet: bool = False):
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
    operations = [] if journal["status"] == "preparing" else restore_operations(backup, state, journal)
    if not quiet:
        print(json.dumps({"restore": display(backup), "targets": [display(t) for t, _, _ in operations]}, indent=2))
    if dry_run:
        return
    if journal["status"] == "preparing":
        # Interrupted before any live entry or manifest moved: nothing to put back.
        journal["status"] = "restored"
        atomic_json(backup / "restore.json", journal)
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
    if journal["status"] == "complete" and journal.get("migration") == MIGRATION:
        marks = read_json(state / MIGRATIONS, {})  # an undone migration is not redone (see migrated_state)
        for client in journal["clients"]:
            if client.get("migrated"):
                marks.setdefault(MIGRATION, {}).setdefault(client["client"], {})["undone"] = time.time()
        atomic_json(state / MIGRATIONS, marks)
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
        roots = roots_of(client)
        if not client.get("new_state") or not roots or roots != roots_of(client["new_state"]):
            raise InstallError("Recovery destination does not match the client manifest")
        if any(safe_absolute(root) != root for root in roots):
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
            if action.get("root", 0) not in range(len(roots)):
                raise InstallError("Invalid recovery action")
            target, saved = target_of(client, action), backup / slot(name, action) / action["entry"]
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


# --- Legacy tarball-installer cache


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


# --- Command line


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


def kept_backups() -> int:
    value = os.environ.get("SKILLS_KEEP_BACKUPS", str(KEEP_BACKUPS))
    if not value.isdigit():
        raise InstallError(f"SKILLS_KEEP_BACKUPS must be a non-negative integer: {value!r}")
    return int(value)


def resolve_clients(args, home: Path, storage: list[Path], source: Path | None) -> list[tuple]:
    """(client, skills roots, state) for each client run: Claude has one root, Codex two."""
    codex_home = native(Path(os.path.abspath(os.environ.get("CODEX_HOME") or home / ".codex")))
    defaults = {"claude": [home / ".claude/skills"], "codex": [codex_home / "skills", home / ".agents/skills"]}
    states = {client: read_json(storage[0] / f"{client}.json", {}) for client in defaults}
    for client, value in states.items():
        validate_state(value, client)

    def configured(client: str, index: int, saved: bool = True) -> Path:
        variable = f"SKILLS_{client.upper()}_DEST" + ("2" if index else "")
        recorded = states[client].get(("destination", "destination2")[index]) if saved else None
        return Path(os.environ.get(variable) or recorded or defaults[client][index])

    clients = []
    for client in ["codex"] if args.codex_only else ["claude"] if args.claude_only else ["claude", "codex"]:
        roots = []
        for i in range(len(defaults[client])):
            try:
                roots.append(safe_absolute(configured(client, i)))
            except InstallError as exc:  # a linked ~/.agents/skills is never written through
                if not i or os.environ.get("SKILLS_CODEX_DEST2"):
                    raise
                warn(f"{exc}; Codex gets only the skills placed in its first root and those named")
        if roots[0] == home / ".agents" or home / ".agents" in roots[0].parents:
            raise InstallError(f"This installer does not own ~/.agents: {display(roots[0])}")
        other = "claude" if client == "codex" else "codex"
        saved = [Path(states[other][k]) for k in ("destination", "destination2") if states[other].get(k)]
        others = [configured(other, i, False) for i in range(len(defaults[other]))] + saved
        resolved = [native(b.expanduser().resolve()) for b in others]
        for a, b in [(a, b) for a in roots for b in resolved] + ([tuple(roots)] if len(roots) > 1 else []):
            if overlap(a, b):
                raise InstallError(f"Client destinations overlap: {display(a)}, {display(b)}")
        for root in [home / ".codex/skills", home / ".claude/skills", home / ".agents", codex_home / "skills", *roots]:
            root = native(root.resolve())
            for path in storage:
                if overlap(path, root):
                    raise InstallError(
                        f"Storage and discovery roots must be disjoint: {display(path)}, {display(root)}"
                    )
        if source is not None and any(overlap(source, root) for root in roots):
            raise InstallError(f"Source and destination overlap: {display(source)}, {display(roots[0])}")
        clients.append((client, roots, states[client]))
    return clients


def migrated_state(old: dict, client: str, undone: bool) -> tuple[dict, dict | None]:
    """(state, migration) for a v1 state, once: Claude's old default @all shows only the router,
    any other selection stays visible, and the rest is installed hidden. A migration undone with
    --restore is an opt-out: the old selection stays and nothing is hidden."""
    if not old or old.get("selection_version") == SELECTION_VERSION:
        return old, None
    visible, manual = old["selection"], [] if undone else ["@all"]
    if client == "claude" and visible == ["@all"] and not undone:
        visible = ["@library"]
    base = dict(old, selection=visible, manual=manual, selection_version=SELECTION_VERSION)
    return base, None if undone else {"from": old["selection"], "selection": visible, "manual": manual}


def make_plans(args, clients: list, library: Library, home: Path, state: Path, data: Path) -> list:
    marks = read_json(state / MIGRATIONS, {}).get(MIGRATION, {})
    plans = []
    for client, roots, old in clients:
        base, migration = migrated_state(old, client, bool(marks.get(client, {}).get("undone")))
        visible, manual = selection(args, client, base, library), manual_set(args, client, base, library)
        router = router_info(client, launcher_call(data))
        plans.append(plan_client(client, roots, old, base, visible, manual, library, router, home))
        if migration:
            plans[-1]["migration"] = migration
    every = [root for p in plans for root in roots_of(p)]
    for i, a in enumerate(every):
        for b in every[i + 1 :]:
            if overlap(a, b):
                raise InstallError(f"Client destinations overlap: {display(a)}, {display(b)}")
    return plans


def record_migrations(state: Path, plans: list, backup: Path):
    """Mark migrated clients once their transaction is complete: an interrupted one is redone."""
    migrated = [p["client"] for p in plans if "migration" in p]
    if migrated:
        marks = read_json(state / MIGRATIONS, {})
        for client in migrated:
            marks.setdefault(MIGRATION, {})[client] = {"time": time.time(), "backup": display(backup)}
        atomic_json(state / MIGRATIONS, marks)


def summary(p: dict) -> str:
    """One line for a large plan, such as a first install or a migration of thousands of copies."""
    records, client, m = p["state"]["managed"].values(), p["client"], p.get("migration")
    hidden = sum(info.get("invocation") == "manual" for info in records)
    if m:
        undo = f"--selection {','.join(m['from'])}" if m["selection"] != m["from"] else "--manual ''"
        visible = ",".join(m["selection"]) or "nothing"
        return f"Migrated {client}: {','.join(m['from'])} -> visible {visible}, {hidden} hidden; undo: --{client}-only {undo}"
    copied = sum(a["after"] is not None for a in p["actions"])
    removed = len(p["actions"]) - copied
    return f"Updated {client}: {copied} copied, {removed} removed; {len(records) - hidden} visible, {hidden} hidden"


def report(dry_run: bool, library: Library, plans: list, legacy: list[Path], pending: Path | None = None) -> dict:
    hidden = {"state", "previous_state", "managed_before", "router"}
    clients = [{k: v for k, v in p.items() if k not in hidden} | {"selection": p["state"]["selection"]} for p in plans]
    result = {
        "dry_run": dry_run,
        "library_entries": len(library.skills),
        "library": library.describe(),
        "skipped_library_entries": library.skipped,
        "legacy_cache_cleanup": [display(p) for p in legacy],
        "clients": clients,
    }
    if pending:
        result["interrupted_transaction"] = display(pending)
    return result


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
            env=git_env(),
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
    parser.add_argument("--selection", help="replace ONE client's visible set: IDs, @library, @all; empty for none")
    parser.add_argument("--manual", metavar="SPEC", help="replace ONE client's hidden set: @all, IDs, or empty")
    parser.add_argument("--enable", action="append", default=[], metavar="ID", help="show ID to the model")
    parser.add_argument("--disable", action="append", default=[], metavar="ID", help="stop showing ID")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="plan against the library clone as it is (offline)")
    parser.add_argument("--list", action="store_true", help="list full-library metadata and name conflicts")
    parser.add_argument("--search", default="", help="filter --list by ID, name, description or origin")
    parser.add_argument("--restore", type=Path, help="restore a backup, refusing later modifications")
    parser.add_argument(
        "--allow-mass-removal",
        action="store_true",
        help="let an update without selection flags remove most managed skills at once",
    )
    parser.add_argument("--delete", action="store_true", help="deprecated: prune only verified managed deselections")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    changes = args.selection is not None or args.manual is not None or args.enable or args.disable
    if changes and not (args.codex_only or args.claude_only):
        parser.error("selection changes require --codex-only or --claude-only")
    home = native(Path(os.path.abspath(Path.home())))  # compared with normalized roots
    data_default = default_data(home)
    state = storage_path("SKILLS_STATE_DIR", data_default if WINDOWS else home / ".local/share/awesome-skills")
    legacy_cache = storage_path("SKILLS_CACHE_DIR", home / ".cache/awesome-skills")
    keep = kept_backups()
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
        pyyaml()  # a checkout's skills are read in full: fail once, before any lock or write
    url = os.environ.get("SKILLS_REPOSITORY_URL") or REPOSITORY_URL
    branch = os.environ.get("SKILLS_BRANCH") or "main"
    if not re.fullmatch(r"[A-Za-z0-9._][A-Za-z0-9._/-]*", branch) or ".." in branch:
        raise InstallError(f"Invalid SKILLS_BRANCH: {branch!r}")
    git = Git() if remote else None  # a missing or old git fails before anything is written
    if args.list:
        library = listed_library(git, source, data)
        matches = {i: s for i, s in library.skills.items() if args.search.lower() in json.dumps([i, s]).lower()}
        emit({"revision": library.revision, "skills": matches, "conflicts": conflict_groups(matches)})
        return 0
    return run_update(args, git, home, state, data, legacy_cache, source, url, branch, keep)


def run_update(args, git, home, state, data, legacy_cache, source, url, branch, keep) -> int:
    storage, remote = [state, data, legacy_cache], git is not None
    with ExitStack() as stack:
        # A remote run fetches into the shared clone and a stale transaction is undone before
        # planning, both under the lock. A local plan is computed without writes.
        if remote and (args.dry_run or args.no_fetch):
            existing_clone(data)  # before the lock: a dry run on a fresh HOME writes nothing
        locked = remote or (not args.dry_run and interrupted_transaction(state, keep) is not None)
        if locked:
            stack.enter_context(state_lock(state))
            if remote and data != state:
                stack.enter_context(state_lock(data))
            if not args.dry_run:
                recover(state, keep)
        clients = resolve_clients(args, home, storage, source)
        mode = "dry-run" if args.dry_run else "apply"
        library = stack.enter_context(open_library(git, source, data, url, branch, mode, not args.no_fetch))
        plans = make_plans(args, clients, library, home, state, data)
        blocked = mass_removal(args, plans) or overflow(plans)
        if args.dry_run:
            emit(report(True, library, plans, legacy_caches(legacy_cache), interrupted_transaction(state, keep)))
            if blocked:
                warn(blocked)
            return 0
        if blocked:
            raise PersonNeeded(blocked)
        if not locked:
            stack.enter_context(state_lock(state))
        backup = apply_plans(plans, state, library, keep)
        if backup:
            record_migrations(state, plans, backup)
            prune_backups(state, keep)
        write_launchers(data, state, library)
        removed = remove_legacy_caches(legacy_cache) if migrated(state) else []
    failures = [dict(f, client=p["client"]) for p in plans for f in p["failed"]]
    if backup and sum(len(p["actions"]) for p in plans) > SUMMARY_ACTIONS:
        print("\n".join(map(summary, plans)))
    elif backup:
        emit(report(False, library, plans, removed))
    if backup:
        print(f"Recovery backup: {display(backup)}")
    elif not failures:
        print("Already current; selection preserved.")
    if removed:
        print(f"Removed {len(removed)} legacy cache snapshot(s) under {display(legacy_cache)}")
    if failures:
        entries = ", ".join(f"{f['client']}:{f['entry']} ({f['error']})" for f in failures)
        print(
            f"awesome-skills: {len(failures)} skill(s) were not installed and kept as they were: {entries}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LockBusy as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(LOCK_BUSY) from None
    except PersonNeeded as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(NEEDS_PERSON) from None
    except (InstallError, OSError, ValueError) as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("awesome-skills: interrupted", file=sys.stderr)
        raise SystemExit(130) from None
