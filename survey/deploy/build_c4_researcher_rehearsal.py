"""Prepare a separate researcher rehearsal identity using unchanged C4 audio."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from survey.deploy.start import validate_assets

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'survey/deploy/study/c4_participant_bundle_v1.json'
SOURCE_CONFIG = ROOT/'survey/config/c4_participants_v1.json'
OUTPUT = SOURCE.with_name('c4_researcher_rehearsal_v1.json')
OUTPUT_CONFIG = SOURCE_CONFIG.with_name('c4_researcher_rehearsal_v1.json')
STUDY_ID = 'c4_researcher_rehearsal_v1'
PROTOCOL_VERSION = 'c4_researcher_rehearsal_2026-10-21_v1_no_practice'
DATA_ORIGIN = 'researcher_entered_rehearsal'
NOTICE = ('Researcher rehearsal only. Fresh answers are entered by research team members '
          'for internal testing and review, not by independent study participants. '
          'All responses are excluded from participant research analysis.')


def normalized_digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def build(source, digest):
    if source.get('study_id') != 'c4_clap_participants_v1' or source.get('rehearsal') is not False:
        raise ValueError('Use the frozen C4 participant audio bundle as the metadata source')
    if len(source['assignments']) != 100 or len(source['canonical_triplets']) != 200 or len(source['samples']) != 603:
        raise ValueError('Expected 100 assignments, 200 triplets and the existing 600 + 3 sound bank')
    for block in source['assignments']:
        primary = [trial['triplet_id'] for trial in block['trials'] if trial['kind'] == 'primary']
        practices = [trial for trial in block['trials'] if trial['kind'] == 'practice']
        repeats = [trial for trial in block['trials'] if trial['kind'] == 'repeat']
        if len(block['trials']) != 24 or len(primary) != 20 or len(set(primary)) != 20 or len(practices) != 2 or len(repeats) != 2:
            raise ValueError('Expected 20 unique comparisons, 2 hidden repeats and 2 practices in each assignment')
    result = copy.deepcopy(source)
    result.update(study_id=STUDY_ID, rehearsal=True, data_origin=DATA_ORIGIN,
                  purpose='Internal research team rehearsal of the C4 interface; excluded from participant analysis.',
                  rehearsal_note=NOTICE, source_participant_bundle_sha256=digest,
                  source_participant_bundle_hash_format='lf_utf8')
    for number, block in enumerate(result['assignments'], 1):
        block['assignment_id'] = f'c4_researcher_rehearsal_{number:03d}'
        block['trials'] = [trial for trial in block['trials'] if trial['kind'] != 'practice']
    design = result['design']
    design.update(practice_comparisons=0, total_presentations=22)
    for key in ('target_completed_min', 'target_completed_max', 'replication_at_50_complete_round_assignments',
                'replication_at_100_complete_round_assignments', 'coverage_condition'):
        design.pop(key, None)
    design['note'] = 'Internal team test assignments; these do not represent independent study participants.'
    return result


def build_config(source, digest):
    if source.get('study_id') != 'c4_clap_participants_v1' or source.get('collection_mode') != 'participants':
        raise ValueError('Use the current C4 participant configuration as the interface source')
    result = copy.deepcopy(source)
    for key in ('target_completed_min', 'target_completed_max', 'participant_notice'):
        result.pop(key, None)
    result.update(study_id=STUDY_ID, protocol_version=PROTOCOL_VERSION,
                  collection_mode='researcher_rehearsal', data_origin=DATA_ORIGIN,
                  information_version='c4_researcher_rehearsal_information_2026-10-21_v1',
                  practice_comparisons=0,
                  description='Internal research team rehearsal of the C4 listening interface.',
                  review_notice=NOTICE, source_participant_config_sha256=digest,
                  source_participant_config_hash_format='lf_utf8',
                  retention_statement='Internal rehearsal responses are stored separately with access restricted to the research team. '
                                      'They are excluded from participant research analysis. No automatic deletion date has been set. '
                                      'Contact the researcher with your listener code about stored rehearsal responses.')
    result['information'][0] = NOTICE
    result['information'][2] = ('Set a comfortable listening volume, then complete 22 comparisons: '
                              '20 different comparisons and 2 hidden repeats to check consistency. '
                              'There are no practice rounds. A break follows comparison 11.')
    return result


def serialized(value):
    return (json.dumps(value, indent=2, ensure_ascii=False)+'\n').encode('utf-8')


def prepare(source_path=SOURCE, output_path=OUTPUT, source_config_path=SOURCE_CONFIG,
            output_config_path=OUTPUT_CONFIG, *, check_only=False):
    source_path, output_path = Path(source_path), Path(output_path)
    source_config_path, output_config_path = Path(source_config_path), Path(output_config_path)
    if source_path.resolve().parent != output_path.resolve().parent:
        raise ValueError('Keep the rehearsal bundle beside the existing verified playback assets')
    if len({path.resolve() for path in (source_path, output_path, source_config_path, output_config_path)}) != 4:
        raise ValueError('Source and rehearsal outputs must be distinct files')
    source = validate_assets(source_path)
    result = build(source, normalized_digest(source_path))
    cfg = build_config(json.loads(source_config_path.read_bytes()), normalized_digest(source_config_path))
    outputs = [(output_path, serialized(result)), (output_config_path, serialized(cfg))]
    for path, payload in outputs:
        if path.exists():
            if path.read_bytes().replace(b'\r\n', b'\n') != payload:
                raise FileExistsError('Rehearsal metadata differs; use a new version instead of overwriting')
        elif check_only:
            raise FileNotFoundError('Prepare the researcher rehearsal metadata before checking it')
    if not check_only:
        for path, payload in outputs:
            if not path.exists():
                path.write_bytes(payload)
    validate_assets(output_path)
    return dict(study_id=STUDY_ID, protocol_version=PROTOCOL_VERSION, data_origin=DATA_ORIGIN,
                rehearsal=True, analysis_include=False, assignments=100, bank_triplets=200,
                study_sounds=600, practice_sounds=0, presentations_per_listener=22,
                audio_rendered=False, responses_copied=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--source-config', type=Path, default=SOURCE_CONFIG)
    parser.add_argument('--output-config', type=Path, default=OUTPUT_CONFIG)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.source_config,
                             args.output_config, check_only=args.check), indent=2))
