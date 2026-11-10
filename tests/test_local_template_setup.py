"""REQ-33: local input preparation must preserve existing files."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_template_setup", ROOT / "prepare_local_templates.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class LocalTemplateSetupTests(unittest.TestCase):
    def test_templates_are_created_at_expected_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in setup.FILES:
                source = root / "templates" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"synthetic-header")
            self.assertEqual(setup.prepare(root), 3)
            for relative in setup.FILES:
                self.assertEqual((root / relative).read_bytes(), b"synthetic-header")

    def test_existing_local_inputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in setup.FILES:
                source = root / "templates" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"synthetic-header")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"existing-local-input")
            self.assertEqual(setup.prepare(root), 0)
            for relative in setup.FILES:
                self.assertEqual((root / relative).read_bytes(), b"existing-local-input")


if __name__ == "__main__":
    unittest.main()
