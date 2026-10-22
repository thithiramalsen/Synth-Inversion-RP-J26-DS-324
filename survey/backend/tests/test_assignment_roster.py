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

    def change_code(self, component, roster, record=None, **changes):
        row = record or roster['assignments'][0]
        body = dict(bundle_hash=roster['bundle_hash'], assignment_id=row['assignment_id'],
                    expected_version=row['version'], expected_invitation=row['invitation_version'],
                    reason='Recruiter needs to send a fresh invitation code', confirm_session_close=False)
        body.update(changes)
        return self.client.post(f'/api/{component}-pilot/admin/assignment-invitation', headers=self.admin, json=body)

    def start_code(self, component, code):
        return self.client.post(f'/api/{component}-pilot/sessions', json={
            'invitation': code, 'adult': True, 'consent': True, 'headphones': True,
            'quiet_environment': True, 'understands_language': True, 'activities': ['Sound design'],
            'experience_months': 12, 'recent_frequency': 'Weekly', 'tools': 'Test synthesizer',
            'example': 'I made synthesizer sounds for a music production.',
        })

    def test_current_codes_are_recoverable_only_in_admin_roster_and_encrypted_in_storage(self):
        for component in ('c1', 'c4'):
            prefix = f'/api/{component}-pilot'
            issued = self.client.post(prefix+'/admin/invitations', headers=self.admin).json()['invitations']
            code = issued[0]['invitation']
            row = self.roster(component)['assignments'][0]
            self.assertEqual(row['invitation'], code)
            self.assertEqual(row['invitation_status'], 'available')
            assignment_roster.initialize_roster_database()
            self.assertEqual(self.roster(component)['assignments'][0]['invitation'], code)
            with database.get_connection() as db:
                encrypted = db.execute('SELECT encrypted_code FROM invitation_code_vault WHERE component=? AND invite_hash=?',
                                       (component, security.token_hash(code))).fetchone()[0]
            self.assertNotIn(code, encrypted)
            for suffix in ('/admin/summary', '/admin/export', '/admin/sessions', '/admin/responses', '/status'):
                self.assertNotIn(code, self.client.get(prefix+suffix, headers=self.admin).text)
            started = self.start_code(component, code)
            self.assertEqual(started.status_code, 200, started.text)
            self.assertNotIn(code, started.text)

    def test_inline_code_creation_and_replacement_reject_stale_recruiters(self):
        for component in ('c1', 'c4'):
            initial = self.roster(component)
            self.assertEqual(self.save(component, initial, 'Assigned listener').status_code, 200)
            current = self.roster(component)
            created = self.change_code(component, current)
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.headers['cache-control'], 'private, no-store')
            first = created.json()['assignment']
            self.assertEqual(first['participant_name'], 'Assigned listener')
            self.assertEqual(self.change_code(component, current).status_code, 409)
            replaced = self.change_code(component, current, first)
            self.assertEqual(replaced.status_code, 200, replaced.text)
            second = replaced.json()['assignment']
            self.assertNotEqual(first['invitation'], second['invitation'])
            self.assertEqual(second['participant_name'], 'Assigned listener')
            self.assertEqual(self.roster(component)['assignments'][0]['invitation'], second['invitation'])
            self.assertEqual(self.change_code(component, current, first).status_code, 409)
            self.assertEqual(self.start_code(component, first['invitation']).status_code, 403)
            self.assertEqual(self.start_code(component, second['invitation']).status_code, 200)
            self.assertEqual(self.change_code(component, current, second, bundle_hash='stale-bundle').status_code, 409)
            self.assertEqual(self.change_code(component, current, second, expected_version=0).status_code, 409)

    def test_inline_replacement_requires_confirmation_for_started_sessions_and_protects_completion(self):
        for component in ('c1', 'c4'):
            initial = self.roster(component)
            created = self.change_code(component, initial).json()['assignment']
            started = self.start_code(component, created['invitation'])
            self.assertEqual(started.status_code, 200, started.text)
            session_id = started.json()['session_id']
            self.assertEqual(self.change_code(component, initial, created).status_code, 409)
            replaced = self.change_code(component, initial, created, confirm_session_close=True)
            self.assertEqual(replaced.status_code, 200, replaced.text)
            with database.get_connection() as db:
                preserved = db.execute(f'SELECT phase,feedback_json FROM {component}_sessions WHERE session_id=?', (session_id,)).fetchone()
            self.assertEqual(preserved['phase'], 'replaced')
            self.assertIn('fresh invitation code', preserved['feedback_json'])
            new_row = replaced.json()['assignment']
            new_session = self.start_code(component, new_row['invitation']).json()['session_id']
            with database.get_connection() as db:
                db.execute(f"UPDATE {component}_sessions SET phase='complete',completed_at='test-completed' WHERE session_id=?", (new_session,))
            self.assertEqual(self.roster(component)['assignments'][0]['can_replace_invitation'], False)
            self.assertEqual(self.change_code(component, initial, new_row, confirm_session_close=True).status_code, 409)

    def test_old_hash_only_codes_are_labelled_without_being_invalidated(self):
        for component in ('c1', 'c4'):
            initial = self.roster(component)
            row = self.change_code(component, initial).json()['assignment']
            with database.get_connection() as db:
                db.execute('DELETE FROM invitation_code_vault WHERE component=? AND invite_hash=?', (component, row['invitation_version']))
            legacy = self.roster(component)['assignments'][0]
            self.assertIsNone(legacy['invitation'])
            self.assertEqual(legacy['invitation_status'], 'legacy_unavailable')
            self.assertEqual(self.start_code(component, row['invitation']).status_code, 200)

    def test_ciphertext_and_key_changes_never_return_a_wrong_code(self):
        from invitation_codes import recover_code
        initial = self.roster('c1')
        row = self.change_code('c1', initial).json()['assignment']
        with database.get_connection() as db:
            encrypted = db.execute('SELECT encrypted_code FROM invitation_code_vault WHERE component=? AND invite_hash=?', ('c1', row['invitation_version'])).fetchone()[0]
        self.assertEqual(recover_code('c4', row['invitation_version'], encrypted), (None, 'unreadable'))
        self.assertEqual(recover_code('c1', 'wrong-hash', encrypted), (None, 'unreadable'))
        self.assertEqual(recover_code('c1', row['invitation_version'], encrypted[:-4]+'AAAA'), (None, 'unreadable'))
        with patch.dict(os.environ, SURVEY_INVITATION_SECRET='different-test-key-at-least-32-characters-long'):
            self.assertEqual(recover_code('c1', row['invitation_version'], encrypted), (None, 'unreadable'))

    def test_inline_invitation_endpoint_requires_researcher_authentication(self):
        row = self.roster('c1')['assignments'][0]
        response = self.client.post('/api/c1-pilot/admin/assignment-invitation', json=dict(bundle_hash='test', assignment_id=row['assignment_id'],
            expected_version=0, expected_invitation=None, reason='Attempted without researcher authentication'))
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
