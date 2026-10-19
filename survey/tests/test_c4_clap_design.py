"""Coverage, canonical identities and immutable playback for the C4 CLAP design."""
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from survey.deploy.build_c4_clap import build, build_from_files, main, materialize, sha256


def fixture():
    digest = hashlib.sha256(b'fixture-playback').hexdigest()
    practice = ['practice_1', 'practice_2', 'practice_3']
    source = dict(assignments=[dict(trials=[dict(kind='practice', reference=practice[0],
                    candidate_a=practice[1], candidate_b=practice[2])])],
                  samples={sid: dict(playback_path=f'audio/{sid}.wav', playback_sha256=digest)
                           for sid in practice},
                  headphones=[dict(screen_id='headphones_01', path='headphones_01.wav', sha256=digest)],
                  calibration=dict(path='volume.wav', sha256=digest))
    bank = []
    for i in range(200):
        row = dict(triplet_id=f'Q{i + 1:03d}', clap_similarity_a='0.8', clap_similarity_b='0.6',
                   selection_method='CLAP near-band versus moderately-near-band; both sampled without replacement',
                   candidate_parameter_distance_a='0.1', candidate_parameter_distance_b='0.2',
                   clap_nearer_sample_id=f'study_{3 * i + 1:03d}')
        for j, role in enumerate(('reference', 'candidate_a', 'candidate_b')):
            sid = f'study_{3 * i + j:03d}'
            row.update({f'{role}_sample_id': sid, f'{role}_playback_path': f'bank_audio/{sid}.wav',
                        f'{role}_playback_sha256': digest, f'{role}_raw_audio_path': f'raw/{sid}.wav'})
        bank.append(row)
    return source, bank


class C4ClapDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.bank = fixture()
        cls.bundle = build(cls.source, cls.bank)

    def test_determinism_source_preservation_and_new_review_identity(self):
        original_source, original_bank = copy.deepcopy(self.source), copy.deepcopy(self.bank)
        self.assertEqual(self.bundle, build(self.source, self.bank))
        self.assertEqual(self.source, original_source)
        self.assertEqual(self.bank, original_bank)
        self.assertEqual(self.bundle['study_id'], 'c4_clap_review_v1')
        self.assertTrue(self.bundle['rehearsal'])
        self.assertEqual(len(self.bundle['samples']), 603)

    def test_each_ten_assignment_round_covers_bank_and_50_100_replicate(self):
        assignments = self.bundle['assignments']
        self.assertEqual(len(assignments), 100)
        for start in range(0, 100, 10):
            counts = Counter(t['triplet_id'] for a in assignments[start:start + 10]
                             for t in a['trials'] if t['kind'] == 'primary')
            self.assertEqual(len(counts), 200)
            self.assertEqual(set(counts.values()), {1})
        for n in (50, 100):
            counts = Counter(t['triplet_id'] for a in assignments[:n]
                             for t in a['trials'] if t['kind'] == 'primary')
            self.assertEqual(set(counts.values()), {n // 10})

    def test_twenty_unique_primary_triplets_and_different_sets(self):
        question_sets = set()
        practice = {'practice_1', 'practice_2', 'practice_3'}
        for assignment in self.bundle['assignments']:
            trials = assignment['trials']
            self.assertEqual(Counter(t['kind'] for t in trials), {'practice': 2, 'primary': 20, 'repeat': 2})
            primary = [t for t in trials if t['kind'] == 'primary']
            question_sets.add(tuple(sorted(t['triplet_id'] for t in primary)))
            sounds = [t[r] for t in primary for r in ('reference', 'candidate_a', 'candidate_b')]
            self.assertEqual(len(set(sounds)), 60)
            self.assertFalse(set(sounds) & practice)
            for t in trials[:2]:
                self.assertEqual({t[r] for r in ('reference', 'candidate_a', 'candidate_b')}, practice)
        self.assertEqual(len(question_sets), 100)

    def test_candidate_scores_follow_ids_and_balance_across_rounds(self):
        bank = {t['triplet_id']: t for t in self.bank}
        side_counts = {50: Counter(), 100: Counter()}
        for assignment_index, assignment in enumerate(self.bundle['assignments']):
            for t in assignment['trials']:
                if t['kind'] == 'practice':
                    continue
                original = bank[t['triplet_id']]
                expected_scores = {original['candidate_a_sample_id']: (.8, .1),
                                   original['candidate_b_sample_id']: (.6, .2)}
                for role in ('a', 'b'):
                    self.assertEqual(t['clap_similarity_' + role], expected_scores[t['candidate_' + role]][0])
                    self.assertEqual(t['candidate_parameter_distance_' + role], expected_scores[t['candidate_' + role]][1])
                if t['kind'] == 'primary':
                    for n in (50, 100):
                        if assignment_index < n:
                            side_counts[n][(t['triplet_id'], t['candidate_a'])] += 1
        self.assertEqual(set(side_counts[100].values()), {5})
        self.assertEqual(set(side_counts[50].values()), {2, 3})

    def test_repeat_links_reverse_sides_with_six_intervening_positions(self):
        for assignment in self.bundle['assignments']:
            trials = assignment['trials']
            positions = {t['presentation_id']: i for i, t in enumerate(trials)}
            for i, t in enumerate(trials):
                if t['kind'] != 'repeat':
                    continue
                previous_index = positions[t['repeat_of']]
                previous = trials[previous_index]
                self.assertEqual(previous['kind'], 'primary')
                self.assertGreaterEqual(i - previous_index - 1, 6)
                self.assertEqual(t['triplet_id'], previous['triplet_id'])
                self.assertEqual(t['reference'], previous['reference'])
                self.assertEqual(t['candidate_a'], previous['candidate_b'])
                self.assertEqual(t['candidate_b'], previous['candidate_a'])

    def test_reject_duplicate_sound_or_bad_hash(self):
        bad = copy.deepcopy(self.bank)
        bad[1]['reference_sample_id'] = bad[0]['reference_sample_id']
        with self.assertRaisesRegex(ValueError, 'globally distinct'):
            build(self.source, bad)
        bad = copy.deepcopy(self.bank)
        bad[0]['reference_playback_sha256'] = 'bad'
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            build(self.source, bad)


class C4ClapArtifactTests(unittest.TestCase):
    def test_cli_never_discovers_or_probes_a_local_corpus_implicitly(self):
        # The same default package must result on a fresh clone and a corpus PC.
        # Only an explicit audit option may introduce host-local manifest bytes.
        for explicit in (False, True):
            with self.subTest(explicit_manifest=explicit):
                argv = ['build_c4_clap', '--check']
                if explicit:
                    argv += ['--corpus-manifest', 'explicit-audit.csv']
                with patch.object(sys, 'argv', argv), \
                     patch('survey.deploy.build_c4_clap.Path.exists',
                           side_effect=AssertionError('CLI must not discover local corpus state')), \
                     patch('survey.deploy.build_c4_clap.build_from_files', return_value=({}, [])) as reader, \
                     patch('survey.deploy.build_c4_clap.materialize', return_value={}), \
                     patch('builtins.print'):
                    main()
                self.assertEqual(reader.call_args.kwargs['corpus_manifest_path'],
                                 Path('explicit-audit.csv') if explicit else None)

    def test_copy_verification_is_idempotent_and_never_overwrites_unequal(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'source.wav'
            source.write_bytes(b'original audio')
            assets = [(source, 'clap_audio/sound.wav', sha256(source))]
            output = base / 'result/c4_clap_bundle.json'
            bundle = dict(study_id='c4_clap_review_v1', assignments=[])
            result = materialize(bundle, assets, output, check_only=True)
            self.assertFalse(result['output_written'])
            self.assertFalse(output.parent.exists())
            materialize(bundle, assets, output)
            self.assertEqual(materialize(bundle, assets, output)['bundle_sha256'], result['bundle_sha256'])
            saved = output.read_bytes()
            with self.assertRaisesRegex(FileExistsError, 'Bundle already exists'):
                materialize(dict(bundle, changed=True), assets, output)
            self.assertEqual(output.read_bytes(), saved)
            target = output.parent / assets[0][1]
            target.write_bytes(b'changed destination')
            with self.assertRaisesRegex(FileExistsError, 'Playback already exists'):
                materialize(bundle, assets, output)
            self.assertEqual(target.read_bytes(), b'changed destination')

    def test_changed_source_fails_before_writing_any_asset_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'source.wav'
            source.write_bytes(b'audio')
            bundle = dict(study_id='c4_clap_review_v1', assignments=[])
            output = base / 'result/bundle.json'
            assets = [(source, 'clap_audio/a.wav', sha256(source)),
                      (source, 'clap_audio/b.wav', '0' * 64)]
            with self.assertRaisesRegex(ValueError, 'Source playback hash mismatch'):
                materialize(bundle, assets, output)
            self.assertFalse(output.parent.exists())
            with self.assertRaisesRegex(ValueError, 'path'):
                materialize(bundle, [(source, '../escape.wav', sha256(source))], output)

    def test_file_builder_freezes_hashes_and_refuses_wrong_bank_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source, bank = fixture()
            source_path = base / 'legacy.json'
            source_path.write_text(json.dumps(source))
            bank_path = base / 'bank.csv'
            with bank_path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(bank[0]))
                writer.writeheader()
                writer.writerows(bank)
            cache = dict(sample_ids=[f'study_{i:03d}' for i in range(1024)],
                         manifest_sha256='a' * 64, model='pinned-clap', revision='frozen-revision',
                         seed=17, embedding_dimension=512)
            run = dict(full_corpus_size=131072, clap_pool_size=1024, corpus_manifest_sha256='a' * 64)
            (base / 'clap_embedding_cache.json').write_text(json.dumps(cache))
            (base / 'generation_metadata.json').write_text(json.dumps(run))
            current = base / 'manifest.csv'
            current.write_text('current metadata layout')
            result, assets = build_from_files(source_path=source_path, bank_path=bank_path,
                                              project_root=base, corpus_manifest_path=current,
                                              expected_bank_sha256=sha256(bank_path))
            self.assertEqual(result['provenance']['source_bank_csv_sha256'], sha256(bank_path))
            self.assertEqual(result['provenance']['corpus_manifest_sha256_recorded'], 'a' * 64)
            self.assertEqual(result['provenance']['corpus_manifest_sha256_current'], sha256(current))
            self.assertEqual(result['provenance']['clap_model_revision'], 'frozen-revision')
            self.assertEqual(len(assets), 605)
            with self.assertRaisesRegex(ValueError, 'bank SHA256 mismatch'):
                build_from_files(source_path=source_path, bank_path=bank_path,
                                 expected_bank_sha256='0' * 64, project_root=base)


if __name__ == '__main__':
    unittest.main()
