"""Check isolation and researcher-only export using disposable synthetic fixtures."""
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from c2_estimation.human_study.design import CONSENT
from c2_estimation.human_study.test_study import StudyTests as FixtureSource
from .export import export
from .server import ROOT, create_app


class SelfReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureSource()
        self.fixture.setUp()
        self.temp = tempfile.TemporaryDirectory(
            prefix="researcher_self_review_test_", dir=ROOT / "data/processed/c2_v4")
        self.database = Path(self.temp.name) / "responses.sqlite3"

    def tearDown(self):
        self.temp.cleanup()
        self.fixture.tearDown()

    def test_frontend_identity_and_database_isolation(self):
        previous = self.fixture.db.read_bytes()
        app = create_app(self.database, self.fixture.bundle)
        with TestClient(app) as client:
            html = client.get("/")
            self.assertEqual(html.status_code, 200)
            self.assertIn("RESEARCHER SELF-REVIEW", html.text)
            self.assertIn("frame-ancestors", html.headers["content-security-policy"])
            javascript = client.get("/assets/app.js").text
            self.assertIn("c2-researcher-self-review-v1-token", javascript)
            self.assertIn("your judgments are developer observations", javascript)
            self.assertNotIn("c2-human-v1-rehearsal-token", javascript)
            info = client.get("/api/info").json()
            self.assertEqual(info["purpose"], "researcher_self_review")
            self.assertFalse(info["research_collection_enabled"])
            state = client.post("/api/start", headers={"Authorization": "Bearer " + "b" * 64},
                                json={"consent": {k: True for k in CONSENT},
                                      "experience": "1_to_3"}).json()
            self.assertTrue(state["excluded_from_research"])
            self.assertEqual(state["mode"], "rehearsal")
        self.assertEqual(self.fixture.db.read_bytes(), previous)
        # A second launch preserves the self-review database and its session.
        with TestClient(create_app(self.database, self.fixture.bundle)) as client:
            resumed = client.get("/api/session", headers={"Authorization": "Bearer " + "b" * 64})
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(resumed.json()["code"], state["code"])
        with self.assertRaisesRegex(ValueError, "researcher_self_review"):
            create_app(self.fixture.db, self.fixture.bundle)

    def test_export_counts_runs_not_participants_and_refuses_wrong_database(self):
        app = create_app(self.database, self.fixture.bundle)
        with app.state.store.connect() as db:
            for i in range(2):
                synthetic = {"code": f"TEST-{i}", "phase": "complete", "mode": "rehearsal",
                             "excluded_from_research": True, "created": "fixture", "completed": "fixture",
                             "assignment": [], "responses": [], "feedback": {}, "fingerprint": "fixture"}
                db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (str(i), synthetic["code"], json.dumps(synthetic)))
        output = Path(self.temp.name) / "export"
        export(self.database, output)
        summary = json.loads((output / "self_review_summary.json").read_text())
        self.assertEqual(summary["completed_rehearsal_runs"], 2)
        self.assertEqual(summary["independent_participants"], 0)
        self.assertFalse(summary["group_statistics_computed"])
        with self.assertRaisesRegex(ValueError, "not a researcher self-review"):
            export(self.fixture.db, Path(self.temp.name) / "wrong_export")
        with self.assertRaisesRegex(ValueError, "new export folder"):
            export(self.database, output)

    def test_participant_preview_is_separate_and_stays_rehearsal(self):
        with tempfile.TemporaryDirectory(prefix="participant_preview_test_",
                                         dir=ROOT / "data/processed/c2_v4") as directory:
            preview_db = Path(directory) / "responses.sqlite3"
            app = create_app(preview_db, self.fixture.bundle, purpose="participant_preview")
            with TestClient(app) as client:
                self.assertIn("PARTICIPANT STUDY PREVIEW", client.get("/").text)
                self.assertIn("8767", client.get("/").text)
                self.assertIn("8768", client.get("/").text)
                info = client.get("/api/info").json()
                self.assertEqual(info["purpose"], "participant_preview")
                self.assertFalse(info["research_collection_enabled"])
                self.assertIn("c2-participant-preview-v1-token", client.get("/assets/app.js").text)
                before = client.get("/api/info").json()["fingerprint"]
                example = client.get("/api/walkthrough").json()
                self.assertFalse(example["responses_saved"])
                self.assertEqual(len(example["parameters"]), 13)
                self.assertEqual(set(example["parameters"][0]), {"name", "label", "predicted_z", "q"})
                self.assertEqual(client.get("/walkthrough").status_code, 200)
                self.assertEqual(client.get("/api/walkthrough/audio/target").status_code, 200)
                self.assertEqual(client.get("/api/walkthrough/audio/answer_keys").status_code, 404)
                self.assertEqual(client.get("/api/info").json()["fingerprint"], before)
                with app.state.store.connect() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
            with self.assertRaisesRegex(ValueError, "not a researcher self-review"):
                export(preview_db, Path(directory) / "wrong_export")


if __name__ == "__main__":
    unittest.main()
