import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli/image2ppt/runtime"))

from prepare_deck_run import MAX_SLIDE_INCHES, source_size_slide  # noqa: E402


class SourceSizeSlideTest(unittest.TestCase):
    def test_normal_image_keeps_96_px_per_inch(self):
        slide = source_size_slide(1920, 1080)
        self.assertEqual(20.0, slide["width"])
        self.assertEqual(11.25, slide["height"])
        self.assertEqual(96, slide["px_per_inch"])

    def test_wide_image_is_scaled_to_fit_powerpoint_limit(self):
        slide = source_size_slide(6000, 3000)  # 62.5 in at 96 dpi
        self.assertLessEqual(slide["width"], MAX_SLIDE_INCHES + 1e-9)
        self.assertAlmostEqual(MAX_SLIDE_INCHES, slide["width"])
        self.assertAlmostEqual(6000 / 3000, slide["width"] / slide["height"])

    def test_tall_image_is_scaled_on_its_height(self):
        slide = source_size_slide(3000, 9000)
        self.assertAlmostEqual(MAX_SLIDE_INCHES, slide["height"])
        self.assertLessEqual(slide["width"], MAX_SLIDE_INCHES)


if __name__ == "__main__":
    unittest.main()
