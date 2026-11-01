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
import copy
import functools
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
# Exit status when some upstream skills were rejected but the valid rest was synced.
# The workflow commits the valid rest, then fails the run so the rejection is seen.
REJECTED_EXIT = 3
# Codex refuses a skill name over 64 characters, and every Codex copy is named after its ID;
# 61 leaves room for the `-N` suffix of a taken variant ID.
VARIANT_ID_MAX = 61

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
# Valid unquoted block scalars with these headers are collapsed the same way,
# and that output must stay byte-for-byte what it has been: library_sources.json
# pins every sanitized tree's digest, and a legacy or shared copy is never
# replaced in place, so any change to the sanitized form of an upstream skill
# adds a duplicate variant at the next sync. A multi-line result keeps its raw
# line breaks; `_indent_flow_lines` then indents its continuation lines, which
# Claude Code requires and YAML folding ignores.
_FOLDED_SCALAR_MARKERS = {">", ">-", ">+", "|", "|-", "|+"}
# Characters a double-quoted YAML scalar must not hold raw: those YAML forbids,
# a carriage return, and the line breaks only YAML 1.1 (PyYAML) folds. Tabs and
# line feeds stay raw.
_DQ_ESCAPE = re.compile("[^\t\n\x20-\x7e\xa0-\u2027\u202a-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_DQ_NAMED_ESCAPES = {"\0": "\\0", "\r": "\\r", "\x1b": "\\e", "\x85": "\\N", "\u2028": "\\L", "\u2029": "\\P"}

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
    (
        "https://github.com/AIScientists-Dev/academic-humanizer.git",
        "academic-humanizer",
        "Academic-humanizer — clarify & de-AI academic prose and grant proposals",
    ),
    (
        "https://github.com/google-deepmind/science-skills.git",
        "gdm-science",
        "Google DeepMind Science Skills — genomics, structural bio, cheminformatics, literature DBs",
    ),
    ("https://github.com/adaptyvbio/protein-design-skills.git", "adaptyv-protein", "Adaptyv protein-design [P0]"),
    # --- general-purpose dev/productivity collections ---
    ("https://github.com/wshobson/agents.git", "wshobson-agents", "wshobson agents (155 dev skills, 35.5k ⭐)"),
    (
        "https://github.com/anthropics/claude-plugins-official.git",
        "anthropics-plugins",
        "Anthropic official plugins (19.5k ⭐)",
    ),
    # --- foundational / official collections ---
    (
        "https://github.com/forrestchang/andrej-karpathy-skills.git",
        "karpathy-skills",
        "Andrej Karpathy CLAUDE.md skill (133.3k ⭐)",
    ),
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
    """A command in `cwd`; git finds no repository above that folder (a shared temporary directory may
    hold another user's .git, whose url.*.insteadOf or core.sshCommand git would honor)."""
    env = None if cwd is None else {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(cwd).resolve().parent)}
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True, env=env)


def shallow_clone(url: str, dest: Path) -> bool:
    try:
        run(["git", "clone", "--depth", "1", "--single-branch", url, str(dest)], cwd=dest.parent)
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
            if tuple(parts[i : i + len(needles)]) == needles:
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
    """Wrap `value` in YAML double-quotes, escaping `\\`, `"` and the characters a quoted scalar
    must not hold raw (`_DQ_ESCAPE`). Line feeds stay raw line breaks, which YAML folds."""

    def escape(match: re.Match) -> str:
        char = match.group()
        if char in _DQ_NAMED_ESCAPES:
            return _DQ_NAMED_ESCAPES[char]
        return f"\\x{ord(char):02x}" if ord(char) < 0x100 else f"\\u{ord(char):04x}"

    escaped = _DQ_ESCAPE.sub(escape, value.replace("\\", "\\\\").replace('"', '\\"'))
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
    """Reverse of `_yaml_double_quote` / single-quote form. Returns raw text.

    A double-quoted value is decoded as YAML reads it, so escapes count as the one character
    they stand for in the length cap and are not escaped a second time when it is re-quoted."""
    stripped = value.strip()
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        try:
            loaded = yaml.safe_load(stripped)
        except yaml.YAMLError:
            loaded = None
        if isinstance(loaded, str):
            return loaded
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


def _shallow_flow_lines(text: str) -> list[tuple[int, int]]:
    """(offset, spaces to add) for each line of a multi-line quoted scalar or flow collection in
    YAML `text` that is not indented deeper than the block collection holding it. PyYAML ignores
    that indentation, but YAML requires it, and Claude Code rejects such frontmatter as a whole
    (it then drops every field, disable-model-invocation included). Adding spaces brings the line
    two columns past its block; YAML folding drops leading whitespace, so values stay the same."""
    try:
        tokens = list(yaml.scan(text))
    except yaml.YAMLError:
        return []
    spans, blocks, depth, start = [], [-1], 0, 0
    for token in tokens:
        if isinstance(token, yaml.BlockMappingStartToken | yaml.BlockSequenceStartToken):
            blocks.append(token.start_mark.column)
        elif isinstance(token, yaml.BlockEndToken):
            blocks.pop()
        elif isinstance(token, yaml.FlowSequenceStartToken | yaml.FlowMappingStartToken):
            start = token.start_mark.index if depth == 0 else start
            depth += 1
        elif isinstance(token, yaml.FlowSequenceEndToken | yaml.FlowMappingEndToken):
            depth -= 1
            if depth == 0:
                spans.append((start, token.end_mark.index, blocks[-1]))
        elif depth == 0 and isinstance(token, yaml.ScalarToken) and token.style in ('"', "'"):
            spans.append((token.start_mark.index, token.end_mark.index, blocks[-1]))
    found = []
    for begin, end, column in spans:
        k = text.find("\n", begin, end)
        while k != -1:
            j = k + 1
            while text[j : j + 1] == " ":
                j += 1
            if text[j : j + 1] not in ("", "\r", "\n") and j - k - 1 <= column:
                found.append((k + 1, column + 3 - (j - k)))
            k = text.find("\n", k + 1, end)
    return found


def _indent_flow_lines(text: str) -> str:
    """Canonicalization B: indent the lines `_shallow_flow_lines` finds, so that a column-0 line
    under a top-level key gains two spaces. Claude Code then parses what PyYAML always read."""
    out, last = [], 0
    for offset, spaces in _shallow_flow_lines(text):
        out += [text[last:offset], " " * spaces]
        last = offset
    return "".join(out) + text[last:]


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
      4. Indent the lines of multi-line quoted scalars and flow collections
         that are not deeper than their block (`_indent_flow_lines`), which
         Claude Code cannot parse.
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
                end_idx -= next_i - i - 1
                i += 1
                continue

        new_value = _sanitize_field_value(key, value)
        if new_value != value:
            lines[i] = f"{key}: {new_value}\n"
        i += 1

    frontmatter = "".join(lines[1:end_idx])
    lines[1:end_idx] = [_indent_flow_lines(frontmatter)]
    new_text = "".join(lines)
    if new_text != text:
        skill_file.write_text(new_text, encoding="utf-8")
        return "sanitized"
    return "valid"


# Backwards-compatible alias retained so the older import path still works.
normalize_skill_frontmatter = sanitize_skill_frontmatter


def copy_skill(src: Path, dest: Path, lfs_paths: set[Path], within: Path | None = None) -> tuple[int, int, int]:
    """Copy src tree into dest, filtering.

    A file link is followed only to a regular file of `within` (the upstream checkout; by default
    src) outside its .git: any other is copied as the link it is, which candidate_problems rejects,
    so no file of the runner (its .git/config, /dev/zero) ever becomes library content.

    Returns (files copied, frontmatter blocks normalized, missing frontmatter).
    """
    if dest.exists():
        shutil.rmtree(dest)
    base = (within or src).resolve()
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
            target_file = target_root / f
            if src_file.is_symlink():
                resolved = src_file.resolve()
                inside = resolved.is_relative_to(base) and not set(resolved.relative_to(base).parts) & IGNORE_DIR_NAMES
                if not (inside and resolved.is_file()):
                    os.symlink(os.readlink(src_file), target_file)
                    files_copied += 1
                    continue
            try:
                if src_file.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
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


def _reserved(skill_id: str) -> bool:
    """Library IDs that would shadow a bundled Codex system skill (a plain `$ID` then matches
    two skills and injects neither); such a skill gets a source-qualified variant ID."""
    return skill_id.casefold() in _installer().CODEX_SYSTEM_SKILLS


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
        """`base--source--hash`, with base shortened so that the ID, even with a `-N` suffix,
        stays within the 64 characters Codex accepts as a skill name."""
        source = re.sub(r"[^a-zA-Z0-9_-]", "-", source_name)
        key = json.dumps(_origin_key(origin), ensure_ascii=True).encode()
        tail = f"--{source}--{hashlib.sha256(key).hexdigest()[:10]}"
        qualified = base[: max(1, VARIANT_ID_MAX - len(tail))].rstrip("-") + tail
        skill_id = qualified
        suffix = 2
        while self._taken(skill_id):
            skill_id = f"{qualified}-{suffix}"
            suffix += 1
        return skill_id

    def _taken(self, skill_id: str) -> bool:
        """An ID is taken by an exact or case-only match: Windows and macOS cannot hold both.
        The bundled Codex system skill names are always taken."""
        if skill_id in self.entries or os.path.lexists(self.skills_dest / skill_id) or _reserved(skill_id):
            return True
        folded = skill_id.casefold()
        return any(other.casefold() == folded for other in (*self.entries, *self.actual))

    def release_reserved(self) -> list[tuple[str, str]]:
        """Move each library skill whose ID is reserved (`_reserved`) to the variant ID its
        current upstream origin gives it, with its provenance. Returns (old, new) ID pairs."""
        sources = {url: name for url, name, _ in UPSTREAMS}
        moved = []
        for skill_id in sorted(self.actual):
            root = self.skills_dest / skill_id
            if not _reserved(skill_id) or root.is_symlink() or skill_id not in self.entries:
                continue
            origins = self.entries[skill_id]["origins"] or [{"path": f"skills/{skill_id}"}]
            current = [o for o in origins if o.get("repository") in sources and o.get("current", True)]
            origin = (current or origins)[0]
            new_id = self._variant_id(skill_id, sources.get(origin.get("repository"), "legacy"), origin)
            root.rename(self.skills_dest / new_id)
            self.entries[new_id] = self.entries.pop(skill_id)
            self.actual[new_id] = self.actual.pop(skill_id)
            moved.append((skill_id, new_id))
        return moved

    def accept_sanitized(self, skill_ids) -> None:
        """Record the sanitizer's own rewrite of unmodified copies: their recorded digest follows
        the new content, as if a sync had installed the newly sanitized upstream tree."""
        for skill_id in skill_ids:
            root = self.skills_dest / skill_id
            if skill_id not in self.actual or root.is_symlink():
                continue
            entry = self.entries[skill_id]
            unmodified = entry.get("digest") == self.actual[skill_id][1] and not entry.get("locally_modified")
            try:
                name = skill_frontmatter_name(root)
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                name = None
            self.actual[skill_id] = name, skill_tree_digest(root)
            if unmodified:
                entry["name"], entry["digest"] = self.actual[skill_id]

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
            if same_name or self._taken(skill_id):
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


def candidate_problems(prepared: Path, skill_id: str) -> list[str]:
    """Why a filtered, sanitized upstream skill must not enter skills/: the installer's own
    portability rules (Windows names, case-only collisions, links, git metadata files)
    plus frontmatter it can parse. Checked before anything is copied into the library.

    A remote install verifies each copy's name with the installer's standard-library reader
    against library_index.json, which PyYAML wrote, so both must read the same name."""
    installer = _installer()
    kinds = {}
    for path in sorted(prepared.rglob("*")):
        if path.is_symlink():
            kinds[path.relative_to(prepared).as_posix()] = "link"
        elif path.is_file():
            kinds[path.relative_to(prepared).as_posix()] = "file"
    problems = installer.skill_problems(skill_id, kinds)
    if "link" in kinds.values():
        return problems  # never read through a link: it may lead to any file of the runner
    try:
        data = (prepared / "SKILL.md").read_bytes()
        metadata = installer.metadata(data, skill_id)
    except (installer.InstallError, OSError) as error:
        problems.append(str(error))
        return problems
    name = metadata["name"]
    try:
        plain = installer.frontmatter_name(data, skill_id)
    except installer.InstallError as error:
        problems.append(f"remote installs cannot read the frontmatter name without PyYAML ({error})")
    else:
        if plain != name:
            problems.append(f"frontmatter name {name!r} reads as {plain!r} without PyYAML")
    return problems + copy_problems(prepared, skill_id, data, metadata)


def copy_problems(prepared: Path, skill_id: str, data: bytes, metadata: dict | None = None) -> list[str]:
    """Why the installer could not make this skill's hidden or Codex copies safely: the frontmatter
    Claude Code cannot parse (it would then ignore disable-model-invocation), then
    `hidden_copy_problems`. The installer asks this of every skill it edits from a local tree."""
    installer = _installer()
    metadata = installer.metadata(data, skill_id) if metadata is None else metadata
    problems = []
    text = installer.frontmatter(data, skill_id)
    if _shallow_flow_lines(text):
        problems.append(
            "frontmatter has a multi-line quoted scalar or flow collection with a line not indented past "
            "its key, which Claude Code cannot parse"
        )
    # Claude Code 2.1.316 takes the frontmatter as /^---\s*\n([\s\S]*?)---\s*\n?/: it ends at the
    # first `---` anywhere, even inside a value, and what is left rarely parses.
    if "---" in text:
        problems.append(
            "frontmatter holds `---` before its closing line, where Claude Code ends it and then drops "
            "every field, disable-model-invocation included"
        )
    return problems + hidden_copy_problems(prepared, skill_id, data, metadata)


def hidden_copy_problems(prepared: Path, skill_id: str, data: bytes, metadata: dict) -> list[str]:
    """Why the installer could not hide this skill from the model safely: its line-by-line edits
    of SKILL.md (disable-model-invocation) and of each skill directory's agents/openai.yaml
    (policy.allow_implicit_invocation) must succeed and leave everything else as PyYAML read it."""
    installer = _installer()
    problems = []
    try:
        hidden = installer.hidden_skill_md(data, skill_id)
        same = installer.metadata(hidden, skill_id) == {**metadata, installer.HIDDEN_KEY: True}
        try:
            plain = installer.frontmatter_name(data, skill_id)
        except installer.InstallError:
            plain = None  # reported by candidate_problems
        if not same or plain is not None and installer.frontmatter_name(hidden, skill_id) != plain:
            problems.append(f"adding `{installer.HIDDEN_KEY}: true` changes how the rest of the frontmatter reads")
    except installer.InstallError as error:
        problems.append(str(error))
    if metadata.get("user-invocable", True) is not True:
        # Claude Code reads any value it cannot take as true as false; with the key, a hidden copy
        # could then be run neither by the model nor with /ID.
        problems.append("user-invocable is not true: its hidden copy could not be run at all")
    for directory in sorted({prepared, *(p.parent for p in prepared.rglob("SKILL.md"))}):
        path = directory / installer.POLICY_FILE
        if os.path.lexists(path):
            label = "/".join([skill_id, *directory.relative_to(prepared).parts])
            problems += policy_problems(path, label)
    return problems + codex_copy_problems(prepared, skill_id)


def codex_copy_problems(prepared: Path, skill_id: str) -> list[str]:
    """Why the installer could not make this skill's Codex copy: every SKILL.md, the nested ones
    included, must take its new name line by line and otherwise read as before, and each
    agents/openai.yaml it gives the policy must keep everything else."""
    installer = _installer()
    files = {p.relative_to(prepared).as_posix(): ("100644", "") for p in prepared.rglob("*") if p.is_file()}
    try:
        edits = installer.copy_edits("codex", skill_id, "auto", files, lambda rel: (prepared / rel).read_bytes())
    except installer.InstallError as error:
        return [str(error)]
    problems = []
    for rel, data in sorted(edits.items()):
        if rel.endswith(installer.POLICY_FILE):
            original = prepared / rel
            try:
                expected = (yaml.safe_load(original.read_bytes()) or {}) if original.is_file() else {}
                expected = {**expected, "policy": {**expected.get("policy", {}), "allow_implicit_invocation": False}}
                same = yaml.safe_load(data) == expected
            except (yaml.YAMLError, AttributeError, TypeError):
                same = False
            if not same:
                problems.append(f"giving {skill_id}/{rel} the Codex policy changes how the rest of it reads")
            continue
        name = skill_id if rel == "SKILL.md" else installer.nested_name(skill_id, rel)
        try:
            before = yaml.safe_load(installer.frontmatter((prepared / rel).read_bytes(), rel))
            after = yaml.safe_load(installer.frontmatter(data, rel))
        except (installer.InstallError, yaml.YAMLError):
            before = after = None
        if not isinstance(before, dict) or after != {**before, "name": name}:
            problems.append(f"naming {skill_id}/{rel} {name!r} for Codex changes how its frontmatter reads")
    return problems


def _duplicate_keys(node) -> list[str]:
    if not isinstance(node, yaml.MappingNode):
        return []
    keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
    return sorted({key for key in keys if keys.count(key) > 1})


# The typed fields Codex 0.165 reads from agents/openai.yaml (probed: an unknown key is ignored, any
# scalar reads as a string). A known field of another shape, or a product it does not know, makes
# Codex ignore the whole file, the policy included, so the skill would stay in the model's catalog.
CODEX_INTERFACE_FIELDS = (
    "display_name",
    "short_description",
    "icon_small",
    "icon_large",
    "brand_color",
    "default_prompt",
)
CODEX_TOOL_FIELDS = ("type", "value", "description", "transport", "command", "url")
CODEX_PRODUCTS = frozenset({"atlas", "chatgpt", "codex", "ATLAS", "CHATGPT", "CODEX"})


def codex_metadata_problems(value: dict) -> list[str]:
    """The fields of a loaded agents/openai.yaml that Codex cannot read into its typed schema."""
    problems = []

    def section(node, where: str) -> dict:  # absent or null: empty
        if node is not None and not isinstance(node, dict):
            problems.append(f"{where} is not a mapping")
        return node if isinstance(node, dict) else {}

    def scalars(node: dict, where: str, keys: tuple):
        problems.extend(
            f"{where}.{key} is not a single value" for key in keys if isinstance(node.get(key), dict | list)
        )

    scalars(section(value.get("interface"), "interface"), "interface", CODEX_INTERFACE_FIELDS)
    tools = section(value.get("dependencies"), "dependencies").get("tools")
    if tools is not None and not isinstance(tools, list):
        problems.append("dependencies.tools is not a list")
    for i, tool in enumerate(tools if isinstance(tools, list) else []):
        where = f"dependencies.tools[{i}]"
        if not isinstance(tool, dict):
            problems.append(f"{where} is not a mapping")
            continue
        scalars(tool, where, CODEX_TOOL_FIELDS)
        oauth = section(tool.get("oauth"), f"{where}.oauth")
        ports = [oauth[key] for key in ("callback_port", "callbackPort") if key in oauth]  # one is an alias
        if len(ports) > 1 or any(p is not None and (type(p) is not int or not 0 <= p <= 65535) for p in ports):
            problems.append(f"{where}.oauth.callbackPort is not one port number")
    products = section(value.get("policy"), "policy").get("products")
    if products is not None and (
        not isinstance(products, list) or any(not isinstance(p, str) or p not in CODEX_PRODUCTS for p in products)
    ):
        problems.append(f"policy.products is not a list of {', '.join(sorted(CODEX_PRODUCTS))}")
    return problems


def policy_problems(path: Path, label: str) -> list[str]:
    """Why setting policy.allow_implicit_invocation to false in this agents/openai.yaml is unsafe.
    Codex reads the file with serde_yaml, which refuses duplicate keys, and ignores a file it
    cannot read as a whole, policy included: the skill would silently stay in the catalog."""
    installer = _installer()
    prefix = f"Cannot hide {label}: {installer.POLICY_FILE}"
    try:
        data = path.read_bytes()
        before, original = yaml.compose(data), yaml.safe_load(data)
    except OSError as error:
        return [f"{prefix} cannot be read ({error})"]
    except yaml.YAMLError as error:
        return [f"{prefix} is not valid YAML ({str(error).splitlines()[0]})"]
    if not isinstance(before, yaml.MappingNode) or before.flow_style:
        return [f"{prefix} is not a block-style mapping"]
    try:
        merged = installer.hidden_policy(data, label)
        after, result = yaml.compose(merged), yaml.safe_load(merged)
    except installer.InstallError as error:
        return [str(error)]
    except yaml.YAMLError:
        after = result = None
    expected = copy.deepcopy(original)
    if isinstance(expected.get("policy", {}), dict):
        expected.setdefault("policy", {})["allow_implicit_invocation"] = False
    policy = [value for key, value in before.value if isinstance(key, yaml.ScalarNode) and key.value == "policy"]
    duplicates = _duplicate_keys(before) + (_duplicate_keys(policy[-1]) if policy else [])
    problems = [f"{prefix} has duplicate keys: {', '.join(duplicates)}"] if duplicates else []
    if result != expected or _duplicate_keys(after) != _duplicate_keys(before):
        problems.append(f"{prefix} would read differently once policy.allow_implicit_invocation is false")
    unread = codex_metadata_problems(result) if isinstance(result, dict) else []
    if unread:
        problems.append(f"{prefix} is ignored as a whole by Codex, its policy included: {'; '.join(unread)}")
    return problems


def library_problems(skills: Path) -> list[str]:
    """The same rules over the whole tree, including content synced before they existed."""
    installer = _installer()
    ids = installer.skill_ids(skills)
    problems = [f"{skill_id}: {reason}" for skill_id, reason in installer.case_collisions(ids).items()]
    problems += [f"{skill_id}: reserved for a bundled Codex system skill" for skill_id in ids if _reserved(skill_id)]
    for skill_id in ids:
        found = candidate_problems(skills / skill_id, skill_id)
        problems += [f"{skill_id}: {p}" for p in found if not p.startswith("Invalid frontmatter")]
    return problems


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
    new = updated = deduplicated = invalid = rejected = 0
    frontmatter_normalized = 0
    missing_frontmatter = 0
    for root in roots:
        skill_name = root.name
        if skill_name.startswith(".") or skill_name in SKIP_TOPLEVEL_NAMES:
            continue
        # Compare the final filtered/sanitized content, not the raw upstream.
        prepared = staging / "prepared" / name / root.relative_to(repo_dir)
        _, normalized_count, missing_count = copy_skill(root, prepared, lfs_paths, repo_dir)
        frontmatter_normalized += normalized_count
        missing_frontmatter += missing_count
        origin = {
            "repository": url,
            "revision": revision,
            "path": root.relative_to(repo_dir).as_posix(),
            "current": True,
        }
        problems = candidate_problems(prepared, skill_name)
        if problems:
            rejected += 1
            print(f"  REJECTED {origin['path']}: {'; '.join(problems[:5])}", file=sys.stderr)
            continue
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
        f"  installed: {new} new, {updated} updated, {deduplicated} deduplicated, {invalid} invalid, "
        f"{rejected} rejected (total roots: {len(roots)})"
    )
    if frontmatter_normalized or missing_frontmatter:
        print(f"  frontmatter: {frontmatter_normalized} normalized, {missing_frontmatter} missing")
    stats[name] = {
        "new": new,
        "updated": updated,
        "deduplicated": deduplicated,
        "invalid": invalid,
        "rejected": rejected,
        "removed": 0,
        "total": len(roots),
        "frontmatter_normalized": frontmatter_normalized,
        "missing_frontmatter": missing_frontmatter,
    }


def write_summary(stats: dict, before: int, after: int) -> str:
    lines = [
        "Per-repo sync summary:",
        "",
        "| Source | New | Updated | Deduplicated | Invalid | Rejected | Total roots |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for repo, s in stats.items():
        if "error" in s:
            lines.append(f"| {repo} | — | — | — | — | — | error: {s['error']} |")
        else:
            lines.append(
                f"| {repo} | {s['new']} | {s['updated']} | {s.get('deduplicated', 0)} | {s.get('invalid', 0)} "
                f"| {s.get('rejected', 0)} | {s['total']} |"
            )
            if s.get("frontmatter_normalized") or s.get("missing_frontmatter"):
                lines.append(
                    f"| frontmatter | {s.get('frontmatter_normalized', 0)} normalized | "
                    f"{s.get('missing_frontmatter', 0)} missing |  |  |  |  |"
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


@functools.cache
def _installer():
    """The installer defines how SKILL.md frontmatter is read; the index must agree with it."""
    path = Path(__file__).with_name("install_skills.py")
    spec = importlib.util.spec_from_file_location("awesome_skills_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_index(skills: Path) -> dict:
    """The committed index (`installer.INDEX`): every source ID's frontmatter name and description,
    as PyYAML reads them."""
    installer = _installer()
    index = {}
    for skill_id in installer.skill_ids(skills):
        fm = installer.metadata((skills / skill_id / "SKILL.md").read_bytes(), skill_id)
        index[skill_id] = {"name": fm["name"], "description": fm.get("description", "")}
    return {"schema": installer.SCHEMA, "skills": index}


def index_text(index: dict) -> str:
    return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_library_index(skills: Path | None = None, path: Path | None = None) -> bool:
    """Regenerate the committed full-library index (names and descriptions) the installer
    reads instead of downloading every skill body. Returns True when the file changed."""
    skills, path = skills or SKILLS_DEST, path or LIBRARY_INDEX_PATH
    content = index_text(build_index(skills))
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

    On the library itself it also leaves what a sync would: skills moved off
    reserved IDs, provenance digests that follow the sanitizer's rewrites of
    unmodified copies, and a regenerated index.
    """
    if not target.exists():
        print(f"sanitize-only: {target} does not exist", file=sys.stderr)
        return 1
    library = None
    if target.resolve() == SKILLS_DEST.resolve():
        try:
            library = LibrarySources(SKILLS_DEST, LIBRARY_SOURCES_PATH)
        except (OSError, ValueError, yaml.YAMLError) as error:
            print(f"Cannot safely load library provenance: {error}", file=sys.stderr)
            return 1
        for old, new in library.release_reserved():
            print(f"  moved: skills/{old} -> skills/{new} ({old} is a bundled Codex system skill)")

    total = sanitized = synthesized = invalid = 0
    invalid_files: list[Path] = []
    rewritten: set[str] = set()
    for skill_md in sorted(target.rglob("SKILL.md")):
        total += 1
        status = sanitize_skill_frontmatter(skill_md)
        if status in ("sanitized", "synthesized"):
            rewritten.add(skill_md.relative_to(target).parts[0])
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
    print(f"sanitize-only: scanned {total}, rewrote {sanitized}, synthesized {synthesized}, {invalid} unrecoverable")
    if invalid_files:
        for f in invalid_files[:20]:
            print(f"  unrecoverable: {f.relative_to(target.parent)}", file=sys.stderr)
        if len(invalid_files) > 20:
            print(f"  ... and {len(invalid_files) - 20} more", file=sys.stderr)
    if library is not None:
        library.accept_sanitized(sorted(rewritten))
        library.save()
        if write_library_index():
            print(f"Updated {LIBRARY_INDEX_PATH.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sanitize-only",
        action="store_true",
        help="skip upstream sync; only normalize/sanitize existing SKILL.md files in ./skills/ (there also move "
        "skills off reserved IDs and keep library_sources.json and library_index.json in step)",
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
    for old, new in library.release_reserved():
        print(f"Moved skills/{old} to skills/{new}: {old} is a bundled Codex system skill")
    before = sum(1 for p in SKILLS_DEST.iterdir() if p.is_dir())
    print(f"Skills before: {before}")
    stats: dict = {}
    with tempfile.TemporaryDirectory(prefix="awesome-skills-staging-") as tmpdir:
        staging = Path(tmpdir)
        for url, name, desc in UPSTREAMS:
            sync_upstream(url, name, desc, staging, stats, library)
    library.save()
    problems = library_problems(SKILLS_DEST)
    if problems:
        for problem in problems[:50]:
            print(f"::error::skills/{problem}", file=sys.stderr)
        print(f"{len(problems)} library entries break installer rules; nothing should be committed.", file=sys.stderr)
        return 1
    try:
        if write_library_index():
            print(f"Updated {LIBRARY_INDEX_PATH.name}")
    except (_installer().InstallError, OSError, ValueError) as error:
        print(f"::error::Could not regenerate {LIBRARY_INDEX_PATH.name}: {error}", file=sys.stderr)
        return 1
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
    rejected = sum(s.get("rejected", 0) for s in stats.values())
    if rejected:
        summary += f"\n\n{rejected} upstream skill(s) were rejected; see the REJECTED lines in the sync log."
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        Path(step_summary).write_text(summary + "\n", encoding="utf-8")
    return REJECTED_EXIT if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
