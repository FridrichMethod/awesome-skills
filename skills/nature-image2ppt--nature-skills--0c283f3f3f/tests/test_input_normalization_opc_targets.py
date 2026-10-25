import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli/image2ppt/runtime"))

import _input_normalization as normalization  # noqa: E402

REL_HEAD = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
PRES = (
    '<?xml version="1.0"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>'
)


def pptx_with_slide_target(target: str) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("ppt/presentation.xml", PRES)
        z.writestr(
            "ppt/_rels/presentation.xml.rels",
            REL_HEAD + f'<Relationship Id="rId1" Type="slide" Target="{target}"/></Relationships>',
        )
        z.writestr("ppt/slides/slide1.xml", "<x/>")
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


class OpcTargetTest(unittest.TestCase):
    def test_relative_slide_target(self):
        with pptx_with_slide_target("slides/slide1.xml") as z:
            self.assertEqual(["ppt/slides/slide1.xml"], normalization.slide_parts_from_pptx(z))

    def test_absolute_slide_target_resolves_inside_the_package(self):
        with pptx_with_slide_target("/ppt/slides/slide1.xml") as z:
            self.assertEqual(["ppt/slides/slide1.xml"], normalization.slide_parts_from_pptx(z))

    def test_resolve_target_handles_relative_parent_and_absolute(self):
        rels = "ppt/slides/_rels/slide1.xml.rels"
        self.assertEqual("ppt/media/image1.png", normalization.resolve_target(rels, "../media/image1.png"))
        self.assertEqual("ppt/media/image1.png", normalization.resolve_target(rels, "/ppt/media/image1.png"))


if __name__ == "__main__":
    unittest.main()
