"""C3 uses the existing researcher service without sharing participant data or logins."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'survey/backend'))
from fastapi.testclient import TestClient
import c1_researcher_rehearsal as rehearsal
import database
import security
from c3_design import CONSENT, N_SCORED, SET_QUESTIONS

BASE = '/c3/api'


class C3ResearcherRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.participant = self.root / 'participant.sqlite'
        with closing(sqlite3.connect(self.participant)) as db:
            db.execute('CREATE TABLE sentinel (data TEXT)')
            db.execute("INSERT INTO sentinel VALUES ('participant fixture remains unchanged')")
            db.commit()
        self.participant_hash = hashlib.sha256(self.participant.read_bytes()).hexdigest()
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.participant))
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='postgresql://unused.invalid/participant',
                                     SURVEY_DATABASE_PATH=str(self.participant), RENDER=''))
        self.state_dir = self.root / 'researcher'
        self.app = rehearsal.create_app(self.state_dir)
        self.client = self.enterContext(TestClient(self.app))
        self.access = json.loads((self.state_dir / 'private_access.json').read_text())
        self.headers = {'Authorization': 'Bearer ' + secrets.token_hex(32)}

    def login(self):
        result = self.client.post('/api/researcher/login', json={
            'username': self.access['researcher_username'], 'password': self.access['researcher_password']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn(rehearsal.REHEARSAL_COOKIE, self.client.cookies)
        self.assertNotIn(security.SESSION_COOKIE, self.client.cookies)

    def start(self, purpose='researcher_self_review'):
        return self.client.post(BASE + '/start', headers=self.headers, json={
            'consent': dict.fromkeys(CONSENT, True), 'experience': '1_to_3', 'purpose': purpose})

    def state(self):
        response = self.client.get(BASE + '/session', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def action(self, op, answers=None):
        response = self.client.post(BASE + '/action', headers=self.headers, json={
            'revision': self.state()['revision'], 'op': op, 'answers': answers or {}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_signed_out_boundary_pages_assets_and_all_study_apis(self):
        for path in ('/c3', '/c3/', '/c3/?view=researcher'):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.headers['location'], '/c3/admin')
        self.assertEqual(self.client.get('/c3/admin').status_code, 200)
        for name in ('admin.js', 'app.js', 'style.css'):
            self.assertEqual(self.client.get('/c3/assets/' + name).status_code, 200)
        for path in ('/info', '/session', '/audio/volume_reference', '/admin/summary', '/admin/export'):
            self.assertEqual(self.client.get(BASE + path, headers=self.headers).status_code, 401)
        for path in ('/start', '/play', '/action', '/admin/invitations'):
            self.assertEqual(self.client.post(BASE + path, json={}).status_code, 401)
        self.assertEqual(self.client.get('/api/studies').status_code, 404)
        self.login()
        for path in ('/c3/bundle.json', '/c3/assets/bundle.json', '/c3/api/audio/case_01_target'):
            self.assertIn(self.client.get(path).status_code, (401, 404))

    def test_shared_login_selects_researcher_view_and_preserves_other_studies(self):
        self.login()
        response = self.client.get('/c3/', follow_redirects=False)
        self.assertEqual(response.headers['location'], '/c3/?view=researcher')
        page = self.client.get('/c3/').text
        self.assertIn('RESEARCHER SELF-REVIEW', page)
        self.assertNotIn('PARTICIPANT PREVIEW', page)
        info = self.client.get(BASE + '/info').json()
        self.assertTrue(info['researcher_only'])
        self.assertFalse(info['research_collection_enabled'])
        for component in ('c1', 'c4'):
            status = self.client.get(f'/api/{component}-pilot/status').json()
            self.assertTrue(status['ready'])
            self.assertTrue(status['rehearsal'])
        self.assertTrue(self.client.get('/api/c2-pilot/v2/status').json()['researcher_only'])
        self.assertEqual(database.DATABASE_PATH, self.state_dir / 'researcher_rehearsal.sqlite')
        self.assertEqual(hashlib.sha256(self.participant.read_bytes()).hexdigest(), self.participant_hash)

    def test_preview_start_and_invitation_issuance_are_disabled(self):
        self.login()
        self.assertEqual(self.start('participant_preview').status_code, 403)
        self.assertEqual(self.client.post(BASE + '/admin/invitations', json={}).status_code, 409)
        summary = self.client.get(BASE + '/admin/summary').json()
        self.assertTrue(summary['researcher_only'])
        self.assertEqual(summary['invitations'], [])
        self.assertEqual(summary['sessions'], [])

    def test_saved_self_review_requires_its_owner_and_survives_restart(self):
        self.login()
        started = self.start()
        self.assertEqual(started.status_code, 200, started.text)
        code = started.json()['code']
        self.action('skip_screen')
        invitation = self.client.post('/api/researcher/invitations', json={}).json()['invitation']
        self.client.post('/api/researcher/logout')
        self.assertEqual(self.client.get(BASE + '/session', headers=self.headers).status_code, 401)
        signed_up = self.client.post('/api/researcher/signup', json={
            'username': 'other-c3-researcher', 'password': 'separate-test-researcher-123', 'invitation': invitation})
        self.assertEqual(signed_up.status_code, 201, signed_up.text)
        self.assertEqual(self.client.get(BASE + '/session', headers=self.headers).status_code, 403)
        self.client.post('/api/researcher/logout')
        self.login()
        self.assertEqual(self.state()['code'], code)
        self.assertEqual(self.state()['phase'], 'practice')
        self.assertEqual(self.start().json()['code'], code)
        app = rehearsal.create_app(self.state_dir)
        with TestClient(app) as reopened:
            response = reopened.post('/api/researcher/login', json={
                'username': self.access['researcher_username'], 'password': self.access['researcher_password']})
            self.assertEqual(response.status_code, 200)
            resumed = reopened.get(BASE + '/session', headers=self.headers).json()
            self.assertEqual((resumed['code'], resumed['phase']), (code, 'practice'))
        self.assertEqual(hashlib.sha256(self.participant.read_bytes()).hexdigest(), self.participant_hash)

    def test_complete_self_review_exports_only_rehearsal_and_leaves_other_tables_unchanged(self):
        self.login()

        def counts():
            with database.get_connection() as db:
                names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                return {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}

        before = counts()
        self.assertEqual(self.start().status_code, 200)
        self.action('skip_screen')
        while self.state()['phase'] != 'feedback':
            state = self.state()
            if state['phase'] in ('instructions', 'break'):
                self.action('continue')
                continue
            for audio_id in state['audio_ids']:
                audio = self.client.get(BASE + '/audio/' + audio_id, headers=self.headers)
                self.assertEqual(audio.status_code, 200)
                for event in ('start', 'end'):
                    response = self.client.post(BASE + '/play', headers=self.headers,
                                                json={'audio_id': audio_id, 'event': event})
                    self.assertEqual(response.status_code, 200, response.text)
            self.action('response', dict(
                closeness={str(sound['number']): 4 for sound in state['case']['sounds']},
                **dict.fromkeys(SET_QUESTIONS, 'A'), confidence=3, reason=''))
        self.action('finish', dict(knob_bars=4, length='about_right', comment=''))
        exported = self.client.get(BASE + '/admin/export')
        self.assertEqual(exported.status_code, 200, exported.text)
        payload = exported.json()
        self.assertEqual(payload['independent_participants'], 0)
        self.assertEqual(payload['completed_rehearsal_runs'], 1)
        record = payload['records'][0]
        self.assertEqual(record['purpose'], 'researcher_self_review')
        self.assertTrue(record['screen_skipped'])
        self.assertTrue(record['excluded_from_research'])
        self.assertFalse(record['analysis_include'])
        self.assertEqual(len(record['responses']), N_SCORED)
        after = counts()
        self.assertEqual({name for name in before if before[name] != after[name]}, {'c3_v2_sessions'})
        self.assertEqual(hashlib.sha256(self.participant.read_bytes()).hexdigest(), self.participant_hash)

    def test_https_proxy_keeps_the_dedicated_secure_cookie(self):
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
        with TestClient(ProxyHeadersMiddleware(self.app, trusted_hosts='*')) as client:
            result = client.post('/api/researcher/login', headers={'X-Forwarded-Proto': 'https'}, json={
                'username': self.access['researcher_username'], 'password': self.access['researcher_password']})
        self.assertEqual(result.status_code, 200, result.text)
        cookie = result.headers['set-cookie']
        self.assertTrue(cookie.startswith(rehearsal.REHEARSAL_COOKIE + '='))
        self.assertIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie)


if __name__ == '__main__':
    unittest.main()
