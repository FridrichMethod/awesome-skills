from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_consistency.py"
SPEC = importlib.util.spec_from_file_location("check_consistency", SCRIPT)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


class ConsistencyCheckerTests(unittest.TestCase):
    def run_text(
        self,
        text: str,
        groups: dict[str, tuple[str, ...]] | None = None,
    ) -> list[object]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manuscript.tex"
            path.write_text(text, encoding="utf-8")
            return CHECKER.run_checks([path], groups)

    def test_clean_text_has_no_findings(self) -> None:
        findings = self.run_text(
            "This study used a 35 mm specimen and obtained values of 8.26 and 9.14.",
            CHECKER.DEFAULT_TERM_GROUPS,
        )
        self.assertEqual([], findings)

    def test_term_variants_are_reported(self) -> None:
        findings = self.run_text(
            "This study defines the task. Later, this work reports the results.",
            CHECKER.DEFAULT_TERM_GROUPS,
        )
        self.assertIn("TERM_VARIANTS_PRESENT", {item.code for item in findings})

    def test_numeric_precision_variants_are_reported(self) -> None:
        findings = self.run_text("The score was 8.26 in Table 1 and 8.260 in the abstract.")
        self.assertIn("NUMERIC_PRECISION_VARIANT", {item.code for item in findings})

    def test_equivalent_length_units_are_reported(self) -> None:
        findings = self.run_text("The cover was 35 mm in Methods and 3.5 cm in the caption.")
        self.assertIn(
            "EQUIVALENT_LENGTH_UNIT_VARIANT",
            {item.code for item in findings},
        )

    def test_custom_term_group_is_supported(self) -> None:
        findings = self.run_text(
            "The test specimen was loaded. Each sample was then measured.",
            {"test-object": ("specimen", "sample")},
        )
        self.assertIn("TERM_VARIANTS_PRESENT", {item.code for item in findings})

    def test_number_at_end_of_sentence_is_matched(self) -> None:
        self.assertEqual(["0.05"], CHECKER.NUMBER_PATTERN.findall("The effect was 0.05."))
        self.assertEqual(["0.05", "12"], CHECKER.NUMBER_PATTERN.findall("p = 0.05, n = 12."))
        self.assertEqual([], CHECKER.NUMBER_PATTERN.findall("See version 1.2.3 for details"))

    def test_precision_variants_are_found_when_a_number_ends_a_sentence(self) -> None:
        sources = {
            Path("a.md"): "The effect was 0.05.",
            Path("b.md"): "The effect was 0.050 (Table 1).",
        }
        self.assertTrue(CHECKER.check_numeric_precision(sources))

    def test_millimolar_is_not_a_length(self) -> None:
        self.assertEqual([], [m.group(0) for m in CHECKER.LENGTH_PATTERN.finditer("Add 10 mM NaCl.")])
        sources = {Path("a.md"): "Add 10 mM NaCl.", Path("b.md"): "Scale bar 1 cm."}
        self.assertEqual([], CHECKER.check_equivalent_length_units(sources))

    def test_real_equivalent_lengths_are_still_reported(self) -> None:
        sources = {Path("a.md"): "The scale bar is 10 mm.", Path("b.md"): "The scale bar is 1 cm."}
        self.assertTrue(CHECKER.check_equivalent_length_units(sources))


if __name__ == "__main__":
    unittest.main()
