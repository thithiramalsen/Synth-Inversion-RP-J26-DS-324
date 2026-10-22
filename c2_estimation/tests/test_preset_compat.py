"""Metadata-only conversion and isolated HTTP checks, never real study data."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from c2_estimation.live.preset_compat import (
    AUDIT_NAME, PATCH_NAME, CompatibilityError, cached_export, checked_inputs,
    convert_document, export_directory, input_hashes, prepare_export, sha,
)
from c2_estimation.live.server import create_app
from c2_estimation.tests.scratch import temporary_directory


def document():
    return {"synth_version": "99999.9.9", "comments": "Keep 99999.9.9 in ordinary text.",
            "settings": {"cutoff": .5, "modulations": [{"source": "env_2", "destination": "filter"}],
                         "wavetables": [{"version": "99999.9.9", "data": "AA99999.9.9=="} for _ in range(3)]}}


def fake_checks(*args):
    return {"all_controls_exact": True, "research_controls_match_saved": True,
            "raw_stereo_audio_exact": True, "conditioned_audio_exact": True,
            "saved_reconstruction_exact": True}


class ConversionTests(unittest.TestCase):
    def test_only_four_known_version_fields_change(self):
        source = document()
        original = deepcopy(source)
        converted, changes = convert_document(source)
        self.assertEqual(source, original)
        self.assertEqual(len(changes), 4)
        self.assertEqual(converted["synth_version"], "1.6.4")
        self.assertEqual(converted["comments"], source["comments"])
        for table in converted["settings"]["wavetables"]:
            self.assertEqual(table["version"], "1.6.4")
            self.assertEqual(table["data"], "AA99999.9.9==")
        converted["synth_version"] = source["synth_version"]
        for table in converted["settings"]["wavetables"]:
            table["version"] = "99999.9.9"
        self.assertEqual(converted, source)

    def test_matching_target_is_idempotent(self):
        converted, _ = convert_document(document())
        again, changes = convert_document(converted)
        self.assertEqual(again, converted)
        self.assertEqual(changes, [])

    def test_real_future_versions_are_not_downgraded(self):
        source = document()
        source["synth_version"] = "1.7.0"
        with self.assertRaises(CompatibilityError):
            convert_document(source)
        source = document()
        source["settings"]["wavetables"][0]["version"] = "2.0.0"
        with self.assertRaises(CompatibilityError):
            convert_document(source)

    def test_unknown_schema_is_rejected(self):
        for value in (None, {}, {"synth_version": "99999.9.9"}):
            with self.subTest(value=value), self.assertRaises(CompatibilityError):
                convert_document(value)

    def test_result_id_cannot_escape_output_folder(self):
        for job in ("../outside", "a/b", "", "x" * 32):
            with self.subTest(job=job), self.assertRaises(CompatibilityError):
                export_directory(Path("unused"), job)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_directory(prefix="desktop-export-test-")
        self.root = Path(self.temp.name)
        self.job = "a" * 32
        job_folder = self.root / "jobs" / self.job
        job_folder.mkdir(parents=True)
        (self.root / "status").mkdir()
        self.status = self.root / "status" / (self.job + ".json")
        self.status.write_text(json.dumps({"state": "complete"}))
        source = job_folder / "predicted.vital"
        source.write_text(json.dumps(document()))
        (job_folder / "result.json").write_text(json.dumps({"export_audit": {"patch_sha256": sha(source)}}))
        (job_folder / "reconstruction_float.wav").write_bytes(b"synthetic mock waveform")
        (job_folder / "manifest.json").write_text(json.dumps({"files": {
            p.name: sha(p) for p in job_folder.iterdir() if p.is_file()}}))
        self.paths = checked_inputs(self.root, self.job)
        self.folder = export_directory(self.root, self.job)
        self.originals = {p: sha(p) for p in job_folder.iterdir() if p.is_file()}
        self.originals[self.status] = sha(self.status)

    def tearDown(self):
        self.temp.cleanup()

    def assert_originals_unchanged(self):
        self.assertEqual({p: sha(p) for p in self.originals}, self.originals)

    def test_success_keeps_original_job_and_caches_verified_copy(self):
        with patch("c2_estimation.live.preset_compat.verify_pair", side_effect=fake_checks) as verify:
            exported, audit = prepare_export(None, self.paths, self.folder)
            self.assertEqual(exported.name, PATCH_NAME)
            self.assertFalse(audit["desktop_vital_checked"])
            self.assertEqual(len(audit["metadata_changes"]), 4)
            self.assertTrue((self.folder / AUDIT_NAME).is_file())
            self.assertEqual(prepare_export(None, self.paths, self.folder)[0], exported)
            self.assertEqual(verify.call_count, 1)
        self.assert_originals_unchanged()

    def test_verification_failure_publishes_nothing(self):
        with patch("c2_estimation.live.preset_compat.verify_pair", side_effect=CompatibilityError("audio changed")):
            with self.assertRaisesRegex(CompatibilityError, "audio changed"):
                prepare_export(None, self.paths, self.folder)
        self.assertFalse(self.folder.exists())
        self.assertFalse(list(self.folder.parent.glob(".building-*")))
        self.assert_originals_unchanged()

    def test_tampered_copy_is_not_served_or_overwritten(self):
        with patch("c2_estimation.live.preset_compat.verify_pair", side_effect=fake_checks):
            exported, _ = prepare_export(None, self.paths, self.folder)
        exported.write_text("tampered")
        with self.assertRaises(CompatibilityError):
            cached_export(self.folder, input_hashes(self.paths))
        with self.assertRaises(CompatibilityError):
            prepare_export(None, self.paths, self.folder)
        self.assertEqual(exported.read_text(), "tampered")
        self.assert_originals_unchanged()

    def test_modified_source_or_unfinished_job_is_rejected(self):
        self.paths["predicted.vital"].write_text("changed")
        with self.assertRaises(CompatibilityError):
            checked_inputs(self.root, self.job)
        self.status.write_text(json.dumps({"state": "running"}))
        with self.assertRaisesRegex(CompatibilityError, "completed"):
            checked_inputs(self.root, self.job)

    def test_http_export_uses_worker_and_preserves_job(self):
        fake = SimpleNamespace(metadata=lambda: {"device": "fixture"})
        app = create_app(self.root, engine_factory=lambda: fake)
        base = f"/api/jobs/{self.job}/compatibility/vital-1.6.4"
        with TestClient(app, base_url="http://127.0.0.1:8770") as client:
            self.assertEqual(client.post(base).status_code, 403)
            self.assertEqual(client.get(base + "/patch").status_code, 409)
            def check_worker(*args):
                self.assertEqual(app.state.jobs.active, self.job)
                return fake_checks()
            with patch("c2_estimation.live.preset_compat.verify_pair", side_effect=check_worker):
                response = client.post(base, headers={"X-C2-Request": "1"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNone(app.state.jobs.active)
            download = client.get(response.json()["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.json()["synth_version"], "1.6.4")
            self.assertIn(PATCH_NAME, download.headers["content-disposition"])
            self.assertFalse(client.get(response.json()["audit_url"]).json()["desktop_vital_checked"])
            self.assertEqual(client.get(base + "/unknown").status_code, 404)
            app.state.jobs.active = "b" * 32
            self.assertEqual(client.post(base, headers={"X-C2-Request": "1"}).status_code, 409)
            app.state.jobs.active = None
        self.assert_originals_unchanged()


if __name__ == "__main__":
    unittest.main()
