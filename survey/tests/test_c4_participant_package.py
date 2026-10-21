"""Participant packaging preserves the existing real triplet bank and review data."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from survey.deploy import build_c4_participants as participant_builder
from survey.deploy.build_c4_participants import build, prepare, bundle_digest

ROOT = Path(__file__).resolve().parents[2]


class C4ParticipantPackageTests(unittest.TestCase):
    def test_packaged_version_preserves_audio_assignments_and_review_identity(self):
        path = ROOT / 'survey/deploy/study/c4_clap_bundle.json'
        payload = path.read_bytes()
        source = json.loads(payload)
        source_hash = bundle_digest(payload)
        result = build(source, source_hash)
        self.assertEqual(result, build(source, source_hash))
        self.assertTrue(source['rehearsal'])
        self.assertEqual(source['study_id'], 'c4_clap_review_v1')
        self.assertFalse(result['rehearsal'])
        self.assertEqual(result['study_id'], 'c4_clap_participants_v1')
        self.assertEqual(result['samples'], source['samples'])
        self.assertEqual(result['canonical_triplets'], source['canonical_triplets'])
        self.assertEqual(result['design'], source['design'])
        for number, (old, new) in enumerate(zip(source['assignments'], result['assignments']), 1):
            self.assertEqual(new['assignment_id'], f'c4_participant_{number:03d}')
            self.assertNotEqual(new['assignment_id'], old['assignment_id'])
            self.assertEqual(new['trials'], old['trials'])
            self.assertEqual(len(new['trials']), 24)
        stored = json.loads((path.parent / 'c4_participant_bundle_v1.json').read_text(encoding='utf-8'))
        self.assertEqual(stored, result)
        self.assertEqual(stored['source_review_bundle_sha256'], source_hash)
        self.assertEqual(stored['source_review_bundle_hash_format'], 'lf_utf8')

    def test_source_digest_matches_git_lf_bytes_on_both_platforms(self):
        lf = b'{\n  "study_id": "c4_clap_review_v1"\n}\n'
        self.assertEqual(bundle_digest(lf), hashlib.sha256(lf).hexdigest())
        self.assertEqual(bundle_digest(lf.replace(b'\n', b'\r\n')), bundle_digest(lf))

    def test_refuses_source_that_is_not_the_frozen_clap_review(self):
        for source in ({}, dict(study_id='c4_clap_review_v1', rehearsal=False),
                       dict(study_id='c4_review_v1', rehearsal=True)):
            with self.assertRaisesRegex(ValueError, 'frozen C4 CLAP review'):
                build(source, 'fixture-hash')

    def test_prepare_restores_missing_local_playback_from_tracked_frozen_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'bank').mkdir()
            (root / 'deployment/audio').mkdir(parents=True)
            clip = b'RIFF frozen source fixture'
            digest = hashlib.sha256(clip).hexdigest()
            (root / 'bank/a.wav').write_bytes(clip)
            (root / 'deployment/audio/volume.wav').write_bytes(clip)
            source = dict(study_id='c4_clap_review_v1', rehearsal=True,
                assignments=[dict(assignment_id='review_001', trials=[])],
                samples={'a': dict(playback_path='clap_audio/a.wav', source_playback_path='bank/a.wav', playback_sha256=digest)},
                headphones=[], calibration=dict(path='volume.wav', sha256=digest))
            source_path = root / 'deployment/review.json'
            source_path.write_text(json.dumps(source), encoding='utf-8')
            original = source_path.read_bytes()
            output = source_path.with_name('participant.json')
            with patch.object(participant_builder, 'ROOT', root):
                result = prepare(source_path, output)
            self.assertTrue(result['output_written'])
            self.assertEqual((root / 'deployment/clap_audio/a.wav').read_bytes(), clip)
            self.assertEqual(source_path.read_bytes(), original)
            self.assertFalse(json.loads(output.read_text())['rehearsal'])
