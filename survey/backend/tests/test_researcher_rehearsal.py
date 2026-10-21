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


class ResearcherRehearsalTests(unittest.TestCase):
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
        issued = self.client.post('/api/c1-pilot/admin/invitations', json={})
        self.assertEqual(issued.status_code, 200, issued.text)
        code = issued.json()['invitations'][0]['invitation']
        response = self.client.post('/api/c1-pilot/sessions', json={
            'invitation': code, 'adult': True, 'consent': True, 'headphones': True,
            'quiet_environment': True, 'understands_language': True, 'activities': ['Instrument performance'],
            'experience_months': 12, 'recent_frequency': 'Weekly', 'tools': 'Piano',
            'example': 'TEST FIXTURE: I practise piano pieces and dynamics.'})
        self.assertEqual(response.status_code, 200, response.text)
        self.session = response.json()
        self.base = '/api/c1-pilot/sessions/'+self.session['session_id']
        self.headers = {'Authorization': 'Bearer '+self.session['token']}

    def test_inherited_participant_store_and_original_metadata_are_untouched(self):
        self.assertEqual(os.environ['SURVEY_DATABASE_URL'], '')
        self.assertEqual(database.DATABASE_PATH, self.state_dir/'researcher_rehearsal.sqlite')
        self.assertEqual(hashlib.sha256(self.main_store.read_bytes()).hexdigest(), self.original_hash)
        self.assertFalse(json.loads((ROOT/'survey/deploy/study/c1_participant_bundle_v1.json').read_bytes())['rehearsal'])
        self.assertEqual(json.loads((ROOT/'survey/config/c1_participants_v1.json').read_bytes())['collection_mode'], 'participants')
        self.login()
        status = self.client.get('/api/c1-pilot/status').json()
        self.assertTrue(status['rehearsal'])
        self.assertEqual(status['config']['data_origin'], rehearsal.ORIGIN)
        self.assertEqual(status['rated_presentations'], 20)

    def test_every_study_endpoint_requires_researcher_authentication(self):
        self.assertEqual(self.client.get('/pilot', follow_redirects=False).headers['location'], '/pilot/admin')
        self.assertEqual(self.client.get('/c4', follow_redirects=False).headers['location'], '/c4/admin')
        for path in ('/api/c1-pilot/status', '/api/c1-pilot/admin/summary', '/api/c1-pilot/sessions/unknown/audio/test', '/api/c4-pilot/status', '/api/c4-pilot/admin/summary'):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/c1-pilot/sessions', json={}).status_code, 401)
        for path in ('/api/studies', '/docs', '/openapi.json'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.login()
        self.assertEqual(self.client.get('/api/c1-pilot/status').status_code, 200)
        self.assertEqual(self.client.get('/api/c4-pilot/status').status_code, 200)

    def test_fresh_answers_save_with_actor_and_export_only_as_rehearsal(self):
        self.start()
        state = self.client.get(self.base, headers=self.headers).json()
        self.assertEqual(self.client.get(self.base+'/audio/volume_reference', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post(self.base+'/volume', headers=self.headers, json={'completed_plays':1}).status_code, 200)
        state = self.client.get(self.base, headers=self.headers).json()
        self.assertEqual(state['phase'], 'rating')
        for index in range(20):
            state = self.client.get(self.base, headers=self.headers).json()
            if state['phase'] == 'break':
                self.assertEqual(self.client.post(self.base+'/continue', headers=self.headers, json={}).status_code, 200)
                state = self.client.get(self.base, headers=self.headers).json()
            self.assertFalse(state['practice'])
            self.assertEqual(state['display_number'], index+1)
            self.assertEqual(state['display_total'], 20)
            self.assertEqual(self.client.post(self.base+'/playback/'+state['presentation_id'], headers=self.headers, json={}).status_code, 200)
            response = self.client.post(self.base+'/ratings', headers=self.headers, json={
                'presentation_id':state['presentation_id'], 'started_at':state['server_time'], 'play_count':1, 'completed_plays':1,
                'answers':{'brightness':4, 'roughness':3, 'percussiveness':2, 'sustainedness':5, 'comment':'AUTOMATED TEST FIXTURE'}})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(self.base+'/feedback', headers=self.headers,
            json={'clarity':'Clear', 'length':'About right'}).status_code, 200)
        self.assertEqual(self.client.get(self.base, headers=self.headers).json()['phase'], 'complete')
        response = self.client.get('/api/c1-pilot/admin/export')
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 20)
        for row in rows:
            self.assertEqual(row['analysis_include'], 'False')
            self.assertEqual(row['data_origin'], rehearsal.ORIGIN)
            self.assertEqual(row['entered_by'], 'researcher')
            self.assertEqual(row['study_id'], rehearsal.STUDY_ID)
            self.assertEqual(row['session_type'], 'researcher_rehearsal')
        self.assertIn('c1_researcher_rehearsal_responses.csv', response.headers['content-disposition'])
        audit = list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/sessions').text)))
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

    def test_existing_rehearsal_sessions_keep_their_original_bundle_and_responses(self):
        legacy = ROOT/'survey/deploy/study/c1_researcher_rehearsal_v1.json'
        legacy_config = ROOT/'survey/config/c1_researcher_rehearsal_v1.json'
        with patch.dict(os.environ, SURVEY_C1_BUNDLE=str(legacy), SURVEY_C1_CONFIG=str(legacy_config)):
            self.start()
            self.client.post(self.base+'/volume', headers=self.headers, json={'completed_plays':1})
        state = self.client.get(self.base, headers=self.headers)
        self.assertEqual(state.status_code, 200, state.text)
        self.assertEqual(state.json()['total_presentations'], 23)
        self.assertTrue(state.json()['practice'])
        self.assertEqual(state.json()['display_number'], 1)
        self.assertEqual(state.json()['display_total'], 3)
        self.assertEqual(state.json()['config']['protocol_version'], 'c1_researcher_rehearsal_2026-10-21_v1')
        self.assertEqual(self.client.get('/api/c1-pilot/status').json()['total_presentations'], 20)

    def test_admin_keeps_saved_sessions_and_answers_visible_across_rehearsal_versions(self):
        legacy = ROOT/'survey/deploy/study/c1_researcher_rehearsal_v1.json'
        legacy_config = ROOT/'survey/config/c1_researcher_rehearsal_v1.json'
        with patch.dict(os.environ, SURVEY_C1_BUNDLE=str(legacy), SURVEY_C1_CONFIG=str(legacy_config)):
            self.start()
            self.client.post(self.base+'/volume', headers=self.headers, json={'completed_plays':1})
            state = self.client.get(self.base, headers=self.headers).json()
            self.client.post(self.base+'/playback/'+state['presentation_id'], headers=self.headers, json={})
            saved = self.client.post(self.base+'/ratings', headers=self.headers, json={
                'presentation_id':state['presentation_id'], 'started_at':state['server_time'],
                'play_count':1, 'completed_plays':1,
                'answers':dict(brightness=4, roughness=3, percussiveness=2, sustainedness=5)})
            self.assertEqual(saved.status_code, 200, saved.text)
        legacy_id = self.session['session_id']
        tables = ('c1_sessions', 'c1_ratings', 'c1_invites', 'rehearsal_session_actors')
        with database.get_connection() as db:
            before = {table: [dict(row) for row in db.execute(f'SELECT * FROM {table}').fetchall()] for table in tables}
        summary = self.client.get('/api/c1-pilot/admin/summary').json()
        self.assertEqual(len(summary['sessions']), 1)
        self.assertEqual(summary['previous_version_sessions'], 1)
        self.assertFalse(summary['sessions'][0]['is_current_version'])
        self.assertEqual(summary['sessions'][0]['current_index'], 1)
        response = self.client.get('/api/c1-pilot/admin/responses?limit=1')
        self.assertEqual(response.status_code, 200, response.text)
        page = response.json()
        self.assertEqual(page['total'], 1)
        self.assertTrue(page['includes_previous_versions'])
        self.assertEqual(page['responses'][0]['ratings']['brightness'], 4)
        self.assertFalse(page['responses'][0]['is_current_version'])
        self.assertFalse(page['responses'][0]['analysis_include'])
        for private in ('entry_json', 'token_hash', 'entered_by', legacy_id):
            self.assertNotIn(private, response.text)
        for query in ('offset=1', 'kind=primary', 'phase=complete', 'listener_number=999'):
            self.assertEqual(self.client.get('/api/c1-pilot/admin/responses?'+query).json()['responses'], [])
        self.assertEqual(self.client.get('/api/c1-pilot/admin/responses?kind=practice&phase=in_progress&listener_number=1').json()['total'], 1)
        with database.get_connection() as db:
            for table in tables:
                self.assertEqual([dict(row) for row in db.execute(f'SELECT * FROM {table}').fetchall()], before[table])
        # New codes still start the current 20-sound protocol; the old session
        # keeps its 23-step snapshot, saved rating and research exclusion.
        self.start()
        summary = self.client.get('/api/c1-pilot/admin/summary').json()
        self.assertEqual(len(summary['sessions']), 2)
        self.assertEqual(summary['previous_version_sessions'], 1)
        self.assertEqual(sum(row['is_current_version'] for row in summary['sessions']), 1)
        self.assertEqual(self.client.get(self.base, headers=self.headers).json()['total_presentations'], 20)
        exported = list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export').text)))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]['session_id'], legacy_id)
        self.assertEqual(exported[0]['analysis_include'], 'False')

    def test_rehearsal_admin_does_not_include_other_studies_or_unknown_bundles(self):
        self.start()
        with database.get_connection() as db:
            db.execute("UPDATE c1_sessions SET bundle_hash='unknown-unregistered-bundle'")
        participant = str(ROOT/'survey/deploy/study/c1_participant_bundle_v1.json')
        legacy = os.environ['SURVEY_C1_LEGACY_BUNDLES']
        with patch.dict(os.environ, SURVEY_C1_LEGACY_BUNDLES=os.pathsep.join([legacy, participant])):
            import c1_pilot
            bundle, checksum = c1_pilot.load_bundle()
            hashes = c1_pilot.admin_bundle_hashes(bundle, checksum)
            self.assertEqual(len(hashes), 2)
            self.assertNotIn(hashlib.sha256(Path(participant).read_bytes()).hexdigest(), hashes)
            self.assertEqual(self.client.get('/api/c1-pilot/admin/summary').json()['sessions'], [])
            self.assertEqual(self.client.get('/api/c1-pilot/admin/responses').json()['total'], 0)

    def test_store_guard_rejects_participant_data_before_initialization(self):
        with database.get_connection() as db:
            db.execute("INSERT INTO c4_sessions(session_id,token_hash,participant_id,bundle_hash,protocol_hash,study_id,protocol_snapshot,assignment_id,entry_json,trial_order,screen_order,started_at) VALUES ('fixture','x','x','x','x','real-c4','{}','x','{}','[]','[]','test')")
        with self.assertRaisesRegex(RuntimeError, 'another study'):
            rehearsal.assert_separate_store()

    def test_existing_c1_database_upgrades_in_place_and_preserves_accounts_codes_names_and_answers(self):
        self.start()
        self.client.post(self.base+'/volume', headers=self.headers, json={'completed_plays':1})
        state = self.client.get(self.base, headers=self.headers).json()
        self.client.post(self.base+'/playback/'+state['presentation_id'], headers=self.headers, json={})
        result = self.client.post(self.base+'/ratings', headers=self.headers, json={
            'presentation_id':state['presentation_id'], 'started_at':state['server_time'], 'play_count':1, 'completed_plays':1,
            'answers':dict(brightness=4, roughness=3, percussiveness=2, sustainedness=5)})
        self.assertEqual(result.status_code, 200, result.text)
        roster = self.client.get('/api/c1-pilot/admin/roster').json()
        slot = roster['assignments'][0]
        saved = self.client.post('/api/c1-pilot/admin/assignment-name', json=dict(bundle_hash=roster['bundle_hash'],
            assignment_id=slot['assignment_id'], participant_name='Test researcher', expected_version=slot['version']))
        self.assertEqual(saved.status_code, 200, saved.text)
        tables = ('c1_sessions', 'c1_ratings', 'c1_invites', 'rehearsal_session_actors',
                  'researcher_accounts', 'researcher_sessions', 'assignment_roster', 'invitation_code_vault')
        with database.get_connection() as db:
            before = {table: [dict(r) for r in db.execute(f'SELECT * FROM {table}').fetchall()] for table in tables}
            # The previous C1 deployment has the shared empty C4 schema but no C4 ownership table.
            db.execute('DROP TABLE c4_rehearsal_session_actors')
        new_app = rehearsal.create_app(self.state_dir)
        with TestClient(new_app) as upgraded:
            upgraded.cookies.set(rehearsal.REHEARSAL_COOKIE, self.client.cookies.get(rehearsal.REHEARSAL_COOKIE))
            self.assertTrue(upgraded.get('/api/c1-pilot/status').json()['ready'])
            self.assertTrue(upgraded.get('/api/c4-pilot/status').json()['ready'])
            restored = upgraded.get(self.base, headers=self.headers)
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()['saved_presentations'], 1)
            after_roster = upgraded.get('/api/c1-pilot/admin/roster').json()['assignments'][0]
            self.assertEqual(after_roster['invitation'], slot['invitation'])
            self.assertEqual(after_roster['participant_name'], 'Test researcher')
            with database.get_connection() as db:
                for table in tables:
                    self.assertEqual([dict(r) for r in db.execute(f'SELECT * FROM {table}').fetchall()], before[table], table)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM c4_rehearsal_session_actors').fetchone()[0], 0)

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
