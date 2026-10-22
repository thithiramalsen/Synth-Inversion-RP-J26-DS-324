"""Hosted C3 rehearsal: separate tables, invitations, blinding, researcher-only skip, export."""
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
import c3_design
from c3_design import CONSENT, N_SCORED, SET_QUESTIONS

ADMIN = 'c3-test-only-persistent-secret-at-least-32-chars'
PASSWORD = 'c3-test-password-123'
BASE = '/c3/api'


class HostedC3Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(database, 'DATABASE_PATH', self.root / 'participant.db'))
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL='', SURVEY_ADMIN_TOKEN=ADMIN, SURVEY_REMOTE_MODE='1',
                                     SURVEY_C3_RESEARCHER_ONLY='0',
                                     SURVEY_RESEARCHER_USERNAME='c3tester',
                                     SURVEY_RESEARCHER_PASSWORD_HASH=security.password_hash(PASSWORD)))
        self.client = self.enterContext(TestClient(main.app))
        self.admin = {'Authorization': 'Bearer ' + ADMIN}
        self.headers = {'Authorization': 'Bearer ' + secrets.token_hex(32)}
        self.bundle = json.loads((ROOT / 'survey/deploy/study/c3_rehearsal_v2/bundle.json').read_text(encoding='utf-8'))

    # ------------------------------------------------------------------ helpers
    def start(self, code='', purpose='participant_preview', headers=None):
        return self.client.post(BASE + '/start', headers=headers or self.headers,
                                json=dict(consent=dict.fromkeys(CONSENT, True), experience='1_to_3', invitation=code, purpose=purpose))

    def state(self):
        return self.client.get(BASE + '/session', headers=self.headers).json()

    def action(self, op, answers=None):
        return self.client.post(BASE + '/action', headers=self.headers,
                                json=dict(op=op, revision=self.state()['revision'], answers=answers or {}))

    def listen(self):
        for audio in self.state()['audio_ids']:
            self.assertEqual(self.client.get(BASE + '/audio/' + audio, headers=self.headers).status_code, 200)
            for event in ('start', 'end'):
                self.assertEqual(self.client.post(BASE + '/play', headers=self.headers,
                                                  json=dict(audio_id=audio, event=event)).status_code, 200)

    def invite(self):
        response = self.client.post(BASE + '/admin/invitations', headers=self.admin, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['invitations'][0]['invitation']

    def pass_setup(self):
        self.listen()
        self.assertEqual(self.action('volume', dict(headphones=True, quiet=True, comfortable=True)).status_code, 200)
        for item in self.bundle['headphones']:
            self.listen()
            self.action('headphone', dict(interval=item['correct_interval']))
        self.assertEqual(self.state()['phase'], 'practice')

    def answers(self):
        numbers = [str(s['number']) for s in self.state()['case']['sounds']]
        return dict(closeness=dict.fromkeys(numbers, 4), **dict.fromkeys(SET_QUESTIONS, 'A'), confidence=3, reason='')

    # ------------------------------------------------------------------ tests
    def test_design_copy_equals_the_c3_source_design(self):
        sys.path.insert(0, str(ROOT / 'c3_recommendation'))
        from human_study import design as original
        for name in ('VERSION', 'SEED', 'TARGET', 'CAP', 'N_SCORED', 'CLOSENESS', 'MAX_SCREEN_ATTEMPTS',
                     'SET_CHOICES', 'SET_QUESTIONS', 'CONSENT', 'OPERATING_POINT'):
            self.assertEqual(getattr(c3_design, name), getattr(original, name), name)
        self.assertEqual([c3_design.assignment(i) for i in range(12)], [original.assignment(i) for i in range(12)])

    def test_pages_status_and_research_disabled(self):
        page = self.client.get('/c3/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('PARTICIPANT PREVIEW', page.text)
        self.assertEqual(self.client.get('/c3/admin').status_code, 200)
        self.assertEqual(self.client.get('/c3/?view=researcher').status_code, 401)
        info = self.client.get(BASE + '/info').json()
        self.assertFalse(info['research_collection_enabled'])
        self.assertEqual(info['version'], 'c3-human-v2')
        self.assertEqual(self.client.get('/c3/assets/../bundle.json').status_code, 404)

    def test_invitation_required_single_use_and_admin_protected(self):
        self.assertEqual(self.start().status_code, 403)
        self.assertEqual(self.client.post(BASE + '/admin/invitations', json={}).status_code, 401)
        code = self.invite()
        self.assertTrue(code.startswith('C3-PREVIEW-'))
        self.assertEqual(self.start(code).status_code, 200)
        other = {'Authorization': 'Bearer ' + secrets.token_hex(32)}
        self.assertEqual(self.start(code, headers=other).status_code, 403)
        summary = self.client.get(BASE + '/admin/summary', headers=self.admin).json()
        self.assertEqual(len(summary['invitations']), 12)
        self.assertTrue(summary['invitations'][0]['used'])

    def test_full_participant_run_blinded_and_exported_without_secrets(self):
        self.start(self.invite())
        self.assertEqual(self.action('skip_screen').status_code, 403)  # participants can never skip
        self.pass_setup()
        self.listen()
        self.action('response', self.answers())
        self.action('continue')
        for i in range(N_SCORED):
            if i == N_SCORED // 2:
                self.action('continue')
            encoded = json.dumps(self.state()['case'])
            for secret in ('mmr', 'topk', 'restricted_bend_sustain', 'relevance', 'audio_rank'):
                self.assertNotIn(secret, encoded)
            self.listen()
            self.assertEqual(self.action('response', self.answers()).status_code, 200)
        self.assertEqual(self.action('finish', dict(knob_bars=4, length='about_right', comment='')).status_code, 200)
        export = self.client.get(BASE + '/admin/export', headers=self.admin)
        self.assertEqual(export.status_code, 200)
        body = export.json()
        self.assertEqual(body['completed_rehearsal_runs'], 1)
        text = export.text
        for secret in ('C3-PREVIEW-', 'token', 'restricted_bend_sustain', 'correct_interval'):
            self.assertNotIn(secret, text)
        record = body['records'][0]
        self.assertFalse(record['analysis_include'])
        self.assertEqual(len(record['responses']), N_SCORED)
        self.assertIn('membership', record['responses'][0])

    def test_researcher_self_review_can_skip_and_is_owned(self):
        self.assertEqual(self.start(purpose='researcher_self_review').status_code, 401)
        login = self.client.post('/api/researcher/login', json=dict(username='c3tester', password=PASSWORD))
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(self.client.get('/c3/?view=researcher').status_code, 200)
        started = self.start(purpose='researcher_self_review')
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(started.json()['demo'])
        self.assertEqual(self.action('skip_screen').status_code, 200)
        self.assertEqual(self.state()['phase'], 'practice')
        summary = self.client.get(BASE + '/admin/summary').json()
        self.assertTrue(summary['sessions'][0]['screen_skipped'])
        self.client.post('/api/researcher/logout')
        self.assertEqual(self.client.get(BASE + '/session', headers=self.headers).status_code, 403)

    def test_c3_writes_only_to_its_own_tables(self):
        def counts():
            with database.get_connection() as db:
                names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                return {n: db.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
        code = self.invite()
        before = counts()
        self.assertEqual(self.start(code).status_code, 200)
        self.pass_setup()
        after = counts()
        self.assertTrue({'c3_v2_metadata', 'c3_v2_sessions', 'c3_v2_invites'} <= set(after))
        changed = {n for n in after if after[n] != before.get(n)}
        self.assertEqual(changed, {'c3_v2_sessions'})  # the shared/C1/C2/C4 tables are untouched


if __name__ == '__main__':
    unittest.main()
