# Synthetic test fixtures only; values here are invented and are not student records.
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.colors import black
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]


def load_upload_module():
    spec = importlib.util.spec_from_file_location("studenttracker_upload", ROOT / "02-upload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PdfWatermarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upload = load_upload_module()

    def test_header_is_once_and_rendered_above_opaque_vendor_content(self):
        if shutil.which("pdftoppm") is None:
            self.skipTest("pdftoppm is required for rendered watermark verification")

        header = "CCR STUDENTTRACKER REPORT - DUAL ENROLLMENT STUDENTS ONLY"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "source.pdf"
            output = temp / "watermarked.pdf"
            rendered_prefix = temp / "rendered"

            vendor = canvas.Canvas(str(source), pagesize=(792, 612))
            vendor.setFillColor(black)
            vendor.drawString(72, 500, "VENDOR BODY")
            # Simulate a BASIC cover whose black logo reaches the top edge.
            # Plain black overlay text would be present logically but invisible.
            vendor.setFillColor(black)
            vendor.rect(0, 570, 792, 42, fill=1, stroke=0)
            vendor.save()

            self.upload.add_header_to_pdf(str(source), str(output), header)

            reader = PdfReader(str(output))
            self.assertEqual(len(reader.pages), 1)
            self.assertGreater(float(reader.pages[0].mediabox.height), 612.0)
            self.assertEqual((reader.pages[0].extract_text() or "").count(header), 1)

            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-singlefile",
                    "-png",
                    "-r",
                    "72",
                    str(output),
                    str(rendered_prefix),
                ],
                check=True,
                capture_output=True,
            )
            with Image.open(rendered_prefix.with_suffix(".png")) as image:
                grayscale = image.convert("L")
                top_band = grayscale.crop((20, 0, grayscale.width - 20, 42))
                dark_pixels = sum(pixel < 128 for pixel in top_band.getdata())
                light_pixels = sum(pixel > 220 for pixel in top_band.getdata())
            self.assertGreater(dark_pixels, 100)
            self.assertGreater(light_pixels, 100)


if __name__ == "__main__":
    unittest.main()
