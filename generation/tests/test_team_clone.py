"""Fresh-clone setup safety and byte preservation; no synthesis or real corpus writes."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from generation import prepare_team_clone as setup


class TeamCloneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / "share.zip"
        self.payload = {name: (name + "\r\nfrozen\n").encode() for name in setup.FILES}
        integrity = {name: hashlib.sha256(content).hexdigest() for name, content in self.payload.items()}
        with zipfile.ZipFile(self.bundle, "w") as archive:
            for name, content in self.payload.items():
                archive.writestr(name, content)
            archive.writestr("reference/package_integrity.json", json.dumps({"files": {"recipe": integrity}}))
        self.sha = setup.checksum(self.bundle)

    def run_setup(self, apply):
        with patch.object(setup, "validate_clone"), patch.object(setup, "require_clean_file"):
            setup.prepare(self.bundle, self.root, apply, expected_sha=self.sha)

    def test_check_no_writes_apply_preserves_metadata_and_exact_source_bytes(self):
        metadata = self.root / setup.PILOT_METADATA[0]
        metadata.parent.mkdir(parents=True)
        metadata.write_bytes(b"tracked reference; audio absent")
        source = self.root / "generation/generate_corpus.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"previous clean git revision\r\n")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.run_setup(False)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.run_setup(True)
        self.assertFalse(metadata.exists())
        backups = list((self.root / "data/processed").glob("team_clone_setup_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / setup.PILOT_METADATA[0]).read_bytes(), b"tracked reference; audio absent")
        self.assertEqual((backups[0] / "generation/generate_corpus.py").read_bytes(), b"previous clean git revision\r\n")
        for name, content in self.payload.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertFalse((self.root / "data/raw").exists())
        self.run_setup(True)
        self.assertEqual(len(list((self.root / "data/processed").glob("team_clone_setup_*"))), 1)

    def test_wrong_bundle_or_edited_file_stops_before_writing(self):
        with patch.object(setup, "validate_clone"):
            with self.assertRaisesRegex(ValueError, "checksum"):
                setup.prepare(self.bundle, self.root, True, expected_sha="wrong")
            path = self.root / "requirements.txt"
            path.write_bytes(b"local edits")
            with patch.object(setup, "require_clean_file", side_effect=ValueError("edited")):
                with self.assertRaisesRegex(ValueError, "edited"):
                    setup.prepare(self.bundle, self.root, True, expected_sha=self.sha)
            self.assertEqual(path.read_bytes(), b"local edits")
            self.assertFalse((self.root / "reference").exists())

    def test_existing_dataset_is_rejected(self):
        existing = self.root / "data/raw/corpus_v4"
        existing.mkdir(parents=True)
        with patch.object(setup, "git", return_value=type("Result", (), {
                "returncode": 0, "stdout": str(self.root)})()):
            with self.assertRaisesRegex(ValueError, "Existing dataset"):
                setup.validate_clone(self.root)
        self.assertTrue(existing.exists())

    def test_path_escape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            setup.local_path(self.root, "../outside")


if __name__ == "__main__":
    unittest.main()
