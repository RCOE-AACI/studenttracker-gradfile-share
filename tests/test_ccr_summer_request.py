# Synthetic test fixtures only; values here are invented and are not student records.
import csv
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

import polars as pl


MODULE_PATH = Path(__file__).resolve().parents[1] / "01w-process_ccr_summer_request.py"
SPEC = importlib.util.spec_from_file_location("ccr_summer", MODULE_PATH)
ccr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ccr)


class CcrSummerRequestTests(unittest.TestCase):
    def sample_row(self, program="CC"):
        return {
            "Program": program,
            "FirstName": "Jose.",
            "MiddleName": "A",
            "LastName": "Nunez",
            "Suffix": "",
            "BirthDateParsed": date(2006, 1, 2),
            "ExitDateParsed": date(2025, 6, 10),
            "ACT": "050001",
            "SSID": "1234567890",
            "Gender": "M",
            "EthnicityRace": "Hispanic",
            "SocioEconomicallyDisadvantaged": "Yes",
            "EnglishLearner": "No",
            "StudentswithDisabilities": "No",
            "MigrantEd": "No",
            "FosterYouth": "No",
            "Homeless": "No",
            "UC_CSURequirementsMet": "Yes",
            "Sealofbiliteracy": "No",
        }

    def test_request_row_contract_and_dual_enrollment(self):
        row = ccr.request_body_row(self.sample_row())
        self.assertEqual(len(row), 25)
        self.assertEqual(row[0], "D3")
        self.assertEqual(row[6], "20060102")
        self.assertEqual(row[7], "20250610")
        self.assertEqual(row[11], "1234567890")
        self.assertEqual(row[21], "Y")
        self.assertFalse(row[11].startswith("_"))

    def test_non_cc_request_does_not_set_dual_enrollment(self):
        self.assertEqual(ccr.request_body_row(self.sample_row(program="AP"))[21], "")

    def test_file_envelope_and_trailer_validation(self):
        body = ccr.request_body_row(self.sample_row())
        rows = [
            ["H3", "10000000", "", "TEST DISTRICT", "20260806", "SE", "D"],
            body,
            ["T3", "3"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.txt"
            ccr.write_tsv_atomic(path, rows, overwrite=False)
            result = ccr.validate_request_file(path, "10000000", 1, "20260806")
            self.assertEqual(result["student_rows"], 1)
            with path.open(encoding="utf-8") as handle:
                parsed = list(csv.reader(handle, delimiter="\t"))
            self.assertEqual(parsed[-1], ["T3", "3"])

    def test_name_and_filename_sanitization(self):
        self.assertEqual(ccr.sanitize_text("José.\tNúñez"), "Jose Nunez")
        self.assertEqual(
            ccr.safe_filename_token("Corona-Norco School District"),
            "CORONA-NORCOSCHOOLDISTRICT",
        )

    def test_ccr_batch_allows_one_populated_class_per_program(self):
        rows = [
            {"program": program, "source_class": "2425", "source_rows": 1}
            for program in ccr.PROGRAMS
        ]
        self.assertEqual(
            ccr.validate_ccr_request_scope(pl.DataFrame(rows)),
            ccr.SOURCE_COHORT_YEARS,
        )


if __name__ == "__main__":
    unittest.main()
