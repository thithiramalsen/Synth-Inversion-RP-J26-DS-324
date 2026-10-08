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

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))
import database
import main
from survey.design import assignments

ADMIN = "test-only-admin-token-with-32-characters-minimum"


class C1PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_database = database.DATABASE_PATH
        database.DATABASE_PATH = self.root / "test.db"
        path = self.root / "audio/test.wav"
        path.parent.mkdir()
        # A byte fixture for authenticated media delivery, not a scientific stimulus.
        path.write_bytes(b"RIFF-test-fixture-only")
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        ids = [f"s_{i:03d}" for i in range(64)]
        blocks = assignments(ids)
        for b in blocks:
            b["trials"] = [dict(presentation_id=f"practice_{i}", sample_id=ids[i], kind="practice", repeat_of=None) for i in range(3)] + b["trials"]
        self.bundle = dict(study_id="c1_pilot_v1", rehearsal=False, assignments=blocks,
            samples={s: dict(playback_path="audio/test.wav", playback_sha256=checksum) for s in ids},
            headphones=[dict(screen_id=f"headphones_{i}", correct_interval=(i%3)+1, path="test.wav", sha256=checksum) for i in range(6)],
            calibration=dict(path="test.wav", sha256=checksum))
        self.bundle_path = self.root / "bundle.json"
        self.bundle_path.write_text(json.dumps(self.bundle))
        cfg = json.loads((ROOT / "survey/config/c1_pilot_v1.json").read_text())
        cfg.update(researcher_name="Test researcher", researcher_email="test@example.invalid",
                   supervisor_contact="Test supervisor", retention_statement="Test policy",
                   institutional_review_status="reviewed_clearance_not_required",
                   level_policy_listening_checked=True, rehearsal_completed=True)
        cfg["eligibility"]["supervisor_confirmed"] = True
        self.config_path = self.root / "protocol.json"
        self.config_path.write_text(json.dumps(cfg))
        self.env = patch.dict(os.environ, {"SURVEY_C1_BUNDLE":str(self.bundle_path), "SURVEY_C1_CONFIG":str(self.config_path),
                                          "SURVEY_ADMIN_TOKEN":ADMIN,"SURVEY_C1_OPEN":"1"})
        self.env.start()
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.admin = {"Authorization": f"Bearer {ADMIN}"}

    def tearDown(self):
        self.client_context.__exit__(None,None,None)
        self.env.stop()
        database.DATABASE_PATH = self.previous_database
        self.temp.cleanup()

    def entry(self, invitation):
        return dict(invitation=invitation,adult=True,consent=True,headphones=True,quiet_environment=True,
            understands_language=True,activities=["Sound design"],experience_months=12,recent_frequency="Weekly",
            tools="Test synth",example="I created a collection of synthesizer patches for a game.")

    def start(self):
        issued = self.client.post('/api/c1-pilot/admin/invitations',headers=self.admin,json={})
        self.assertEqual(issued.status_code,200,issued.text)
        invitation = issued.json()["invitations"][0]["invitation"]
        result = self.client.post('/api/c1-pilot/sessions',json=self.entry(invitation))
        self.assertEqual(result.status_code,200,result.text)
        self.session = result.json()
        self.base = f"/api/c1-pilot/sessions/{self.session['session_id']}"
        self.headers = {"Authorization":f"Bearer {self.session['token']}"}
        return invitation

    def state(self):
        result=self.client.get(self.base,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def setup_audio(self, pass_screen=True):
        self.assertEqual(self.client.post(self.base+'/volume',headers=self.headers,json={"completed_plays":1}).status_code,200)
        for _ in range(6):
            current=self.state()
            source=next(s for s in self.bundle["headphones"] if s["screen_id"]==current["audio_id"])
            interval=source["correct_interval"] if pass_screen else source["correct_interval"]%3+1
            result=self.client.post(self.base+'/headphones',headers=self.headers,
                json=dict(screen_number=current["screen_number"],interval=interval,completed_plays=1))
            self.assertEqual(result.status_code,200,result.text)

    def rating_body(self,current):
        return dict(presentation_id=current["presentation_id"],play_count=1,completed_plays=1,
                    started_at=current['server_time'],answers=dict(brightness=4,roughness="unclear",percussiveness=2,comment="=test"))

    def test_complete_balanced_session_repeats_exports_and_withdrawal(self):
        self.start(); self.setup_audio()
        presentations=[]
        while self.state()["phase"] in ("rating","break"):
            current=self.state()
            if current["phase"]=="break":
                self.client.post(self.base+'/continue',headers=self.headers,json={})
                continue
            presentations.append(current["presentation_id"])
            self.client.post(f"{self.base}/playback/{current['presentation_id']}", headers=self.headers)
            body=self.rating_body(current)
            result=self.client.post(self.base+'/ratings',headers=self.headers,json=body)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(self.client.post(self.base+'/ratings',headers=self.headers,json=body).status_code,409)
        self.assertEqual(len(presentations),39)
        self.assertEqual(len(set(presentations)),39)
        self.assertEqual(self.state()["phase"],"feedback")
        self.client.post(self.base+'/feedback',headers=self.headers,json=dict(clarity="Clear",length="About right",comment=""))
        export=self.client.get('/api/c1-pilot/admin/export',headers=self.admin)
        rows=list(csv.DictReader(io.StringIO(export.text)))
        self.assertEqual(len(rows),39)
        self.assertEqual(sum(r['kind']=='repeat' for r in rows),4)
        self.assertEqual(sum(r['analysis_include']=='True' for r in rows),36)
        self.assertTrue(all(r['roughness']=='unclear' for r in rows))
        self.assertTrue(all(r['comment']=="'=test" for r in rows))
        self.assertTrue(all(r['bundle_hash'] and r['protocol_hash'] for r in rows))
        self.assertEqual(self.client.post('/api/c1-pilot/admin/replace-invitation',headers=self.admin,
            json=dict(assignment_id='block_01',reason='Should not replace a completed block')).status_code,409)
        self.client.post(self.base+'/withdraw',headers=self.headers,json={})
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export',headers=self.admin).text)))
        self.assertTrue(all(r['analysis_include']=='False' for r in rows))

    def test_authentication_invitation_reuse_and_no_screen_bypass(self):
        for path in ('/api/admin/export','/api/admin/summary','/api/c1-pilot/admin/export','/api/c1-pilot/admin/summary'):
            self.assertEqual(self.client.get(path).status_code,401)
        invitation=self.start()
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.assertEqual(self.client.post('/api/c1-pilot/sessions',json=self.entry(invitation)).status_code,409)
        body=dict(presentation_id='practice_0',play_count=1,completed_plays=1,
                  started_at='2026-01-01T00:00:00Z',answers=dict(brightness=4,roughness=4,percussiveness=4))
        self.assertEqual(self.client.post(self.base+'/ratings',headers=self.headers,json=body).status_code,409)
        self.setup_audio(pass_screen=False)
        self.assertEqual(self.state()['phase'],'screen_failed')
        self.assertEqual(self.client.post(self.base+'/ratings',headers=self.headers,json=body).status_code,409)

    def test_changed_bundle_rejected_protocol_snapshotted_and_audio_verified(self):
        self.start()
        cfg=json.loads(self.config_path.read_text()); cfg['title']='Changed title'; self.config_path.write_text(json.dumps(cfg))
        self.assertNotEqual(self.state()['config']['title'],'Changed title')
        result=self.client.get(self.base+'/audio/volume_reference',headers=self.headers)
        self.assertEqual(result.status_code,200)
        (self.root/'audio/test.wav').write_bytes(b'changed')
        self.assertEqual(self.client.get(self.base+'/audio/volume_reference',headers=self.headers).status_code,409)
        self.bundle_path.write_text(self.bundle_path.read_text()+' ')
        self.assertEqual(self.client.get(self.base,headers=self.headers).status_code,409)

    def test_replacement_preserves_data_and_closes_previous_session(self):
        self.start(); self.setup_audio()
        current = self.state()
        self.client.post(f"{self.base}/playback/{current['presentation_id']}", headers=self.headers)
        self.client.post(self.base+'/ratings',headers=self.headers,json=self.rating_body(current))
        replacement=self.client.post('/api/c1-pilot/admin/replace-invitation',headers=self.admin,
                                    json=dict(assignment_id='block_01',reason='Test participant cannot finish the session'))
        self.assertEqual(replacement.status_code,200,replacement.text)
        self.assertEqual(self.state()['phase'],'replaced')
        fresh=self.client.post('/api/c1-pilot/sessions',json=self.entry(replacement.json()['invitation']))
        self.assertEqual(fresh.status_code,200)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export',headers=self.admin).text)))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['analysis_include'],'False')

    def test_launch_gate_and_invalid_ratings(self):
        with patch.dict(os.environ,{'SURVEY_C1_OPEN':'0'}):
            self.assertFalse(self.client.get('/api/c1-pilot/status').json()['ready'])
            self.assertEqual(self.client.post('/api/c1-pilot/sessions',json=self.entry('madeupcode')).status_code,403)
        self.start(); self.setup_audio()
        for invalid in (0,8,True,3.5):
            body=self.rating_body(self.state());body['answers']['brightness']=invalid
            self.assertEqual(self.client.post(self.base+'/ratings',headers=self.headers,json=body).status_code,422)
        body=self.rating_body(self.state());body['completed_plays']=0
        self.assertEqual(self.client.post(self.base+'/ratings',headers=self.headers,json=body).status_code,422)

    def test_limited_previous_correction_keeps_original_and_allows_authenticated_playback(self):
        self.start(); self.setup_audio()
        first = self.state()
        self.assertEqual(self.client.post(
            f"{self.base}/playback/{first['presentation_id']}", headers=self.headers
        ).status_code, 200)
        self.assertEqual(self.client.post(
            self.base + '/ratings', headers=self.headers, json=self.rating_body(first)
        ).status_code, 200)
        current = self.state()
        self.assertTrue(current['can_correct_previous'])
        self.assertEqual(self.client.post(
            self.base + '/previous', headers=self.headers,
            json={'current_index': current['current_index']}
        ).status_code, 200)
        correction = self.state()
        self.assertEqual(correction['phase'], 'correction')
        self.assertEqual(correction['saved_answers']['brightness'], 4)
        self.assertEqual(self.client.post(
            f"{self.base}/playback/{correction['presentation_id']}", headers=self.headers
        ).status_code, 200)
        revised = self.rating_body(correction)
        revised['answers']['brightness'] = 7
        revised['correction_token'] = correction['correction_token']
        self.assertEqual(self.client.post(
            self.base + '/previous/save', headers=self.headers, json=revised
        ).status_code, 200)
        self.assertEqual(self.state()['phase'], 'rating')
        with database.get_connection() as db:
            original = db.execute(
                'SELECT answers_json FROM c1_ratings WHERE presentation_id=?',
                (first['presentation_id'],)
            ).fetchone()
            audit = db.execute(
                'SELECT answers_json FROM c1_rating_corrections WHERE presentation_id=?',
                (first['presentation_id'],)
            ).fetchone()
        self.assertEqual(json.loads(original['answers_json'])['brightness'], 4)
        self.assertEqual(json.loads(audit['answers_json'])['brightness'], 7)
        exported = list(csv.DictReader(io.StringIO(self.client.get(
            '/api/c1-pilot/admin/export', headers=self.admin).text)))
        self.assertEqual(exported[0]['brightness_first'], '4')
        self.assertEqual(exported[0]['brightness'], '7')
        self.assertEqual(exported[0]['revision_count'], '1')

    def test_previous_locks_only_on_explicit_start_and_stays_locked_after_reload(self):
        self.start(); self.setup_audio()
        first = self.state()
        self.client.post(f"{self.base}/playback/{first['presentation_id']}", headers=self.headers)
        self.client.post(self.base+'/ratings', headers=self.headers, json=self.rating_body(first))
        current = self.state()
        path = f"{self.base}/playback/{current['presentation_id']}"
        # A read/prefetch must not release the next sound or mutate exposure state.
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 405)
        self.assertEqual(self.client.get(self.base+'/audio/'+current['audio_id'], headers=self.headers).status_code, 403)
        self.assertTrue(self.state()['can_correct_previous'])
        self.assertEqual(self.client.post(path, headers=self.headers).status_code, 200)
        for _ in range(2):
            self.assertFalse(self.state()['can_correct_previous'])
        self.assertEqual(self.client.post(self.base+'/previous', headers=self.headers,
            json={'current_index':current['current_index']}).status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/playback/{first['presentation_id']}", headers=self.headers).status_code, 409)

    def test_correction_survives_reload_blocks_next_sound_and_can_save_without_replay(self):
        self.start(); self.setup_audio()
        first = self.state()
        self.client.post(f"{self.base}/playback/{first['presentation_id']}", headers=self.headers)
        self.client.post(self.base+'/ratings', headers=self.headers, json=self.rating_body(first))
        current = self.state()
        self.client.post(self.base+'/previous', headers=self.headers, json={'current_index':current['current_index']})
        draft = self.state()
        self.assertEqual(draft['phase'], 'correction')
        self.assertEqual(self.state()['correction_token'], draft['correction_token'])
        self.assertEqual(self.client.post(f"{self.base}/playback/{current['presentation_id']}", headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(self.base+'/ratings', headers=self.headers, json=self.rating_body(current)).status_code, 409)
        revised = self.rating_body(draft)
        revised.update(correction_token=draft['correction_token'], play_count=0, completed_plays=0)
        revised['answers']['brightness'] = 6
        self.assertEqual(self.client.post(self.base+'/previous/save', headers=self.headers, json=revised).status_code, 200)
        self.assertEqual(self.client.post(self.base+'/previous/save', headers=self.headers, json=revised).status_code, 409)
        self.client.post(self.base+'/previous', headers=self.headers, json={'current_index':current['current_index']})
        reopened = self.state()
        self.assertEqual(reopened['saved_answers']['brightness'], 6)
        self.assertEqual(self.client.post(self.base+'/previous/cancel', headers=self.headers,
            json={'correction_token':reopened['correction_token']}).status_code, 200)
        self.assertEqual(self.state()['phase'], 'rating')
        self.assertTrue(self.state()['can_correct_previous'])

    def test_old_protocol_retains_its_original_audio_route(self):
        cfg = json.loads(self.config_path.read_text())
        cfg.pop('navigation_policy')
        self.config_path.write_text(json.dumps(cfg))
        self.start(); self.setup_audio()
        current = self.state()
        self.assertEqual(self.client.get(self.base+'/audio/'+current['audio_id'], headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post(self.base+'/ratings', headers=self.headers, json=self.rating_body(current)).status_code, 200)
        self.assertFalse(self.state()['can_correct_previous'])

    def test_session_audit_includes_failed_screens_and_remote_routes_are_closed(self):
        self.start(); self.setup_audio(pass_screen=False)
        self.assertEqual(self.client.get('/api/c1-pilot/admin/sessions').status_code,401)
        export=self.client.get('/api/c1-pilot/admin/sessions',headers=self.admin)
        rows=list(csv.DictReader(io.StringIO(export.text)))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['phase'],'screen_failed')
        self.assertNotIn('token_hash',rows[0])
        self.assertIn('protocol_snapshot',rows[0])
        with patch.object(main,'REMOTE_MODE',True):
            self.assertEqual(self.client.get('/api/studies').status_code,404)
            self.assertEqual(self.client.get('/api/admin/export',headers=self.admin).status_code,404)
            self.assertEqual(self.client.get('/api/c1-pilot/status').status_code,200)


    def test_rehearsal_cannot_masquerade_as_production(self):
        self.bundle['rehearsal']=True
        self.bundle_path.write_text(json.dumps(self.bundle))
        status=self.client.get('/api/c1-pilot/status').json()
        self.assertFalse(status['ready'])
        self.assertIn('must be distinct',status['issues'][0])
        self.bundle['study_id']='c1_full_rehearsal_v1'
        self.bundle_path.write_text(json.dumps(self.bundle))
        self.assertTrue(self.client.get('/api/c1-pilot/status').json()['ready'])

    def test_friendly_labels_are_stable_and_migration_keeps_existing_responses(self):
        import c1_pilot
        self.start(); self.setup_audio()
        current=self.state()
        self.assertEqual(current['participant_label'],'Listener 001')
        original_id=current['participant_id']
        self.client.post(f"{self.base}/playback/{current['presentation_id']}", headers=self.headers)
        self.client.post(self.base+'/ratings',headers=self.headers,json=self.rating_body(current))
        with database.get_connection() as db:
            original_rating=tuple(db.execute('SELECT * FROM c1_ratings').fetchone())
            # Emulate a pre-label database in this isolated temporary fixture.
            db.execute('DROP TABLE c1_listener_labels')
        c1_pilot.initialize_pilot_database()
        c1_pilot.initialize_pilot_database()
        self.assertEqual(self.state()['participant_label'],'Listener 001')
        self.assertEqual(self.state()['participant_id'],original_id)
        self.assertEqual(self.state()['saved_presentations'],1)
        with database.get_connection() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM c1_ratings').fetchone()),original_rating)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM c1_listener_labels').fetchone()[0],1)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/export',headers=self.admin).text)))
        self.assertEqual(rows[0]['participant_label'],'Listener 001')
        sessions=list(csv.DictReader(io.StringIO(self.client.get('/api/c1-pilot/admin/sessions',headers=self.admin).text)))
        self.assertEqual(sessions[0]['participant_label'],'Listener 001')
        # A display label is not a credential and grants no access to responses.
        self.assertEqual(self.client.get('/api/c1-pilot/sessions/Listener%20001').status_code,401)


class AssignmentTests(unittest.TestCase):
    def test_equal_coverage_repeat_separation_and_determinism(self):
        from collections import Counter
        ids=[f's{i}' for i in range(64)]
        blocks=assignments(ids)
        self.assertEqual(blocks,assignments(ids))
        coverage=Counter()
        for block in blocks:
            trials=block['trials']
            unique=[t['sample_id'] for t in trials if t['kind']=='primary']
            self.assertEqual(len(set(unique)),32)
            coverage.update(unique)
            for index,t in enumerate(trials):
                if t['kind']=='repeat':
                    original=next(j for j,s in enumerate(trials) if s['presentation_id']==t['repeat_of'])
                    self.assertGreaterEqual(index-original,8)
                    self.assertEqual(trials[original]['sample_id'],t['sample_id'])
        self.assertEqual(set(coverage.values()),{8})


if __name__=='__main__':
    unittest.main()
