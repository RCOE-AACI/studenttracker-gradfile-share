# Synthetic test fixtures only; values here are invented and are not student records.
import importlib.util
import io
import unittest
from pathlib import Path

import polars as pl


MODULE_PATH = Path(__file__).resolve().parents[1] / "01x-process_avid_request.py"
SPEC = importlib.util.spec_from_file_location("avid_request", MODULE_PATH)
avid = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(avid)


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


def course_frame(ssid: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "SSID": [ssid, "9999999999"],
            "StateCourse": ["9211", "1000"],
            "DistrictCode": ["3366977", "3366977"],
            "School_Code": ["0123456", "0123456"],
        }
    )


def graduate_frame(ssid: str, cohort_year: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "DistrictCode": ["3366977"],
            "SchoolCode": ["0123456"],
            "SSID": [ssid],
            "StudentCompletionStatus": ["100"],
            "CohortCategory": ["HSDiplomaGraduate"],
            "BirthDate": ["01/02/2005"],
            "StudentEnrollmentExitDate": [f"06/10/{cohort_year}"],
            "Gender": ["M"],
            "EthnicityRace": ["Hispanic"],
            "MigrantEd": ["No"],
            "StudentswithDisabilities": ["No"],
            "SocioEconomicallyDisadvantaged": ["Yes"],
            "EnglishLearner": ["No"],
            "FosterYouth": ["No"],
            "Homeless": ["No"],
            "Sealofbiliteracy": ["No"],
            "UC_CSURequirementsMet": ["Yes"],
            "CohortYear": [str(cohort_year)],
        }
    )


class AvidRequestTests(unittest.TestCase):
    def test_default_is_four_classes_and_single_class_is_allowed(self):
        self.assertEqual(
            avid.parse_cohort_years(avid.DEFAULT_COHORT_YEARS),
            (2022, 2023, 2024, 2025),
        )
        self.assertEqual(avid.parse_cohort_years("2025"), (2025,))

    def test_annual_source_keys_pair_same_year_course_and_graduate_reports(self):
        prefix = "calpads-snap/county=33/district=00000"
        self.assertEqual(
            avid.annual_source_key(prefix, 2025, "course"),
            f"{prefix}/year=2025/2024-2025_311_snap.parquet",
        )
        self.assertEqual(
            avid.annual_source_key(prefix, 2025, "graduate"),
            f"{prefix}/year=2025/2024-2025_152_account.parquet",
        )

    def test_multiclass_sources_preserve_year_and_same_year_intersection(self):
        years = (2022, 2023, 2024, 2025)
        objects = {}
        expected = []
        for year in years:
            ssid = f"1234567{year - 2000:03d}"
            expected.append(ssid)
            objects[avid.annual_source_key("prefix", year, "course")] = parquet_bytes(
                course_frame(ssid)
            )
            objects[avid.annual_source_key("prefix", year, "graduate")] = parquet_bytes(
                graduate_frame(ssid, year)
            )
        matched, sources, cohorts, duplicates = avid.load_avid_cohorts(
            FakeS3(objects), "bucket", "prefix", years
        )
        self.assertEqual(matched.get_column("SSID").to_list(), expected)
        self.assertEqual(matched.get_column("CohortYear").to_list(), list(years))
        self.assertEqual(sources.height, 8)
        self.assertEqual(cohorts.height, 4)
        self.assertEqual(duplicates.height, 0)

    def test_same_ssid_in_multiple_classes_is_a_stopper(self):
        objects = {}
        for year in (2024, 2025):
            objects[avid.annual_source_key("prefix", year, "course")] = parquet_bytes(
                course_frame("1234567890")
            )
            objects[avid.annual_source_key("prefix", year, "graduate")] = parquet_bytes(
                graduate_frame("1234567890", year)
            )
        with self.assertRaisesRegex(ValueError, "occur in multiple classes"):
            avid.load_avid_cohorts(
                FakeS3(objects), "bucket", "prefix", (2024, 2025)
            )


if __name__ == "__main__":
    unittest.main()
