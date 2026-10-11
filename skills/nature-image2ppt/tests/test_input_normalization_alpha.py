import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli/image2ppt/runtime"))

import _input_normalization as normalization  # noqa: E402


class TransparencyTest(unittest.TestCase):
    def test_transparent_pixels_become_white_not_black(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(src)
            out = normalization.save_image_page(src, Path(tmp) / "page_001")
            with Image.open(out) as image:
                self.assertEqual("RGB", image.mode)
                self.assertEqual((255, 255, 255), image.getpixel((0, 0)))

    def test_opaque_pixels_are_unchanged_and_partial_alpha_is_blended(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            image = Image.new("RGBA", (2, 1))
            image.putpixel((0, 0), (10, 20, 30, 255))
            image.putpixel((1, 0), (0, 0, 0, 128))
            image.save(src)
            out = normalization.save_image_page(src, Path(tmp) / "page_001")
            with Image.open(out) as result:
                self.assertEqual((10, 20, 30), result.getpixel((0, 0)))
                grey = result.getpixel((1, 0))
                self.assertTrue(120 <= grey[0] <= 135, grey)

    def test_palette_image_with_transparency_becomes_white(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            palette = Image.new("P", (2, 2), 0)
            palette.putpalette([0, 0, 0] * 256)
            palette.info["transparency"] = 0
            palette.save(src, transparency=0)
            out = normalization.save_image_page(src, Path(tmp) / "page_001")
            with Image.open(out) as image:
                self.assertEqual((255, 255, 255), image.getpixel((0, 0)))

    def test_rgb_image_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.png"
            Image.new("RGB", (2, 2), (5, 6, 7)).save(src)
            out = normalization.save_image_page(src, Path(tmp) / "page_001")
            with Image.open(out) as image:
                self.assertEqual((5, 6, 7), image.getpixel((0, 0)))


if __name__ == "__main__":
    unittest.main()
