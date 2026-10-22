"""Integration checks for CLAP assignments and preserved historical C4 sessions."""
import copy
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


ADMIN = 'c4-version-tests-admin-token-at-least-32-characters'
ROLES = ('reference', 'candidate_a', 'candidate_b')


class C4ClapVersioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        scope = patch.object(database, 'DATABASE_PATH', root / 'test.db')
        scope.start()
        self.addCleanup(scope.stop)
        legacy = json.loads((ROOT / 'survey/deploy/study/c4_bundle.json').read_text())
        config = json.loads((ROOT / 'survey/config/c4_review_v1.json').read_text())
        self.legacy = self.write_study(root / 'historical', legacy, config, b'RIFF historical audio')
        clap = self.clap_fixture(legacy)
        clap_config = dict(config, study_id='c4_clap_review_v1',
                           protocol_version='c4_clap_2026-10-19_200triplets_v1',
                           unique_comparisons=20, repeat_comparisons=2,
                           practice_comparisons=2, assignment_capacity=100,
                           break_after_rated=11, target_completed_min=50, target_completed_max=100)
        self.clap = self.write_study(root / 'active', clap, clap_config, b'RIFF active CLAP audio')
        scope = patch.dict(os.environ, SURVEY_C4_BUNDLE=str(self.clap['path']),
                           SURVEY_C4_CONFIG=str(self.clap['config_path']),
                           SURVEY_C4_LEGACY_BUNDLES=str(self.legacy['path']),
                           SURVEY_DATABASE_URL='', SURVEY_ADMIN_TOKEN=ADMIN)
        scope.start()
        self.addCleanup(scope.stop)
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization': 'Bearer ' + ADMIN}

    @staticmethod
    def clap_fixture(legacy):
        """Use distinct sample identities and a complete ten-round assignment bank."""
        bundle = copy.deepcopy(legacy)
        sample = next(iter(legacy['samples'].values()))
        bank = [dict(triplet_id=f'clap_triplet_{i + 1:03d}',
                     reference=f's_{3 * i:04d}', candidate_1=f's_{3 * i + 1:04d}',
                     candidate_2=f's_{3 * i + 2:04d}') for i in range(200)]
        bundle.update(study_id='c4_clap_review_v1', rehearsal=True,
                      canonical_triplets=bank,
                      samples={f's_{i:04d}': copy.deepcopy(sample) for i in range(603)},
                      design=dict(assignment_capacity=100, unique_comparisons=20,
                                  repeat_comparisons=2, practice_comparisons=2,
                                  assignments_per_round=10, target_completed_min=50,
                                  target_completed_max=100))
        assignments = []
        for number in range(100):
            reverse = bool((number // 10) % 2)
            trials = []

            def append(triplet, kind, repeat_of=None, swap=False):
                trials.append(dict(presentation_id=f'p_{len(trials) + 1:02d}',
                                   triplet_id=triplet['triplet_id'], reference=triplet['reference'],
                                   candidate_a=triplet['candidate_2' if swap else 'candidate_1'],
                                   candidate_b=triplet['candidate_1' if swap else 'candidate_2'],
                                   kind=kind, repeat_of=repeat_of))

            for i in range(2):
                append(dict(triplet_id=f'practice_{i + 1}', reference=f's_{600 + i:04d}',
                            candidate_1=f's_{600 + (i + 1) % 3:04d}',
                            candidate_2=f's_{600 + (i + 2) % 3:04d}'), 'practice')
            selected = bank[(number % 10) * 20:(number % 10 + 1) * 20]
            for triplet in selected:
                append(triplet, 'primary', swap=reverse)
            for index in (0, 3):
                append(selected[index], 'repeat', f'p_{index + 3:02d}', not reverse)
            assignments.append(dict(assignment_id=f'c4_clap_{number + 1:03d}', trials=trials))
        bundle['assignments'] = assignments
        return bundle

    @staticmethod
    def write_study(root, bundle, config, audio):
        (root / 'audio').mkdir(parents=True)
        (root / 'audio/test.wav').write_bytes(audio)
        checksum = hashlib.sha256(audio).hexdigest()
        for sample in bundle['samples'].values():
            sample.update(playback_path='audio/test.wav', playback_sha256=checksum)
        for sample in bundle['headphones'] + [bundle['calibration']]:
            sample.update(path='test.wav', sha256=checksum)
        path, config_path = root / 'bundle.json', root / 'config.json'
        path.write_text(json.dumps(bundle), encoding='utf-8')
        config_path.write_text(json.dumps(config), encoding='utf-8')
        return dict(path=path, config_path=config_path, bundle=bundle, audio=audio)

    def activate(self, study):
        os.environ['SURVEY_C4_BUNDLE'] = str(study['path'])
        os.environ['SURVEY_C4_CONFIG'] = str(study['config_path'])

    def issue(self):
        response = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['invitations']

    def start(self, study, invitation):
        entry = dict(invitation=invitation, adult=True, consent=True, headphones=True,
                     quiet_environment=True, understands_language=True, activities=['Sound design'],
                     experience_months=12, recent_frequency='Weekly', tools='Test synthesizer',
                     example='I made synthesizer patches for a music production.')
        response = self.client.post('/api/c4-pilot/sessions', json=entry)
        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()
        return dict(base='/api/c4-pilot/sessions/' + session['session_id'],
                    headers={'Authorization': 'Bearer ' + session['token']},
                    id=session['session_id'], study=study)

    def state(self, session):
        response = self.client.get(session['base'], headers=session['headers'])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, session, suffix, body):
        return self.client.post(session['base'] + '/' + suffix, headers=session['headers'], json=body)

    def setup_audio(self, session):
        self.assertEqual(self.post(session, 'volume', {'completed_plays': 1}).status_code, 200)
        for i in range(6):
            state = self.state(session)
            clip = next(s for s in session['study']['bundle']['headphones'] if s['screen_id'] == state['audio_id'])
            response = self.post(session, 'headphones', dict(screen_number=i + 1,
                                 interval=clip['correct_interval'], completed_plays=1))
            self.assertEqual(response.status_code, 200, response.text)

    def rate(self, session):
        state = self.state(session)
        self.assertEqual(state['phase'], 'rating')
        for role in ROLES:
            response = self.post(session, 'playback/' + state['presentation_id'] + '/' + role, {})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, session['study']['audio'])
        response = self.post(session, 'ratings', dict(
            presentation_id=state['presentation_id'], started_at=state['server_time'],
            play_counts=dict.fromkeys(ROLES, 1), completed_counts=dict.fromkeys(ROLES, 1),
            answers=dict(choice='candidate_a', confidence=4, comment='')))
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
        response = self.post(session, 'feedback', dict(clarity='Clear', length='About right', comment=''))
        self.assertEqual(response.status_code, 200, response.text)

    def summary(self):
        response = self.client.get('/api/c4-pilot/admin/summary', headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_new_session_has_twenty_unique_two_repeats_two_practice_and_frozen_break(self):
        status = self.client.get('/api/c4-pilot/status').json()
        self.assertTrue(status['ready'], status)
        self.assertEqual(status['total_presentations'], 24)
        self.assertEqual(status['rated_presentations'], 22)
        invitations = self.issue()
        self.assertEqual(len(invitations), 100)
        session = self.start(self.clap, invitations[0]['invitation'])
        initial = self.state(session)
        self.assertEqual(initial['config']['unique_comparisons'], 20)
        self.assertEqual(initial['config']['break_after_rated'], 11)
        # A config edit after consent must not move an existing participant's break.
        changed_config = json.loads(self.clap['config_path'].read_text())
        changed_config['break_after_rated'] = 4
        self.clap['config_path'].write_text(json.dumps(changed_config))
        self.setup_audio(session)
        for index in range(24):
            state = self.state(session)
            if index == 13:
                self.assertEqual(state['phase'], 'break')
                self.assertEqual(self.post(session, 'continue', {}).status_code, 200)
                state = self.state(session)
            self.assertEqual(state['phase'], 'rating')
            self.assertEqual(state['current_index'], index)
            self.assertEqual(state['practice'], index < 2)
            self.rate(session)
        self.assertEqual(self.state(session)['phase'], 'feedback')
        self.complete(session)
        with database.get_connection() as db:
            row = db.execute('SELECT * FROM c4_sessions WHERE session_id=?', (session['id'],)).fetchone()
            trials = json.loads(row['trial_order'])
            self.assertEqual(json.loads(row['protocol_snapshot']), initial['config'])
            self.assertEqual(sum(t['kind'] == 'primary' for t in trials), 20)
            self.assertEqual(len({t['triplet_id'] for t in trials if t['kind'] == 'primary'}), 20)
            self.assertEqual(sum(t['kind'] == 'repeat' for t in trials), 2)
            self.assertEqual(sum(t['kind'] == 'practice' for t in trials), 2)
        export = self.client.get('/api/c4-pilot/admin/export', headers=self.admin)
        rows = list(csv.DictReader(io.StringIO(export.text)))
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(row['analysis_include'] == 'False' for row in rows))

    def test_historical_session_resumes_its_config_and_audio_root_after_active_switch(self):
        self.activate(self.legacy)
        invitation = self.issue()[0]['invitation']
        session = self.start(self.legacy, invitation)
        initial = self.state(session)
        self.setup_audio(session)
        self.rate(session)
        with database.get_connection() as db:
            before = dict(db.execute('SELECT * FROM c4_sessions WHERE session_id=?', (session['id'],)).fetchone())
            rating = dict(db.execute('SELECT * FROM c4_ratings WHERE session_id=?', (session['id'],)).fetchone())
        self.activate(self.clap)
        resumed = self.state(session)
        self.assertEqual(resumed['config'], initial['config'])
        self.assertEqual(resumed['total_presentations'], 14)
        self.assertEqual(resumed['current_index'], 1)
        calibration = self.client.get(session['base'] + '/audio/volume_reference', headers=session['headers'])
        self.assertEqual(calibration.status_code, 200, calibration.text)
        self.assertEqual(calibration.content, self.legacy['audio'])
        for _ in range(7):
            self.rate(session)
        self.assertEqual(self.state(session)['phase'], 'break')
        self.assertEqual(self.state(session)['current_index'], 8)
        self.assertEqual(self.post(session, 'continue', {}).status_code, 200)
        self.complete(session)
        with database.get_connection() as db:
            after = dict(db.execute('SELECT * FROM c4_sessions WHERE session_id=?', (session['id'],)).fetchone())
            retained = dict(db.execute('SELECT * FROM c4_ratings WHERE session_id=? AND presentation_id=?',
                                       (session['id'], rating['presentation_id'])).fetchone())
        for column in ('protocol_snapshot', 'protocol_hash', 'bundle_hash', 'trial_order', 'assignment_id'):
            self.assertEqual(after[column], before[column])
        self.assertEqual(retained, rating)
        # Historical sessions do not fill slots or coverage in the newly active bank.
        self.assertEqual(self.summary()['completed'], 0)
        self.assertEqual(self.summary()['coverage']['completed_listeners'], 0)
        fresh = self.start(self.clap, self.issue()[0]['invitation'])
        self.assertEqual(self.state(fresh)['total_presentations'], 24)

    def test_missing_tampered_or_unregistered_historical_bundle_fails_closed(self):
        self.activate(self.legacy)
        session = self.start(self.legacy, self.issue()[0]['invitation'])
        self.setup_audio(session)
        current = self.state(session)
        self.activate(self.clap)
        original = self.legacy['path'].read_bytes()
        for content in (None, original + b' '):
            if content is None:
                self.legacy['path'].unlink()
            else:
                self.legacy['path'].write_bytes(content)
            self.assertEqual(self.client.get(session['base'], headers=session['headers']).status_code, 409)
            playback = self.post(session, 'playback/' + current['presentation_id'] + '/reference', {})
            self.assertEqual(playback.status_code, 409)
            self.assertTrue(self.client.get('/api/c4-pilot/status').json()['ready'])
            self.legacy['path'].write_bytes(original)
            self.assertEqual(self.state(session)['phase'], 'rating')
        os.environ['SURVEY_C4_LEGACY_BUNDLES'] = ''
        self.assertEqual(self.client.get(session['base'], headers=session['headers']).status_code, 409)
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c4_exposures').fetchone()[0], 0)

    def test_mismatched_config_and_bundle_refuse_new_entry(self):
        for bundle, config in ((self.legacy, self.clap), (self.clap, self.legacy)):
            os.environ['SURVEY_C4_BUNDLE'] = str(bundle['path'])
            os.environ['SURVEY_C4_CONFIG'] = str(config['config_path'])
            status = self.client.get('/api/c4-pilot/status').json()
            self.assertFalse(status['ready'])
            self.assertIn('versions do not match', status['issues'][0])

    def test_coverage_counts_only_primary_judgments_from_completed_retained_listeners(self):
        expected_design = dict(bank_triplets=200, unique_per_listener=20, repeats_per_listener=2,
                               practice_per_listener=2, target_min=50, target_max=100)
        initial = self.summary()
        for key, value in expected_design.items():
            self.assertEqual(initial['design'][key], value)
        self.assertEqual(initial['assignment_capacity'], 100)
        self.assertEqual(initial['coverage']['planned_per_triplet'], 10)
        self.assertEqual(initial['coverage']['minimum_completed_judgments'], 0)
        self.assertEqual(len(initial['coverage']['below_two']), 200)
        invitations = self.issue()
        sessions = {}
        # Slots 0 and 10 share a bank subset; distinct listeners supply its two judgments.
        for index in (0, 10, 1, 2, 3):
            session = self.start(self.clap, invitations[index]['invitation'])
            sessions[index] = session
            self.setup_audio(session)
            if index == 2:
                for _ in range(3):
                    self.rate(session)
            else:
                self.complete(session)
        self.assertEqual(self.post(sessions[1], 'withdraw', {}).status_code, 200)
        replacement = self.client.post('/api/c4-pilot/admin/replace-invitation', headers=self.admin,
                                       json=dict(assignment_id=invitations[3]['assignment_id'],
                                                 reason='Replace this completed review assignment.'))
        self.assertEqual(replacement.status_code, 200, replacement.text)
        summary = self.summary()
        coverage = summary['coverage']
        self.assertEqual(coverage['completed_listeners'], 2)
        self.assertEqual(coverage['triplets_with_completed_judgments'], 20)
        self.assertEqual(coverage['triplets_at_least_two'], 20)
        self.assertEqual(coverage['minimum_completed_judgments'], 0)
        self.assertEqual(coverage['maximum_completed_judgments'], 2)
        completed_ids = {t['triplet_id'] for t in self.clap['bundle']['assignments'][0]['trials']
                         if t['kind'] == 'primary'}
        rows = coverage['triplets']
        self.assertEqual(len(rows), 200)
        self.assertTrue(all(row['planned_listeners'] == 10 for row in rows))
        for row in rows:
            self.assertEqual(row['completed_listeners'], 2 if row['triplet_id'] in completed_ids else 0)
        self.assertEqual(set(coverage['below_two']), {t['triplet_id'] for t in rows} - completed_ids)
        # Repeats, practice, withdrawn/replaced records remain available for audit.
        with database.get_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c4_ratings').fetchone()[0], 4 * 24 + 3)


if __name__ == '__main__':
    unittest.main()
