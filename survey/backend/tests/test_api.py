import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import database  # noqa: E402
import main  # noqa: E402


class SurveyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        database.DATABASE_PATH = Path(cls.temporary_directory.name) / "test-survey.db"
        database.initialize_database()
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        cls.temporary_directory.cleanup()

    def start_trial(self, study_id: str) -> tuple[dict, dict]:
        session_response = self.client.post("/api/session/start", json={"study_id": study_id})
        self.assertEqual(session_response.status_code, 200)
        session = session_response.json()
        trial_response = self.client.get(f"/api/session/{session['session_id']}/trial")
        self.assertEqual(trial_response.status_code, 200)
        return session, trial_response.json()

    def test_catalog_exposes_pilot_and_c1_studies(self) -> None:
        response = self.client.get("/api/studies")
        self.assertEqual(response.status_code, 200)
        studies = {study["study_id"]: study for study in response.json()}
        self.assertEqual(set(studies), {"pilot_quality", "c1_descriptors"})
        self.assertEqual(studies["c1_descriptors"]["total_trials"], 20)

    def test_trial_contains_working_nested_audio_url(self) -> None:
        _, payload = self.start_trial("pilot_quality")
        source = payload["trial"]["audio_sources"][0]
        self.assertEqual(source["id"], "sample")
        self.assertNotIn("undefined", source["audio_url"])
        audio_response = self.client.get(source["audio_url"])
        self.assertEqual(audio_response.status_code, 200)
        self.assertEqual(audio_response.headers["content-type"], "audio/wav")

    def test_new_sessions_snapshot_stable_sample_ids(self) -> None:
        session, _ = self.start_trial("pilot_quality")
        with database.get_connection() as connection:
            stored = connection.execute(
                "SELECT trial_order FROM sessions WHERE session_id = ?",
                (session["session_id"],),
            ).fetchone()
        order = json.loads(stored["trial_order"])
        self.assertTrue(order)
        self.assertTrue(all(isinstance(sample_id, str) for sample_id in order))
        self.assertTrue(all(sample_id.startswith("pilot_v1_") for sample_id in order))

    def test_pilot_rejects_invalid_issue_and_zero_plays(self) -> None:
        session, payload = self.start_trial("pilot_quality")
        invalid_issue_request = {
            "trial_id": payload["trial"]["trial_id"],
            "answers": {"issue_type": "NOT_A_REAL_OPTION", "quality_rating": 4, "comment": ""},
            "play_counts": {"sample": 1},
            "started_at": "2026-08-25T10:00:00Z",
        }
        invalid_issue_response = self.client.post(
            f"/api/session/{session['session_id']}/response", json=invalid_issue_request
        )
        self.assertEqual(invalid_issue_response.status_code, 422)

        zero_play_request = {
            **invalid_issue_request,
            "answers": {"issue_type": "none", "quality_rating": 4, "comment": ""},
            "play_counts": {"sample": 0},
        }
        zero_play_response = self.client.post(
            f"/api/session/{session['session_id']}/response", json=zero_play_request
        )
        self.assertEqual(zero_play_response.status_code, 422)

    def test_c1_response_and_study_specific_export(self) -> None:
        session, payload = self.start_trial("c1_descriptors")
        request = {
            "trial_id": payload["trial"]["trial_id"],
            "answers": {
                "dark_bright": 5,
                "smooth_rough": 3,
                "thin_warm": 4,
                "short_sustained": 6,
                "comment": "Internal test",
            },
            "play_counts": {"sample": 1},
            "started_at": "2026-08-25T10:00:00Z",
        }
        response = self.client.post(f"/api/session/{session['session_id']}/response", json=request)
        self.assertEqual(response.status_code, 200)
        export = self.client.get("/api/admin/export/c1_descriptors")
        self.assertEqual(export.status_code, 200)
        self.assertIn("dark_bright", export.text)
        self.assertIn("play_count_sample", export.text)
        self.assertIn("Internal test", export.text)


if __name__ == "__main__":
    unittest.main()
