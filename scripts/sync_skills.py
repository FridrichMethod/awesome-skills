#!/usr/bin/env python3
"""Sync skills from upstream repos into ./skills/.

Run from the repo root. Clones each upstream shallow, finds every SKILL.md,
de-duplicates nested skill dirs, and copies the skill roots into ./skills/
with last-source-wins on name conflict (P0 / specialized repos go last).

Filters out:
- .git/, __pycache__/, *.pyc, node_modules/, .DS_Store
- .gitattributes (prevents LFS issues on push)
- Files >40 MB (GitHub warns >50 MB; stay under threshold)
- Bundled vector DBs and dataset blobs (**/repo/src/db/, **/repo/dataset/)
- Anything referenced by an upstream .gitattributes as Git LFS
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DEST = REPO_ROOT / "skills"

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

# (url, local_name, description). Order matters — later entries win on conflict.
# Order rationale:
#   1) Broad bio/scientific/medical libraries first (provide volume baseline).
#   2) Specialized bio/academic curations next (refine on top).
#   3) General-purpose dev-workflow collections after (override generic
#      names like `brainstorming` with their higher-quality versions).
#   4) Official Anthropic + Superpowers + Karpathy last (highest authority).
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
    ("https://github.com/adaptyvbio/protein-design-skills.git", "adaptyv-protein", "Adaptyv protein-design [P0]"),
    # --- general-purpose dev/productivity collections ---
    ("https://github.com/wshobson/agents.git", "wshobson-agents", "wshobson agents (155 dev skills, 35.5k ⭐)"),
    ("https://github.com/anthropics/claude-plugins-official.git", "anthropics-plugins", "Anthropic official plugins (19.5k ⭐)"),
    # --- foundational / highest-authority (win last on conflict) ---
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
        return "missing_frontmatter"
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


def sync_upstream(url: str, name: str, description: str, staging: Path, stats: dict):
    repo_dir = staging / name
    print(f"\n[{name}] {description}")
    print(f"  cloning {url} ...")
    if not shallow_clone(url, repo_dir):
        stats[name] = {"new": 0, "updated": 0, "removed": 0, "total": 0, "error": "clone_failed"}
        return
    lfs_paths = find_lfs_pointer_files(repo_dir)
    if lfs_paths:
        print(f"  flagged {len(lfs_paths)} LFS pointer files to skip")
    roots = find_skill_roots(repo_dir)
    new = updated = 0
    frontmatter_normalized = 0
    missing_frontmatter = 0
    for root in roots:
        skill_name = root.name
        if skill_name.startswith(".") or skill_name in SKIP_TOPLEVEL_NAMES:
            continue
        dest = SKILLS_DEST / skill_name
        existed = dest.exists()
        _, normalized_count, missing_count = copy_skill(root, dest, lfs_paths)
        frontmatter_normalized += normalized_count
        missing_frontmatter += missing_count
        if existed:
            updated += 1
        else:
            new += 1
    print(f"  installed: {new} new, {updated} updated (total roots: {len(roots)})")
    if frontmatter_normalized or missing_frontmatter:
        print(
            "  frontmatter: "
            f"{frontmatter_normalized} normalized, {missing_frontmatter} missing"
        )
    stats[name] = {
        "new": new,
        "updated": updated,
        "removed": 0,
        "total": len(roots),
        "frontmatter_normalized": frontmatter_normalized,
        "missing_frontmatter": missing_frontmatter,
    }


def write_summary(stats: dict, before: int, after: int) -> str:
    lines = [
        "Per-repo sync summary:",
        "",
        "| Source | New | Updated | Total roots |",
        "|---|---:|---:|---:|",
    ]
    for repo, s in stats.items():
        if "error" in s:
            lines.append(f"| {repo} | — | — | error: {s['error']} |")
        else:
            lines.append(f"| {repo} | {s['new']} | {s['updated']} | {s['total']} |")
            if s.get("frontmatter_normalized") or s.get("missing_frontmatter"):
                lines.append(
                    f"| frontmatter | {s.get('frontmatter_normalized', 0)} normalized | "
                    f"{s.get('missing_frontmatter', 0)} missing |  |"
                )
    lines.append("")
    lines.append(f"Skills before: {before}, after: {after} (delta: {after - before:+d})")
    return "\n".join(lines)


def sanitize_only(target: Path) -> int:
    """Walk `target` and apply `sanitize_skill_frontmatter` to every SKILL.md.

    Used both as a one-shot cleanup of the in-tree `skills/` directory and as
    a unit-friendly entry point for tests. Returns the process exit code.
    """
    if not target.exists():
        print(f"sanitize-only: {target} does not exist", file=sys.stderr)
        return 1

    total = sanitized = invalid = 0
    invalid_files: list[Path] = []
    for skill_md in sorted(target.rglob("SKILL.md")):
        total += 1
        status = sanitize_skill_frontmatter(skill_md)
        if status == "sanitized":
            sanitized += 1
            print(f"  sanitized: {skill_md.relative_to(target.parent)}")
        elif status == "missing_frontmatter":
            invalid += 1
            invalid_files.append(skill_md)

    print()
    print(f"sanitize-only: scanned {total}, rewrote {sanitized}, {invalid} missing frontmatter")
    if invalid_files:
        for f in invalid_files[:20]:
            print(f"  missing frontmatter: {f.relative_to(target.parent)}", file=sys.stderr)
        if len(invalid_files) > 20:
            print(f"  ... and {len(invalid_files) - 20} more", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sanitize-only",
        action="store_true",
        help="skip upstream sync; only normalize/sanitize existing SKILL.md files in ./skills/",
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

    SKILLS_DEST.mkdir(parents=True, exist_ok=True)
    before = sum(1 for p in SKILLS_DEST.iterdir() if p.is_dir())
    print(f"Skills before: {before}")
    stats: dict = {}
    with tempfile.TemporaryDirectory(prefix="awesome-skills-staging-") as tmpdir:
        staging = Path(tmpdir)
        for url, name, desc in UPSTREAMS:
            sync_upstream(url, name, desc, staging, stats)
    after = sum(1 for p in SKILLS_DEST.iterdir() if p.is_dir())
    print()
    summary = write_summary(stats, before, after)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        Path(step_summary).write_text(summary + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
