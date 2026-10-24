#!/usr/bin/env python3
"""Sync skills from upstream repos into ./skills/.

Run from the repo root. Clones each upstream shallow, finds every SKILL.md,
de-duplicates nested skill dirs, and copies the skill roots into ./skills/
with content-based deduplication and explicit, source-qualified variants on
frontmatter name conflicts. library_sources.json records observed provenance;
existing content without provenance is protected as legacy content.

Filters out:
- .git/, __pycache__/, *.pyc, node_modules/, .DS_Store
- .gitattributes (prevents LFS issues on push)
- Files >40 MB (GitHub warns >50 MB; stay under threshold)
- Bundled vector DBs and dataset blobs (**/repo/src/db/, **/repo/dataset/)
- Anything referenced by an upstream .gitattributes as Git LFS
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DEST = REPO_ROOT / "skills"
README_PATH = REPO_ROOT / "README.md"
LIBRARY_SOURCES_PATH = REPO_ROOT / "library_sources.json"
LIBRARY_INDEX_PATH = REPO_ROOT / "library_index.json"

# README headline figures are derived from the live tree on every sync so they
# never drift between runs. Badge/prose use a rounded "<floor>+" figure; the
# repo-layout tree line shows the exact count. See `update_readme_counts`.
SKILL_COUNT_FLOOR_STEP = 100

# Codex skill loader caps `description` at 1024 chars and rejects any
# top-level frontmatter value containing an unquoted mid-line `: ` (which
# YAML reads as a mapping). Both `sanitize_skill_frontmatter` and the
# `--sanitize-only` CLI mode enforce these constraints.
DESCRIPTION_MAX = 1024
DESCRIPTION_TRIM_TARGET = 1020  # leave room for "..." if we have to add it
_FIELD_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*): (.+)$")
_YAML_PROBLEM_PREFIXES = ("{", "[", "!", "&", "*", ">", "|", "%", "@", "`")
# A `description` block that opens with a quoted folded/literal indicator
# (e.g. `description: ">"`, `description: ">-"`, `description: "|"`) is a
# common upstream typo: the author meant the YAML scalar style indicator,
# but the quotes turn the marker into the literal value and the body lines
# below become a nested mapping. We collapse those into one quoted scalar.
_FOLDED_SCALAR_MARKERS = {">", ">-", ">+", "|", "|-", "|+"}

# (url, local_name, description). Order only determines which new variant gets
# the plain directory ID; no source wins a frontmatter name conflict.
UPSTREAMS = [
    # --- bio / scientific / medical libraries (volume baseline) ---
    ("https://github.com/K-Dense-AI/claude-scientific-skills.git", "kdense-sci", "K-Dense scientific-skills"),
    ("https://github.com/K-Dense-AI/claude-scientific-writer.git", "kdense-writer", "K-Dense scientific-writer"),
    ("https://github.com/GPTomics/bioSkills.git", "bioskills", "GPTomics bioSkills"),
    ("https://github.com/FreedomIntelligence/OpenClaw-Medical-Skills.git", "openclaw", "OpenClaw Medical"),
    ("https://github.com/jaechang-hits/SciAgent-Skills.git", "sciagent", "SciAgent-Skills"),
    ("https://github.com/jamditis/claude-skills-journalism.git", "journalism", "Journalism / academia"),
    # --- specialized bio / academic curations ---
    ("https://github.com/lishix520/academic-paper-skills.git", "lishix-paper", "lishix academic-paper"),
    ("https://github.com/Imbad0202/academic-research-skills.git", "imbad-academic", "Imbad academic-research"),
    ("https://github.com/Yuan1z0825/nature-skills.git", "nature-skills", "Nature journal writing & figures (13k ⭐)"),
    ("https://github.com/AIScientists-Dev/academic-humanizer.git", "academic-humanizer", "Academic-humanizer — clarify & de-AI academic prose and grant proposals"),
    ("https://github.com/google-deepmind/science-skills.git", "gdm-science", "Google DeepMind Science Skills — genomics, structural bio, cheminformatics, literature DBs"),
    ("https://github.com/adaptyvbio/protein-design-skills.git", "adaptyv-protein", "Adaptyv protein-design [P0]"),
    # --- general-purpose dev/productivity collections ---
    ("https://github.com/wshobson/agents.git", "wshobson-agents", "wshobson agents (155 dev skills, 35.5k ⭐)"),
    ("https://github.com/anthropics/claude-plugins-official.git", "anthropics-plugins", "Anthropic official plugins (19.5k ⭐)"),
    # --- foundational / official collections ---
    ("https://github.com/forrestchang/andrej-karpathy-skills.git", "karpathy-skills", "Andrej Karpathy CLAUDE.md skill (133.3k ⭐)"),
    ("https://github.com/anthropics/skills.git", "anthropics-skills", "Anthropic official skills (136.1k ⭐)"),
    ("https://github.com/obra/superpowers.git", "obra-superpowers", "Superpowers methodology framework (194.6k ⭐)"),
]

MAX_FILE_BYTES = 40 * 1024 * 1024  # 40 MB — under GitHub's 50 MB warning threshold

IGNORE_FILE_NAMES = {".gitattributes", ".DS_Store"}
IGNORE_DIR_NAMES = {".git", "__pycache__", "node_modules"}
IGNORE_PATH_PARTS = (
    ("repo", "src", "db"),
    ("repo", "dataset"),
)
SKIP_TOPLEVEL_NAMES = {"agents", "scripts", "docs", "examples", "tests", "node_modules"}


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def shallow_clone(url: str, dest: Path) -> bool:
    try:
        run(["git", "clone", "--depth", "1", "--single-branch", url, str(dest)])
        return True
    except subprocess.CalledProcessError as e:
        print(f"  clone failed for {url}: {e.stderr.strip()}", file=sys.stderr)
        return False


def find_lfs_pointer_files(repo: Path) -> set[Path]:
    """Read any .gitattributes inside repo and return files marked as LFS-tracked."""
    lfs_paths: set[Path] = set()
    for gattr in repo.rglob(".gitattributes"):
        try:
            text = gattr.read_text(errors="ignore")
        except OSError:
            continue
        if "filter=lfs" not in text:
            continue
        base = gattr.parent
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "filter=lfs" not in line:
                continue
            pattern = line.split()[0]
            for match in base.rglob(pattern):
                if match.is_file():
                    lfs_paths.add(match.resolve())
    return lfs_paths


def find_skill_roots(repo: Path) -> list[Path]:
    """Return directories containing SKILL.md, not nested inside another skill dir."""
    skill_dirs = sorted({m.parent.resolve() for m in repo.rglob("SKILL.md")}, key=lambda p: len(p.parts))
    roots: list[Path] = []
    for d in skill_dirs:
        if any(str(d).startswith(str(r) + os.sep) for r in roots):
            continue
        roots.append(d)
    return roots


def should_skip_path(path: Path, lfs_paths: set[Path]) -> bool:
    if path.resolve() in lfs_paths:
        return True
    if path.name in IGNORE_FILE_NAMES:
        return True
    parts = path.parts
    if any(p in IGNORE_DIR_NAMES for p in parts):
        return True
    for needles in IGNORE_PATH_PARTS:
        for i in range(len(parts) - len(needles) + 1):
            if tuple(parts[i:i + len(needles)]) == needles:
                return True
    return False


def _smart_trim(text: str, target: int = DESCRIPTION_TRIM_TARGET) -> str:
    """Trim `text` to <= `target` chars, preferring sentence then word boundary.

    Adds an ellipsis when falling back to a word boundary so the truncation
    is visible. The returned string is guaranteed to be <= target + 3 chars.
    """
    if len(text) <= target:
        return text
    truncated = text[:target]
    for boundary in (". ", "! ", "? "):
        idx = truncated.rfind(boundary)
        if idx >= target * 0.5:
            return truncated[: idx + 1]  # keep punctuation, no ellipsis
    idx = truncated.rfind(" ")
    if idx > 0:
        return truncated[:idx].rstrip(",;:") + "..."
    return truncated.rstrip(",;:") + "..."


def _yaml_double_quote(value: str) -> str:
    """Wrap `value` in YAML double-quotes, escaping `\\` and `"`."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _is_yaml_quoted(value: str) -> bool:
    """True if value is already a balanced double- or single-quoted YAML scalar."""
    stripped = value.strip()
    if len(stripped) < 2:
        return False
    if stripped[0] == '"' and stripped[-1] == '"':
        return True
    if stripped[0] == "'" and stripped[-1] == "'":
        return True
    return False


def _is_balanced_flow_collection(value: str) -> bool:
    """True if value is a YAML flow sequence `[...]` or mapping `{...}`.

    Used to keep `tags: [a, b, c]` and `metadata: {x: 1}` intact — without this
    guard, `_needs_yaml_quoting` would flag the leading `[`/`{` and convert
    the collection into a quoted string, changing its parsed type.
    """
    stripped = value.strip()
    return (stripped.startswith("[") and stripped.endswith("]") and len(stripped) >= 2) or (
        stripped.startswith("{") and stripped.endswith("}") and len(stripped) >= 2
    )


def _opens_multiline_quoted(value: str) -> bool:
    """True if the value starts a quoted scalar that does not close on the same line.

    A `key: "first half ... <newline> ... second half"` block parses fine in
    PyYAML but my line-by-line sanitizer would only see `"first half ...` —
    treating it as an unbalanced quote and double-wrapping it. We detect that
    case and skip the value entirely, leaving the multi-line scalar intact.
    """
    stripped = value.strip()
    if not stripped:
        return False
    if stripped[0] == '"':
        escaped = False
        for ch in stripped[1:]:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == '"':
                return False  # closes on the same line
        return True
    if stripped[0] == "'":
        i = 1
        while i < len(stripped):
            if stripped[i] == "'":
                if i + 1 < len(stripped) and stripped[i + 1] == "'":
                    i += 2  # YAML single-quote escape: `''`
                    continue
                return False
            i += 1
        return True
    return False


def _unquote_yaml(value: str) -> str:
    """Reverse of `_yaml_double_quote` / single-quote form. Returns raw text."""
    stripped = value.strip()
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        return stripped[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if stripped.startswith("'") and stripped.endswith("'") and len(stripped) >= 2:
        return stripped[1:-1].replace("''", "'")
    return stripped


def _needs_yaml_quoting(value: str) -> bool:
    """True when an unquoted YAML scalar would be misparsed.

    The biggest hazard upstream skills hit is an unquoted `description`
    containing `: ` mid-value (YAML parses it as a nested mapping). Balanced
    flow collections (`[a, b]`, `{x: 1}`) and balanced quoted scalars are
    explicitly excluded so their parsed type is preserved.
    """
    stripped = value.strip()
    if not stripped:
        return False
    if _is_yaml_quoted(stripped):
        return False
    if _is_balanced_flow_collection(stripped):
        return False
    if ": " in stripped:
        return True
    if stripped.startswith(_YAML_PROBLEM_PREFIXES):
        return True
    if stripped.endswith(":"):
        return True
    return False


def _sanitize_field_value(key: str, raw_value: str) -> str:
    """Return the new RHS for `key: <rhs>`. Conservative — only touch values
    that would otherwise fail the Codex strict loader.

    Modifications:
      - `description` over `DESCRIPTION_MAX` chars: truncate then double-quote.
      - Any field with unquoted mid-value `: ` (a YAML mapping hazard):
        double-quote.
      - Any other YAML-problem prefix or trailing colon: double-quote.

    Values that are already well-formed are returned unchanged so the
    sanitizer doesn't churn the entire tree on every run.
    """
    stripped = raw_value.strip()
    inner = _unquote_yaml(raw_value)

    if key == "description" and len(inner) > DESCRIPTION_MAX:
        return _yaml_double_quote(_smart_trim(inner))

    if _is_yaml_quoted(stripped):
        return raw_value

    if _needs_yaml_quoting(raw_value):
        return _yaml_double_quote(inner)

    return raw_value


def _collect_indented_body(lines: list[str], start_idx: int, end_idx: int) -> tuple[list[str], int]:
    """Collect indented continuation lines starting at `start_idx`, up to `end_idx`.

    Stops at the first non-indented non-blank line, the closing `---`, or
    `end_idx`. Returns (stripped body lines, index just past the block).
    """
    body: list[str] = []
    j = start_idx
    while j < end_idx:
        line = lines[j]
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped and not line.startswith((" ", "\t")):
            break
        body.append(stripped)
        j += 1
    while body and not body[-1]:
        body.pop()
    return body, j


def _fold_scalar(body_lines: list[str], style: str) -> str:
    """Approximate YAML folded (`>`) / literal (`|`) scalar joining.

    Folded: consecutive non-blank lines join with a single space; a blank line
    becomes a real newline. Literal: every line break is preserved.
    """
    if style.startswith("|"):
        return "\n".join(body_lines).rstrip()
    out: list[str] = []
    buf: list[str] = []
    for line in body_lines:
        if not line:
            if buf:
                out.append(" ".join(buf))
                buf = []
            out.append("")
        else:
            buf.append(line)
    if buf:
        out.append(" ".join(buf))
    folded = "\n".join(out)
    while "\n\n\n" in folded:
        folded = folded.replace("\n\n\n", "\n\n")
    return folded.strip()


def _extract_description_from_body(body: str) -> str:
    """Heuristic pick of a description from a markdown body.

    Order of preference: first `## Overview` / `## Description` / `## About`
    section body, otherwise the first non-empty paragraph that isn't a heading
    or a list. Returns an empty string if nothing usable is found.
    """
    lines = body.splitlines()

    # Preferred sections (case-insensitive header match).
    preferred_headers = {"overview", "description", "about", "summary"}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## ") and stripped[3:].strip().lower() in preferred_headers:
            paragraph: list[str] = []
            for follow in lines[i + 1 :]:
                fstrip = follow.strip()
                if fstrip.startswith("#"):
                    break
                if not fstrip:
                    if paragraph:
                        break
                    continue
                if fstrip.startswith(("-", "*", ">", "|", "```")):
                    if paragraph:
                        break
                    continue
                paragraph.append(fstrip)
            if paragraph:
                return " ".join(paragraph)

    # Otherwise: first non-empty plain paragraph that isn't a heading/list/code.
    paragraph = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if paragraph:
                return " ".join(paragraph)
            continue
        if stripped.startswith(("#", "-", "*", ">", "|", "```")):
            if paragraph:
                return " ".join(paragraph)
            continue
        paragraph.append(stripped)
    return " ".join(paragraph)


def _synthesize_frontmatter(skill_file: Path) -> str:
    """Generate `---\\nname: ...\\ndescription: ...\\n---` from filename + body.

    Used when a SKILL.md is pure markdown with no `---`-delimited block at all.
    """
    text = skill_file.read_text(encoding="utf-8", errors="ignore")
    name = skill_file.parent.name

    # Strip a leading H1 (`# Title`) — keep it as a fallback description and
    # remove it from the synthesized body so we don't double-print.
    body = text
    h1_fallback = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# ") and not s.startswith("## "):
            h1_fallback = s[2:].strip()
        break

    description = _extract_description_from_body(body) or h1_fallback or name
    if len(description) > DESCRIPTION_MAX:
        description = _smart_trim(description)
    quoted = _yaml_double_quote(description)
    new_frontmatter = f"---\nname: {name}\ndescription: {quoted}\n---\n\n"
    skill_file.write_text(new_frontmatter + text, encoding="utf-8")
    return "synthesized"


def _reorder_preamble(lines: list[str]) -> list[str] | None:
    """If frontmatter is preceded by a preamble, move the preamble below.

    Returns the reordered line list, or None if frontmatter is absent.
    """
    if lines and lines[0].strip() == "---":
        return lines

    marker_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(marker_indices) < 2:
        return None

    start, end = marker_indices[0], marker_indices[1]
    fm_body = "".join(lines[start + 1 : end])
    if "description:" not in fm_body and "name:" not in fm_body:
        return None

    preamble = lines[:start]
    frontmatter = lines[start : end + 1]
    body = lines[end + 1 :]

    reordered = list(frontmatter)
    if reordered and not reordered[-1].endswith("\n"):
        reordered[-1] += "\n"
    if preamble:
        reordered.append("\n")
        reordered.extend(preamble)
    reordered.extend(body)
    return reordered


def sanitize_skill_frontmatter(skill_file: Path) -> str:
    """Fix common SKILL.md frontmatter issues that break Codex's strict loader.

    Returns one of:
      - "valid"               nothing to change
      - "sanitized"           file rewritten with fixes
      - "missing_frontmatter" no parseable `---`-delimited block at top

    Fixes applied:
      1. Move any preamble (e.g. copyright header) below the frontmatter so
         the file starts with `---`.
      2. Cap `description` at 1024 characters with a sentence-aware trim.
      3. Double-quote any top-level value that contains a bare mid-value `: `
         (which YAML otherwise treats as a nested mapping) or other
         indicator characters.
    """
    try:
        text = skill_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = skill_file.read_text(errors="ignore")

    lines = text.splitlines(keepends=True)
    reordered = _reorder_preamble(lines)
    if reordered is None:
        # No recoverable frontmatter at all — synthesize minimal one so the
        # strict Codex loader can pick it up. Falls back to dir name + first
        # markdown paragraph.
        _synthesize_frontmatter(skill_file)
        return "synthesized"
    lines = reordered

    if not lines or lines[0].strip() != "---":
        return "missing_frontmatter"

    end_idx = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end_idx is None:
        return "missing_frontmatter"

    i = 1
    while i < end_idx:
        line = lines[i]
        stripped = line.strip()
        if not stripped or line.startswith((" ", "\t", "#")):
            i += 1
            continue
        match = _FIELD_LINE.match(line.rstrip("\n"))
        if not match:
            i += 1
            continue
        key, value = match.group(1), match.group(2)

        # A `key: "..."` that doesn't close on the same line is a legitimate
        # multi-line quoted scalar — line-by-line rewriting would corrupt it,
        # so skip the field entirely and let YAML handle it.
        if _opens_multiline_quoted(value):
            i += 1
            continue

        # Detect the broken `key: ">"` (or `"|"`, `">-"`, etc.) pattern where
        # the author quoted the YAML scalar style indicator and put the body
        # on the indented lines below. Collapse the body into a real quoted
        # scalar.
        unquoted = _unquote_yaml(value)
        if unquoted in _FOLDED_SCALAR_MARKERS:
            body, next_i = _collect_indented_body(lines, i + 1, end_idx)
            if body:
                folded = _fold_scalar(body, unquoted)
                if key == "description" and len(folded) > DESCRIPTION_MAX:
                    folded = _smart_trim(folded)
                lines[i:next_i] = [f"{key}: {_yaml_double_quote(folded)}\n"]
                end_idx -= (next_i - i - 1)
                i += 1
                continue

        new_value = _sanitize_field_value(key, value)
        if new_value != value:
            lines[i] = f"{key}: {new_value}\n"
        i += 1

    new_text = "".join(lines)
    if new_text != text:
        skill_file.write_text(new_text, encoding="utf-8")
        return "sanitized"
    return "valid"


# Backwards-compatible alias retained so the older import path still works.
normalize_skill_frontmatter = sanitize_skill_frontmatter


def copy_skill(src: Path, dest: Path, lfs_paths: set[Path]) -> tuple[int, int, int]:
    """Copy src tree into dest, filtering.

    Returns (files copied, frontmatter blocks normalized, missing frontmatter).
    """
    if dest.exists():
        shutil.rmtree(dest)
    files_copied = 0
    frontmatter_normalized = 0
    missing_frontmatter = 0
    for root, dirs, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if d not in IGNORE_DIR_NAMES]
        # Filter dirs by path-part pattern
        dirs[:] = [d for d in dirs if not should_skip_path(Path(root) / d, lfs_paths)]
        target_root = dest / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(root) / f
            if should_skip_path(src_file, lfs_paths):
                continue
            try:
                if src_file.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            target_file = target_root / f
            shutil.copy2(src_file, target_file)
            if f == "SKILL.md":
                status = sanitize_skill_frontmatter(target_file)
                if status == "sanitized":
                    frontmatter_normalized += 1
                elif status == "missing_frontmatter":
                    missing_frontmatter += 1
            files_copied += 1
    return files_copied, frontmatter_normalized, missing_frontmatter


def skill_frontmatter_name(skill_root: Path) -> str:
    """Read the loader's identity, rather than assuming the directory name."""
    lines = (skill_root / "SKILL.md").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing frontmatter: {skill_root / 'SKILL.md'}")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError(f"Unclosed frontmatter: {skill_root / 'SKILL.md'}")
    metadata = yaml.safe_load("\n".join(lines[1:end]))
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Missing string name: {skill_root / 'SKILL.md'}")
    return name


def skill_tree_digest(root: Path) -> str:
    """Hash the complete copied tree, including paths, empty dirs and links.

    Links are hashed as links and never traversed. Executable bits matter;
    timestamps and other host-specific permissions do not.
    """
    digest = hashlib.sha256()

    def visit(path: Path, relative: str) -> None:
        if path.is_symlink():
            kind, content = b"link", os.readlink(path).encode()
        elif path.is_dir():
            kind, content = b"dir", b""
        elif path.is_file():
            kind = b"executable" if path.stat().st_mode & 0o111 else b"file"
            content = path.read_bytes()
        else:
            raise ValueError(f"Unsupported tree entry: {path}")
        for part in (kind, relative.encode(), content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
        if kind == b"dir":
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(child, f"{relative}/{child.name}")

    visit(root, ".")
    return digest.hexdigest()


def _origin_key(origin: dict) -> tuple[str | None, str | None]:
    return origin.get("repository"), origin.get("path")


class LibrarySources:
    """Protect unproven content and track each observation without guessing.

    A matching repository/path can update its sole, unmodified recorded copy.
    Shared, modified, or legacy copies are preserved and get a new variant.
    Historical observations keep ``current: false`` when a source advances.
    """

    def __init__(self, skills_dest: Path, metadata_path: Path):
        self.skills_dest = skills_dest
        self.metadata_path = metadata_path
        self.entries: dict = {}
        self.actual: dict[str, tuple[str | None, str]] = {}
        if metadata_path.exists():
            self.entries = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(self.entries, dict):
                raise ValueError("library_sources.json must be an object")
            for skill_id, entry in self.entries.items():
                if (
                    not isinstance(skill_id, str)
                    or skill_id in {".", ".."}
                    or Path(skill_id).name != skill_id
                    or not isinstance(entry, dict)
                    or not isinstance(entry.get("origins"), list)
                    or not all(isinstance(origin, dict) for origin in entry["origins"])
                ):
                    raise ValueError(f"Invalid library provenance record: {skill_id!r}")
        if not skills_dest.exists():
            return
        for root in sorted(skills_dest.iterdir()):
            if not root.is_symlink() and not (root.is_dir() and (root / "SKILL.md").is_file()):
                continue
            name = None
            if not root.is_symlink():
                try:
                    name = skill_frontmatter_name(root)
                except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                    # An invalid old skill still cannot be overwritten.
                    pass
            tree_digest = skill_tree_digest(root)
            self.actual[root.name] = name, tree_digest
            if root.name not in self.entries:
                self.entries[root.name] = {
                    "name": name,
                    "digest": tree_digest,
                    "origins": [
                        {
                            "kind": "legacy",
                            "path": f"skills/{root.name}",
                            "note": "Pre-existing content; upstream provenance is unknown.",
                        }
                    ],
                }
            elif self.entries[root.name].get("digest") != tree_digest:
                self.entries[root.name]["locally_modified"] = True

    def _refresh(self, skill_id: str) -> None:
        """Recheck a destination immediately before deduplication/replacement."""
        root = self.skills_dest / skill_id
        if not os.path.lexists(root):
            self.actual.pop(skill_id, None)
            return
        name = None
        if not root.is_symlink():
            try:
                name = skill_frontmatter_name(root)
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                pass
        tree_digest = skill_tree_digest(root)
        self.actual[skill_id] = name, tree_digest
        if self.entries[skill_id].get("digest") != tree_digest:
            self.entries[skill_id]["locally_modified"] = True

    def _observe(self, skill_id: str, origin: dict) -> None:
        key = _origin_key(origin)
        for other_id, entry in self.entries.items():
            for previous in entry["origins"]:
                if _origin_key(previous) == key:
                    previous["current"] = other_id == skill_id
        origins = self.entries[skill_id]["origins"]
        existing = next((o for o in origins if _origin_key(o) == key), None)
        if existing is None:
            origins.append(origin)
        else:
            existing.update(origin)

    def _variant_id(self, base: str, source_name: str, origin: dict) -> str:
        source = re.sub(r"[^a-zA-Z0-9_-]", "-", source_name)
        key = json.dumps(_origin_key(origin), ensure_ascii=True).encode()
        qualified = f"{base}--{source}--{hashlib.sha256(key).hexdigest()[:10]}"
        skill_id = qualified
        suffix = 2
        while skill_id in self.entries or os.path.lexists(self.skills_dest / skill_id):
            skill_id = f"{qualified}-{suffix}"
            suffix += 1
        return skill_id

    def install(self, candidate: Path, source_name: str, origin: dict) -> tuple[str, str]:
        name = skill_frontmatter_name(candidate)
        tree_digest = skill_tree_digest(candidate)
        same_content = sorted(skill_id for skill_id, actual in self.actual.items() if actual == (name, tree_digest))
        for skill_id in same_content:
            self._refresh(skill_id)
            if self.actual.get(skill_id) == (name, tree_digest):
                self._observe(skill_id, origin)
                return skill_id, "deduplicated"

        key = _origin_key(origin)
        previous = [
            skill_id
            for skill_id, entry in self.entries.items()
            if skill_id in self.actual
            and any(_origin_key(o) == key and o.get("current", True) for o in entry["origins"])
        ]
        for skill_id in previous:
            self._refresh(skill_id)
        replaceable = [
            skill_id
            for skill_id in previous
            if skill_id in self.actual
            and not self.entries[skill_id].get("locally_modified")
            and self.entries[skill_id].get("digest") == self.actual[skill_id][1]
            and all(_origin_key(o) == key for o in self.entries[skill_id]["origins"])
            and not (self.skills_dest / skill_id).is_symlink()
        ]
        if len(replaceable) == 1:
            skill_id = replaceable[0]
            action = "updated"
        else:
            skill_id = candidate.name
            same_name = any(actual[0] == name for actual in self.actual.values())
            if same_name or skill_id in self.entries or os.path.lexists(self.skills_dest / skill_id):
                skill_id = self._variant_id(skill_id, source_name, origin)
            action = "new"

        # Overwrite is reachable only with a sole recorded repository/path and
        # an unchanged full-tree digest. Unproven roots always get a variant.
        copy_skill(candidate, self.skills_dest / skill_id, set())
        self.actual[skill_id] = name, tree_digest
        self.entries[skill_id] = {"name": name, "digest": tree_digest, "origins": []}
        self._observe(skill_id, origin)
        conflicts = self.conflicts().get(name, [])
        if conflicts:
            print(f"  NAME CONFLICT {name!r}: {', '.join(conflicts)}; all variants preserved", file=sys.stderr)
        return skill_id, action

    def conflicts(self) -> dict[str, list[str]]:
        names: dict[str, list[str]] = {}
        for skill_id, (name, _) in self.actual.items():
            if name is not None:
                names.setdefault(name, []).append(skill_id)
        return {
            name: sorted(ids) for name, ids in names.items() if len({self.actual[skill_id][1] for skill_id in ids}) > 1
        }

    def save(self) -> None:
        conflicts = self.conflicts()
        for skill_id, entry in self.entries.items():
            entry.pop("conflicts", None)
            if skill_id in self.actual and self.actual[skill_id][0] in conflicts:
                entry["conflicts"] = conflicts[self.actual[skill_id][0]]
        content = json.dumps(self.entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if self.metadata_path.exists() and self.metadata_path.read_text(encoding="utf-8") == content:
            return
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.metadata_path.parent,
            prefix=f".{self.metadata_path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(self.metadata_path)
        finally:
            temporary_path.unlink(missing_ok=True)


def sync_upstream(url: str, name: str, description: str, staging: Path, stats: dict, library: LibrarySources):
    repo_dir = staging / name
    print(f"\n[{name}] {description}")
    print(f"  cloning {url} ...")
    if not shallow_clone(url, repo_dir):
        stats[name] = {"new": 0, "updated": 0, "removed": 0, "total": 0, "error": "clone_failed"}
        return
    revision = run(["git", "rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()
    lfs_paths = find_lfs_pointer_files(repo_dir)
    if lfs_paths:
        print(f"  flagged {len(lfs_paths)} LFS pointer files to skip")
    roots = find_skill_roots(repo_dir)
    new = updated = deduplicated = invalid = 0
    frontmatter_normalized = 0
    missing_frontmatter = 0
    for root in roots:
        skill_name = root.name
        if skill_name.startswith(".") or skill_name in SKIP_TOPLEVEL_NAMES:
            continue
        # Compare the final filtered/sanitized content, not the raw upstream.
        prepared = staging / "prepared" / name / root.relative_to(repo_dir)
        _, normalized_count, missing_count = copy_skill(root, prepared, lfs_paths)
        frontmatter_normalized += normalized_count
        missing_frontmatter += missing_count
        origin = {
            "repository": url,
            "revision": revision,
            "path": root.relative_to(repo_dir).as_posix(),
            "current": True,
        }
        try:
            _, action = library.install(prepared, name, origin)
        except (ValueError, yaml.YAMLError) as error:
            invalid += 1
            print(f"  invalid skill {origin['path']}: {error}", file=sys.stderr)
            continue
        if action == "updated":
            updated += 1
        elif action == "new":
            new += 1
        else:
            deduplicated += 1
    print(
        f"  installed: {new} new, {updated} updated, {deduplicated} deduplicated, {invalid} invalid (total roots: {len(roots)})"
    )
    if frontmatter_normalized or missing_frontmatter:
        print(f"  frontmatter: {frontmatter_normalized} normalized, {missing_frontmatter} missing")
    stats[name] = {
        "new": new,
        "updated": updated,
        "deduplicated": deduplicated,
        "invalid": invalid,
        "removed": 0,
        "total": len(roots),
        "frontmatter_normalized": frontmatter_normalized,
        "missing_frontmatter": missing_frontmatter,
    }


def write_summary(stats: dict, before: int, after: int) -> str:
    lines = [
        "Per-repo sync summary:",
        "",
        "| Source | New | Updated | Deduplicated | Invalid | Total roots |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for repo, s in stats.items():
        if "error" in s:
            lines.append(f"| {repo} | — | — | — | — | error: {s['error']} |")
        else:
            lines.append(
                f"| {repo} | {s['new']} | {s['updated']} | {s.get('deduplicated', 0)} | {s.get('invalid', 0)} | {s['total']} |"
            )
            if s.get("frontmatter_normalized") or s.get("missing_frontmatter"):
                lines.append(
                    f"| frontmatter | {s.get('frontmatter_normalized', 0)} normalized | "
                    f"{s.get('missing_frontmatter', 0)} missing |  |  |  |"
                )
    lines.append("")
    lines.append(f"Skills before: {before}, after: {after} (delta: {after - before:+d})")
    return "\n".join(lines)


def update_readme_counts(readme: Path, skill_count: int, source_count: int) -> bool:
    """Rewrite the skill/source count figures in README.md to match the live tree.

    Keeps the README's headline numbers dynamic so they never drift between
    weekly syncs. Each substitution is anchored to stable surrounding text and
    is idempotent — a no-op run leaves the file byte-identical.

    Figures updated:
      - Skills shield badge + intro/bootstrap prose: rounded ``<floor>+``
        (e.g. 1973 -> ``1,900+``), since those read as "at least".
      - Repo-layout tree comment: the exact live count (e.g. ``1,973``).
      - Sources shield badge + intro + heading: the exact ``source_count``.

    Returns True if the file changed.
    """
    if not readme.exists():
        return False
    text = original = readme.read_text(encoding="utf-8")

    floor = (skill_count // SKILL_COUNT_FLOOR_STEP) * SKILL_COUNT_FLOOR_STEP
    floor_str = f"{floor:,}"
    exact_str = f"{skill_count:,}"

    substitutions = [
        # Skills "+floor" figures (the badge URL-encodes "+" as "%2B").
        (r"(badge/skills-)[\d,]+(?:%2B|\+)(-brightgreen)", rf"\g<1>{floor}%2B\g<2>"),
        (r"(collection of )[\d,]+\+( agent skills)", rf"\g<1>{floor_str}+\g<2>"),
        (r"(with \*\*)[\d,]+\+( vetted skills\*\*)", rf"\g<1>{floor_str}+\g<2>"),
        # Repo-layout tree comment: exact count.
        (r"(← )[\d,]+\+?( skill dirs)", rf"\g<1>{exact_str}\g<2>"),
        # Source count: badge, intro sentence, and Sources heading.
        (r"(badge/upstream%20sources-)\d+(-blue)", rf"\g<1>{source_count}\g<2>"),
        (r"(from )\d+( upstream curated collections)", rf"\g<1>{source_count}\g<2>"),
        (r"(Currently \*\*)\d+( sources\*\*)", rf"\g<1>{source_count}\g<2>"),
    ]
    for pattern, repl in substitutions:
        text = re.sub(pattern, repl, text)

    if text != original:
        readme.write_text(text, encoding="utf-8")
        return True
    return False


def _installer():
    """The installer defines how SKILL.md frontmatter is read; the index must agree with it."""
    path = Path(__file__).with_name("install_skills.py")
    spec = importlib.util.spec_from_file_location("awesome_skills_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_library_index(skills: Path = SKILLS_DEST, path: Path = LIBRARY_INDEX_PATH) -> bool:
    """Regenerate the committed full-library index (names and descriptions) the installer
    reads instead of downloading every skill body. Returns True when the file changed."""
    installer = _installer()
    content = installer.index_text(installer.build_index(skills))
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return True


def sanitize_only(target: Path) -> int:
    """Walk `target` and apply `sanitize_skill_frontmatter` to every SKILL.md.

    Used both as a one-shot cleanup of the in-tree `skills/` directory and as
    a unit-friendly entry point for tests. Returns the process exit code.
    """
    if not target.exists():
        print(f"sanitize-only: {target} does not exist", file=sys.stderr)
        return 1

    total = sanitized = synthesized = invalid = 0
    invalid_files: list[Path] = []
    for skill_md in sorted(target.rglob("SKILL.md")):
        total += 1
        status = sanitize_skill_frontmatter(skill_md)
        if status == "sanitized":
            sanitized += 1
            print(f"  sanitized: {skill_md.relative_to(target.parent)}")
        elif status == "synthesized":
            synthesized += 1
            print(f"  synthesized frontmatter: {skill_md.relative_to(target.parent)}")
        elif status == "missing_frontmatter":
            invalid += 1
            invalid_files.append(skill_md)

    print()
    print(
        f"sanitize-only: scanned {total}, rewrote {sanitized}, "
        f"synthesized {synthesized}, {invalid} unrecoverable"
    )
    if invalid_files:
        for f in invalid_files[:20]:
            print(f"  unrecoverable: {f.relative_to(target.parent)}", file=sys.stderr)
        if len(invalid_files) > 20:
            print(f"  ... and {len(invalid_files) - 20} more", file=sys.stderr)
    if target.resolve() == SKILLS_DEST.resolve() and write_library_index():
        print(f"Updated {LIBRARY_INDEX_PATH.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sanitize-only",
        action="store_true",
        help="skip upstream sync; only normalize/sanitize existing SKILL.md files in ./skills/",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="skip upstream sync; only regenerate library_index.json from ./skills/",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=SKILLS_DEST,
        help="directory to sanitize when --sanitize-only is set (default: ./skills/)",
    )
    args = parser.parse_args(argv)

    if args.sanitize_only:
        return sanitize_only(args.target)
    if args.index_only:
        print(f"{LIBRARY_INDEX_PATH.name}: {'updated' if write_library_index() else 'already current'}")
        return 0

    SKILLS_DEST.mkdir(parents=True, exist_ok=True)
    try:
        library = LibrarySources(SKILLS_DEST, LIBRARY_SOURCES_PATH)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Cannot safely load library provenance: {error}", file=sys.stderr)
        return 1
    before = sum(1 for p in SKILLS_DEST.iterdir() if p.is_dir())
    print(f"Skills before: {before}")
    stats: dict = {}
    with tempfile.TemporaryDirectory(prefix="awesome-skills-staging-") as tmpdir:
        staging = Path(tmpdir)
        for url, name, desc in UPSTREAMS:
            sync_upstream(url, name, desc, staging, stats, library)
    library.save()
    if write_library_index():
        print(f"Updated {LIBRARY_INDEX_PATH.name}")
    after = sum(1 for p in SKILLS_DEST.iterdir() if p.is_dir())
    if update_readme_counts(README_PATH, after, len(UPSTREAMS)):
        print(f"Updated README counts: {after:,} skills, {len(UPSTREAMS)} sources")
    print()
    summary = write_summary(stats, before, after)
    conflicts = library.conflicts()
    if conflicts:
        summary += "\n\nFrontmatter name conflicts (variants preserved):\n"
        summary += "\n".join(f"- `{name}`: {', '.join(ids)}" for name, ids in sorted(conflicts.items()))
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        Path(step_summary).write_text(summary + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
