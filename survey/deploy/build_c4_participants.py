"""Create a separate participant bundle from the unchanged real-audio C4 bank."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from survey.deploy.build_c4_clap import materialize

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'survey/deploy/study/c4_clap_bundle.json'
OUTPUT = SOURCE.with_name('c4_participant_bundle_v1.json')


def bundle_digest(payload):
    """Use Git/Render's LF bytes even when a Windows checkout contains CRLF."""
    return hashlib.sha256(payload.replace(b'\r\n', b'\n')).hexdigest()


def build(source, source_hash):
    if source.get('study_id') != 'c4_clap_review_v1' or source.get('rehearsal') is not True:
        raise ValueError('Use the frozen C4 CLAP review bundle as the source')
    bundle = copy.deepcopy(source)
    bundle.update(study_id='c4_clap_participants_v1', rehearsal=False,
                  purpose='Human relative-timbre judgments on the frozen 200-triplet CLAP bank.',
                  source_review_bundle_sha256=source_hash,
                  source_review_bundle_hash_format='lf_utf8')
    for number, block in enumerate(bundle['assignments'], 1):
        block['assignment_id'] = f'c4_participant_{number:03d}'
    return bundle


def prepare(source_path=SOURCE, output_path=OUTPUT, *, check_only=False):
    source_path = Path(source_path)
    source = json.loads(source_path.read_text(encoding='utf-8'))
    bundle = build(source, bundle_digest(source_path.read_bytes()))
    assets = []
    for sample in source['samples'].values():
        path = source_path.parent / sample['playback_path']
        if not path.is_file() and sample.get('source_playback_path'):
            path = (ROOT / sample['source_playback_path']).resolve()
            if not path.is_relative_to(ROOT):
                raise ValueError('Source playback path is outside the project')
        assets.append((path, sample['playback_path'], sample['playback_sha256']))
    assets += [(source_path.parent / 'audio' / s['path'], 'audio/' + s['path'], s['sha256'])
               for s in source['headphones'] + [source['calibration']]]
    return materialize(bundle, assets, output_path, check_only=check_only)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, check_only=args.check), indent=2))


if __name__ == '__main__':
    main()
