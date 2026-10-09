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

    def start(self, number=0):
        codes = self.client.post('/api/c4-pilot/admin/invitations', headers=self.admin, json={}).json()['invitations']
        entry = dict(invitation=codes[number]['invitation'], adult=True, consent=True, headphones=True,
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
