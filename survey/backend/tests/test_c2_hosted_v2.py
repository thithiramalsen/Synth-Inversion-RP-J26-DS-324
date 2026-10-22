"""Disposable SQLite/fixture responses only. No hosted data or human answers."""
import hashlib
import json
import os
import secrets
from unittest.mock import patch
import unittest

from survey.backend.tests import test_c2_hosted as hosted_fixture
import c2_flow_v2
from c2_design_v2 import CONTRACT, PROTOCOL, assignment
import database
import security
import c1_researcher_rehearsal as rehearsal
from fastapi.testclient import TestClient


class HostedC2V2Tests(unittest.TestCase):
    def setUp(self):
        hosted_fixture.HostedC2Tests.setUp(self)
        self.base = '/c2-flow-v2/api'

    start = hosted_fixture.HostedC2Tests.start
    action = hosted_fixture.HostedC2Tests.action
    listen = hosted_fixture.HostedC2Tests.listen

    def invite(self):
        response = self.client.post('/api/c2-pilot/v2/admin/invitations', headers=self.admin, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['invitations'][0]['invitation']

    def raw(self, state, op, answers, revision=None):
        return self.client.post(self.base + '/action', headers=self.headers,
            json=dict(revision=state['revision'] if revision is None else revision, op=op, answers=answers))

    def setup_listening(self, invitation=None):
        state = self.start(invitation or self.invite()).json()
        self.listen(state)
        state = self.action(state, 'volume', dict(headphones=True, quiet=True, comfortable=True))
        for item in self.bundle['headphones']:
            self.listen(state)
            state = self.action(state, 'headphone', dict(interval=item['correct_interval']))
        self.assertEqual(state['phase'], 'practice')
        return state

    def advance_listening(self, state):
        while state['phase'] != 'display_intro':
            self.assertNotIn('parameters', state.get('case', {}))
            self.assertNotIn('condition', state.get('case', {}))
            self.assertNotIn('q', json.dumps(state))
            if state['phase'] in ('listening_intro', 'listening_break'):
                state = self.action(state, 'continue', {})
            else:
                self.listen(state)
                state = self.action(state, 'listening', dict(similarity=3, comment='Synthetic fixture only'))
        return state

    def finish(self, state):
        state = self.action(state, 'continue', {})
        while state['phase'] != 'feedback':
            if state['phase'] == 'display_break':
                state = self.action(state, 'continue', {})
                continue
            self.assertEqual(state['listening_completed'], 8)
            if state['case']['condition'] == 'without':
                self.assertTrue(all('q' not in p for p in state['case']['parameters']))
            else:
                self.assertTrue(all('q' in p for p in state['case']['parameters']))
            self.assertTrue(all('true_z' not in p and 'error_z' not in p for p in state['case']['parameters']))
            # Optional replay is intentionally NOT a condition for display ratings.
            state = self.action(state, 'display', dict(clarity=4, usefulness='cannot_judge'))
        return self.action(state, 'finish', dict(meaning='Synthetic fixture, not a human interpretation',
            guarantee='unsure', impossible='unsure', preference='none', length='about_right', comment=''))

    def test_complete_flow_blinding_export_missingness_and_withdrawal(self):
        state = self.setup_listening()
        # No practice q, no future task audio, and no numerical/comprehension answers before display.
        self.assertNotIn('parameters', state['case'])
        self.assertEqual(self.client.get(self.base + '/audio/case_01_target', headers=self.headers).status_code, 403)
        state = self.advance_listening(state)
        self.assertEqual(state['listening_completed'], 8)
        state = self.finish(state)
        self.assertEqual(state['phase'], 'complete')
        data = self.client.get('/api/c2-pilot/v2/admin/export', headers=self.admin).json()
        self.assertEqual(data['protocol'], PROTOCOL)
        self.assertEqual(data['independent_participants'], 0)
        self.assertEqual(data['completed_rehearsal_runs'], 1)
        record = data['records'][0]
        self.assertFalse(record['analysis_include'])
        self.assertTrue(record['excluded_from_research'])
        self.assertEqual(len(record['listening_responses']), 8)
        self.assertEqual(len(record['display_responses']), 8)
        self.assertEqual(sum(r['condition'] == 'with' for r in record['display_responses']), 4)
        first_display = record['display_responses'][0]['submitted']
        self.assertTrue(all(r['submitted'] <= first_display for r in record['listening_responses']))
        self.assertNotIn(self.token, json.dumps(data))
        for private in ('token_hash', 'correct_interval', 'researcher', 'practice_response', 'true_z'):
            self.assertNotIn(private, record)
        summary = data['summary']['paired_display_ratings']
        self.assertEqual(summary['clarity']['eligible_runs'], 1)
        self.assertEqual(summary['usefulness']['eligible_runs'], 0)
        self.assertEqual(summary['usefulness']['rehearsal_runs'][0]['cannot_judge_counts'], {'with': 4, 'without': 4})
        self.assertIsNone(data['meaning_coding'][0]['agreed_score'])
        self.assertEqual(self.client.get('/api/c2-pilot/admin/export', headers=self.admin).json()['records'], [])
        self.action(state, 'withdraw', {})
        self.assertEqual(self.client.get('/api/c2-pilot/v2/admin/export', headers=self.admin).json()['records'], [])
        with database.get_connection() as db:
            stored = json.loads(db.execute('SELECT state FROM c2_v2_sessions').fetchone()[0])
        self.assertEqual(stored['listening_responses'], [])
        self.assertEqual(stored['display_responses'], [])
        self.assertNotIn('feedback', stored)
        self.assertNotIn('practice_response', stored)

    def test_gates_ratings_revisions_and_no_knob_decisions(self):
        state = self.setup_listening()
        self.assertEqual(self.raw(state, 'continue', {}).status_code, 409)
        self.assertEqual(self.raw(state, 'listening', dict(similarity=3, comment='')).status_code, 400)
        for invalid in (True, 0, 6, 1.0, '3', None, [], {}):
            self.assertEqual(self.raw(state, 'listening', dict(similarity=invalid, comment='')).status_code, 400)
        self.listen(state)
        self.assertEqual(self.raw(state, 'listening', dict(similarity=3, comment='', decisions={})).status_code, 400)
        next_state = self.action(state, 'listening', dict(similarity='cannot_judge', comment=''))
        self.assertEqual(self.raw(next_state, 'continue', {}, revision=state['revision']).status_code, 409)
        state = self.advance_listening(next_state)
        state = self.action(state, 'continue', {})
        self.assertEqual(self.raw(state, 'listening', dict(similarity=5, comment='')).status_code, 409)
        self.assertEqual(self.raw(state, 'display', dict(clarity=3, usefulness=3, decisions={})).status_code, 400)

    def test_v1_invites_and_records_are_separate_and_not_migrated(self):
        old_code = self.client.post('/api/c2-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations'][0]['invitation']
        self.assertEqual(self.start(old_code).status_code, 403)
        old_start = self.client.post('/c2-flow/api/start', headers=self.headers, json=dict(
            consent=dict.fromkeys(c2_flow_v2.CONSENT, True), experience='1_to_3', invitation=old_code, purpose='participant_preview'))
        self.assertEqual(old_start.status_code, 200, old_start.text)
        with database.get_connection() as db:
            old_state = db.execute('SELECT state FROM c2_v1_sessions').fetchone()[0]
            old_invites = [tuple(r) for r in db.execute('SELECT * FROM c2_v1_invites').fetchall()]
            others = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('c1_sessions', 'c4_sessions', 'c1_invites', 'c4_invites')}
        code = self.invite()
        self.assertEqual(self.start(code).status_code, 200)
        self.assertEqual(self.start(code).status_code, 200)  # Idempotent same-token resume.
        self.token = secrets.token_hex(32); self.headers = {'Authorization': 'Bearer ' + self.token}
        self.assertEqual(self.start(code).status_code, 403)
        self.assertEqual(self.start('C4-not-c2').status_code, 403)
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT state FROM c2_v1_sessions').fetchone()[0], old_state)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM c2_v1_invites').fetchall()], old_invites)
            self.assertEqual({t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in others}, others)

    def test_access_privacy_origin_and_research_disabled(self):
        for path in ('session', 'audio/case_01_target'):
            self.assertEqual(self.client.get(self.base + '/' + path).status_code, 401)
        for path in ('summary', 'export'):
            self.assertEqual(self.client.get('/api/c2-pilot/v2/admin/' + path).status_code, 401)
        self.assertFalse(self.client.get('/api/c2-pilot/v2/status').json()['research_collection_enabled'])
        self.assertEqual(self.client.get(self.base + '/bundle.json').status_code, 404)
        self.assertEqual(self.client.post(self.base + '/play', headers={**self.headers, 'Origin': 'https://other.invalid'},
            json=dict(audio_id='volume_reference', event='start')).status_code, 403)
        self.assertEqual(self.start(self.invite(), purpose='researcher_self_review').status_code, 401)

    def test_resume_and_protocol_fingerprint(self):
        state = self.setup_listening()
        with TestClient(c2_flow_v2.create_app()) as restored:
            resumed = restored.get('/api/session', headers=self.headers)
            self.assertEqual(resumed.json()['code'], state['code'])
            self.assertEqual(resumed.json()['revision'], state['revision'])
        with patch.dict(CONTRACT, seed=999):
            with self.assertRaisesRegex(ValueError, 'protocol/bundle changed'):
                c2_flow_v2.create_app()

    def test_failed_headphone_screen_stops_before_listening(self):
        state = self.start(self.invite()).json()
        self.listen(state)
        state = self.action(state, 'volume', dict(headphones=True, quiet=True, comfortable=True))
        for item in self.bundle['headphones']:
            self.listen(state)
            state = self.action(state, 'headphone', dict(interval=item['correct_interval'] % 3 + 1))
        self.assertEqual(state['phase'], 'screen_failed')
        self.assertEqual(self.raw(state, 'continue', {}).status_code, 409)

    def test_researcher_cookie_ownership_and_participant_store_isolation(self):
        participant_path = database.DATABASE_PATH
        before = hashlib.sha256(participant_path.read_bytes()).hexdigest()
        with patch.dict(os.environ):
            app = rehearsal.create_app(self.root / 'researcher-v2')
            access = json.loads((self.root / 'researcher-v2/private_access.json').read_text())
            with TestClient(app) as client:
                self.assertEqual(client.get(self.base + '/info').status_code, 401)
                self.assertEqual(client.post('/api/researcher/login', json=dict(username=access['researcher_username'], password=access['researcher_password'])).status_code, 200)
                self.assertEqual(client.get('/api/c2-pilot/v2/status').status_code, 200)
                self.assertEqual(client.post('/api/c2-pilot/v2/admin/invitations', json={}).status_code, 409)
                self.assertEqual(self.start(client=client).status_code, 403)
                started = self.start(purpose='researcher_self_review', client=client)
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(client.get(self.base + '/session', headers=self.headers).status_code, 200)
                original_cookie = client.cookies.get(rehearsal.REHEARSAL_COOKIE)
                client.cookies.set(rehearsal.REHEARSAL_COOKIE, security.new_session('different-fixture-researcher'))
                self.assertEqual(client.get(self.base + '/session', headers=self.headers).status_code, 403)
                client.cookies.set(rehearsal.REHEARSAL_COOKIE, original_cookie)
                client.post('/api/researcher/logout')
                self.assertEqual(client.get(self.base + '/session', headers=self.headers).status_code, 401)
        database.DATABASE_PATH = participant_path
        self.assertEqual(hashlib.sha256(participant_path.read_bytes()).hexdigest(), before)


class AssignmentV2Tests(unittest.TestCase):
    def test_all_slots_keep_cases_and_complementary_conditions(self):
        counts = {}
        for slot in range(12):
            plan = assignment(slot)
            self.assertEqual(set(plan['listening']), {f'case_{i:02d}' for i in range(1, 9)})
            self.assertEqual(len(plan['listening']), 8)
            self.assertEqual(sum(t['condition'] == 'with' for t in plan['display']), 4)
            for task in plan['display']:
                key = (task['case_id'], task['condition']); counts[key] = counts.get(key, 0) + 1
        self.assertEqual(set(counts.values()), {6})
        with self.assertRaises(ValueError):
            assignment(12)


if __name__ == '__main__':
    unittest.main()
