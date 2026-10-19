"""Participant collection, completed-only exports and historical review isolation."""
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
sys.path.insert(0, str(ROOT / 'survey/backend'))
from fastapi.testclient import TestClient
import database
import main
from c4_protocol import PARTICIPANT_STUDY_ID

ADMIN = 'participant-test-only-admin-token-at-least-32-characters'
ROLES = ('reference', 'candidate_a', 'candidate_b')


class C4ParticipantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.root / 'test.db'))
        self.participant = self.fixture('participant', 'c4_participant_bundle_v1.json', 'c4_participants_v1.json')
        self.review = self.fixture('review', 'c4_clap_bundle.json', 'c4_clap_v1.json')
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='', SURVEY_ADMIN_TOKEN=ADMIN,
            SURVEY_C4_BUNDLE=str(self.participant['path']), SURVEY_C4_CONFIG=str(self.participant['config']),
            SURVEY_C4_LEGACY_BUNDLES=str(self.review['path']), SURVEY_C4_OPEN='1'))
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization': 'Bearer ' + ADMIN}

    def fixture(self, folder, bundle_name, config_name):
        root = self.root / folder
        (root / 'audio').mkdir(parents=True)
        audio = b'RIFF ' + folder.encode() + b' isolated test audio'
        (root / 'audio/test.wav').write_bytes(audio)
        digest = hashlib.sha256(audio).hexdigest()
        bundle = json.loads((ROOT / 'survey/deploy/study' / bundle_name).read_text(encoding='utf-8'))
        for sample in bundle['samples'].values():
            sample.update(playback_path='audio/test.wav', playback_sha256=digest)
        for sample in bundle['headphones'] + [bundle['calibration']]:
            sample.update(path='test.wav', sha256=digest)
        path = root / 'bundle.json'
        path.write_text(json.dumps(bundle), encoding='utf-8')
        config = root / 'config.json'
        config.write_bytes((ROOT / 'survey/config' / config_name).read_bytes())
        return dict(path=path, config=config, bundle=bundle, audio=audio)

    def activate(self, fixture):
        os.environ['SURVEY_C4_BUNDLE'] = str(fixture['path'])
        os.environ['SURVEY_C4_CONFIG'] = str(fixture['config'])

    def start(self, fixture=None):
        fixture = fixture or self.participant
        invitations = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
        invitation = invitations[0]
        entry = dict(invitation=invitation['invitation'], adult=True, consent=True, headphones=True,
            quiet_environment=True, understands_language=True, activities=['Sound design'],
            experience_months=12, recent_frequency='Weekly', tools='QA synthesizer',
            example='Automated QA fixture only; not a human participant response.')
        response = self.client.post('/api/c4-pilot/sessions', json=entry)
        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()
        session.update(base='/api/c4-pilot/sessions/' + session['session_id'],
                       headers={'Authorization': 'Bearer ' + session['token']}, fixture=fixture,
                       assignment=invitation['assignment_id'], entry=entry)
        return session

    def state(self, session):
        response = self.client.get(session['base'], headers=session['headers'])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, session, path, body):
        return self.client.post(session['base'] + '/' + path, headers=session['headers'], json=body)

    def setup_audio(self, session):
        self.assertEqual(self.post(session, 'volume', {'completed_plays': 1}).status_code, 200)
        for number in range(6):
            state = self.state(session)
            clip = next(c for c in session['fixture']['bundle']['headphones'] if c['screen_id'] == state['audio_id'])
            self.assertEqual(self.post(session, 'headphones', dict(screen_number=number+1,
                interval=clip['correct_interval'], completed_plays=1)).status_code, 200)

    def rate(self, session):
        state = self.state(session)
        for role in ROLES:
            response = self.post(session, 'playback/' + state['presentation_id'] + '/' + role, {})
            self.assertEqual(response.content, session['fixture']['audio'])
        counts = dict.fromkeys(ROLES, 1)
        response = self.post(session, 'ratings', dict(presentation_id=state['presentation_id'],
            started_at=state['server_time'], play_counts=counts, completed_counts=counts,
            answers=dict(choice='candidate_a', confidence=4, comment='Automated test response')))
        self.assertEqual(response.status_code, 200, response.text)

    def complete(self, session):
        while True:
            phase = self.state(session)['phase']
            if phase == 'rating':
                self.rate(session)
            elif phase == 'break':
                self.assertEqual(self.post(session, 'continue', {}).status_code, 200)
            else:
                self.assertEqual(phase, 'feedback')
                break
        self.assertEqual(self.post(session, 'feedback', dict(clarity='Clear', length='About right')).status_code, 200)

    def rows(self):
        response = self.client.get('/api/c4-pilot/admin/export', headers=self.admin)
        self.assertEqual(response.status_code, 200)
        return list(csv.DictReader(io.StringIO(response.text)))

    def test_participant_information_and_deliberate_close_switch(self):
        status = self.client.get('/api/c4-pilot/status').json()
        self.assertTrue(status['ready'], status['issues'])
        self.assertFalse(status['rehearsal'])
        self.assertEqual(status['config']['study_id'], PARTICIPANT_STUDY_ID)
        self.assertEqual(status['rated_presentations'], 22)
        self.assertEqual(status['config']['researcher_email'], 'it23203280@my.sliit.lk')
        self.assertNotIn('review_notice', status['config'])
        self.assertIn('not a rating of how similar', status['config']['information'][3])
        os.environ['SURVEY_C4_OPEN'] = '0'
        self.assertFalse(self.client.get('/api/c4-pilot/status').json()['ready'])
        # Valid participant information is not an assertion of ethics approval.
        self.assertEqual(status['config']['institutional_review_status'], 'not_recorded')
        codes = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
        self.assertTrue(all(c['assignment_id'].startswith('c4_participant_') for c in codes))
        entry = dict(invitation=codes[0]['invitation'], adult=True, consent=True, headphones=True,
            quiet_environment=True, understands_language=True, activities=['Sound design'], experience_months=1,
            recent_frequency='Weekly', tools='Synthesizer', example='I create synthesizer patches for personal music practice.')
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json=entry).status_code, 403)

    def test_completion_practice_repeat_withdrawal_and_replacement_policy(self):
        session = self.start()
        self.setup_audio(session)
        for _ in range(3):
            self.rate(session)
        self.assertTrue(all(r['analysis_include'] == 'False' for r in self.rows()))
        self.complete(session)
        rows = self.rows()
        self.assertEqual(len(rows), 24)
        self.assertEqual(sum(r['analysis_include'] == 'True' for r in rows), 22)
        self.assertTrue(all((r['analysis_include'] == 'True') == (r['kind'] != 'practice') for r in rows))
        self.assertTrue(all(r['collection_mode'] == 'participants' for r in rows))
        viewer = self.client.get('/api/c4-pilot/admin/responses', headers=self.admin).json()
        self.assertEqual(sum(r['analysis_include'] for r in viewer['responses']), 22)
        replacement = dict(assignment_id=session['assignment'], reason='Attempted replacement of completed participant slot.')
        self.assertEqual(self.client.post('/api/c4-pilot/admin/replace-invitation', headers=self.admin, json=replacement).status_code, 409)
        self.assertEqual(self.post(session, 'withdraw', {}).status_code, 200)
        self.assertTrue(all(r['analysis_include'] == 'False' for r in self.rows()))
        viewer = self.client.get('/api/c4-pilot/admin/responses', headers=self.admin).json()
        self.assertTrue(all(not r['analysis_include'] for r in viewer['responses']))
        self.assertEqual(self.client.get('/api/c4-pilot/admin/summary', headers=self.admin).json()['coverage']['completed_listeners'], 0)

    def test_review_records_and_tokens_keep_their_original_collection_mode(self):
        self.activate(self.review)
        review = self.start(self.review)
        self.setup_audio(review)
        self.rate(review)
        self.activate(self.participant)
        state = self.state(review)
        self.assertTrue(state['rehearsal'])
        self.assertEqual(state['config']['study_id'], 'c4_clap_review_v1')
        self.rate(review)
        self.complete(review)
        self.assertTrue(all(r['analysis_include'] == 'False' for r in self.rows()))
        summary = self.client.get('/api/c4-pilot/admin/summary', headers=self.admin).json()
        self.assertEqual(summary['completed'], 0)
        self.assertFalse(summary['rehearsal'])
        # The active participant entry cannot consume a historical review invitation.
        self.assertEqual(self.client.post('/api/c4-pilot/sessions', json=review['entry']).status_code, 403)
        self.assertEqual(self.state(review)['phase'], 'complete')


if __name__ == '__main__':
    unittest.main()
