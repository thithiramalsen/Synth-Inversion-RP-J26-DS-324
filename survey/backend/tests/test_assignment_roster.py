"""Recruitment names never enter participant responses or research downloads."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "survey/backend"))
sys.path.insert(0, str(ROOT))
import assignment_roster
import c1_pilot
import c4_pilot
import database
import main
import security

ADMIN = "roster-tests-admin-token-at-least-thirty-two-characters"


class AssignmentRosterTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, "DATABASE_PATH", Path(temporary) / "test.sqlite"))
        self.enterContext(patch.dict(os.environ, {
            "SURVEY_DATABASE_URL": getattr(self, "postgres_test_url", ""),
            "SURVEY_ADMIN_TOKEN": ADMIN,
            "SURVEY_C1_BUNDLE": str(ROOT / "survey/deploy/study/c1_participant_bundle_v1.json"),
            "SURVEY_C1_CONFIG": str(ROOT / "survey/config/c1_participants_v1.json"),
            "SURVEY_C4_BUNDLE": str(ROOT / "survey/deploy/study/c4_participant_bundle_v1.json"),
            "SURVEY_C4_CONFIG": str(ROOT / "survey/config/c4_participants_v1.json"),
            "SURVEY_C1_OPEN": "1", "SURVEY_C4_OPEN": "1",
        }))
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {"Authorization": "Bearer " + ADMIN}

    def roster(self, component):
        response = self.client.get(f"/api/{component}-pilot/admin/roster", headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        return response.json()

    def save(self, component, roster, name, version=0, assignment_id=None, **changes):
        body = dict(bundle_hash=roster["bundle_hash"],
                    assignment_id=assignment_id or roster["assignments"][0]["assignment_id"],
                    participant_name=name, expected_version=version)
        body.update(changes)
        return self.client.post(f"/api/{component}-pilot/admin/assignment-name", headers=self.admin, json=body)

    def test_authentication_required_for_both_studies(self):
        for component in ("c1", "c4"):
            roster = self.roster(component)
            self.assertGreater(len(roster["assignments"]), 0)
            self.assertTrue(all(row["status"] == "missing" for row in roster["assignments"]))
            self.assertEqual(self.client.get(f"/api/{component}-pilot/admin/roster").status_code, 401)
            body = dict(bundle_hash=roster["bundle_hash"], assignment_id=roster["assignments"][0]["assignment_id"],
                        participant_name="A recruiter label", expected_version=0)
            self.assertEqual(self.client.post(f"/api/{component}-pilot/admin/assignment-name", json=body).status_code, 401)

    def test_names_persist_clear_and_record_the_authenticated_researcher(self):
        self.client.cookies.set(security.SESSION_COOKIE, security.new_session("recruiter.two"))
        for component in ("c1", "c4"):
            initial = self.roster(component)
            saved = self.save(component, initial, "  Test participant / nickname  ")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.headers["cache-control"], "private, no-store")
            record = saved.json()["assignment"]
            self.assertEqual(record["participant_name"], "Test participant / nickname")
            self.assertEqual(record["version"], 1)
            self.assertEqual(record["updated_by"], "recruiter.two")
            self.assertIsNotNone(record["updated_at"])
            assignment_roster.initialize_roster_database()
            self.assertEqual(self.roster(component)["assignments"][0], record)
            cleared = self.save(component, initial, "  ", version=1)
            self.assertEqual(cleared.status_code, 200, cleared.text)
            self.assertEqual(cleared.json()["assignment"]["participant_name"], "")
            self.assertEqual(cleared.json()["assignment"]["version"], 2)
            # Clearing does not reset the version and allow a stale first writer.
            self.assertEqual(self.save(component, initial, "Stale recruiter").status_code, 409)

    def test_conflicting_recruiters_and_invalid_versions_cannot_overwrite(self):
        for component in ("c1", "c4"):
            roster = self.roster(component)
            first = self.save(component, roster, "Alice")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["assignment"]["updated_by"], "Admin token")
            stale = self.save(component, roster, "Bob")
            self.assertEqual(stale.status_code, 409)
            self.assertIn("Another researcher", stale.json()["detail"])
            self.assertEqual(self.roster(component)["assignments"][0]["participant_name"], "Alice")
            for version in (-1, True, "1"):
                self.assertEqual(self.save(component, roster, "Bob", version=version).status_code, 422)
            self.assertEqual(self.save(component, roster, "Bob", bundle_hash="old-version").status_code, 409)
            self.assertEqual(self.save(component, roster, "Bob", assignment_id="unknown").status_code, 404)
            self.assertEqual(self.save(component, roster, "x" * 101).status_code, 422)
            self.assertEqual(self.save(component, roster, "Alice\nBob").status_code, 422)

    def test_names_are_isolated_by_component_study_and_bundle(self):
        for component, module in (("c1", c1_pilot), ("c4", c4_pilot)):
            original = self.roster(component)
            self.assertEqual(self.save(component, original, "Private original name").status_code, 200)
            bundle, checksum = module.load_bundle()
            changed_study = dict(bundle, study_id=bundle["study_id"] + "_another_study")
            for altered_bundle, altered_checksum in ((changed_study, checksum), (bundle, "different-bundle-hash")):
                with patch.object(module, "load_bundle", return_value=(altered_bundle, altered_checksum)):
                    isolated = self.roster(component)
                    self.assertEqual(isolated["assignments"][0]["participant_name"], "")
                    self.assertEqual(isolated["assignments"][0]["version"], 0)
                    self.assertEqual(self.save(component, isolated, "Separate name").status_code, 200)
            self.assertEqual(self.roster(component)["assignments"][0]["participant_name"], "Private original name")
        with database.get_connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assignment_roster").fetchone()[0], 6)

    def test_simultaneous_recruiters_reserve_the_same_slot_only_once(self):
        for component in ("c1", "c4"):
            roster = self.roster(component)
            barrier = Barrier(2)

            def reserve(name):
                barrier.wait(timeout=10)
                return self.save(component, roster, name).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(reserve, ("Recruiter one listener", "Recruiter two listener")))
            self.assertEqual(statuses, [200, 409])
            self.assertEqual(self.roster(component)["assignments"][0]["version"], 1)

    def test_a_name_can_reserve_an_assignment_before_invitations_exist(self):
        for component in ("c1", "c4"):
            roster = self.roster(component)
            assignment = roster["assignments"][0]["assignment_id"]
            self.assertEqual(self.save(component, roster, "Reserved before issuing").status_code, 200)
            endpoint = f"/api/{component}-pilot/admin"
            bulk = self.client.post(endpoint + "/replace-unused-invitations", headers=self.admin,
                                    json={"confirm_replace_unused": True})
            self.assertEqual(bulk.status_code, 200, bulk.text)
            self.assertEqual(bulk.json()["reserved_assignments"], [assignment])
            self.assertEqual(self.roster(component)["assignments"][0]["status"], "missing")
            issued = self.client.post(endpoint + "/invitations", headers=self.admin)
            self.assertEqual(issued.status_code, 200, issued.text)
            self.assertEqual([row["assignment_id"] for row in issued.json()["invitations"]], [assignment])
            self.assertEqual(self.roster(component)["assignments"][0]["status"], "issued")

    def test_reserved_names_protect_codes_from_bulk_replacement(self):
        for component in ("c1", "c4"):
            initial = self.roster(component)
            prefix = f"/api/{component}-pilot"
            codes = self.client.post(prefix + "/admin/invitations", headers=self.admin).json()["invitations"]
            assignment = codes[0]["assignment_id"]
            self.assertEqual(self.save(component, initial, "Already assigned", assignment_id=assignment).status_code, 200)
            regenerated = self.client.post(prefix + "/admin/replace-unused-invitations", headers=self.admin,
                                           json={"confirm_replace_unused": True})
            self.assertEqual(regenerated.status_code, 200, regenerated.text)
            self.assertIn(assignment, regenerated.json()["skipped_assignments"])
            self.assertEqual(regenerated.json()["reserved_assignments"], [assignment])
            self.assertNotIn(assignment, [row["assignment_id"] for row in regenerated.json()["invitations"]])
            with database.get_connection() as db:
                existing = db.execute(f"SELECT invite_hash FROM {component}_invites WHERE bundle_hash=? "
                                      "AND assignment_id=? AND retired_at IS NULL",
                                      (initial["bundle_hash"], assignment)).fetchone()
            self.assertEqual(existing["invite_hash"], security.token_hash(codes[0]["invitation"]))
            # The explicit, one-slot replacement preserves its recruitment label.
            replacement = self.client.post(prefix + "/admin/replace-invitation", headers=self.admin,
                                           json={"assignment_id": assignment, "reason": "Recruiter explicitly requests a new code"})
            self.assertEqual(replacement.status_code, 200, replacement.text)
            self.assertEqual(self.roster(component)["assignments"][0]["participant_name"], "Already assigned")

    def test_names_never_enter_sessions_rating_exports_or_response_viewer(self):
        for component in ("c1", "c4"):
            prefix = f"/api/{component}-pilot"
            initial = self.roster(component)
            codes = self.client.post(prefix + "/admin/invitations", headers=self.admin).json()["invitations"]
            private_name = f"PRIVATE-RECRUITMENT-NAME-{component}"
            self.assertEqual(self.save(component, initial, private_name).status_code, 200)
            session = self.client.post(prefix + "/sessions", json={
                "invitation": codes[0]["invitation"], "adult": True, "consent": True,
                "headphones": True, "quiet_environment": True, "understands_language": True,
                "activities": ["Sound design"], "experience_months": 12, "recent_frequency": "Weekly",
                "tools": "Test synthesizer", "example": "I made synthesizer sounds for a music production.",
            })
            self.assertEqual(session.status_code, 200, session.text)
            data = session.json()
            auth = {"Authorization": "Bearer " + data["token"]}
            row = self.roster(component)["assignments"][0]
            self.assertEqual(row["status"], "in_progress")
            self.assertEqual(row["participant_label"], "Listener 001")
            for suffix in ("/admin/summary", "/admin/export", "/admin/sessions", "/admin/responses", "/status"):
                response = self.client.get(prefix + suffix, headers=self.admin)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn(private_name, response.text)
                self.assertNotIn("participant_name", response.text)
            participant_state = self.client.get(prefix + "/sessions/" + data["session_id"], headers=auth)
            self.assertEqual(participant_state.status_code, 200, participant_state.text)
            self.assertNotIn(private_name, participant_state.text)
            self.assertEqual(self.client.get(prefix + "/admin/roster", headers=auth).status_code, 401)
            with database.get_connection() as db:
                stored = db.execute(f"SELECT * FROM {component}_sessions").fetchall()
            self.assertNotIn(private_name, str([dict(row) for row in stored]))


if __name__ == "__main__":
    unittest.main()
