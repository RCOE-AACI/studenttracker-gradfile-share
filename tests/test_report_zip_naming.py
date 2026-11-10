# Synthetic test fixtures only; values here are invented and are not student records.
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_upload_module():
    spec = importlib.util.spec_from_file_location("studenttracker_upload", ROOT / "02-upload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportZipNamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upload = load_upload_module()

    def test_default_zip_name_remains_compatible(self):
        self.assertEqual(
            self.upload._renamed_zip_name("Alvord"),
            "Alvord_renamed.zip",
        )

    def test_student_group_suffix_is_included(self):
        self.assertEqual(
            self.upload._renamed_zip_name("Alvord", "_CCR_AP"),
            "Alvord_CCR_AP_renamed.zip",
        )

    def test_cte_suffix_is_included(self):
        self.assertEqual(
            self.upload._renamed_zip_name(
                "Alvord", self.upload.CTE_REPORT_SUFFIX
            ),
            "Alvord_CTE_renamed.zip",
        )

    def test_cte_batch_is_registered_for_scaffolding(self):
        cte_specs = [
            spec
            for spec in self.upload.DEFAULT_REPORT_BATCH_SPECS
            if spec["batch_type"] == "CTE"
        ]
        self.assertEqual(len(cte_specs), 1)
        self.assertEqual(
            cte_specs[0]["glob"],
            "requestfiles/20260828_*_CTE.txt",
        )
        self.assertIn("CTE COMPLETERS", self.upload.CTE_REPORT_HEADER)


if __name__ == "__main__":
    unittest.main()
