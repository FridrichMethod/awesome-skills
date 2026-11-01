#!/usr/bin/env bash
# Local or curl|bash bootstrap: the same command is the first install and every update.
# Selection, ownership, git transport and locking live in the Python installer.
set -euo pipefail
python="${SKILLS_PYTHON:-python3}"
if ! command -v "$python" >/dev/null 2>&1; then
  echo "awesome-skills: Python 3.11+ is required; not found: $python (set SKILLS_PYTHON)" >&2
  exit 1
fi
if ! "$python" -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
  echo "awesome-skills: Python 3.11+ is required; $python is older (set SKILLS_PYTHON)" >&2
  exit 1
fi
# Python never imports from a folder it was not given: a checkout's installer runs with -P (its own
# folder stays off sys.path; PyYAML may live in the user's site-packages), a download with -I.
script_path="${BASH_SOURCE[0]:-}"
if [[ -n "$script_path" && -f "$script_path" ]]; then
  script_dir="$(cd "$(dirname "$script_path")" && pwd)"
  if [[ -f "$script_dir/scripts/install_skills.py" ]]; then
    exec "$python" -P -B "$script_dir/scripts/install_skills.py" "$@"
  fi
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "awesome-skills: curl is required to download the installer" >&2
  exit 1
fi
url="${SKILLS_INSTALLER_URL:-https://raw.githubusercontent.com/FridrichMethod/awesome-skills/${SKILLS_BRANCH:-main}/scripts/install_skills.py}"
# Keep the download in memory, including on --dry-run, with no bootstrap temp directory. Python reads
# it on standard input, which has no size limit (Linux limits one argument to 128 KiB); the installer
# reads nothing else from it. Its exit status (0, 1, 2, 3 or 75) is this script's.
if ! installer="$(curl -fsSL "$url")"; then
  echo "awesome-skills: could not download the installer from $url" >&2
  exit 1
fi
status=0
printf '%s\n' "$installer" | "$python" -I -B - --remote "$@" || status=$?
exit "$status"
