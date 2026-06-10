"""Tests for ``update_readme_counts`` in ``scripts/sync_skills.py``.

The sync script regenerates the README's headline figures from the live skill
tree on every run so they never drift between weekly syncs. These tests pin
that behavior:

1.  Badge + prose use a rounded ``<floor>+`` figure (1973 -> ``1,900+``).
2.  The repo-layout tree line shows the exact count (``1,973``).
3.  Source count (badge, intro sentence, heading) tracks ``len(UPSTREAMS)``.
4.  Substitution is idempotent and a no-op leaves the file byte-identical.
5.  A missing README returns ``False`` rather than raising.
"""
from __future__ import annotations

from pathlib import Path

from scripts import sync_skills as ss

# A representative README skeleton carrying every figure the function rewrites.
SAMPLE = """\
**A curated, auto-synced collection of 1,800+ agent skills for Claude Code.**

[![Skills](https://img.shields.io/badge/skills-1800%2B-brightgreen)](#sources)
[![Sources](https://img.shields.io/badge/upstream%20sources-15-blue)](#sources)

1. **Aggregates** the best skills from 15 upstream curated collections — bio.

The result bootstraps a fresh laptop with **1,800+ vetted skills** ready to use.

Currently **15 sources**.

```
awesome-skills/
├── skills/                          ← 1,668 skill dirs (managed by sync; do not edit directly)
```
"""


def _write(tmp_path: Path, body: str = SAMPLE) -> Path:
    f = tmp_path / "README.md"
    f.write_text(body, encoding="utf-8")
    return f


class TestUpdateReadmeCounts:
    def test_rewrites_all_figures(self, tmp_path: Path) -> None:
        f = _write(tmp_path)
        assert ss.update_readme_counts(f, skill_count=1973, source_count=16) is True
        out = f.read_text()
        # Skills badge + prose use the rounded floor.
        assert "badge/skills-1900%2B-brightgreen" in out
        assert "collection of 1,900+ agent skills" in out
        assert "with **1,900+ vetted skills**" in out
        # Repo-layout tree line uses the exact count (and drops any "+").
        assert "← 1,973 skill dirs" in out
        assert "1,668" not in out
        # Source count everywhere.
        assert "badge/upstream%20sources-16-blue" in out
        assert "from 16 upstream curated collections" in out
        assert "Currently **16 sources**" in out

    def test_idempotent_second_pass_is_noop(self, tmp_path: Path) -> None:
        f = _write(tmp_path)
        ss.update_readme_counts(f, 1973, 16)
        snapshot = f.read_text()
        assert ss.update_readme_counts(f, 1973, 16) is False
        assert f.read_text() == snapshot

    def test_floor_rounds_down_to_step(self, tmp_path: Path) -> None:
        # 2003 -> floor 2000 for badge/prose, exact 2,003 for the tree line.
        f = _write(tmp_path)
        ss.update_readme_counts(f, skill_count=2003, source_count=17)
        out = f.read_text()
        assert "badge/skills-2000%2B-brightgreen" in out
        assert "with **2,000+ vetted skills**" in out
        assert "← 2,003 skill dirs" in out

    def test_already_current_file_unchanged(self, tmp_path: Path) -> None:
        f = _write(tmp_path)
        ss.update_readme_counts(f, 1973, 16)
        current = f.read_text()
        # Re-running with the same numbers must report no change.
        assert ss.update_readme_counts(f, 1973, 16) is False
        assert f.read_text() == current

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        assert ss.update_readme_counts(tmp_path / "nope.md", 1973, 16) is False
