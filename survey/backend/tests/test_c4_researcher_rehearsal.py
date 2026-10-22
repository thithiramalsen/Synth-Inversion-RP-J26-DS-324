"""Fresh team tests stay separate from participant records and identities."""
import csv
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'survey/backend'))
from fastapi.testclient import TestClient
import database
import main
import security
import c1_researcher_rehearsal as rehearsal


class C4ResearcherRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.main_store = self.root/'participant.sqlite'
        with closing(sqlite3.connect(self.main_store)) as db:
            db.execute('CREATE TABLE sentinel (data TEXT)')
            db.execute("INSERT INTO sentinel VALUES ('unchanged participant fixture')")
            db.commit()
        self.original_hash = hashlib.sha256(self.main_store.read_bytes()).hexdigest()
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.main_store))
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='postgresql://unused.invalid/participant',
                                     SURVEY_DATABASE_PATH=str(self.main_store), RENDER=''))
        self.state_dir = self.root/'researcher-only'
        self.app = rehearsal.create_app(self.state_dir)
        self.client = self.enterContext(TestClient(self.app))
        self.access = json.loads((self.state_dir/'private_access.json').read_text())

    def login(self):
        response = self.client.post('/api/researcher/login', json={
            'username': self.access['researcher_username'], 'password': self.access['researcher_password']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(rehearsal.REHEARSAL_COOKIE, self.client.cookies)
        self.assertNotIn(security.SESSION_COOKIE, self.client.cookies)

    def start(self):
        self.login()
        issued = self.client.post('/api/c4-pilot/admin/invitations', json={})
        self.assertEqual(issued.status_code, 200, issued.text)
        code = issued.json()['invitations'][0]['invitation']
        response = self.client.post('/api/c4-pilot/sessions', json={
            'invitation': code, 'adult': True, 'consent': True, 'headphones': True,
            'quiet_environment': True, 'understands_language': True, 'activities': ['Instrument performance'],
            'experience_months': 12, 'recent_frequency': 'Weekly', 'tools': 'Piano',
            'example': 'TEST FIXTURE: I practise piano pieces and dynamics.'})
        self.assertEqual(response.status_code, 200, response.text)
        self.session = response.json()
        self.base = '/api/c4-pilot/sessions/'+self.session['session_id']
        self.headers = {'Authorization': 'Bearer '+self.session['token']}

    def test_inherited_participant_store_and_original_metadata_are_untouched(self):
        self.assertEqual(os.environ['SURVEY_DATABASE_URL'], '')
        self.assertEqual(database.DATABASE_PATH, self.state_dir/'researcher_rehearsal.sqlite')
        self.assertEqual(hashlib.sha256(self.main_store.read_bytes()).hexdigest(), self.original_hash)
        self.assertFalse(json.loads((ROOT/'survey/deploy/study/c4_participant_bundle_v1.json').read_bytes())['rehearsal'])
        self.assertEqual(json.loads((ROOT/'survey/config/c4_participants_v1.json').read_bytes())['collection_mode'], 'participants')
        self.login()
        status = self.client.get('/api/c4-pilot/status').json()
        self.assertTrue(status['rehearsal'])
        self.assertEqual(status['config']['data_origin'], rehearsal.ORIGIN)
        self.assertEqual(status['rated_presentations'], 22)

    def test_every_study_endpoint_requires_researcher_authentication(self):
        self.assertEqual(self.client.get('/c4', follow_redirects=False).headers['location'], '/c4/admin')
        for path in ('/api/c4-pilot/status', '/api/c4-pilot/admin/summary', '/api/c4-pilot/sessions/unknown/audio/test'):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json={}).status_code, 401)
        self.assertEqual(self.client.get('/pilot', follow_redirects=False).headers['location'], '/pilot/admin')
        for path in ('/api/c1-pilot/status', '/api/c1-pilot/admin/summary'):
            self.assertEqual(self.client.get(path).status_code, 401)
        for path in ('/api/studies', '/docs', '/openapi.json'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.login()
        self.assertEqual(self.client.get('/api/c4-pilot/status').status_code, 200)

    def test_fresh_answers_save_with_actor_and_export_only_as_rehearsal(self):
        self.start()
        state = self.client.get(self.base, headers=self.headers).json()
        self.assertEqual(self.client.get(self.base+'/audio/volume_reference', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post(self.base+'/volume', headers=self.headers, json={'completed_plays':1}).status_code, 200)
        state = self.client.get(self.base, headers=self.headers).json()
        self.assertEqual(state['phase'], 'rating')
        for index in range(22):
            state = self.client.get(self.base, headers=self.headers).json()
            if state['phase'] == 'break':
                self.assertEqual(self.client.post(self.base+'/continue', headers=self.headers, json={}).status_code, 200)
                state = self.client.get(self.base, headers=self.headers).json()
            self.assertFalse(state['practice'])
            self.assertEqual(state['display_number'], index+1)
            self.assertEqual(state['display_total'], 22)
            for role in ('reference', 'candidate_a', 'candidate_b'):
                self.assertEqual(self.client.post(self.base+'/playback/'+state['presentation_id']+'/'+role, headers=self.headers, json={}).status_code, 200)
            counts = dict(reference=1, candidate_a=1, candidate_b=1)
            response = self.client.post(self.base+'/ratings', headers=self.headers, json={
                'presentation_id':state['presentation_id'], 'started_at':state['server_time'], 'play_counts':counts, 'completed_counts':counts,
                'answers':{'choice':'candidate_a', 'confidence':4, 'comment':'AUTOMATED TEST FIXTURE'}})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(self.base+'/feedback', headers=self.headers,
            json={'clarity':'Clear', 'length':'About right'}).status_code, 200)
        self.assertEqual(self.client.get(self.base, headers=self.headers).json()['phase'], 'complete')
        response = self.client.get('/api/c4-pilot/admin/export')
        self.assertEqual(len(response.headers.get_list('content-disposition')), 1)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 22)
        self.assertEqual(sum(row['kind'] == 'primary' for row in rows), 20)
        self.assertEqual(sum(row['kind'] == 'repeat' for row in rows), 2)
        for row in rows:
            self.assertEqual(row['analysis_include'], 'False')
            self.assertEqual(row['data_origin'], rehearsal.ORIGIN)
            self.assertEqual(row['entered_by'], 'researcher')
            self.assertEqual(row['study_id'], rehearsal.C4_STUDY_ID)
            self.assertEqual(row['session_type'], 'researcher_rehearsal')
        self.assertIn('c4_researcher_rehearsal_responses.csv', response.headers['content-disposition'])
        audit_response = self.client.get('/api/c4-pilot/admin/sessions')
        self.assertEqual(len(audit_response.headers.get_list('content-disposition')), 1)
        audit = list(csv.DictReader(io.StringIO(audit_response.text)))
        self.assertEqual(audit[0]['entered_by'], 'researcher')
        self.assertEqual(json.loads(audit[0]['entry_json'])['data_origin'], rehearsal.ORIGIN)
        self.assertEqual(hashlib.sha256(self.main_store.read_bytes()).hexdigest(), self.original_hash)

    def test_participant_token_alone_or_another_researcher_cannot_resume_the_session(self):
        self.start()
        cookie = self.client.cookies.get(rehearsal.REHEARSAL_COOKIE)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 401)
        self.client.cookies.set(rehearsal.REHEARSAL_COOKIE, security.new_session('another-researcher'))
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 403)
        self.client.cookies.clear()
        self.client.cookies.set(rehearsal.REHEARSAL_COOKIE, cookie)
        self.assertEqual(self.client.get(self.base, headers=self.headers).status_code, 200)

    def test_store_guard_rejects_participant_data_before_initialization(self):
        with database.get_connection() as db:
            db.execute("INSERT INTO c1_sessions(session_id,token_hash,participant_id,bundle_hash,protocol_hash,study_id,protocol_snapshot,assignment_id,entry_json,trial_order,screen_order,started_at) VALUES ('fixture','x','x','x','x','real-c1','{}','x','{}','[]','[]','test')")
        with self.assertRaisesRegex(RuntimeError, 'another study'):
            rehearsal.assert_separate_store()

    def test_same_postgres_database_is_rejected_without_connecting(self):
        with patch.dict(os.environ, SURVEY_DATABASE_URL='postgresql://user:one@database.invalid:5432/main',
                         SURVEY_REHEARSAL_DATABASE_URL='postgresql://other:two@database.invalid/main?sslmode=require'):
            with self.assertRaisesRegex(RuntimeError, 'separate rehearsal database'):
                rehearsal.configure(self.state_dir, use_postgres=True)

    def test_render_requires_persistent_storage_without_creating_local_files(self):
        target = self.root/'not-created'
        with patch.dict(os.environ, RENDER='true'):
            with self.assertRaisesRegex(RuntimeError, 'separate persistent database'):
                rehearsal.configure(target)
        self.assertFalse(target.exists())

    def test_hosted_configuration_uses_only_the_explicit_rehearsal_database(self):
        target = self.root/'no-local-files-on-host'
        url = 'postgresql://test:fixture@database.invalid/rehearsal'
        with patch.object(database, 'DATABASE_PATH', database.DATABASE_PATH), patch.dict(os.environ,
                SURVEY_REHEARSAL_DATABASE_URL=url,
                SURVEY_REHEARSAL_ADMIN_TOKEN='separate-fixture-token-at-least-32-characters',
                SURVEY_RESEARCHER_USERNAME='team', SURVEY_RESEARCHER_PASSWORD_HASH='fixture$hash', RENDER='true'):
            rehearsal.configure(target, use_postgres=True)
            self.assertEqual(os.environ['SURVEY_DATABASE_URL'], url)
            self.assertEqual(os.environ['SURVEY_ADMIN_TOKEN'], 'separate-fixture-token-at-least-32-characters')
            self.assertFalse(target.exists())

    def test_unknown_existing_schema_is_rejected_before_migration(self):
        with patch.object(database, 'DATABASE_PATH', self.main_store):
            with self.assertRaisesRegex(RuntimeError, 'empty, separate rehearsal database'):
                rehearsal.assert_separate_store()
        self.assertEqual(hashlib.sha256(self.main_store.read_bytes()).hexdigest(), self.original_hash)

    def test_one_login_and_database_support_both_studies_without_mixing_codes_or_exports(self):
        self.start()
        cookie = self.client.cookies.get(rehearsal.REHEARSAL_COOKIE)
        issued = self.client.post('/api/c1-pilot/admin/invitations', json={})
        self.assertEqual(issued.status_code, 200, issued.text)
        code = issued.json()['invitations'][0]['invitation']
        entry = dict(invitation=code, adult=True, consent=True, headphones=True,
                     quiet_environment=True, understands_language=True, activities=['Instrument performance'],
                     experience_months=12, recent_frequency='Weekly', tools='Piano',
                     example='AUTOMATED TEST FIXTURE: piano practice.')
        wrong_study = self.client.post('/api/c4-pilot/sessions', json=entry)
        self.assertEqual(wrong_study.status_code, 403)
        response = self.client.post('/api/c1-pilot/sessions', json=entry)
        self.assertEqual(response.status_code, 200, response.text)
        c1 = response.json()
        self.assertEqual(self.client.cookies.get(rehearsal.REHEARSAL_COOKIE), cookie)
        self.assertNotEqual(c1['session_id'], self.session['session_id'])
        headers = {'Authorization': 'Bearer '+c1['token']}
        base = '/api/c1-pilot/sessions/'+c1['session_id']
        self.assertEqual(self.client.post(base+'/volume', headers=headers, json={'completed_plays':1}).status_code, 200)
        state = self.client.get(base, headers=headers).json()
        self.assertFalse(state['practice'])
        self.assertEqual(state['display_number'], 1)
        self.assertEqual(state['display_total'], 20)
        self.client.post(base+'/playback/'+state['presentation_id'], headers=headers, json={})
        result = self.client.post(base+'/ratings', headers=headers, json={
            'presentation_id':state['presentation_id'], 'started_at':state['server_time'], 'play_count':1, 'completed_plays':1,
            'answers':dict(brightness=4, roughness=3, percussiveness=2, sustainedness=5, comment='AUTOMATED TEST FIXTURE')})
        self.assertEqual(result.status_code, 200, result.text)
        c1_rows = list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export').text)))
        c4_rows = list(csv.DictReader(io.StringIO(self.client.get('/api/c4-pilot/admin/export').text)))
        self.assertEqual(len(c1_rows), 1)
        self.assertEqual(c4_rows, [])
        self.assertEqual(c1_rows[0]['entered_by'], 'researcher')
        self.assertEqual(c1_rows[0]['study_id'], rehearsal.STUDY_ID)
        self.assertEqual(c1_rows[0]['analysis_include'], 'False')
        self.assertEqual(self.client.get(self.base, headers=self.headers).json()['saved_presentations'], 0)
        self.assertEqual(self.client.get(self.base, headers=headers).status_code, 401)
        # The guard accepts the existing C1 store after adding C4 researcher records.
        rehearsal.assert_separate_store()
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c1_sessions').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c4_sessions').fetchone()[0], 1)
        self.assertEqual(hashlib.sha256(self.main_store.read_bytes()).hexdigest(), self.original_hash)

    def test_forwarded_https_login_uses_secure_dedicated_cookie(self):
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
        with TestClient(ProxyHeadersMiddleware(self.app, trusted_hosts='*')) as client:
            response = client.post('/api/researcher/login', headers={'X-Forwarded-Proto':'https'}, json={
                'username':self.access['researcher_username'], 'password':self.access['researcher_password']})
            self.assertEqual(response.status_code, 200, response.text)
            cookie = response.headers['set-cookie']
            self.assertTrue(cookie.startswith(rehearsal.REHEARSAL_COOKIE+'='))
            self.assertIn('Secure', cookie)
            self.assertIn('HttpOnly', cookie)

    def test_deployed_command_respects_port_and_proxy_mode(self):
        with patch.dict(os.environ, PORT='10000'), patch.object(sys, 'argv',
                ['rehearsal', '--postgres', '--host', '0.0.0.0']), patch.object(rehearsal, 'create_app', return_value=self.app), patch('uvicorn.run') as serve:
            rehearsal.main()
        self.assertEqual(serve.call_args.kwargs['host'], '0.0.0.0')
        self.assertEqual(serve.call_args.kwargs['port'], 10000)
        self.assertEqual(serve.call_args.kwargs['forwarded_allow_ips'], '*')


if __name__ == '__main__':
    unittest.main()
