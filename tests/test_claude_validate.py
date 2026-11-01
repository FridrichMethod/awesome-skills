"""Optional: Claude Code's own parser accepts every library SKILL.md, as written and as the hidden
copy the installer makes (disable-model-invocation inserted). A frontmatter Claude Code cannot
parse loads with no fields at all, so a hidden copy of it would stay visible to the model.

Opt in with AWESOME_SKILLS_CLAUDE_VALIDATE=1; it needs claude 2.1.233 or newer on PATH (or at
AWESOME_SKILLS_CLAUDE). `claude plugin validate` runs in a temporary HOME with no credentials and
API traffic pointed at a closed local port; it starts no model turn.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import install_skills as installer

ROOT = Path(__file__).resolve().parents[1]
MINIMUM = (2, 1, 233)  # first release whose `claude plugin validate` checks a bare skills directory


def claude_binary() -> str:
    if os.environ.get("AWESOME_SKILLS_CLAUDE_VALIDATE") != "1":
        pytest.skip("Set AWESOME_SKILLS_CLAUDE_VALIDATE=1 to validate the library with a local claude")
    path = os.environ.get("AWESOME_SKILLS_CLAUDE") or shutil.which("claude")
    if not path:
        pytest.skip("claude is not installed")
    return path


def isolated(tmp_path: Path) -> tuple[dict, Path]:
    home = tmp_path / "home"
    work = tmp_path / "work"
    for directory in (home / ".claude", home / ".config", work):
        directory.mkdir(parents=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "TERM": "dumb",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "CODEX_HOME": str(home / ".codex"),
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",
        "ANTHROPIC_API_KEY": "sk-ant-offline-test",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    if os.name == "nt":
        env.update({k: os.environ[k] for k in ("SYSTEMROOT", "COMSPEC", "PATHEXT") if k in os.environ})
    return env, work


def claude(binary: str, args: list[str], env: dict, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [binary, *args], env=env, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
    )


@pytest.mark.parametrize("hidden", [False, True], ids=["as-written", "hidden-copies"])
def test_claude_plugin_validate_accepts_every_library_skill(tmp_path, hidden):
    binary = claude_binary()
    env, work = isolated(tmp_path)
    found = re.match(r"(\d+)\.(\d+)\.(\d+)", claude(binary, ["--version"], env, work, 60).stdout.strip())
    if not found or tuple(map(int, found.groups())) < MINIMUM:
        pytest.skip(f"claude {MINIMUM[0]}.{MINIMUM[1]}.{MINIMUM[2]} or newer is needed")
    skills = tmp_path / "skills"
    for skill_id in installer.skill_ids(ROOT / "skills"):
        data = (ROOT / "skills" / skill_id / "SKILL.md").read_bytes()
        (skills / skill_id).mkdir(parents=True)
        (skills / skill_id / "SKILL.md").write_bytes(installer.hidden_skill_md(data, skill_id) if hidden else data)
    result = claude(binary, ["plugin", "validate", str(skills)], env, work, 900)
    assert result.returncode == 0, (result.stdout[-6000:], result.stderr[-2000:])
    assert "Validation passed" in result.stdout
