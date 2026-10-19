"""C1 participant collection and isolation from historical rehearsal records."""
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
from fastapi.testclient import TestClient
import database
import main
from survey.deploy.build_c1_participants import build

ADMIN = 'c1-participant-tests-only-admin-token-with-32-characters'


class C1ParticipantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.root/'test.db'))
        (self.root/'audio').mkdir()
        audio = b'RIFF simulated API audio fixture only'
        (self.root/'audio/test.wav').write_bytes(audio)
        digest = hashlib.sha256(audio).hexdigest()
        self.review = json.loads((ROOT/'survey/deploy/study/bundle.json').read_text())
        for sample in self.review['samples'].values():
            sample.update(playback_path='audio/test.wav', playback_sha256=digest)
        for sample in self.review['headphones']+[self.review['calibration']]:
            sample.update(path='test.wav', sha256=digest)
        self.participant = build(self.review, 'test-source-hash')
        self.review_path, self.participant_path = self.root/'review.json', self.root/'participant.json'
        self.review_path.write_text(json.dumps(self.review))
        self.participant_path.write_text(json.dumps(self.participant))
        self.review_config, self.participant_config = self.root/'review-config.json', self.root/'participant-config.json'
        self.review_config.write_bytes((ROOT/'survey/config/c1_review_20_v1.json').read_bytes())
        self.participant_config.write_bytes((ROOT/'survey/config/c1_participants_v1.json').read_bytes())
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='', SURVEY_ADMIN_TOKEN=ADMIN,
            SURVEY_C1_BUNDLE=str(self.participant_path), SURVEY_C1_CONFIG=str(self.participant_config),
            SURVEY_C1_LEGACY_BUNDLES=str(self.review_path), SURVEY_C1_OPEN='1'))
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization':'Bearer '+ADMIN}

    def start(self):
        code = self.client.post('/api/c1-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations'][0]['invitation']
        self.entry = dict(invitation=code, adult=True, consent=True, headphones=True, quiet_environment=True,
            understands_language=True, activities=['Instrument performance'], experience_months=12,
            recent_frequency='Weekly', tools='Piano', example='I practised a piece on my piano.')
        result = self.client.post('/api/c1-pilot/sessions', json=self.entry)
        self.assertEqual(result.status_code, 200, result.text)
        self.base = '/api/c1-pilot/sessions/'+result.json()['session_id']
        self.headers = {'Authorization':'Bearer '+result.json()['token']}

    def state(self):
        response = self.client.get(self.base, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, body):
        return self.client.post(self.base+'/'+path, headers=self.headers, json=body)

    def setup_audio(self):
        self.post('volume', {'completed_plays':1})
        for number in range(1, 7):
            state = self.state()
            clip = next(item for item in self.review['headphones'] if item['screen_id'] == state['audio_id'])
            self.assertEqual(self.post('headphones', dict(screen_number=number, interval=clip['correct_interval'], completed_plays=1)).status_code, 200)

    def rate(self):
        state = self.state()
        self.assertEqual(self.post('playback/'+state['presentation_id'], {}).status_code, 200)
        self.assertEqual(self.post('ratings', dict(presentation_id=state['presentation_id'], started_at=state['server_time'],
            play_count=1, completed_plays=1, answers=dict(brightness=4, roughness='unclear', percussiveness=2, sustainedness=5, comment='SIMULATED'))).status_code, 200)

    def rows(self):
        return list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export', headers=self.admin).text)))

    def finish(self):
        while self.state()['phase'] in ('rating', 'break'):
            if self.state()['phase'] == 'break':
                self.assertEqual(self.state()['saved_presentations'], 13)
                self.post('continue', {})
            else:
                self.rate()
        self.assertEqual(self.post('feedback', dict(clarity='Clear', length='About right')).status_code, 200)

    def test_participant_information_ready_and_completed_only_exports(self):
        status = self.client.get('/api/c1-pilot/status').json()
        self.assertTrue(status['ready'], status['issues'])
        self.assertFalse(status['rehearsal'])
        self.assertEqual((status['rated_presentations'], status['total_presentations']), (20, 23))
        self.assertNotIn('review_notice', status['config'])
        self.assertEqual(status['config']['institutional_review_status'], 'not_recorded')
        self.start(); self.setup_audio(); self.rate()
        self.assertTrue(all(row['analysis_include'] == 'False' for row in self.rows()))
        self.finish()
        rows = self.rows()
        self.assertEqual(len(rows), 23)
        self.assertEqual(sum(row['analysis_include'] == 'True' for row in rows), 20)
        self.assertTrue(all(row['target_ratings_per_sound'] == '5' for row in rows))
        viewer = self.client.get('/api/c1-pilot/admin/responses', headers=self.admin).json()
        self.assertEqual(sum(row['analysis_include'] for row in viewer['responses']), 20)
        self.assertEqual(self.client.post('/api/c1-pilot/admin/replace-invitation', headers=self.admin,
            json=dict(assignment_id='c1_participant_01', reason='Do not replace a completed participant')).status_code, 409)
        self.post('withdraw', {})
        self.assertTrue(all(row['analysis_include'] == 'False' for row in self.rows()))

    def test_close_switch_blocks_new_entry_but_not_resume(self):
        self.start()
        code = self.client.post('/api/c1-pilot/admin/replace-unused-invitations', headers=self.admin,
                               json=dict(confirm_replace_unused=True)).json()['invitations'][0]['invitation']
        os.environ['SURVEY_C1_OPEN'] = '0'
        self.assertFalse(self.client.get('/api/c1-pilot/status').json()['ready'])
        self.assertEqual(self.client.post('/api/c1-pilot/sessions', json={**self.entry, 'invitation':code}).status_code, 403)
        self.assertEqual(self.state()['phase'], 'volume')
        self.assertEqual(self.post('volume', {'completed_plays':1}).status_code, 200)

    def test_review_keeps_audio_protocol_and_exclusion_after_switch(self):
        os.environ.update(SURVEY_C1_BUNDLE=str(self.review_path), SURVEY_C1_CONFIG=str(self.review_config))
        self.start(); self.setup_audio(); self.rate()
        review_entry = dict(self.entry)
        os.environ.update(SURVEY_C1_BUNDLE=str(self.participant_path), SURVEY_C1_CONFIG=str(self.participant_config))
        self.assertTrue(self.state()['rehearsal'])
        self.assertEqual(self.state()['config']['protocol_version'], 'c1_pilot_2026-10-19_20unique_tags_v2')
        self.finish()
        self.assertTrue(all(row['analysis_include'] == 'False' for row in self.rows()))
        self.assertEqual(self.client.get('/api/c1-pilot/admin/summary', headers=self.admin).json()['completed'], 0)
        self.assertEqual(self.client.post('/api/c1-pilot/sessions', json=review_entry).status_code, 403)

    def test_mismatched_protocol_and_assignment_design_stay_closed(self):
        cfg = json.loads(self.participant_config.read_text())
        cfg['protocol_version'] = 'mismatched'
        self.participant_config.write_text(json.dumps(cfg))
        self.assertFalse(self.client.get('/api/c1-pilot/status').json()['ready'])
        self.participant_config.write_bytes((ROOT/'survey/config/c1_participants_v1.json').read_bytes())
        broken = json.loads(self.participant_path.read_text())
        broken['assignments'][0]['trials'].pop()
        self.participant_path.write_text(json.dumps(broken))
        self.assertFalse(self.client.get('/api/c1-pilot/status').json()['ready'])
