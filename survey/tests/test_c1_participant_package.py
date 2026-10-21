import hashlib
import json
from pathlib import Path
import unittest

from survey.deploy.build_c1_participants import build, prepare

ROOT = Path(__file__).resolve().parents[2]


class C1ParticipantPackageTests(unittest.TestCase):
    def test_frozen_participant_package_keeps_audio_and_balanced_assignments(self):
        source_path = ROOT/'survey/deploy/study/bundle.json'
        source = json.loads(source_path.read_bytes())
        digest = hashlib.sha256(source_path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        result = build(source, digest)
        self.assertEqual(result, build(source, digest))
        stored = json.loads((source_path.parent/'c1_participant_bundle_v1.json').read_text(encoding='utf-8'))
        self.assertEqual(result, stored)
        self.assertTrue(source['rehearsal'])
        self.assertFalse(result['rehearsal'])
        self.assertEqual(source['samples'], result['samples'])
        for number, (old, new) in enumerate(zip(source['assignments'], result['assignments']), 1):
            self.assertEqual(new['assignment_id'], f'c1_participant_{number:02d}')
            self.assertEqual(old['trials'], new['trials'])
        self.assertFalse(prepare(check_only=True)['audio_rendered'])

    def test_only_the_frozen_review_is_a_valid_source(self):
        for source in ({}, dict(study_id='c1_20_review_v1', rehearsal=False)):
            with self.assertRaises(ValueError):
                build(source, 'test-hash')
