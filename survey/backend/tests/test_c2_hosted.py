"""Hosted C2 keeps the two existing deployments and all C1/C4 data separate."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'survey/backend'))
from fastapi.testclient import TestClient
import database
import main
import security
import c1_researcher_rehearsal as rehearsal
from c2_design import CONSENT, NAMES

ADMIN = 'c2-test-only-persistent-secret-at-least-32-chars'


class HostedC2Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.root/'participant.db'))
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='', SURVEY_ADMIN_TOKEN=ADMIN,
                                     SURVEY_C2_RESEARCHER_ONLY='0', SURVEY_REMOTE_MODE='1'))
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization': 'Bearer ' + ADMIN}
        self.token = secrets.token_hex(32)
        self.headers = {'Authorization': 'Bearer ' + self.token}
        self.base = '/c2-flow/api'
        self.bundle = json.loads((ROOT/'survey/deploy/study/c2_rehearsal_v1/bundle.json').read_text())

    def start(self, code='', purpose='participant_preview', client=None):
        return (client or self.client).post(self.base+'/start', headers=self.headers,
            json=dict(consent=dict.fromkeys(CONSENT, True), experience='1_to_3', invitation=code, purpose=purpose))

    def invite(self):
        response = self.client.post('/api/c2-pilot/admin/invitations', headers=self.admin, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['invitations'][0]['invitation']

    def action(self, state, op, answers):
        response = self.client.post(self.base+'/action', headers=self.headers,
                                    json=dict(revision=state['revision'], op=op, answers=answers))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def listen(self, state):
        for audio_id in state['audio_ids']:
            self.assertEqual(self.client.get(self.base+'/audio/'+audio_id, headers=self.headers).status_code, 200)
            for event in ('start', 'end'):
                self.assertEqual(self.client.post(self.base+'/play', headers=self.headers, json=dict(audio_id=audio_id, event=event)).status_code, 200)

    def test_invitation_gate_idempotence_and_c1_c4_isolation(self):
        with database.get_connection() as db:
            before = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('c1_sessions', 'c4_sessions', 'c1_invites', 'c4_invites')}
        self.assertEqual(self.start().status_code, 403)
        self.assertEqual(self.start('C1-other-study').status_code, 403)
        code = self.invite()
        first = self.start(code)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()['excluded_from_research'])
        self.assertEqual(self.start(code).json()['code'], first.json()['code'])
        self.token = secrets.token_hex(32); self.headers = {'Authorization': 'Bearer '+self.token}
        self.assertEqual(self.start(code).status_code, 403)
        codes = self.client.post('/api/c2-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
        self.assertEqual(codes[0]['invitation'], code)
        with database.get_connection() as db:
            after = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in before}
        self.assertEqual(before, after)
        self.assertEqual(self.client.get('/api/c2-pilot/admin/summary').status_code, 401)

    def test_practice_public_but_private_bundle_and_future_audio_unavailable(self):
        data = self.client.get(self.base+'/walkthrough').json()
        self.assertFalse(data['responses_saved'])
        self.assertEqual(len(data['parameters']), 13)
        self.assertEqual(set(data['parameters'][0]), {'name', 'label', 'predicted_z', 'q'})
        self.assertEqual(self.client.get(self.base+'/audio/case_01_target').status_code, 401)
        self.assertEqual(self.client.get('/c2-flow/assets/bundle.json').status_code, 404)
        self.assertEqual(self.client.get(self.base+'/walkthrough/audio/case_01').status_code, 404)
        self.assertEqual(self.client.get('/c2-flow/?view=researcher').status_code, 401)
        state = self.start(self.invite()).json()
        self.assertEqual(self.client.get(self.base+'/audio/case_01_target', headers=self.headers).status_code, 403)
        self.assertEqual(self.client.post(self.base+'/action', headers=self.headers,
            json=dict(revision=state['revision'], op='volume', answers=dict(headphones=True, quiet=True, comfortable=True))).status_code, 400)
        self.assertEqual(self.client.get('/api/c2-pilot/status').json()['research_collection_enabled'], False)
        self.assertEqual(self.client.post(self.base+'/play', headers={**self.headers, 'Origin': 'https://evil.invalid'}, json=dict(audio_id='volume_reference', event='start')).status_code, 403)

    def test_complete_flow_counterbalance_export_and_withdrawal(self):
        state = self.start(self.invite()).json()
        self.listen(state)
        state = self.action(state, 'volume', dict(headphones=True, quiet=True, comfortable=True))
        for item in self.bundle['headphones']:
            self.listen(state)
            state = self.action(state, 'headphone', dict(interval=item['correct_interval']))
        self.assertEqual(state['phase'], 'practice')
        conditions = []
        while state['phase'] != 'feedback':
            if state['phase'] in ('break', 'instructions'):
                state = self.action(state, 'continue', {})
                continue
            self.listen(state)
            condition = state['case']['condition']
            if state['phase'] == 'task':
                conditions.append(condition)
            if condition == 'without':
                self.assertTrue(all('q' not in p for p in state['case']['parameters']))
            answers = dict(decisions=dict.fromkeys(NAMES, 'cannot_judge'), usefulness=3, clarity=3, confidence=3, reason='Fixture')
            if condition == 'with':
                answers.update(meaning='Fixture interpretation', guarantee='no', impossible='no')
            state = self.action(state, 'response', answers)
        self.assertEqual(conditions.count('with'), 4)
        self.assertEqual(conditions.count('without'), 4)
        state = self.action(state, 'finish', dict(preference='none', length='about_right', comment='Fixture'))
        exported = self.client.get('/api/c2-pilot/admin/export', headers=self.admin).json()
        self.assertEqual(exported['completed_rehearsal_runs'], 1)
        self.assertEqual(exported['independent_participants'], 0)
        self.assertNotIn(self.token, json.dumps(exported))
        self.assertFalse(exported['records'][0]['analysis_include'])
        self.action(state, 'withdraw', {})
        self.assertEqual(self.client.get('/api/c2-pilot/admin/export', headers=self.admin).json()['records'], [])

    def test_researcher_service_shared_login_and_separate_cookie_store(self):
        participant_path = database.DATABASE_PATH
        before = hashlib.sha256(participant_path.read_bytes()).hexdigest()
        with patch.dict(os.environ):
            app = rehearsal.create_app(self.root/'researcher')
            access = json.loads((self.root/'researcher/private_access.json').read_text())
            with TestClient(app) as client:
                self.assertEqual(client.get(self.base+'/info').status_code, 401)
                login = client.post('/api/researcher/login', json=dict(username=access['researcher_username'], password=access['researcher_password']))
                self.assertEqual(login.status_code, 200, login.text)
                self.assertIn(rehearsal.REHEARSAL_COOKIE, client.cookies)
                self.assertNotIn(security.SESSION_COOKIE, client.cookies)
                for component in ('c1', 'c2', 'c4'):
                    self.assertEqual(client.get(f'/api/{component}-pilot/status').status_code, 200)
                self.assertEqual(client.post('/api/c2-pilot/admin/invitations', json={}).status_code, 409)
                self.assertEqual(self.start(client=client).status_code, 403)
                state = self.start(purpose='researcher_self_review', client=client)
                self.assertEqual(state.status_code, 200, state.text)
                self.assertEqual(state.json()['purpose'], 'researcher_self_review')
                self.assertEqual(client.get(self.base+'/session', headers=self.headers).status_code, 200)
                client.post('/api/researcher/logout')
                self.assertEqual(client.get(self.base+'/session', headers=self.headers).status_code, 401)
        database.DATABASE_PATH = participant_path
        self.assertEqual(hashlib.sha256(participant_path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
