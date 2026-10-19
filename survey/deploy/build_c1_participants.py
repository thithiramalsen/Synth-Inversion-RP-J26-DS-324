"""Freeze a distinct C1 participant identity while reusing verified review audio."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

from survey.deploy.start import validate_assets

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'survey/deploy/study/bundle.json'
OUTPUT = SOURCE.with_name('c1_participant_bundle_v1.json')


def build(source, digest):
    if source.get('study_id') != 'c1_20_review_v1' or source.get('rehearsal') is not True:
        raise ValueError('Use the frozen C1 20-sound review bundle')
    for block in source['assignments']:
        primary = [trial['sample_id'] for trial in block['trials'] if trial['kind'] == 'primary']
        if len(block['trials']) != 23 or len(primary) != 20 or len(set(primary)) != 20:
            raise ValueError('Expected 20 unique study sounds and 3 practices per assignment')
        if sum(trial['kind'] == 'practice' for trial in block['trials']) != 3:
            raise ValueError('Expected 3 practices per assignment')
    counts = Counter(trial['sample_id'] for block in source['assignments'][:16]
                     for trial in block['trials'] if trial['kind'] == 'primary')
    if len(source['assignments']) < 16 or len(counts) != 64 or set(counts.values()) != {5}:
        raise ValueError('The first 16 assignments must cover all 64 sounds five times')
    result = copy.deepcopy(source)
    result.update(study_id='c1_20_participants_v1', rehearsal=False,
                  purpose='Participant ratings of four timbre descriptors on the frozen C1 64-sound bank.',
                  source_review_bundle_sha256=digest, source_review_bundle_hash_format='lf_utf8')
    for number, block in enumerate(result['assignments'], 1):
        block['assignment_id'] = f'c1_participant_{number:02d}'
    return result


def prepare(source_path=SOURCE, output_path=OUTPUT, *, check_only=False):
    source_path, output_path = Path(source_path), Path(output_path)
    if source_path.resolve().parent != output_path.resolve().parent:
        raise ValueError('Keep the participant bundle beside the frozen review playback assets')
    source = validate_assets(source_path)
    digest = hashlib.sha256(source_path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    result = build(source, digest)
    payload = (json.dumps(result, indent=2, ensure_ascii=False)+'\n').encode('utf-8')
    if output_path.exists():
        if output_path.read_bytes().replace(b'\r\n', b'\n') != payload:
            raise FileExistsError('Participant bundle differs; use a new version instead of overwriting')
    elif check_only:
        raise FileNotFoundError('Prepare the participant bundle before checking it')
    else:
        output_path.write_bytes(payload)
    validate_assets(output_path)
    return dict(study_id=result['study_id'], assignments=len(result['assignments']),
                study_sounds=64, practice_sounds=3, presentations_per_listener=23,
                target_completed=16, target_ratings_per_sound=5, audio_rendered=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, check_only=args.check), indent=2))
