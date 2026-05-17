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

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DEST = REPO_ROOT / "skills"

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


def copy_skill(src: Path, dest: Path, lfs_paths: set[Path]) -> int:
    """Copy src tree into dest, filtering. Returns number of files copied."""
    if dest.exists():
        shutil.rmtree(dest)
    files_copied = 0
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
            shutil.copy2(src_file, target_root / f)
            files_copied += 1
    return files_copied


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
    for root in roots:
        skill_name = root.name
        if skill_name.startswith(".") or skill_name in SKIP_TOPLEVEL_NAMES:
            continue
        dest = SKILLS_DEST / skill_name
        existed = dest.exists()
        copy_skill(root, dest, lfs_paths)
        if existed:
            updated += 1
        else:
            new += 1
    print(f"  installed: {new} new, {updated} updated (total roots: {len(roots)})")
    stats[name] = {"new": new, "updated": updated, "removed": 0, "total": len(roots)}


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
    lines.append("")
    lines.append(f"Skills before: {before}, after: {after} (delta: {after - before:+d})")
    return "\n".join(lines)


def main() -> int:
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
    # Emit summary to GITHUB_STEP_SUMMARY if running in Actions
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        Path(step_summary).write_text(summary + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
