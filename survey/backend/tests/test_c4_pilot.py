import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'survey/backend'))
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
import database
import c4_pilot
import main
from survey.deploy.build_c4_review import build

ADMIN = 'c4-test-only-admin-token-at-least-32-characters'
ROLES = ('reference', 'candidate_a', 'candidate_b')


class C4PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.scope = patch.object(database, 'DATABASE_PATH', root/'test.db')
        self.scope.start(); self.addCleanup(self.scope.stop)
        self.bundle = json.loads((ROOT/'survey/deploy/study/c4_bundle.json').read_text())
        (root/'audio').mkdir()
        fixture = b'RIFF fixture for authenticated delivery only'
        (root/'audio/test.wav').write_bytes(fixture)
        digest = hashlib.sha256(fixture).hexdigest()
        for sample in self.bundle['samples'].values():
            sample.update(playback_path='audio/test.wav', playback_sha256=digest)
        for sample in self.bundle['headphones'] + [self.bundle['calibration']]:
            sample.update(path='test.wav', sha256=digest)
        self.bundle_path = root/'bundle.json'
        self.bundle_path.write_text(json.dumps(self.bundle))
        scope = patch.dict(os.environ, SURVEY_C4_BUNDLE=str(self.bundle_path),
                           SURVEY_DATABASE_URL=getattr(self, 'postgres_test_url', ''), SURVEY_ADMIN_TOKEN=ADMIN)
        scope.start(); self.addCleanup(scope.stop)
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization': 'Bearer '+ADMIN}

    def start(self, number=0, invitation=None):
        if invitation is None:
            codes = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
            invitation = codes[number]['invitation']
        entry = dict(invitation=invitation, adult=True, consent=True, headphones=True,
                     quiet_environment=True, understands_language=True, activities=['Sound design'],
                     experience_months=12, recent_frequency='Weekly', tools='Test synthesizer',
                     example='I made synthesizer patches for a music production.')
        response = self.client.post('/api/c4-pilot/sessions', json=entry)
        self.assertEqual(response.status_code,200,response.text)
        session = response.json()
        self.base = '/api/c4-pilot/sessions/'+session['session_id']
        self.headers = {'Authorization': 'Bearer '+session['token']}
        self.entry = entry
        return session

    def state(self):
        return self.client.get(self.base, headers=self.headers).json()

    def post(self, path, body):
        return self.client.post(self.base+'/'+path, headers=self.headers, json=body)

    def setup_audio(self):
        self.assertEqual(self.post('volume', {'completed_plays':1}).status_code,200)
        for i in range(6):
            state = self.state()
            clip = next(s for s in self.bundle['headphones'] if s['screen_id'] == state['audio_id'])
            self.assertEqual(self.post('headphones', dict(screen_number=i+1,interval=clip['correct_interval'],completed_plays=1)).status_code,200)

    def body(self, state, choice='candidate_a'):
        return dict(presentation_id=state['presentation_id'], started_at=state['server_time'],
                    play_counts=dict.fromkeys(ROLES,1), completed_counts=dict.fromkeys(ROLES,1),
                    answers=dict(choice=choice,confidence=None if choice=='cannot_decide' else 4,comment='=unsafe formula'))

    def expose(self, state):
        for role in ROLES:
            self.assertEqual(self.post('playback/'+state['presentation_id']+'/'+role,{}).status_code,200)

    def admin_summary(self):
        response = self.client.get('/api/c4-pilot/admin/summary', headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_assignment_inventory_before_and_after_invitation_issuance(self):
        self.assertEqual(self.client.get('/api/c4-pilot/admin/summary').status_code, 401)
        summary = self.admin_summary()
        expected_ids = [block['assignment_id'] for block in self.bundle['assignments']]
        self.assertEqual(summary['assignment_capacity'], len(expected_ids))
        self.assertEqual(summary['missing_invitation_count'], len(expected_ids))
        self.assertEqual(summary['sessions'], [])
        self.assertEqual(summary['completed'], 0)
        self.assertEqual([row['assignment_id'] for row in summary['assignments']], expected_ids)
        for row in summary['assignments']:
            self.assertEqual(row['status'], 'missing')
            self.assertIsNone(row['issued_at'])
            self.assertIsNone(row['participant_label'])
            self.assertFalse(row['can_replace'])
        issued = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()
        self.assertEqual(len(issued['invitations']), len(expected_ids))
        summary = self.admin_summary()
        self.assertEqual(summary['missing_invitation_count'], 0)
        self.assertEqual(summary['sessions'], [])
        for row in summary['assignments']:
            self.assertEqual(row['status'], 'issued')
            self.assertTrue(row['issued_at'])
            self.assertIsNone(row['participant_label'])
            self.assertIsNone(row['phase'])
            self.assertEqual(row['saved_presentations'], 0)
            self.assertTrue(row['can_replace'])
            self.assertNotIn('invitation', row)
            self.assertNotIn('invite_hash', row)
        self.assertEqual(self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations'], [])

    def test_assignment_inventory_replacement_preserves_saved_responses(self):
        self.start(); self.setup_audio()
        state = self.state()
        self.expose(state)
        self.assertEqual(self.post('ratings', self.body(state)).status_code, 200)
        assignment = self.admin_summary()['assignments'][0]
        self.assertEqual(assignment['status'], 'in_progress')
        self.assertEqual(assignment['participant_label'], 'Listener 001')
        self.assertEqual(assignment['phase'], 'rating')
        self.assertEqual(assignment['saved_presentations'], 1)
        self.assertTrue(assignment['can_replace'])
        export_before = list(csv.DictReader(io.StringIO(self.client.get('/api/c4-pilot/admin/export', headers=self.admin).text)))
        response = self.client.post('/api/c4-pilot/admin/replace-invitation', headers=self.admin,
                                    json=dict(assignment_id=assignment['assignment_id'], reason='The original invitation was lost.'))
        self.assertEqual(response.status_code, 200, response.text)
        summary = self.admin_summary()
        replacement = summary['assignments'][0]
        self.assertEqual(replacement['status'], 'issued')
        self.assertIsNone(replacement['participant_label'])
        self.assertIsNone(replacement['phase'])
        self.assertEqual(replacement['saved_presentations'], 0)
        self.assertTrue(replacement['can_replace'])
        self.assertEqual(summary['missing_invitation_count'], 0)
        self.assertEqual(summary['sessions'][0]['phase'], 'replaced')
        self.assertEqual(summary['sessions'][0]['current_index'], 1)
        self.assertEqual(self.state()['phase'], 'replaced')
        export_after = list(csv.DictReader(io.StringIO(self.client.get('/api/c4-pilot/admin/export', headers=self.admin).text)))
        self.assertEqual(len(export_after), 1)
        for column in ('session_id', 'presentation_id', 'choice', 'chosen_sample_id', 'confidence', 'comment', 'submitted_at'):
            self.assertEqual(export_after[0][column], export_before[0][column])
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json=self.entry).status_code, 403)
        self.start(invitation=response.json()['invitation'])
        self.assertEqual(self.admin_summary()['assignments'][0]['participant_label'], 'Listener 002')

    def test_authentication_isolation_and_gates(self):
        self.assertEqual(self.client.get('/api/c4-pilot/admin/summary').status_code,401)
        self.start()
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.assertEqual(self.client.post('/api/c4-pilot/sessions',json=self.entry).status_code,409)
        self.assertEqual(self.post('playback/p_01/reference',{}).status_code,409)
        self.assertEqual(self.post('continue',{}).status_code,409)
        self.setup_audio(); state=self.state(); body=self.body(state)
        self.assertEqual(self.post('ratings',body).status_code,409)
        self.expose(state)
        body['completed_counts']['candidate_b']=0
        self.assertEqual(self.post('ratings',body).status_code,422)
        body=self.body(state); body['answers']['confidence']=None
        self.assertEqual(self.post('ratings',body).status_code,422)
        self.assertEqual(self.post('ratings',self.body(state)).status_code,200)
        self.assertEqual(self.post('ratings',self.body(state)).status_code,409)
        self.assertEqual(self.post('playback/'+state['presentation_id']+'/reference',{}).status_code,409)
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c1_sessions').fetchone()[0],0)
        with patch.object(main,'REMOTE_MODE',True):
            self.assertEqual(self.client.get('/api/c4-pilot/status').status_code,200)
            self.assertEqual(self.client.get('/api/studies').status_code,404)

    def test_bulk_unused_download_protects_started_sessions_responses_and_c1(self):
        endpoint = '/api/c4-pilot/admin/replace-unused-invitations'
        body = dict(confirm_replace_unused=True)
        self.assertEqual(self.client.post(endpoint, json=body).status_code, 401)
        for invalid in ({}, {'confirm_replace_unused': False}):
            self.assertEqual(self.client.post(endpoint, headers=self.admin, json=invalid).status_code, 422)
        original = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
        for item, phase in zip(original[:4], ['rating', 'complete', 'withdrawn', 'screen_failed']):
            session = self.start(invitation=item['invitation'])
            if phase == 'rating':
                self.setup_audio()
                state = self.state()
                self.expose(state)
                self.assertEqual(self.post('ratings', self.body(state)).status_code, 200)
            with database.get_connection() as db:
                db.execute('UPDATE c4_sessions SET phase=? WHERE session_id=?', (phase, session['session_id']))
        with database.get_connection() as db:
            sessions = [dict(row) for row in db.execute('SELECT * FROM c4_sessions ORDER BY session_id').fetchall()]
            protected = [dict(row) for row in db.execute('SELECT * FROM c4_invites WHERE session_id IS NOT NULL ORDER BY assignment_id').fetchall()]
            ratings = [dict(row) for row in db.execute('SELECT * FROM c4_ratings').fetchall()]
            self.assertEqual(len(ratings), 1)
            db.execute('INSERT INTO c4_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)',
                       ('other-bundle-hash', 'other-bundle', original[4]['assignment_id'], 'fixture'))
            db.execute('INSERT INTO c1_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)',
                       ('c1-test-hash', 'c1-test-bundle', 'block_01', 'fixture'))
            c1_invites = [dict(row) for row in db.execute('SELECT * FROM c1_invites ORDER BY invite_hash').fetchall()]
        response = self.client.post(endpoint, headers=self.admin, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        result = response.json()
        self.assertEqual(result['skipped_assignments'], [item['assignment_id'] for item in original[:4]])
        self.assertEqual([item['assignment_id'] for item in result['invitations']], [item['assignment_id'] for item in original[4:]])
        self.assertEqual(result['replaced_count'], len(original)-4)
        self.assertEqual(result['created_count'], 0)
        with database.get_connection() as db:
            self.assertEqual(sessions, [dict(row) for row in db.execute('SELECT * FROM c4_sessions ORDER BY session_id').fetchall()])
            self.assertEqual(protected, [dict(row) for row in db.execute('SELECT * FROM c4_invites WHERE session_id IS NOT NULL ORDER BY assignment_id').fetchall()])
            self.assertEqual(ratings, [dict(row) for row in db.execute('SELECT * FROM c4_ratings').fetchall()])
            self.assertEqual(c1_invites, [dict(row) for row in db.execute('SELECT * FROM c1_invites ORDER BY invite_hash').fetchall()])
            self.assertIsNone(db.execute("SELECT retired_at FROM c4_invites WHERE bundle_hash='other-bundle'").fetchone()['retired_at'])
        expired_entry = dict(self.entry, invitation=original[4]['invitation'])
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json=expired_entry).status_code, 403)
        fresh = result['invitations'][0]
        session = self.start(invitation=fresh['invitation'])
        with database.get_connection() as db:
            actual = db.execute('SELECT assignment_id FROM c4_sessions WHERE session_id=?', (session['session_id'],)).fetchone()
            self.assertEqual(actual['assignment_id'], fresh['assignment_id'])

    def test_bulk_unused_download_creates_missing_codes_and_skips_all_claimed_slots(self):
        endpoint = '/api/c4-pilot/admin/replace-unused-invitations'
        body = dict(confirm_replace_unused=True)
        response = self.client.post(endpoint, headers=self.admin, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['created_count'], len(self.bundle['assignments']))
        self.assertEqual(result['replaced_count'], 0)
        for item in result['invitations']:
            self.start(invitation=item['invitation'])
        with database.get_connection() as db:
            before = [dict(row) for row in db.execute('SELECT * FROM c4_invites ORDER BY assignment_id').fetchall()]
        result = self.client.post(endpoint, headers=self.admin, json=body).json()
        self.assertEqual(result['invitations'], [])
        self.assertEqual(result['created_count'], 0)
        self.assertEqual(result['replaced_count'], 0)
        self.assertEqual(len(result['skipped_assignments']), len(self.bundle['assignments']))
        with database.get_connection() as db:
            self.assertEqual(before, [dict(row) for row in db.execute('SELECT * FROM c4_invites ORDER BY assignment_id').fetchall()])

    def test_bulk_unused_download_rolls_back_partial_failure(self):
        self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={})
        with database.get_connection() as db:
            before = [dict(row) for row in db.execute('SELECT * FROM c4_invites ORDER BY assignment_id').fetchall()]
        with patch.object(c4_pilot.secrets, 'token_urlsafe', side_effect=['test-code-only', RuntimeError('simulated failure')]):
            with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
                self.client.post('/api/c4-pilot/admin/replace-unused-invitations', headers=self.admin,
                                 json=dict(confirm_replace_unused=True))
        with database.get_connection() as db:
            self.assertEqual(before, [dict(row) for row in db.execute('SELECT * FROM c4_invites ORDER BY assignment_id').fetchall()])

    def test_complete_resume_export_withdraw_and_replacement(self):
        self.start(); self.setup_audio()
        for index in range(14):
            state=self.state()
            if index == 8:
                self.assertEqual(state['phase'],'break')
                self.assertEqual(self.post('continue',{}).status_code,200)
                state=self.state()
            self.assertEqual(state['phase'],'rating')
            self.assertEqual(state['current_index'],index)
            self.expose(state)
            self.assertEqual(self.post('ratings',self.body(state,'cannot_decide' if index==3 else 'candidate_a')).status_code,200)
            self.assertEqual(self.state()['current_index'],index+1)
        self.assertEqual(self.state()['phase'],'feedback')
        self.assertEqual(self.post('feedback',dict(clarity='Clear',length='About right',comment='')).status_code,200)
        summary = self.admin_summary()
        self.assertEqual(summary['assignments'][0]['status'], 'completed')
        self.assertEqual(summary['assignments'][0]['saved_presentations'], 14)
        self.assertTrue(summary['assignments'][0]['can_replace'])
        self.assertEqual(summary['completed'], 1)
        formal_bundle = dict(self.bundle, rehearsal=False)
        with patch.object(c4_pilot, 'load_bundle', return_value=(formal_bundle, summary['bundle_hash'])):
            self.assertFalse(self.admin_summary()['assignments'][0]['can_replace'])
            protected = self.client.post('/api/c4-pilot/admin/replace-invitation', headers=self.admin,
                                          json=dict(assignment_id='c4_review_01', reason='This completed study must stay protected.'))
            self.assertEqual(protected.status_code, 409)
        output=self.client.get('/api/c4-pilot/admin/export',headers=self.admin)
        rows=list(csv.DictReader(io.StringIO(output.text)))
        self.assertEqual(len(rows),14)
        self.assertTrue(all(r['analysis_include']=='False' for r in rows))
        self.assertEqual(rows[0]['chosen_sample_id'],rows[0]['candidate_a'])
        self.assertEqual(rows[3]['chosen_sample_id'],'')
        self.assertTrue(rows[0]['comment'].startswith("'="))
        self.assertEqual(sum(r['kind']=='repeat' for r in rows),2)
        self.assertEqual(self.post('withdraw',{}).status_code,200)
        self.assertEqual(self.state()['phase'],'withdrawn')
        withdrawn = self.admin_summary()
        self.assertEqual(withdrawn['assignments'][0]['status'], 'withdrawn')
        self.assertTrue(withdrawn['assignments'][0]['can_replace'])
        self.assertEqual(withdrawn['completed'], 0)
        self.assertEqual(self.post('playback/p_01/reference',{}).status_code,409)
        r=self.client.post('/api/c4-pilot/admin/replace-invitation',headers=self.admin,
                           json=dict(assignment_id='c4_review_01',reason='Repeat the interface review.'))
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/c4-pilot/admin/sessions',headers=self.admin).status_code,200)

    def test_audio_tamper_and_review_only_gate(self):
        self.start(); self.setup_audio()
        (self.bundle_path.parent/'audio/test.wav').write_bytes(b'changed')
        self.assertEqual(self.post('playback/p_01/reference',{}).status_code,409)
        self.bundle['rehearsal']=False; self.bundle['study_id']='c4_main'
        self.bundle_path.write_text(json.dumps(self.bundle))
        self.assertFalse(self.client.get('/api/c4-pilot/status').json()['ready'])
        self.assertEqual(self.client.post('/api/c4-pilot/sessions',json=self.entry).status_code,403)

    def test_tagged_entry_uses_same_catalogue_and_exports_choices(self):
        cfg = self.client.get('/api/c4-pilot/status').json()['config']
        self.assertEqual(cfg['experience_selection']['version'], 'experience_tags_v1')
        self.assertEqual(cfg['protocol_version'], 'c4_review_2026-10-19_navigation_v3')
        self.start()
        code = self.client.post('/api/c4-pilot/admin/replace-unused-invitations', headers=self.admin,
                                json=dict(confirm_replace_unused=True)).json()['invitations'][0]['invitation']
        entry = dict(self.entry, invitation=code, tools='', example='', experience_selection=dict(
            version='experience_tags_v1', tool_ids=['bass', 'singing'], example_ids=['sang_song'], tools_other='', example_other=''))
        invalid = {**entry, 'experience_selection': {**entry['experience_selection'], 'tool_ids': ['unknown']}}
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json=invalid).status_code, 422)
        response = self.client.post('/api/c4-pilot/sessions', json=entry)
        self.assertEqual(response.status_code, 200, response.text)
        exported = list(csv.DictReader(io.StringIO(self.client.get('/api/c4-pilot/admin/sessions', headers=self.admin).text)))
        saved = next(json.loads(row['entry_json']) for row in exported if row['session_id'] == response.json()['session_id'])
        self.assertEqual(saved['experience_selection'], entry['experience_selection'])
        self.assertEqual(saved['tools'], 'Bass guitar; Singing / vocals')
        self.assertEqual(saved['example'], 'Practised, performed or recorded a song with my voice')

    def test_previous_correction_preserves_original_and_exports_canonical_revisions(self):
        self.start(); self.setup_audio()
        first = self.state()
        self.assertFalse(first['can_correct_previous'])
        self.expose(first)
        self.assertEqual(self.post('ratings', self.body(first)).status_code, 200)
        current = self.state()
        self.assertTrue(current['can_correct_previous'])
        self.assertEqual(self.post('previous', {'current_index': current['current_index']}).status_code, 200)
        correction = self.state()
        self.assertEqual(correction['phase'], 'correction')
        self.assertEqual(correction['presentation_id'], first['presentation_id'])
        self.assertEqual(correction['saved_answers']['choice'], 'candidate_a')
        self.assertEqual(self.state()['correction_token'], correction['correction_token'])
        # Correction may replay only its own three sounds, never the next comparison.
        self.expose(correction)
        self.assertEqual(self.post('playback/'+current['presentation_id']+'/reference', {}).status_code, 409)
        self.assertEqual(self.post('ratings', self.body(current)).status_code, 409)
        revised = self.body(correction, 'candidate_b')
        revised['correction_token'] = correction['correction_token']
        revised['play_counts'] = dict.fromkeys(ROLES, 0)
        revised['completed_counts'] = dict.fromkeys(ROLES, 0)
        self.assertEqual(self.post('previous/save', revised).status_code, 200)
        self.assertEqual(self.post('previous/save', revised).status_code, 409)
        self.assertEqual(self.state()['presentation_id'], current['presentation_id'])
        with database.get_connection() as db:
            original = db.execute('SELECT * FROM c4_ratings WHERE presentation_id=?', (first['presentation_id'],)).fetchone()
            self.assertEqual(json.loads(original['answers_json'])['choice'], 'candidate_a')
            expected_id = json.loads(original['triplet_json'])['candidate_b']
        rows = list(csv.DictReader(io.StringIO(self.client.get('/api/c4-pilot/admin/export', headers=self.admin).text)))
        self.assertEqual(rows[0]['choice_first'], 'candidate_a')
        self.assertEqual(rows[0]['choice'], 'candidate_b')
        self.assertEqual(rows[0]['chosen_sample_id'], expected_id)
        self.assertEqual(rows[0]['revision_count'], '1')
        self.assertEqual(json.loads(json.loads(rows[0]['corrections_json'])[0]['answers_json'])['chosen_sample_id'], expected_id)
        # Reopen the latest answer, then cancel without creating another revision.
        self.assertEqual(self.post('previous', {'current_index': current['current_index']}).status_code, 200)
        reopened = self.state()
        self.assertEqual(reopened['saved_answers']['choice'], 'candidate_b')
        self.assertEqual(self.post('previous/cancel', {'correction_token': 'wrong-token'}).status_code, 409)
        self.assertEqual(self.post('previous/cancel', {'correction_token': reopened['correction_token']}).status_code, 200)
        self.assertTrue(self.state()['can_correct_previous'])

    def test_admin_response_viewer_omits_private_fields_and_tracks_corrections(self):
        endpoint = '/api/c4-pilot/admin/responses'
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        session = self.start(); self.setup_audio()
        self.assertEqual(self.client.get(endpoint, headers=self.headers).status_code, 401)
        first = self.state(); self.expose(first)
        self.post('ratings', self.body(first))
        self.post('previous', {'current_index':self.state()['current_index']})
        correction = self.state()
        revised = dict(self.body(correction, 'candidate_b'), correction_token=correction['correction_token'])
        revised['answers']['comment'] = 'PRIVATE_COMMENT_NAME@example.invalid'
        self.assertEqual(self.post('previous/save', revised).status_code, 200)
        with database.get_connection() as db:
            db.execute('UPDATE c4_sessions SET entry_json=?,feedback_json=? WHERE session_id=?',
                       (json.dumps({'tools':'PRIVATE_ENTRY_NAME'}), json.dumps({'comment':'PRIVATE_FEEDBACK_NAME'}), session['session_id']))
        response = self.client.get(endpoint+'?limit=1', headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        page = response.json(); row = page['responses'][0]
        self.assertEqual(page['total'], 1)
        self.assertEqual(row['participant_label'], 'Listener 001')
        self.assertEqual(row['answer'], dict(choice='candidate_b', confidence=4))
        self.assertEqual(row['first_answer'], dict(choice='candidate_a', confidence=4))
        self.assertEqual(row['revision_count'], 1)
        self.assertEqual(row['triplet_id'], self.bundle['assignments'][0]['trials'][0]['triplet_id'])
        self.assertFalse(row['analysis_include'])
        for value in ('PRIVATE_', 'session_id', 'participant_id', 'entry_json', 'feedback_json', 'comment', 'token',
                      'screen_answers', 'protocol_snapshot', 'invite', session['session_id'], session['token']):
            self.assertNotIn(value, response.text)
        for query in ('offset=1', 'kind=repeat', 'phase=complete', 'listener_number=999'):
            self.assertEqual(self.client.get(endpoint+'?'+query, headers=self.admin).json()['responses'], [], query)
        self.assertEqual(self.client.get(endpoint+'?phase=in_progress&kind=practice&listener_number=1', headers=self.admin).json()['total'], 1)
        for query in ('limit=101', 'offset=-1', 'listener_number=0', 'phase=unknown', 'kind=unknown'):
            self.assertEqual(self.client.get(endpoint+'?'+query, headers=self.admin).status_code, 422)
        self.assertEqual(self.post('withdraw', {}).status_code, 200)
        withdrawn = self.client.get(endpoint+'?phase=withdrawn', headers=self.admin).json()
        self.assertEqual(withdrawn['total'], 1)
        self.assertFalse(withdrawn['responses'][0]['analysis_include'])
        self.bundle_path.write_text(self.bundle_path.read_text()+' ')
        self.assertEqual(self.client.get(endpoint, headers=self.admin).json()['total'], 0)

    def test_previous_locks_on_any_next_clip_and_rejects_invalid_corrections(self):
        self.start(); self.setup_audio()
        first = self.state(); self.expose(first)
        self.post('ratings', self.body(first))
        current = self.state()
        self.assertEqual(self.client.post(self.base+'/previous', json={'current_index': current['current_index']}).status_code, 401)
        self.assertEqual(self.post('previous', {'current_index': 99}).status_code, 409)
        self.assertEqual(self.post('previous', {'current_index': current['current_index']}).status_code, 200)
        correction = self.state()
        revised = dict(self.body(correction), correction_token=correction['correction_token'])
        for update in ({'presentation_id': current['presentation_id']}, {'correction_token': 'wrong'}):
            self.assertEqual(self.post('previous/save', {**revised, **update}).status_code, 409)
        revised['answers']['confidence'] = None
        self.assertEqual(self.post('previous/save', revised).status_code, 422)
        revised = dict(self.body(correction, 'cannot_decide'), correction_token=correction['correction_token'],
                       play_counts=dict.fromkeys(ROLES, 0), completed_counts=dict.fromkeys(ROLES, 0))
        self.assertEqual(self.post('previous/save', revised).status_code, 200)
        # A GET/prefetch does not claim audio. Any explicitly requested role locks Previous.
        path = self.base+'/playback/'+current['presentation_id']+'/candidate_b'
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 405)
        self.assertTrue(self.state()['can_correct_previous'])
        self.assertEqual(self.client.post(path, headers=self.headers).status_code, 200)
        self.assertFalse(self.state()['can_correct_previous'])
        self.assertFalse(self.state()['can_correct_previous'])
        self.assertEqual(self.post('previous', {'current_index': current['current_index']}).status_code, 409)
        self.assertEqual(self.post('playback/'+first['presentation_id']+'/reference', {}).status_code, 409)

    def test_previous_at_break_feedback_and_old_protocol_boundaries(self):
        self.start(); self.setup_audio()
        for _ in range(14):
            state = self.state()
            if state['phase'] == 'break':
                self.assertTrue(state['can_correct_previous'])
                self.post('previous', {'current_index': state['current_index']})
                correction = self.state()
                self.assertEqual(self.post('continue', {}).status_code, 409)
                self.post('previous/cancel', {'correction_token': correction['correction_token']})
                self.post('continue', {})
                state = self.state()
            self.expose(state)
            self.assertEqual(self.post('ratings', self.body(state)).status_code, 200)
        state = self.state()
        self.assertEqual(state['phase'], 'feedback')
        self.assertTrue(state['can_correct_previous'])
        self.post('previous', {'current_index': state['current_index']})
        correction = self.state()
        feedback = dict(clarity='Clear', length='About right')
        self.assertEqual(self.post('feedback', feedback).status_code, 409)
        revised = dict(self.body(correction), correction_token=correction['correction_token'])
        self.assertEqual(self.post('previous/save', revised).status_code, 200)
        self.assertEqual(self.post('feedback', feedback).status_code, 200)
        self.assertFalse(self.state()['can_correct_previous'])
        self.assertEqual(self.post('previous', {'current_index': state['current_index']}).status_code, 409)
        # An older snapshot keeps forward-only navigation after deployment.
        cfg = c4_pilot.config(); cfg.pop('navigation_policy')
        code = self.client.post('/api/c4-pilot/admin/replace-unused-invitations', headers=self.admin,
                                json=dict(confirm_replace_unused=True)).json()['invitations'][0]['invitation']
        with patch.object(c4_pilot, 'config', return_value=cfg):
            self.start(invitation=code)
        self.setup_audio(); first = self.state(); self.expose(first)
        self.post('ratings', self.body(first))
        self.assertFalse(self.state()['can_correct_previous'])
        self.assertEqual(self.post('previous', {'current_index': self.state()['current_index']}).status_code, 409)


class C4DesignTests(unittest.TestCase):
    def test_reproducible_distinct_counterbalanced_and_separated(self):
        source=json.loads((ROOT/'survey/deploy/study/bundle.json').read_text())
        b=build(source)
        self.assertEqual(b,build(source))
        for i, block in enumerate(b['assignments']):
            trials=block['trials']
            self.assertEqual(len(trials),14)
            self.assertEqual(sum(t['kind']=='primary' for t in trials),10)
            self.assertEqual(len({t['triplet_id'] for t in trials if t['kind']=='primary'}),10)
            for j,t in enumerate(trials):
                self.assertEqual(len({t[r] for r in ROLES}),3)
                if t['repeat_of']:
                    original=next((k,p) for k,p in enumerate(trials) if p['presentation_id']==t['repeat_of'])
                    self.assertGreaterEqual(j-original[0],6)
                    self.assertEqual(t['candidate_a'],original[1]['candidate_b'])
                paired=b['assignments'][i ^ 1]['trials'][j]
                self.assertEqual(t['reference'],paired['reference'])
                self.assertEqual(t['candidate_a'],paired['candidate_b'])
