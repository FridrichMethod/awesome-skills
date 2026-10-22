#!/usr/bin/env python3
"""Install independent persistent client selections with conservative ownership.

Dry-run computes the same plan in memory, including remote downloads.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

try:
    import yaml
except ImportError:
    print("awesome-skills requires PyYAML; use an existing Python environment or install PyYAML>=6.0.", file=sys.stderr)
    raise SystemExit(1) from None

REPOSITORY = "https://github.com/FridrichMethod/awesome-skills"
SCHEMA = 1
ROUTER = "awesome-skills-library"


class InstallError(Exception):
    pass


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
        if p.is_symlink():
            entries[rel] = ("link", mode, os.readlink(p).encode())
        elif p.is_dir():
            entries[rel] = ("dir", mode, b"")
            for child in sorted(p.iterdir()):
                visit(child, f"{rel}/{child.name}" if rel else child.name)
        elif p.is_file():
            entries[rel] = ("file", mode, p.read_bytes())
        else:
            raise InstallError(f"Unsupported file type: {p}")

    visit(path, "")
    return entries


def fingerprint(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    return digest(tree(path))


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


def read_json(path: Path, default: dict) -> dict:
    if path.is_symlink():
        raise InstallError(f"Refusing symlink state: {path}")
    if not path.exists():
        return default
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise InstallError(f"Expected an object: {path}")
    return value


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


class Library:
    def __init__(self, source: Path | None, remote: bool = False):
        self.source = source
        self.archive = None
        self.members = {}
        self.provenance = {}
        self.revision = "unversioned"
        if remote:
            branch = os.environ.get("SKILLS_BRANCH", "main")
            with urlopen(f"{REPOSITORY}/archive/refs/heads/{branch}.tar.gz", timeout=120) as response:
                self.archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
            archive_root = None
            for member in self.archive.getmembers():
                parts = PurePosixPath(member.name).parts
                if member.name.startswith("/") or ".." in parts:
                    raise InstallError(f"Unsafe archive member: {member.name}")
                if len(parts) > 1:
                    if archive_root is not None and archive_root != parts[0]:
                        raise InstallError("Archive has multiple repository roots")
                    archive_root = parts[0]
                    key = "/".join(parts[1:])
                    if key in self.members:
                        raise InstallError(f"Duplicate archive member: {key}")
                    self.members[key] = member
            if "library_sources.json" in self.members:
                self.provenance = json.loads(self.read("library_sources.json"))
            self.revision = f"branch:{branch}"
            ids = sorted({p.split("/")[1] for p in self.members if p.count("/") == 2 and p.endswith("/SKILL.md")})
        else:
            if source is None or not source.is_dir():
                raise InstallError(f"Missing source library: {source}")
            self.provenance = read_json(source.parent / "library_sources.json", {})
            result = (
                subprocess.run(["git", "-C", str(source.parent), "rev-parse", "HEAD"], capture_output=True, text=True)
                if shutil.which("git")
                else None
            )
            if result is not None and result.returncode == 0:
                self.revision = result.stdout.strip()
            ids = sorted(p.name for p in source.iterdir() if not p.is_symlink() and (p / "SKILL.md").is_file())
        self.skills = {}
        for skill_id in ids:
            if skill_id.startswith("."):
                continue
            content = self.content(skill_id)
            fm = metadata(content["SKILL.md"][2], skill_id)
            origins = self.provenance.get(skill_id, {}).get("origins", [])
            self.skills[skill_id] = {
                "name": fm["name"],
                "description": fm.get("description", ""),
                "sha256": digest(content),
                "origins": origins
                or [
                    {
                        "repository": REPOSITORY,
                        "revision": self.revision,
                        "path": f"skills/{skill_id}",
                        "upstream": "not recorded by legacy sync",
                    }
                ],
            }
        self.helper = self.read("scripts/install_skills.py") if remote else Path(__file__).read_bytes()
        self.snapshot = hashlib.sha256(
            json.dumps(
                {"skills": self.skills, "installer_sha256": hashlib.sha256(self.helper).hexdigest()}, sort_keys=True
            ).encode()
        ).hexdigest()

    def read(self, name: str) -> bytes:
        with self.archive.extractfile(self.members[name]) as stream:
            return stream.read()

    def content(self, skill_id: str) -> dict:
        if self.archive is None:
            return tree(self.source / skill_id)
        prefix = f"skills/{skill_id}"
        entries = {}
        for path, member in self.members.items():
            if path != prefix and not path.startswith(prefix + "/"):
                continue
            rel = path[len(prefix) :].lstrip("/")
            if member.isdir():
                entries[rel] = ("dir", member.mode, b"")
            elif member.isfile():
                entries[rel] = ("file", member.mode, self.read(path))
            elif member.issym():
                entries[rel] = ("link", member.mode, member.linkname.encode())
            else:
                raise InstallError(f"Unsupported archive member: {path}")
        validate_tree(entries)
        return entries

    def materialize(self, skill_id: str, target: Path):
        if self.archive is None:
            shutil.copytree(self.source / skill_id, target, symlinks=True)
        else:
            write_tree(self.content(skill_id), target)


def validate_tree(entries: dict):
    links = {p for p, (kind, _, _) in entries.items() if kind == "link"}
    for path in entries:
        if any(parent.as_posix() in links for parent in PurePosixPath(path).parents):
            raise InstallError(f"Archive writes through a symlink: {path}")
    if "" not in entries or entries[""][0] != "dir":
        raise InstallError("Skill root must be a directory")


def write_tree(entries: dict, target: Path):
    validate_tree(entries)
    for rel, (kind, mode, data) in sorted(entries.items()):
        p = target / rel
        if kind == "dir":
            p.mkdir(parents=True, exist_ok=True)
        elif kind == "file":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            p.chmod(mode)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.symlink_to(data.decode())
    for rel, (kind, mode, _) in sorted(entries.items(), reverse=True):
        if kind == "dir":
            (target / rel).chmod(mode)


def router_tree(cache: Path) -> dict:
    import shlex

    helper = shlex.quote(str(cache / "install_skills.py"))
    python = shlex.quote(sys.executable)
    body = f"""---
name: {ROUTER}
description: Search the complete awesome-skills library and enable only the skills needed for a task, with source provenance.
---

The full library is cached outside automatic discovery at `{cache / "skills"}`.
Search its index (IDs, frontmatter names, descriptions, hashes, and origins):

```bash
{python} -B {helper} --list --search protein
```

Enable a source ID for Codex, persist it across updates, then restart the session:

```bash
{python} -B {helper} --codex-only --enable SOURCE_ID
```

Read a cached `skills/SOURCE_ID/SKILL.md` directly when session restart is inconvenient.
Use its relative supporting files from that same directory. Do not invent provenance
or silently choose between different same-name variants. `--disable SOURCE_ID`
reversibly removes an unmodified managed copy. `--dry-run` previews all actions
without writing. `--list` reports conflicts. Selection changes require a client flag.
"""
    return {"": ("dir", 0o755, b""), "SKILL.md": ("file", 0o644, body.encode())}


def conflict_groups(skills: dict) -> dict:
    by_name = defaultdict(list)
    for skill_id, info in skills.items():
        by_name[info["name"]].append(skill_id)
    return {name: ids for name, ids in sorted(by_name.items()) if len({skills[i]["sha256"] for i in ids}) > 1}


def protected(path: Path) -> bool:
    return path.name.startswith(".") or path.is_symlink()


def no_symlink_ancestors(path: Path):
    for p in (path, *path.parents):
        if p.is_symlink():
            raise InstallError(f"Refusing symlink directory or ancestor: {p}")


def safe_absolute(path: Path) -> Path:
    path = path.expanduser().absolute()
    no_symlink_ancestors(path)
    return Path(os.path.abspath(path))


def valid_entry(entry: str):
    if not isinstance(entry, str) or not entry or entry.startswith(".") or "/" in entry or "\\" in entry:
        raise InstallError(f"Invalid managed entry: {entry!r}")


def valid_hash(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise InstallError(f"Invalid fingerprint: {value!r}")


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


def plan_client(client: str, dest: Path, old: dict, ids: list[str], library: Library, cache: Path) -> dict:
    managed = old.get("managed", {}) if old.get("destination") == str(dest) else {}
    selected = set(library.skills) if "@all" in ids else set(ids) - {"@library"}
    if "@library" in ids and ROUTER in selected:
        raise InstallError(f"Source ID collides with reserved library entry: {ROUTER}")
    selected_info = {i: library.skills[i] for i in selected}
    if "@library" in ids:
        selected_info["@library"] = {"name": ROUTER, "sha256": digest(router_tree(cache))}
    conflicts = conflict_groups(selected_info)
    if conflicts and client == "codex":
        raise InstallError(
            f"Codex selection has different-content frontmatter name conflicts: {json.dumps(conflicts)}. "
            "Select one explicit source ID per name; all variants remain in the cache."
        )
    # Preserve Claude's full paths. Codex deduplicates identical trees and records aliases.
    desired, seen = {}, {}
    for skill_id in sorted(selected):
        info = dict(library.skills[skill_id], source_ids=[skill_id])
        key = (info["name"], info["sha256"])
        if client == "codex" and key in seen:
            desired[seen[key]]["source_ids"].append(skill_id)
        else:
            seen[key] = skill_id
            desired[skill_id] = info
    if "@library" in ids:
        desired[ROUTER] = {
            "name": ROUTER,
            "sha256": digest(router_tree(cache)),
            "source_ids": ["@library"],
            "origins": [{"repository": REPOSITORY, "path": "scripts/install_skills.py"}],
        }
    actions, kept, new_managed = [], [], {}
    existing = {p.name: p for p in dest.iterdir()} if dest.exists() else {}
    for entry in sorted(set(existing) | set(desired)):
        target, want = dest / entry, desired.get(entry)
        current = fingerprint(target)
        owned = False
        if current is not None and not protected(target):
            if entry in managed:
                owned = current == managed[entry]["sha256"]
            elif entry in library.skills:
                # Legacy adoption requires an exact whole-tree hash, never a name alone.
                owned = current == library.skills[entry]["sha256"]
        if current is not None and not owned:
            kept.append({"entry": entry, "reason": "protected, modified, or unproven ownership"})
            if entry in managed:
                # Retain the last installed fingerprint so future updates keep
                # recognizing the edited copy, including after deselection.
                new_managed[entry] = managed[entry]
            if want and current != want["sha256"] and entry not in managed and client == "codex":
                raise InstallError(f"Cannot install {client}:{entry}: preserved destination differs: {target}")
            continue
        if want:
            new_managed[entry] = want
            if current != want["sha256"]:
                actions.append({"entry": entry, "before": current, "after": want["sha256"]})
        elif owned:
            actions.append({"entry": entry, "before": current, "after": None})
    # Include preserved external skills, even symlinks, in frontmatter collision checks.
    external = {}
    external_paths = {item["entry"]: dest / item["entry"] for item in kept}
    if client == "codex":
        agents = Path.home() / ".agents/skills"
        if agents.is_dir() and agents != dest:
            external_paths.update({f".agents/{p.name}": p for p in agents.iterdir()})
    for entry, directory in external_paths.items():
        p = directory / "SKILL.md"
        if p.is_file():
            try:
                external[entry] = {
                    "name": metadata(p.read_bytes(), str(p))["name"],
                    "sha256": fingerprint(p.parent),
                    "path": str(directory),
                }
            except InstallError:
                pass
    preserved_entries = {item["entry"] for item in kept}
    for entry, info in list(new_managed.items()):
        if entry in preserved_entries:
            continue  # The recorded hash is historical for a modified managed copy.
        for other, ext in external.items():
            if other != entry and ext["name"] == info["name"]:
                if ext["sha256"] != info["sha256"]:
                    if client == "codex":
                        raise InstallError(
                            f"Frontmatter name conflict with preserved {ext['path']}: {info['name']} ({entry})"
                        )
                    conflicts[info["name"]] = sorted(
                        set(conflicts.get(info["name"], [])) | {entry, f"external:{ext['path']}"}
                    )
                    continue
                if client == "codex":
                    new_managed.pop(entry, None)
                    actions = [a for a in actions if a["entry"] != entry]
                    current = fingerprint(dest / entry)
                    if current is not None:
                        actions.append({"entry": entry, "before": current, "after": None})
                    kept.append({"entry": entry, "reason": f"identical external name at {other}; not claimed"})
    new = {"schema": SCHEMA, "client": client, "destination": str(dest), "selection": ids, "managed": new_managed}
    return {
        "client": client,
        "destination": str(dest),
        "actions": actions,
        "preserved": kept,
        "conflicts": conflicts,
        "external_conflicts": conflict_groups(external),
        "state": new,
        "previous_state": old,
    }


def ensure_cache(library: Library, cache: Path):
    if cache.exists():
        if read_json(cache / "index.json", {}) != library.skills:
            raise InstallError(f"Cache index changed: {cache}")
        if (cache / "install_skills.py").read_bytes() != library.helper:
            raise InstallError(f"Cache helper changed: {cache}")
        if read_json(cache / "library_sources.json", {}) != {
            i: {"origins": s["origins"]} for i, s in library.skills.items()
        }:
            raise InstallError(f"Cache provenance changed: {cache}")
        for skill_id, info in library.skills.items():
            if fingerprint(cache / "skills" / skill_id) != info["sha256"]:
                raise InstallError(f"Cache content changed: {cache / 'skills' / skill_id}")
        return
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_name(cache.name + ".tmp-" + uuid.uuid4().hex)
    temp.mkdir()
    for skill_id in library.skills:
        library.materialize(skill_id, temp / "skills" / skill_id)
        if fingerprint(temp / "skills" / skill_id) != library.skills[skill_id]["sha256"]:
            raise InstallError(f"Source changed while caching: {skill_id}")
    atomic_json(temp / "index.json", library.skills)
    (temp / "install_skills.py").write_bytes(library.helper)
    atomic_json(temp / "library_sources.json", {i: {"origins": s["origins"]} for i, s in library.skills.items()})
    temp.rename(cache)


@contextmanager
def state_lock(state: Path):
    no_symlink_ancestors(state / ".lock")
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallError("Another awesome-skills installer is running") from exc
        yield


def apply_plans(plans: list, state: Path, library: Library, cache: Path) -> Path | None:
    with state_lock(state):
        return _apply_plans(plans, state, library, cache)


def _apply_plans(plans: list, state: Path, library: Library, cache: Path) -> Path | None:
    no_symlink_ancestors(state / "backups")
    if (state / "backups").exists():
        for saved in (state / "backups").iterdir():
            if read_json(saved / "restore.json", {}).get("status") == "applying":
                raise InstallError(f"Incomplete transaction; restore it first with --restore {saved}")
    for p in plans:
        if read_json(state / f"{p['client']}.json", {}) != p["previous_state"]:
            raise InstallError(f"Selection changed since planning: {p['client']}")
        for action in p["actions"]:
            target = Path(p["destination"]) / action["entry"]
            no_symlink_ancestors(target)
            if fingerprint(target) != action["before"]:
                raise InstallError(f"Destination changed since planning: {target}")
            ancestor = target.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            if ancestor.stat().st_dev != state.stat().st_dev:
                raise InstallError(f"Recovery state and destination must be on the same filesystem: {state}, {target}")
    ensure_cache(library, cache)
    changed = [p for p in plans if p["actions"] or read_json(state / f"{p['client']}.json", {}) != p["state"]]
    if not changed:
        return None
    backup = state / "backups" / (time.strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns():020d}-" + uuid.uuid4().hex[:8])
    no_symlink_ancestors(backup)
    backup.mkdir(parents=True)
    journal = {"schema": SCHEMA, "state_dir": str(state), "status": "applying", "clients": []}
    for p in changed:
        statefile = state / f"{p['client']}.json"
        journal["clients"].append(
            {
                "client": p["client"],
                "destination": p["destination"],
                "old_state": read_json(statefile, {}) if statefile.exists() else None,
                "new_state": p["state"],
                "actions": p["actions"],
            }
        )
    atomic_json(backup / "restore.json", journal)
    # Fully prepare and verify replacements before moving any live entry.
    for p in changed:
        for action in p["actions"]:
            if action["after"] is None:
                continue
            entry = action["entry"]
            prepared = backup / "prepared" / p["client"] / entry
            prepared.parent.mkdir(parents=True, exist_ok=True)
            if p["state"]["managed"][entry]["source_ids"] == ["@library"]:
                write_tree(router_tree(cache), prepared)
            else:
                shutil.copytree(cache / "skills" / entry, prepared, symlinks=True)
            if fingerprint(prepared) != action["after"]:
                raise InstallError(f"Prepared copy changed: {prepared}; recovery journal: {backup}")
    for p in changed:
        dest = Path(p["destination"])
        for action in p["actions"]:
            entry, target = action["entry"], dest / action["entry"]
            if fingerprint(target) != action["before"] or target.is_symlink():
                raise InstallError(f"Destination changed since planning: {target}; recovery journal: {backup}")
            if action["before"] is not None:
                saved = backup / p["client"] / entry
                saved.parent.mkdir(parents=True, exist_ok=True)
                target.rename(saved)
            if action["after"] is not None:
                dest.mkdir(parents=True, exist_ok=True)
                (backup / "prepared" / p["client"] / entry).rename(target)
        atomic_json(state / f"{p['client']}.json", p["state"])
    journal["status"] = "complete"
    atomic_json(backup / "restore.json", journal)
    return backup


def restore(backup: Path, state: Path, dry_run: bool):
    if dry_run:
        _restore(backup, state, True)
    else:
        with state_lock(state):
            _restore(backup, state, False)


def _restore(backup: Path, state: Path, dry_run: bool):
    no_symlink_ancestors(backup)
    if backup.parent != state / "backups":
        raise InstallError(f"Recovery backup must belong to this state directory: {state}")
    journal = read_json(backup / "restore.json", {})
    if (
        journal.get("schema") != SCHEMA
        or journal.get("state_dir") != str(state)
        or journal.get("status") not in {"complete", "applying"}
        or not isinstance(journal.get("clients"), list)
    ):
        raise InstallError(f"Invalid or already restored journal: {backup}")
    operations = []
    seen_clients = set()
    for client in journal["clients"]:
        name = client.get("client")
        if name not in {"claude", "codex"} or name in seen_clients:
            raise InstallError(f"Invalid recovery client: {name}")
        seen_clients.add(name)
        validate_state(client.get("new_state", {}), name)
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
                raise InstallError(f"Recovery target is not a skill directory: {target}")
            current = fingerprint(target)
            if current == action["before"] and not saved.exists():
                continue
            if current not in [action["after"], None] or target.is_symlink():
                raise InstallError(f"Refusing to overwrite changes during restore: {target}")
            if action["before"] is not None and fingerprint(saved) != action["before"]:
                raise InstallError(f"Missing or changed recovery copy: {saved}")
            operations.append((target, saved, current))
    print(json.dumps({"restore": str(backup), "targets": [str(t) for t, _, _ in operations]}, indent=2))
    if dry_run:
        return
    for target, saved, current in reversed(operations):
        if current is not None:
            redo = backup / "replaced-on-restore" / (target.name + "-" + uuid.uuid4().hex[:8])
            redo.parent.mkdir(parents=True, exist_ok=True)
            target.rename(redo)
        if saved.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            saved.rename(target)
    for client in journal["clients"]:
        path = state / f"{client['client']}.json"
        if client["old_state"] is None:
            path.unlink(missing_ok=True)
        else:
            atomic_json(path, client["old_state"])
    journal["status"] = "restored"
    atomic_json(backup / "restore.json", journal)


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    if (args.selection is not None or args.enable or args.disable) and not (args.codex_only or args.claude_only):
        parser.error("selection changes require --codex-only or --claude-only")
    home = Path.home()
    state = safe_absolute(Path(os.environ.get("SKILLS_STATE_DIR", str(home / ".local/share/awesome-skills"))))
    cache_root = safe_absolute(Path(os.environ.get("SKILLS_CACHE_DIR", str(home / ".cache/awesome-skills"))))
    for storage in (state, cache_root):
        if any(
            a in {".agents", ".codex", ".claude"} and b == "skills"
            for a, b in zip(storage.parts, storage.parts[1:], strict=False)
        ):
            raise InstallError(f"Storage must be disjoint from project/global discovery: {storage}")
    if args.restore:
        restore(safe_absolute(args.restore), state, args.dry_run)
        return 0
    adjacent = Path(globals().get("__file__", str(Path.cwd() / "install_skills.py"))).resolve().parent
    source = (
        args.source or (adjacent / "skills" if (adjacent / "skills").exists() else adjacent.parent / "skills")
    ).resolve()
    library = Library(source if not args.remote else None, args.remote)
    if args.list:
        matches = {i: s for i, s in library.skills.items() if args.search.lower() in json.dumps([i, s]).lower()}
        print(json.dumps({"skills": matches, "conflicts": conflict_groups(matches)}, indent=2, ensure_ascii=False))
        return 0
    cache = cache_root / "libraries" / library.snapshot
    plans = []
    for client in ["codex"] if args.codex_only else ["claude"] if args.claude_only else ["claude", "codex"]:
        old = read_json(state / f"{client}.json", {})
        validate_state(old, client)
        dest = safe_absolute(
            Path(
                os.environ.get(f"SKILLS_{client.upper()}_DEST", old.get("destination", str(home / f".{client}/skills")))
            )
        )
        if dest == home / ".agents" or home / ".agents" in dest.parents:
            raise InstallError(f"This installer does not own ~/.agents: {dest}")
        other = "claude" if client == "codex" else "codex"
        other_state = read_json(state / f"{other}.json", {})
        validate_state(other_state, other)
        other_roots = {Path(os.environ.get(f"SKILLS_{other.upper()}_DEST", str(home / f".{other}/skills")))}
        if other_state.get("destination"):
            other_roots.add(Path(other_state["destination"]))
        for root in other_roots:
            root = root.expanduser().resolve()
            if dest == root or dest in root.parents or root in dest.parents:
                raise InstallError(f"Client destinations overlap: {dest}, {root}")
        codex_root = Path(os.path.abspath(Path(os.environ.get("CODEX_HOME", str(home / ".codex"))))) / "skills"
        for root in [home / ".codex/skills", home / ".claude/skills", home / ".agents", codex_root, dest]:
            root = root.resolve()
            for storage in [state, cache_root]:
                if storage == root or root in storage.parents or storage in root.parents:
                    raise InstallError(f"Storage and discovery roots must be disjoint: {storage}, {root}")
        if source == dest or source in dest.parents or dest in source.parents:
            raise InstallError(f"Source and destination overlap: {source}, {dest}")
        plans.append(plan_client(client, dest, old, selection(args, client, old, library), library, cache))
    if len(plans) == 2:
        a, b = (Path(p["destination"]) for p in plans)
        if a == b or a in b.parents or b in a.parents:
            raise InstallError(f"Client destinations overlap: {a}, {b}")
    printable = [
        {k: v for k, v in p.items() if k not in {"state", "previous_state"}} | {"selection": p["state"]["selection"]}
        for p in plans
    ]
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "library_entries": len(library.skills),
                "cache": str(cache),
                "clients": printable,
            },
            indent=2,
        )
    )
    if not args.dry_run:
        backup = apply_plans(plans, state, library, cache)
        print(f"Recovery backup: {backup}" if backup else "Already current; selection preserved.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"awesome-skills: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
