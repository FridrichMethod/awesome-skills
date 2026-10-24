#!/usr/bin/env bash
# Local or curl|bash bootstrap: the same command is the first install and every update.
# Selection, ownership, git transport and locking live in the Python installer.
set -euo pipefail
python="${SKILLS_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1; then
  echo "awesome-skills: Python 3.11+ is required; not found: $python (set SKILLS_PYTHON)" >&2
  exit 1
fi
script_path="${BASH_SOURCE[0]:-}"
if [[ -n "$script_path" && -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  if [[ -f "$script_dir/scripts/install_skills.py" ]]; then
    exec "$python" -B "$script_dir/scripts/install_skills.py" "$@"
  fi
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "awesome-skills: curl is required to download the installer" >&2
  exit 1
fi
url="${SKILLS_INSTALLER_URL:-https://raw.githubusercontent.com/FridrichMethod/awesome-skills/${SKILLS_BRANCH:-main}/scripts/install_skills.py}"
# Keep the download in memory, including on --dry-run. No bootstrap temp directory.
if ! installer="$(curl -fsSL "$url")"; then
  echo "awesome-skills: could not download the installer from $url" >&2
  exit 1
fi
exec "$python" -B -c "$installer" --remote "$@"
