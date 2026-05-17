#!/usr/bin/env bash
# Install Claude Code + Codex skills from github.com/FridrichMethod/awesome-skills
# into ~/.claude/skills/ and ~/.codex/skills/.
#
# One-line install (no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash
#
# With flags:
#   curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash -s -- --claude-only
#
# Local usage (when run from a clone):
#   ./install.sh [--claude-only|--codex-only] [--dry-run] [--delete]
set -euo pipefail

REPO="FridrichMethod/awesome-skills"
BRANCH="${SKILLS_BRANCH:-main}"
TARBALL_URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"

CLAUDE_DEST="${SKILLS_CLAUDE_DEST:-$HOME/.claude/skills}"
CODEX_DEST="${SKILLS_CODEX_DEST:-$HOME/.codex/skills}"

DO_CLAUDE=1
DO_CODEX=1
DO_DELETE=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash
  curl -fsSL .../install.sh | bash -s -- [--claude-only|--codex-only] [--dry-run] [--delete]

Flags:
  --claude-only   only install to ~/.claude/skills
  --codex-only    only install to ~/.codex/skills
  --dry-run       show what would change without writing
  --delete        mirror exactly (remove skills not present in the repo)

Env overrides:
  SKILLS_BRANCH        branch to pull from (default: main)
  SKILLS_CLAUDE_DEST   override ~/.claude/skills
  SKILLS_CODEX_DEST    override ~/.codex/skills
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --claude-only) DO_CODEX=0 ;;
    --codex-only)  DO_CLAUDE=0 ;;
    --dry-run)     DRY_RUN=1 ;;
    --delete)      DO_DELETE=1 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage; exit 1 ;;
  esac
done

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required tool: $1. Install it and re-run." >&2
    exit 1
  }
}

# Detect whether we have a local skills/ dir adjacent to this script.
script_path="${BASH_SOURCE[0]:-}"
script_dir=""
if [[ -n "$script_path" && -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" 2>/dev/null && pwd || true)"
fi

cleanup() { :; }
trap 'cleanup' EXIT

if [[ -n "$script_dir" && -d "$script_dir/skills" ]]; then
  SRC="$script_dir/skills"
  echo "Using local skills/ at $SRC"
else
  need curl
  need tar
  tmp="$(mktemp -d -t awesome-skills.XXXXXX)"
  cleanup() { rm -rf "$tmp"; }
  echo "Fetching $TARBALL_URL ..."
  curl -fsSL "$TARBALL_URL" | tar -xz -C "$tmp"
  # GitHub tarballs extract into <repo>-<branch>/
  extracted="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  SRC="$extracted/skills"
  if [[ ! -d "$SRC" ]]; then
    echo "Could not locate skills/ inside tarball ($SRC)" >&2
    exit 1
  fi
fi

need rsync

rsync_opts=(-a --human-readable)
[[ $DRY_RUN  -eq 1 ]] && rsync_opts+=(--dry-run --itemize-changes)
[[ $DO_DELETE -eq 1 ]] && rsync_opts+=(--delete)

count_src=$(find "$SRC" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
echo "Source: $SRC ($count_src skills)"

install_to() {
  local dest="$1" name="$2"
  mkdir -p "$dest"
  local before
  before=$(find "$dest" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  echo
  echo "→ Syncing to $name ($dest) — $before existing skills"
  rsync "${rsync_opts[@]}" "$SRC/" "$dest/"
  local after
  after=$(find "$dest" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  echo "  done: $after skills present"
}

[[ $DO_CLAUDE -eq 1 ]] && install_to "$CLAUDE_DEST" ".claude"
[[ $DO_CODEX  -eq 1 ]] && install_to "$CODEX_DEST"  ".codex"

echo
echo "All done."
