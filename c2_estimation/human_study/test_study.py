"""Synthetic-fixture tests only; never touch existing study databases or test audio."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from .design import assignment, CONSENT, NAMES, VERSION, select_cases
from .server import create_app, digest, ROOT
from .manage import summarize


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="c2-human-tests-", dir=ROOT / "data/processed")
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "audio").mkdir(parents=True)
        self.db = self.root / "responses.sqlite3"
        cases = []
        for case_id in [*[f"case_{i:02d}" for i in range(1, 9)], "practice"]:
            audio = {}
            for label in ("target", "predicted"):
                name = f"{case_id}_{label}.wav"
                (self.bundle / "audio" / name).write_bytes(b"test fixture only")
                audio[label] = {"file": name}
            cases.append({"case_id": case_id, "parameters": [
                {"name": n, "label": n, "predicted_z": .4, "q": .8, "actual_z": .39, "error_z": .01} for n in NAMES], "audio": audio})
        screens = [{"screen_id": f"headphones_{i:02d}", "path": f"headphones_{i:02d}.wav", "correct_interval": i % 3 + 1} for i in range(6)]
        for name in [s["path"] for s in screens] + ["volume_reference.wav"]:
            (self.bundle / "audio" / name).write_bytes(b"test fixture only")
        data = {"version": VERSION, "test_evaluated": False, "cases": cases, "headphones": screens,
                "volume": {"path": "volume_reference.wav"}, "assignments": [assignment(i) for i in range(12)]}
        (self.bundle / "bundle.json").write_text(json.dumps(data))
        self.manifest()
        self.app = create_app(self.bundle, self.db)
        self.client = TestClient(self.app)
        self.auth = {"Authorization": "Bearer " + "a"*64}

    def manifest(self):
        (self.bundle / "manifest.json").write_text(json.dumps({"files": {
            p.relative_to(self.bundle).as_posix(): digest(p) for p in self.bundle.rglob("*") if p.is_file() and p.name != "manifest.json"}}))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def start(self):
        return self.client.post("/api/start", headers=self.auth, json={"consent": {k: True for k in CONSENT}, "experience": "1_to_3"})

    def state(self):
        return self.client.get("/api/session", headers=self.auth).json()

    def action(self, op, answers=None, revision=None):
        return self.client.post("/api/action", headers=self.auth, json={"op": op,
            "revision": self.state()["revision"] if revision is None else revision, "answers": answers or {}})

    def listen(self):
        for audio in self.state()["audio_ids"]:
            self.assertEqual(self.client.get("/api/audio/"+audio, headers=self.auth).status_code, 200)
            for event in ("start", "end"):
                self.assertEqual(self.client.post("/api/play", headers=self.auth, json={"audio_id": audio, "event": event}).status_code, 200)

    def to_practice(self):
        self.assertEqual(self.start().status_code, 200)
        self.listen()
        self.assertEqual(self.action("volume", {"headphones": True, "quiet": True, "comfortable": True}).status_code, 200)
        for i in range(6):
            self.listen()
            self.assertEqual(self.action("headphone", {"interval": i % 3 + 1}).status_code, 200)
        self.assertEqual(self.state()["phase"], "practice")

    def answers(self):
        answer = {"decisions": {n: "cannot_judge" for n in NAMES}, "usefulness": 3, "clarity": 4, "confidence": "cannot_judge", "reason": ""}
        if self.state()["case"]["condition"] == "with":
            answer.update(meaning="I do not know", guarantee="unsure", impossible="no")
        return answer

    def test_counterbalance_and_selection(self):
        counts = Counter()
        for slot in range(12):
            plan = assignment(slot)
            self.assertEqual(plan, assignment(slot))
            self.assertEqual(len({p["case_id"] for p in plan}), 8)
            self.assertEqual(Counter(p["condition"] for p in plan), {"with": 4, "without": 4})
            counts.update((p["case_id"], p["condition"]) for p in plan)
        self.assertEqual(set(counts.values()), {6})
        frame = pd.DataFrame({"sample_id": list("abcdefghi"), "diagnostic_rank": list(range(9)), "split": "validation", "validation_role": "reliability"})
        self.assertEqual(select_cases(frame.iloc[::-1]).sample_id.tolist(), list("abcdefghi"))
        frame.loc[8, "split"] = "test"
        with self.assertRaises(ValueError):
            select_cases(frame)

    def test_consent_access_controls_and_duplicate_start(self):
        self.assertEqual(self.client.get("/api/session").status_code, 401)
        self.assertEqual(self.client.get("/bundle.json").status_code, 404)
        denied = self.client.post("/api/start", headers=self.auth, json={"consent": {k: False for k in CONSENT}, "experience": "1_to_3"})
        self.assertEqual(denied.status_code, 400)
        initial = self.start().json()
        self.assertEqual(self.start().json()["code"], initial["code"])
        self.assertEqual(self.client.get("/api/audio/case_01_target", headers=self.auth).status_code, 403)
        self.assertEqual(self.action("continue").status_code, 409)
        self.assertEqual(self.action("volume", {"headphones": True, "quiet": True, "comfortable": True}).status_code, 400)
        self.assertEqual(self.client.post("/api/start", headers={**self.auth, "Origin": "https://elsewhere.example"}, json={}).status_code, 403)
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example"}).status_code, 403)

    def test_complete_resume_blinding_and_withdrawal(self):
        self.to_practice()
        self.listen()
        self.assertEqual(self.action("response", self.answers()).status_code, 200)
        self.assertEqual(self.action("continue").status_code, 200)
        observed = []
        for i in range(8):
            if i == 4:
                self.assertEqual(self.state()["phase"], "break")
                self.action("continue")
            state = self.state()
            observed.append(state["case"]["case_id"])
            encoded = json.dumps(state["case"])
            self.assertNotIn("actual_z", encoded)
            self.assertNotIn("error_z", encoded)
            if state["case"]["condition"] == "without":
                self.assertNotIn('"q"', encoded)
            self.listen()
            old_revision = state["revision"]
            result = self.action("response", self.answers())
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.action("response", {}, revision=old_revision).status_code, 409)
            with TestClient(create_app(self.bundle, self.db)) as restarted:
                self.assertEqual(restarted.get("/api/session", headers=self.auth).json(), self.state())
        self.assertEqual(len(set(observed)), 8)
        self.assertEqual(self.action("finish", {"preference": "none", "length": "about_right", "comment": ""}).status_code, 200)
        with self.app.state.store.connect() as db:
            states = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions")]
        report = summarize(states)
        self.assertEqual(report["completed_participants"], 1)
        self.assertEqual(report["scored_task_observations"], 8)
        self.assertEqual(report["paired_exploratory"]["confidence"]["n_paired_participants"], 0)
        self.assertEqual(self.action("withdraw").status_code, 200)
        with self.app.state.store.connect() as db:
            saved = json.loads(db.execute("SELECT state FROM sessions").fetchone()[0])
        self.assertEqual(saved["responses"], [])
        self.assertNotIn("experience", saved)
        self.assertNotIn("practice_response", saved)
        self.assertEqual(summarize([saved])["completed_participants"], 0)
        self.assertEqual(self.client.get("/api/audio/practice_target", headers=self.auth).status_code, 403)

    def test_replacement_slot_and_enrolment_cap(self):
        for i in range(16):
            self.auth = {"Authorization": "Bearer " + hashlib.sha256(str(i).encode()).hexdigest()}
            self.assertEqual(self.start().status_code, 200)
            with self.app.state.store.connect() as db:
                row = db.execute("SELECT state FROM sessions WHERE token_hash=?", (hashlib.sha256(self.auth["Authorization"][7:].encode()).hexdigest(),)).fetchone()
                self.assertEqual(json.loads(row[0])["slot"], 0)
            self.action("withdraw")
        self.auth = {"Authorization": "Bearer " + "f"*64}
        self.assertEqual(self.start().status_code, 409)

    def test_screen_failure_and_tamper_detection(self):
        self.start(); self.listen()
        self.action("volume", {"headphones": True, "quiet": True, "comfortable": True})
        for i in range(6):
            self.listen(); self.action("headphone", {"interval": (i+1) % 3 + 1})
        self.assertEqual(self.state()["phase"], "screen_failed")
        self.assertEqual(self.action("continue").status_code, 409)
        (self.bundle / "audio/volume_reference.wav").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            create_app(self.bundle, self.db)


if __name__ == "__main__":
    unittest.main()
