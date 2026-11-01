#!/usr/bin/env python3
"""Search the awesome-skills library offline: read-only, standard library only, no git.

The routers run it through the launcher the installer writes (`awesome-skills search WORDS`).
It reads library_index.json next to its own directory and matches every word against each
skill's ID, frontmatter name and description, treating '-', '_', '/' and spaces alike. Matches
are ranked (the exact ID first, then ID and name hits, then description hits) and printed as
`ID - description`, at most --limit of them. With --state and --client, the IDs that client
shows the model are marked [visible], for Codex each match gets its installed SKILL.md, and for
Claude Code a match with no installed copy says so.
Exit status: 0 with matches, 1 with none, 2 on a usage or index error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "library_index.json"
SEPARATORS = re.compile(r"[-_/\s]+")
LIMIT, MAX_LIMIT, WIDTH = 12, 50, 150


def words(text: str) -> list[str]:
    return SEPARATORS.sub(" ", text.lower()).split()


def score(query: list[str], skill_id: str, info: dict) -> int | None:
    """None unless every word occurs in the ID, name or description; higher ranks first."""
    head = " " + " ".join(words(f"{skill_id} {info.get('name', '')}")) + " "
    body = " " + " ".join(words(str(info.get("description", "")))) + " "
    if not all(word in head or word in body for word in query):
        return None
    points = 1000 if words(skill_id) == query else 0
    for word in query:
        points += 20 * (f" {word} " in head) + 10 * (word in head) + 3 * (f" {word} " in body) + (word in body)
    return points


def read_state(directory: Path | None, client: str | None) -> dict:
    if directory is None or client is None:
        return {}
    try:
        value = json.loads((directory / f"{client}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def visible(state: dict, ids) -> set:
    selection = state.get("selection", [])
    return set(ids) if "@all" in selection else set(selection)


def codex_path(state: dict, skill_id: str) -> Path | None:
    """The installed Codex SKILL.md: in the root its record names, else in either root."""
    roots = [state.get("destination"), state.get("destination2")]
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    roots += [str(codex_home / "skills"), str(home / ".agents/skills/awesome-skills")]  # the installer's defaults
    record = state.get("managed", {}).get(skill_id)
    if isinstance(record, dict) and record.get("root") in (0, 1):
        roots.insert(0, roots[record["root"]])
    for root in roots:
        if isinstance(root, str) and (Path(root) / skill_id / "SKILL.md").is_file():
            return Path(root) / skill_id / "SKILL.md"
    return None


def claude_copy(state: dict, skill_id: str) -> bool | None:
    """Whether Claude's recorded skills folder holds the skill (/ID finds nothing otherwise); None
    without a recorded folder."""
    root = state.get("destination")
    return (Path(root) / skill_id / "SKILL.md").is_file() if isinstance(root, str) else None


def shorten(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= WIDTH else text[: WIDTH - 3].rstrip() + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", nargs="+", metavar="WORD")
    parser.add_argument("--client", choices=["claude", "codex"], help="mark this client's visible skills")
    parser.add_argument("--state", type=Path, help="the installer's state directory")
    parser.add_argument("--limit", type=int, default=LIMIT, help=f"matches to print (at most {MAX_LIMIT})")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    query = words(" ".join(args.words))
    if not query:
        parser.error("give at least one word")
    try:
        skills = json.loads(INDEX.read_text(encoding="utf-8"))["skills"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"awesome-skills search: cannot read {INDEX}: {error}", file=sys.stderr)
        return 2
    ranked = sorted(
        (-points, skill_id) for skill_id, info in skills.items() if (points := score(query, skill_id, info))
    )
    state = read_state(args.state, args.client)
    shown = visible(state, skills)
    limit = max(1, min(args.limit, MAX_LIMIT))
    print(
        f"{len(ranked)} match(es) for {' '.join(args.words)!r}"
        + (f"; the best {limit}:" if len(ranked) > limit else ":")
    )
    for _, skill_id in ranked[:limit]:
        mark = " [visible]" if skill_id in shown else ""
        print(f"{skill_id}{mark} - {shorten(skills[skill_id].get('description', ''))}")
        if args.client == "codex":
            path = codex_path(state, skill_id)
            print(f"  {path}" if path else "  (not installed for Codex)")
        elif args.client == "claude" and claude_copy(state, skill_id) is False:
            print("  (not installed for Claude Code)")
    if len(ranked) > limit:
        print(f"... {len(ranked) - limit} more; add a word to narrow the search")
    return 0 if ranked else 1


if __name__ == "__main__":
    raise SystemExit(main())
