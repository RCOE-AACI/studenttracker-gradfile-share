# Synthetic test fixtures only; values here are invented and are not student records.
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import paramiko


MODULE_PATH = Path(__file__).resolve().parents[1] / "02-upload.py"
SPEC = importlib.util.spec_from_file_location("studenttracker_upload", MODULE_PATH)
upload = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(upload)


class _FailingTransport:
    connect_calls = 0

    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def connect(self, **_kwargs):
        type(self).connect_calls += 1
        raise paramiko.ssh_exception.AuthenticationException()

    def close(self):
        self.closed = True


class _FailingSSHClient:
    connect_calls = 0

    def set_missing_host_key_policy(self, _policy):
        pass

    def connect(self, **_kwargs):
        type(self).connect_calls += 1
        raise paramiko.ssh_exception.AuthenticationException()

    def close(self):
        pass


class TransferAuthenticationFailFastTests(unittest.TestCase):
    def setUp(self):
        _FailingTransport.connect_calls = 0
        _FailingSSHClient.connect_calls = 0
        self.credentials = [
            {"sa": "10000001", "user": "account1", "pass": "secret1", "district": "One"},
            {"sa": "10000002", "user": "account2", "pass": "secret2", "district": "Two"},
        ]

    def test_upload_stops_after_first_authentication_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("requestfiles").mkdir()
                Path("requestfiles/20260825_10000001_One.txt").write_text("test")
                Path("requestfiles/20260825_10000002_Two.txt").write_text("test")
                with mock.patch.object(upload.paramiko.transport, "Transport", _FailingTransport):
                    with self.assertRaises(upload.TransferAuthenticationError):
                        upload.upload_requests(
                            self.credentials,
                            request=True,
                            run_date="20260825",
                            state_base=str(Path(tmp) / "state"),
                            cohort_years=(2024, 2025),
                        )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(_FailingTransport.connect_calls, 1)

    def test_upload_scope_stops_before_any_connection(self):
        with mock.patch.object(upload.paramiko.transport, "Transport", _FailingTransport):
            with self.assertRaisesRegex(ValueError, "cohort_years is required"):
                upload.upload_requests(self.credentials, request=True)
            with self.assertRaisesRegex(ValueError, "at least 1"):
                upload.upload_requests(
                    self.credentials, request=True, cohort_years=()
                )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                upload.upload_requests(
                    self.credentials, request=False, cohort_years=(2024, 2025)
                )
        self.assertEqual(_FailingTransport.connect_calls, 0)

    def test_download_stops_after_first_authentication_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with mock.patch.object(upload.paramiko, "SSHClient", _FailingSSHClient):
                    with self.assertRaises(upload.TransferAuthenticationError):
                        upload.download_files(
                            "20260825",
                            self.credentials,
                            state_base=str(Path(tmp) / "state"),
                        )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(_FailingSSHClient.connect_calls, 1)


if __name__ == "__main__":
    unittest.main()
