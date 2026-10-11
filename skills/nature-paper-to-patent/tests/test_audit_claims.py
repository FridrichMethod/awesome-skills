import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_claims", ROOT / "scripts" / "audit_claims.py")
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def codes(text):
    return [finding.code for finding in AUDIT.audit(text)]


class AntecedentBasisTests(unittest.TestCase):
    def test_term_used_with_suo_shu_but_never_introduced_is_flagged(self):
        self.assertIn("ANTECEDENT_BASIS", codes("1. 一种装置，其特征在于，包括所述电极。\n"))

    def test_term_introduced_earlier_in_the_same_claim_is_not_flagged(self):
        self.assertNotIn(
            "ANTECEDENT_BASIS", codes("1. 一种检测装置，其特征在于，包括电极和基板，所述电极设置于所述基板上。\n")
        )

    def test_term_introduced_in_a_referenced_claim_is_not_flagged(self):
        text = "1. 一种检测装置，其特征在于，包括电极和基板。\n2. 根据权利要求1所述的装置，其特征在于，所述电极为金属电极。\n"
        self.assertNotIn("ANTECEDENT_BASIS", codes(text))


class GenericReferenceTests(unittest.TestCase):
    def test_reference_phrase_in_a_dependent_claim_is_not_a_term(self):
        text = "1. 一种检测装置，其特征在于，包括电极和基板，所述电极设置于所述基板上。\n2. 根据权利要求1所述的检测装置，其特征在于，所述电极为金属电极。\n"
        self.assertNotIn("ANTECEDENT_BASIS", codes(text))


if __name__ == "__main__":
    unittest.main()
