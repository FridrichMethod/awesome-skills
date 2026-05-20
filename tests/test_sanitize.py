"""Tests for ``scripts/sync_skills.py`` frontmatter sanitizer.

Coverage targets the six sanitization classes the sync workflow relies on:

1.  Preamble reorder — frontmatter preceded by a header gets moved below.
2.  Length cap — ``description`` > 1024 chars is smart-trimmed.
3.  Mid-value colon quoting — ``foo: bar: baz`` gets double-quoted.
4.  Broken folded-scalar collapse — ``description: ">"`` block joins into one
    quoted scalar honoring ``>`` / ``>-`` / ``|`` semantics.
5.  Flow-collection passthrough — ``tags: [a, b]`` and ``metadata: {x: 1}``
    keep their parsed list/dict types.
6.  Multi-line quoted scalar passthrough — ``description: "first\\nsecond"``
    is left alone so PyYAML can parse it.

Plus idempotency and missing-frontmatter handling.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import sync_skills as ss


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "SKILL.md"
    f.write_text(body, encoding="utf-8")
    return f


def _parse_frontmatter(text: str) -> dict | None:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    return yaml.safe_load("".join(lines[1:end]))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSmartTrim:
    def test_no_trim_when_under_target(self) -> None:
        assert ss._smart_trim("short", target=100) == "short"

    def test_prefer_sentence_boundary(self) -> None:
        text = "First sentence. Second sentence. Third sentence."
        out = ss._smart_trim(text, target=30)
        assert out.endswith(". ") or out.endswith(".")
        assert len(out) <= 30

    def test_fallback_to_word_boundary(self) -> None:
        text = "one two three four five six seven eight nine ten"
        out = ss._smart_trim(text, target=20)
        assert out.endswith("...")
        assert len(out) <= 23

    def test_long_run_no_spaces(self) -> None:
        text = "X" * 200
        out = ss._smart_trim(text, target=50)
        assert len(out) <= 53


class TestYamlQuoteHelpers:
    def test_double_quote_escapes_backslash_and_quote(self) -> None:
        assert ss._yaml_double_quote('a"b\\c') == '"a\\"b\\\\c"'

    @pytest.mark.parametrize(
        "value, expected",
        [
            ('"foo"', True),
            ("'foo'", True),
            ("foo", False),
            ('"unbalanced', False),
            ("", False),
            ('"', False),
        ],
    )
    def test_is_yaml_quoted(self, value: str, expected: bool) -> None:
        assert ss._is_yaml_quoted(value) is expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("[a, b, c]", True),
            ("{x: 1, y: 2}", True),
            ("[ a, b ]", True),
            ("[a", False),
            ("foo", False),
            ("", False),
        ],
    )
    def test_is_balanced_flow_collection(self, value: str, expected: bool) -> None:
        assert ss._is_balanced_flow_collection(value) is expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            ('"closed on this line"', False),
            ('"opens but never closes', True),
            ('"first \\" still open', True),
            ('"escaped \\" then closed"', False),
            ("'closed single'", False),
            ("'opens but never closes", True),
            ("'escaped '' then closed'", False),
            ("plain", False),
            ("", False),
        ],
    )
    def test_opens_multiline_quoted(self, value: str, expected: bool) -> None:
        assert ss._opens_multiline_quoted(value) is expected


class TestNeedsYamlQuoting:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("plain text", False),
            ("has: a colon", True),
            ("[a, b, c]", False),  # flow list — leave alone
            ("{x: 1}", False),  # flow mapping — leave alone
            ('"already quoted: ok"', False),
            ("> with marker", True),
            ("ends:", True),
            ("", False),
        ],
    )
    def test_needs_quoting(self, value: str, expected: bool) -> None:
        assert ss._needs_yaml_quoting(value) is expected


# ---------------------------------------------------------------------------
# End-to-end on SKILL.md content
# ---------------------------------------------------------------------------


class TestSanitizeSkillFrontmatter:
    """Each test writes a minimal SKILL.md, runs the sanitizer, and asserts on
    the resulting frontmatter via PyYAML."""

    def test_valid_file_untouched(self, tmp_path: Path) -> None:
        body = "---\nname: foo\ndescription: A short description.\n---\n\nbody\n"
        f = _write(tmp_path, body)
        assert ss.sanitize_skill_frontmatter(f) == "valid"
        assert f.read_text() == body

    def test_length_cap_smart_trims(self, tmp_path: Path) -> None:
        long_desc = (". ".join(["Sentence " + str(i) for i in range(200)]) + ".")
        assert len(long_desc) > 1024
        body = f"---\nname: foo\ndescription: {long_desc}\n---\n"
        f = _write(tmp_path, body)
        assert ss.sanitize_skill_frontmatter(f) == "sanitized"
        doc = _parse_frontmatter(f.read_text())
        assert isinstance(doc, dict)
        assert len(doc["description"]) <= ss.DESCRIPTION_MAX

    def test_mid_value_colon_gets_quoted(self, tmp_path: Path) -> None:
        body = "---\nname: foo\nprimary_tool: tool: with colon\n---\n"
        f = _write(tmp_path, body)
        assert ss.sanitize_skill_frontmatter(f) == "sanitized"
        doc = _parse_frontmatter(f.read_text())
        assert doc["primary_tool"] == "tool: with colon"

    def test_flow_list_preserved(self, tmp_path: Path) -> None:
        """Regression: 45 files had `tags: [a, b]` corrupted to a string."""
        body = "---\nname: foo\ndescription: x\ntags: [a, b, c]\n---\n"
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        doc = _parse_frontmatter(f.read_text())
        assert doc["tags"] == ["a", "b", "c"]

    def test_flow_mapping_preserved(self, tmp_path: Path) -> None:
        body = "---\nname: foo\ndescription: x\nmetadata: {x: 1, y: 2}\n---\n"
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        doc = _parse_frontmatter(f.read_text())
        assert doc["metadata"] == {"x": 1, "y": 2}

    def test_broken_folded_scalar_collapsed(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "name: foo\n"
            'description: ">"\n'
            "  First line of body.\n"
            "  Second line.\n"
            "\n"
            "  Paragraph two.\n"
            "license: MIT\n"
            "---\n"
        )
        f = _write(tmp_path, body)
        assert ss.sanitize_skill_frontmatter(f) == "sanitized"
        doc = _parse_frontmatter(f.read_text())
        assert "First line of body. Second line." in doc["description"]
        assert "Paragraph two." in doc["description"]
        assert doc["license"] == "MIT"

    @pytest.mark.parametrize("marker", ['"|"', '"|-"', '"|+"'])
    def test_broken_literal_scalar_collapsed(self, tmp_path: Path, marker: str) -> None:
        body = (
            "---\n"
            "name: foo\n"
            f"description: {marker}\n"
            "  Line A.\n"
            "  Line B.\n"
            "---\n"
        )
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        doc = _parse_frontmatter(f.read_text())
        # Literal-style preserves newlines between lines.
        assert "Line A." in doc["description"]
        assert "Line B." in doc["description"]

    def test_multiline_quoted_scalar_left_alone(self, tmp_path: Path) -> None:
        """Regression: previously double-wrapped multi-line strings."""
        body = (
            '---\n'
            'name: foo\n'
            'description: "first half ...\n'
            '\n'
            'second half."\n'
            'license: MIT\n'
            '---\n'
        )
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        after = f.read_text()
        # The sanitizer must not touch the description in this case.
        assert "first half" in after
        assert "second half" in after
        # PyYAML still parses it correctly.
        doc = _parse_frontmatter(after)
        assert doc is not None
        assert "first half" in doc["description"]

    def test_preamble_reordered_below_frontmatter(self, tmp_path: Path) -> None:
        body = (
            "<!-- upstream copyright header -->\n"
            "\n"
            "---\n"
            "name: foo\n"
            "description: A description.\n"
            "---\n"
            "\n"
            "body\n"
        )
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        out = f.read_text()
        assert out.startswith("---\n")
        # Preamble preserved somewhere below.
        assert "<!-- upstream copyright header -->" in out

    def test_synthesizes_frontmatter_when_pure_markdown(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "scholar-evaluation"
        skill_dir.mkdir()
        body = (
            "# Scholar Evaluation\n"
            "\n"
            "## Overview\n"
            "\n"
            "Apply the ScholarEval framework to systematically evaluate "
            "scholarly and research work.\n"
            "\n"
            "## When to Use This Skill\n"
            "- one\n"
            "- two\n"
        )
        f = skill_dir / "SKILL.md"
        f.write_text(body, encoding="utf-8")
        assert ss.sanitize_skill_frontmatter(f) == "synthesized"
        doc = _parse_frontmatter(f.read_text())
        assert isinstance(doc, dict)
        assert doc["name"] == "scholar-evaluation"
        assert "ScholarEval" in doc["description"]
        # Original body preserved below the new frontmatter.
        assert "# Scholar Evaluation" in f.read_text()

    def test_synthesizes_from_h1_when_no_overview(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "foo-bar"
        skill_dir.mkdir()
        f = skill_dir / "SKILL.md"
        f.write_text("# Foo Bar\n\nA quick body sentence.\n", encoding="utf-8")
        assert ss.sanitize_skill_frontmatter(f) == "synthesized"
        doc = _parse_frontmatter(f.read_text())
        assert doc["name"] == "foo-bar"
        # Falls back to the first paragraph after the H1.
        assert "quick body sentence" in doc["description"]

    def test_synthesizes_with_only_dirname_fallback(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "barebones"
        skill_dir.mkdir()
        f = skill_dir / "SKILL.md"
        f.write_text("# Barebones\n", encoding="utf-8")
        ss.sanitize_skill_frontmatter(f)
        doc = _parse_frontmatter(f.read_text())
        assert doc["name"] == "barebones"
        assert doc["description"]  # non-empty


class TestIdempotency:
    """Running the sanitizer twice on any input produces the same output."""

    cases = [
        # (label, body)
        (
            "already_valid",
            "---\nname: foo\ndescription: clean\n---\n",
        ),
        (
            "needs_length_cap",
            "---\nname: foo\ndescription: " + "X" * 1500 + "\n---\n",
        ),
        (
            "needs_quoting",
            "---\nname: foo\ndescription: has: colon\n---\n",
        ),
        (
            "broken_folded",
            (
                "---\n"
                "name: foo\n"
                'description: ">"\n'
                "  L1.\n"
                "  L2.\n"
                "---\n"
            ),
        ),
        (
            "flow_list",
            "---\nname: foo\ndescription: x\ntags: [a, b]\n---\n",
        ),
        (
            "multiline_quoted",
            (
                '---\n'
                'name: foo\n'
                'description: "first\n'
                '\n'
                'second"\n'
                '---\n'
            ),
        ),
    ]

    @pytest.mark.parametrize("label, body", cases, ids=[c[0] for c in cases])
    def test_second_pass_is_noop(self, tmp_path: Path, label: str, body: str) -> None:
        f = _write(tmp_path, body)
        ss.sanitize_skill_frontmatter(f)
        snapshot = f.read_text()
        result = ss.sanitize_skill_frontmatter(f)
        assert result == "valid"
        assert f.read_text() == snapshot

    def test_full_tree_idempotency(self, tmp_path: Path) -> None:
        """If a skills/ directory exists, a second --sanitize-only pass must
        rewrite zero files. This guards against regressions where the
        sanitizer keeps re-touching the same file forever.

        Operates on a copy in tmp_path so the test never mutates the
        committed skills/ tree.
        """
        import shutil

        src = ss.REPO_ROOT / "skills"
        if not src.exists():
            pytest.skip("no skills/ tree to scan in this checkout")
        dst = tmp_path / "skills"
        shutil.copytree(src, dst, symlinks=True)

        # First pass — may rewrite up to a handful of files.
        ss.sanitize_only(dst)
        # Second pass — must touch nothing.
        rewrote_second = 0
        for skill_md in dst.rglob("SKILL.md"):
            before = skill_md.read_text(encoding="utf-8", errors="ignore")
            ss.sanitize_skill_frontmatter(skill_md)
            after = skill_md.read_text(encoding="utf-8", errors="ignore")
            if before != after:
                rewrote_second += 1
        assert rewrote_second == 0


class TestPostSanitizeInvariants:
    """End-to-end checks: after sanitization, every result is YAML-valid and
    every description is within the Codex loader length limit."""

    def test_yaml_valid_after_sanitize(self, tmp_path: Path) -> None:
        cases = [
            "---\nname: foo\ndescription: A: B: C: D\n---\n",
            "---\nname: foo\ndescription: " + "Y" * 2000 + "\n---\n",
            "---\nname: foo\ndescription: \">\"\n  Body.\n---\n",
        ]
        for i, body in enumerate(cases):
            f = tmp_path / f"case_{i}.md"
            f.write_text(body, encoding="utf-8")
            ss.sanitize_skill_frontmatter(f)
            doc = _parse_frontmatter(f.read_text())
            assert isinstance(doc, dict), f"case {i} failed to parse"
            desc = doc.get("description", "")
            assert isinstance(desc, str)
            assert len(desc) <= ss.DESCRIPTION_MAX
