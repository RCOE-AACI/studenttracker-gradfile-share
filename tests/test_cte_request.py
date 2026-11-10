# Synthetic test fixtures only; values here are invented and are not student records.
import csv
import importlib.util
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

import polars as pl


MODULE_PATH = Path(__file__).resolve().parents[1] / "01y-process_cte_request.py"
SPEC = importlib.util.spec_from_file_location("cte_request", MODULE_PATH)
cte = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(cte)


class FakeBody:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, Bucket: str, Key: str):
        return {"Body": FakeBody(self.objects[Key]), "ETag": '"test-etag"'}


def parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


class CteRequestTests(unittest.TestCase):
    def sample_row(self):
        return {
            "FirstName": "Jose.",
            "MiddleName": "NA",
            "LastName": "Nunez",
            "Suffix": "",
            "BirthDateParsed": date(2007, 1, 2),
            "ExitDateParsed": date(2025, 6, 10),
            "ACT": "50001",
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

    def source_frame(self, ssids, cohort_year):
        count = len(ssids)
        return pl.DataFrame(
            {
                "DistrictCode": ["3366977"] * count,
                "SchoolCode": ["0123456"] * count,
                "SSID": ssids,
                "StudentCompletionStatus": ["100"] * count,
                "CohortCategory": ["HSDiplomaGraduate"] * count,
                "BirthDate": ["01/02/2005"] * count,
                "StudentEnrollmentExitDate": [f"06/10/{cohort_year}"] * count,
                "Gender": ["M"] * count,
                "EthnicityRace": ["Hispanic"] * count,
                "MigrantEd": ["No"] * count,
                "StudentswithDisabilities": ["No"] * count,
                "SocioEconomicallyDisadvantaged": ["Yes"] * count,
                "EnglishLearner": ["No"] * count,
                "FosterYouth": ["No"] * count,
                "Homeless": ["No"] * count,
                "Sealofbiliteracy": ["No"] * count,
                "UC_CSURequirementsMet": ["Yes"] * count,
                "LegacyExtraColumn": ["ignored"] * count,
            }
        )

    def test_default_cohort_range_is_three_consecutive_classes(self):
        self.assertEqual(cte.parse_cohort_years(cte.DEFAULT_COHORT_YEARS), (2023, 2024, 2025))
        self.assertEqual(cte.parse_cohort_years("2023,2024,2025"), (2023, 2024, 2025))
        with self.assertRaises(ValueError):
            cte.parse_cohort_years("2023,2025")
        with self.assertRaisesRegex(ValueError, "at least 3"):
            cte.parse_cohort_years("2025")
        with self.assertRaisesRegex(ValueError, "at least 3"):
            cte.parse_cohort_years("2024-2025")

    def test_cte_cohort_source_key_uses_filtered_152_account_file(self):
        self.assertEqual(
            cte.cte_cohort_source_key("calpads-snap/county=33/district=00000", 2025),
            "calpads-snap/county=33/district=00000/year=2025/"
            "2024-2025_152_account_cte.parquet",
        )

    def test_multiclass_cte_sources_preserve_cohort_year_and_deduplicate(self):
        objects = {}
        years = (2023, 2024, 2025)
        for year in years:
            ssids = [f"1234567{year - 2000:03d}"]
            if year == 2025:
                ssids.append(ssids[0])
            key = cte.cte_cohort_source_key(
                "calpads-snap/county=33/district=00000", year
            )
            objects[key] = parquet_bytes(self.source_frame(ssids, year))
        graduates, summary, duplicates = cte.load_cte_cohorts(
            FakeS3(objects),
            "example-studenttracker-bucket",
            "calpads-snap/county=33/district=00000",
            years,
        )
        self.assertEqual(graduates.height, 3)
        self.assertEqual(graduates.get_column("CohortYear").to_list(), [2023, 2024, 2025])
        self.assertEqual(summary.height, 3)
        self.assertEqual(duplicates.height, 1)
        self.assertEqual(duplicates.row(0, named=True)["CohortYear"], 2025)

    def test_same_ssid_in_multiple_classes_is_a_stopper(self):
        objects = {}
        for year in (2024, 2025):
            key = cte.cte_cohort_source_key(
                "calpads-snap/county=33/district=00000", year
            )
            objects[key] = parquet_bytes(self.source_frame(["1234567890"], year))
        with self.assertRaisesRegex(ValueError, "occur in multiple classes"):
            cte.load_cte_cohorts(
                FakeS3(objects),
                "example-studenttracker-bucket",
                "calpads-snap/county=33/district=00000",
                (2024, 2025),
            )

    def test_request_row_contract_and_optional_name_blanking(self):
        row = cte.request_body_row(self.sample_row())
        self.assertEqual(len(row), 25)
        self.assertEqual(row[0], "D3")
        self.assertEqual(row[3], "")
        self.assertEqual(row[6], "20070102")
        self.assertEqual(row[7], "20250610")
        self.assertEqual(row[8], "050001")
        self.assertEqual(row[11], "1234567890")
        self.assertEqual(row[21], "")

    def test_legitimate_na_name_is_not_treated_as_placeholder(self):
        self.assertEqual(cte.sanitize_text("Na", optional=True), "Na")

    def test_file_envelope_and_trailer_validation(self):
        body = cte.request_body_row(self.sample_row())
        rows = [
            ["H3", "10000000", "", "TEST DISTRICT", "20260828", "SE", "D"],
            body,
            ["T3", "3"],
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.txt"
            cte.write_tsv_atomic(path, rows, overwrite=False)
            result = cte.validate_request_file(path, "10000000", 1, "20260828")
            self.assertEqual(result["student_rows"], 1)
            with path.open(encoding="utf-8") as handle:
                parsed = list(csv.reader(handle, delimiter="\t"))
            self.assertEqual(parsed[-1], ["T3", "3"])


if __name__ == "__main__":
    unittest.main()
