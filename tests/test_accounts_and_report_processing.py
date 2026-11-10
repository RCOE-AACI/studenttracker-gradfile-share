"""Synthetic integration tests for REQ-03, REQ-11A, REQ-12, and REQ-15."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccountAndReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upload = load("02-upload.py", "report_processing_test")
        cls.migrant = load("13-build_migrant_workbook.py", "migrant_title_test")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.chdir, self.old_cwd)
        self.cred = {"sa": "10000001", "user": "demo", "pass": "unused-synthetic", "district": "Example"}

    def test_receive_fallback_uses_current_login(self):
        self.assertEqual(self.upload._receive_target_dirs("demo"),
                         ["receive", "/receive", "/Home/demo/receive"])

    def test_report_processing_preserves_scope_dates_and_detail_isolation(self):
        raw = Path("downloads/20261110/Example")
        raw.mkdir(parents=True)
        files = {
            "demo_10000001_050001_987_BASIC_EFFDT_20260101_RUNDT_20260102.xls": b"school",
            "demo_10000001_10000001_987_BASIC_EFFDT_20260101_RUNDT_20260102.pdf": b"district",
            "demo_10000001-987-DETAIL-EFFDT-20260101-RUNDT-20260102.csv": b"synthetic-detail",
        }
        for name, payload in files.items():
            (raw / name).write_bytes(payload)
        school_refs = pd.DataFrame([{"SA": "10000001", "ACT": "050001", "HSName": "Example High"}])
        with mock.patch.object(self.upload, "schools", school_refs), contextlib.redirect_stdout(io.StringIO()):
            self.upload.expand_and_rename("20261110", suffix="_CTE", creds_override=[self.cred],
                                          comprehensive_only=False)
        processed = Path("processed/20261110/Example")
        expected = {
            "NSC_Example_Example High_Basic_CTE_EFFDT20260101_RUNDT20260102.xls",
            "NSC_Example__Districtwide_Basic_CTE_EFFDT20260101_RUNDT20260102.pdf",
        }
        self.assertEqual({p.name for p in (processed / "reports").iterdir()}, expected)
        self.assertEqual([p.name for p in (processed / "detail").iterdir()],
                         ["NSC_Example_Detail_10000001_987_CTE_EFFDT20260101_RUNDT20260102.csv"])
        with zipfile.ZipFile(processed / "Example_CTE_renamed.zip") as archive:
            self.assertEqual(set(archive.namelist()), expected)
        self.assertEqual({p.name: p.read_bytes() for p in raw.iterdir()}, files)

    def test_equal_size_different_reports_are_both_retained(self):
        Path("source.xls").write_bytes(b"new!")
        Path("target.xls").write_bytes(b"old!")
        self.upload._move_or_dedupe("source.xls", "target.xls")
        self.assertEqual(Path("target.xls").read_bytes(), b"old!")
        self.assertEqual(Path("target__dup2.xls").read_bytes(), b"new!")
        Path("source.xls").write_bytes(b"old!")
        self.upload._move_or_dedupe("source.xls", "target.xls")
        self.assertFalse(Path("source.xls").exists())
        self.assertFalse(Path("target__dup3.xls").exists())

    def test_conflicting_account_school_mapping_is_rejected(self):
        refs = pd.DataFrame([{"SA": "10000001", "ACT": "050001", "HSName": name}
                             for name in ("Example One", "Example Two")])
        with mock.patch.object(self.upload, "schools", refs), self.assertRaisesRegex(ValueError, "Conflicting"):
            self.upload._build_school_lookup()

    def test_numeric_excel_codes_and_vendor_act_prefixes_are_normalized(self):
        refs = pd.DataFrame([{"SA": "00000001", "ACT": "50001", "HSName": "Example"}])
        with mock.patch.object(self.upload, "schools", refs):
            self.assertEqual(self.upload._build_school_lookup(), {("00000001", "050001"): "Example"})
        self.assertEqual(self.upload._normalize_act_token("HS050001"), "050001")
        self.assertEqual(self.upload._normalize_act_token("HSA30452"), "A30452")

    def test_foreign_service_account_cannot_be_labeled_as_selected_district(self):
        raw = Path("downloads/20261110/Example")
        raw.mkdir(parents=True)
        (raw / "demo_10000002_050001_987_BASIC.xls").write_bytes(b"other-account")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "SA does not match"):
            self.upload.expand_and_rename("20261110", creds_override=[self.cred], comprehensive_only=False)
        self.assertFalse(list(Path("processed").rglob("NSC_*")))

    def test_archive_errors_never_persist_vendor_exception_text(self):
        marker = "synthetic-sensitive-exception-payload"
        with mock.patch.object(self.upload, "_connect_sftp", side_effect=OSError(marker)):
            result = self.upload.inventory_receive_archive([self.cred], output_path="inventory.json")
        self.assertEqual(result[0]["error"], "OSError")
        self.assertNotIn(marker, Path("inventory.json").read_text())

    def test_download_transfer_errors_are_recorded_as_class_only(self):
        marker = "synthetic-sensitive-exception-payload"
        ssh = mock.Mock()
        ssh.open_sftp.side_effect = OSError(marker)
        output = io.StringIO()
        with mock.patch.object(self.upload.paramiko, "SSHClient", return_value=ssh), contextlib.redirect_stdout(output):
            self.upload.download_files("20261110", [self.cred])
        state = Path("state/downloads/20261110/download/demo.json").read_text()
        self.assertEqual(json.loads(state)["error"], "OSError")
        self.assertNotIn(marker, output.getvalue() + state)
        ssh.close.assert_called_once()

    def test_upload_connection_error_is_sanitized(self):
        Path("requestfiles").mkdir()
        Path("requestfiles/20261110_10000001_Example.txt").write_text("synthetic")
        transport = mock.Mock()
        transport.connect.side_effect = OSError("synthetic-sensitive-exception-payload")
        with mock.patch.object(self.upload.paramiko.transport, "Transport", return_value=transport), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "Upload connection failed: OSError") as error:
                self.upload.upload_requests([self.cred], request=True, cohort_years=(2025,), run_date="20261110")
        state = next(Path("state").rglob("*.json")).read_text()
        self.assertEqual(json.loads(state)["error"], "OSError")
        self.assertNotIn("synthetic-sensitive-exception-payload", str(error.exception) + state)

    def test_migrant_title_matches_participating_scope(self):
        one = pd.DataFrame({"district": ["Example District", "Example District"]})
        many = pd.DataFrame({"district": ["Example District", "Other District"]})
        self.assertEqual(self.migrant.workbook_title(one), "Example District - Migrant StudentTracker Summary")
        self.assertEqual(self.migrant.workbook_title(many), "Participating Districts - Migrant StudentTracker Summary")
        self.assertEqual(self.migrant.workbook_title(many, "Explicit scope"), "Explicit scope")
        with self.assertRaises(ValueError):
            self.migrant.workbook_title(pd.DataFrame({"district": []}))


if __name__ == "__main__":
    unittest.main()
