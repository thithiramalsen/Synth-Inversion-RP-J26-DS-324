"""Removing the screen must preserve older responses and setup evidence."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import c1_protocol
import c4_protocol
from listening_setup import retire_participant_screen, session_screening_enabled, REMOVAL_POLICY


class ListeningSetupTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, 'DATABASE_PATH', Path(temp) / 'setup.db'))
        self.enterContext(patch.dict(os.environ, SURVEY_DATABASE_URL=''))
        with database.get_connection() as db:
            for table in ('c1_sessions', 'c4_sessions'):
                db.execute(f'''CREATE TABLE {table} (session_id TEXT PRIMARY KEY,study_id TEXT,phase TEXT,
                    entry_json TEXT,protocol_snapshot TEXT,protocol_hash TEXT,screen_order TEXT,
                    screen_answers TEXT,trial_order TEXT)''')

    def insert(self, study, protocol, phase, *, participant=True):
        snapshot = json.dumps(dict(study_id=protocol.PARTICIPANT_STUDY_ID, collection_mode='participants',
            protocol_version=protocol.PARTICIPANT_PROTOCOL_VERSIONS[0]))
        with database.get_connection() as db:
            db.execute(f'INSERT INTO {study.lower()}_sessions VALUES (?,?,?,?,?,?,?,?,?)',
                (phase, protocol.PARTICIPANT_STUDY_ID if participant else 'historical_review', phase,
                 json.dumps(dict(tools='Existing experience')), snapshot, hashlib.sha256(snapshot.encode()).hexdigest(),
                 json.dumps([f'headphones_{i}' for i in range(6)]),
                 json.dumps([dict(screen_id='headphones_0', interval=2, correct=False)]),
                 json.dumps([dict(kind='practice', presentation_id='p_01')])) )
        return self.row(study, phase)

    def row(self, study, sid):
        with database.get_connection() as db:
            return db.execute(f'SELECT * FROM {study.lower()}_sessions WHERE session_id=?', (sid,)).fetchone()

    def test_unfinished_participant_setup_is_retired_once_without_rewriting_evidence(self):
        for study, protocol in (('C1', c1_protocol), ('C4', c4_protocol)):
            for phase in ('headphones', 'volume'):
                before = self.insert(study, protocol, phase)
                self.assertTrue(retire_participant_screen(before, protocol.PARTICIPANT_STUDY_ID, study))
                after = self.row(study, phase)
                self.assertEqual(after['phase'], 'rating' if phase == 'headphones' else 'volume')
                for key in ('protocol_snapshot', 'protocol_hash', 'screen_order', 'screen_answers', 'trial_order'):
                    self.assertEqual(after[key], before[key])
                audit = json.loads(after['entry_json'])['headphone_screening_change']
                self.assertEqual(audit['policy'], REMOVAL_POLICY)
                self.assertEqual(audit['previous_phase'], phase)
                self.assertEqual(audit['answered_questions'], 1)
                self.assertFalse(session_screening_enabled(after))
                self.assertFalse(retire_participant_screen(after, protocol.PARTICIPANT_STUDY_ID, study))
                self.assertEqual(dict(self.row(study, phase)), dict(after))

    def test_finished_failed_withdrawn_and_review_sessions_are_not_reopened(self):
        for study, protocol in (('C1', c1_protocol), ('C4', c4_protocol)):
            for phase in ('complete', 'screen_failed', 'withdrawn', 'replaced', 'rating'):
                before = self.insert(study, protocol, phase)
                self.assertFalse(retire_participant_screen(before, protocol.PARTICIPANT_STUDY_ID, study))
                self.assertEqual(dict(self.row(study, phase)), dict(before))
            review = self.insert(study, protocol, 'headphones', participant=False)
            self.assertFalse(retire_participant_screen(review, protocol.PARTICIPANT_STUDY_ID, study))

    def test_both_participant_protocol_generations_keep_export_eligibility(self):
        for protocol in (c1_protocol, c4_protocol):
            for version in protocol.PARTICIPANT_PROTOCOL_VERSIONS:
                row = dict(study_id=protocol.PARTICIPANT_STUDY_ID, phase='complete', completed_at='2026-10-19',
                    withdrawn_at=None, kind='primary', protocol_snapshot=json.dumps(dict(
                        study_id=protocol.PARTICIPANT_STUDY_ID, collection_mode='participants', protocol_version=version)))
                self.assertTrue(protocol.analysis_include(row), version)
                self.assertFalse(protocol.analysis_include(dict(row, withdrawn_at='2026-10-19')), version)
                self.assertFalse(protocol.analysis_include(dict(row, kind='practice')), version)


if __name__ == '__main__':
    unittest.main()
