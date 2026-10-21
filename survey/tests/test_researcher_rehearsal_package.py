"""The team rehearsal reuses stimuli, never participant response data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from survey.backend.c1_protocol import analysis_include
from survey.deploy.build_c1_researcher_rehearsal import (
    DATA_ORIGIN, NOTICE, OUTPUT, OUTPUT_CONFIG, SOURCE, SOURCE_CONFIG, STUDY_ID,
    build, build_config, normalized_digest, prepare,
)


class ResearcherRehearsalPackageTests(unittest.TestCase):
    def test_distinct_identity_same_stimuli_questions_and_source_bytes(self):
        source_bytes, config_bytes = SOURCE.read_bytes(), SOURCE_CONFIG.read_bytes()
        source, cfg = json.loads(source_bytes), json.loads(config_bytes)
        original_source, original_cfg = copy.deepcopy(source), copy.deepcopy(cfg)
        result = build(source, normalized_digest(SOURCE))
        result_cfg = build_config(cfg, normalized_digest(SOURCE_CONFIG))
        self.assertEqual(result, json.loads(OUTPUT.read_bytes()))
        self.assertEqual(result_cfg, json.loads(OUTPUT_CONFIG.read_bytes()))
        self.assertEqual(source, original_source)
        self.assertEqual(cfg, original_cfg)
        self.assertFalse(source['rehearsal'])
        self.assertTrue(result['rehearsal'])
        self.assertNotEqual(result['study_id'], source['study_id'])
        self.assertEqual(result['data_origin'], DATA_ORIGIN)
        for key in ('samples', 'headphones', 'calibration', 'level_policy', 'dc_policy', 'selection'):
            self.assertEqual(result[key], source[key])
        for number, (old, new) in enumerate(zip(source['assignments'], result['assignments']), 1):
            self.assertEqual(new['assignment_id'], f'researcher_rehearsal_{number:02d}')
            self.assertEqual(old['trials'], new['trials'])
        for key in ('descriptors', 'scale', 'experience_question', 'experience_tools_label',
                    'experience_tools_placeholder', 'experience_entry_format', 'navigation_policy',
                    'headphone_screening_enabled', 'break_after_rated', 'eligibility'):
            self.assertEqual(cfg[key], result_cfg[key])
        self.assertEqual(result_cfg['information'][0], NOTICE)
        self.assertEqual(cfg['information'][1:], result_cfg['information'][1:])
        self.assertEqual(cfg['institutional_review_status'], result_cfg['institutional_review_status'])
        self.assertNotIn('target_participants', result_cfg)
        self.assertNotIn('target_ratings_per_sound', result_cfg)
        self.assertNotIn('participant_notice', result_cfg)
        metadata = json.dumps([result, result_cfg])
        for key in ('answers', 'ratings', 'responses', 'session_id', 'participant_id'):
            self.assertNotIn(f'"{key}":', metadata)
        readiness = prepare(check_only=True)
        self.assertFalse(readiness['audio_rendered'])
        self.assertEqual(readiness['responses_copied'], 0)
        self.assertEqual(SOURCE.read_bytes(), source_bytes)
        self.assertEqual(SOURCE_CONFIG.read_bytes(), config_bytes)

    def test_complete_team_rehearsal_cannot_be_included_in_participant_analysis(self):
        cfg = json.loads(OUTPUT_CONFIG.read_bytes())
        row = dict(phase='complete', completed_at='fixture', withdrawn_at=None, kind='primary',
                   study_id=STUDY_ID, protocol_snapshot=json.dumps(cfg))
        self.assertFalse(analysis_include(row))
        row['kind'] = 'practice'
        self.assertFalse(analysis_include(row))

    def test_preparation_is_idempotent_and_refuses_different_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, cfg_source = root/'source.json', root/'source-config.json'
            output, cfg_output = root/'rehearsal.json', root/'rehearsal-config.json'
            source.write_bytes(SOURCE.read_bytes())
            cfg_source.write_bytes(SOURCE_CONFIG.read_bytes())
            with patch('survey.deploy.build_c1_researcher_rehearsal.validate_assets',
                       side_effect=lambda path: json.loads(Path(path).read_bytes())):
                paths = source, output, cfg_source, cfg_output
                with self.assertRaises(FileNotFoundError):
                    prepare(*paths, check_only=True)
                prepare(*paths)
                frozen = output.read_bytes(), cfg_output.read_bytes()
                prepare(*paths)
                self.assertEqual(frozen, (output.read_bytes(), cfg_output.read_bytes()))
                cfg_output.write_text('{}', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    prepare(*paths)
                self.assertEqual(output.read_bytes(), frozen[0])
                self.assertEqual(cfg_output.read_text(encoding='utf-8'), '{}')

    def test_only_participant_metadata_is_accepted_and_sources_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            build(dict(study_id=STUDY_ID, rehearsal=True), 'test-hash')
        with self.assertRaises(ValueError):
            build_config(dict(study_id=STUDY_ID, collection_mode='researcher_rehearsal'), 'test-hash')
        with self.assertRaises(ValueError):
            prepare(output_path=SOURCE)


if __name__ == '__main__':
    unittest.main()
