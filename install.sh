#!/usr/bin/env bash
# Install skills from this repo into ~/.claude/skills/ and ~/.codex/skills/.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills/"

CLAUDE_DEST="$HOME/.claude/skills/"
CODEX_DEST="$HOME/.codex/skills/"

DO_CLAUDE=1
DO_CODEX=1
RSYNC_OPTS=(-a --human-readable)

for arg in "$@"; do
  case "$arg" in
    --claude-only) DO_CODEX=0 ;;
    --codex-only)  DO_CLAUDE=0 ;;
    --dry-run)     RSYNC_OPTS+=(--dry-run --itemize-changes) ;;
    --delete)      RSYNC_OPTS+=(--delete) ;;
    -h|--help)
      sed -n '1,30p' "$0" | grep '^#'
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$SRC" ]]; then
  echo "Source skills/ not found at $SRC" >&2
  exit 1
fi

count_src=$(find "$SRC" -maxdepth 1 -mindepth 1 -type d | wc -l)
echo "Source: $SRC ($count_src skills)"

install_to() {
  local dest="$1" name="$2"
  mkdir -p "$dest"
  local before
  before=$(find "$dest" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
  echo ""
  echo "→ Syncing to $name ($dest) — $before existing skills"
  rsync "${RSYNC_OPTS[@]}" "$SRC" "$dest"
  local after
  after=$(find "$dest" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
  echo "  done: $after skills present"
}

[[ $DO_CLAUDE -eq 1 ]] && install_to "$CLAUDE_DEST" ".claude"
[[ $DO_CODEX  -eq 1 ]] && install_to "$CODEX_DEST"  ".codex"

echo ""
echo "All done."
