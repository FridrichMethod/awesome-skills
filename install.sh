#!/usr/bin/env bash
# Local or curl|bash bootstrap. Selection and ownership live in the Python installer.
set -euo pipefail
script_path="${BASH_SOURCE[0]:-}"
if [[ -n "$script_path" && -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  if [[ -f "$script_dir/scripts/install_skills.py" ]]; then
    exec "${SKILLS_PYTHON:-python3}" -B "$script_dir/scripts/install_skills.py" "$@"
  fi
fi
# Keep downloads in memory, including on --dry-run. No bootstrap temp directory.
installer="$(curl -fsSL "https://raw.githubusercontent.com/FridrichMethod/awesome-skills/${SKILLS_BRANCH:-main}/scripts/install_skills.py")"
exec "${SKILLS_PYTHON:-python3}" -B -c "$installer" --remote "$@"
