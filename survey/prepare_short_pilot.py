"""Copy frozen audio into a 20-unique-sound study; preserve every source file."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from survey.design import short_assignments

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, output: Path, *, rehearsal=False):
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError('Use a new destination; existing studies are never overwritten')
    if source.parent.is_relative_to(output):
        raise ValueError('Destination must not contain the source bundle')
    source_hash = digest(source)
    bundle = json.loads(source.read_text(encoding='utf-8'))
    study_ids = sorted({t['sample_id'] for a in bundle['assignments'] for t in a['trials'] if t['kind'] == 'primary'})
    practice_ids = sorted({t['sample_id'] for a in bundle['assignments'] for t in a['trials'] if t['kind'] == 'practice'})
    if len(study_ids) != 64 or len(practice_ids) != 3 or set(study_ids) & set(practice_ids):
        raise ValueError('Expected the frozen 64 study + 3 practice selection')
    checked = []
    for s in bundle['samples'].values():
        checked.extend([(s['playback_path'], s['playback_sha256']), (s['feature_path'], s['feature_sha256'])])
    checked.extend(('audio/'+s['path'], s['sha256']) for s in bundle['headphones'])
    checked.append(('audio/'+bundle['calibration']['path'], bundle['calibration']['sha256']))
    for relative, expected in checked:
        path = (source.parent / relative).resolve()
        if not path.is_relative_to(source.parent) or digest(path) != expected:
            raise ValueError(f'Invalid or changed source asset: {relative}')
    blocks = short_assignments(study_ids)
    report = {}
    for n in (13, 16, 19, 22, 26):
        counts = Counter(t['sample_id'] for b in blocks[:n] for t in b['trials'])
        report[str(n)] = dict(sorted(Counter(counts.values()).items()))
    for b in blocks:
        b['trials'] = [dict(presentation_id=f'practice_{i+1:02d}', sample_id=s, kind='practice', repeat_of=None)
                       for i, s in enumerate(practice_ids)] + b['trials']
    bundle.update(study_id='c1_20_review_v1' if rehearsal else 'c1_pilot_v1', rehearsal=rehearsal,
                  assignments=blocks, assignment_version='20_unique_no_repeats_v1',
                  source_bundle_sha256=source_hash, design_sha256=digest(ROOT/'survey/design.py'),
                  assignment_preparation_sha256=digest(Path(__file__)),
                  assignment_plan=dict(target_completions=16, capacity=26, unique_per_person=20,
                      repeats_per_person=0, practice_per_person=3, break_after_rated=10,
                      completed_prefix_coverage=report,
                      note='Issue in block order and fill missing blocks. Prefix balance is not a full BIBD. No within-listener repeatability estimate.'))
    if rehearsal:
        bundle['rehearsal_note'] = 'Supervisor review only; pending approval, excluded from research analysis.'
    output.mkdir(parents=True)
    for relative, expected in checked:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.parent / relative, target)
        if digest(target) != expected:
            raise RuntimeError('Copied audio failed verification')
    destination = output/'bundle.json'
    destination.write_text(json.dumps(bundle, indent=2)+'\n', encoding='utf-8')
    if digest(source) != source_hash:
        raise RuntimeError('Source changed during preparation')
    (output/'PREPARATION.json').write_text(json.dumps(dict(
        source_bundle_sha256=source_hash, bundle_sha256=digest(destination),
        audio_unchanged=True, copied_assets=len(checked), assignments=len(blocks),
        presentations_per_assignment=23, unique_study_per_assignment=20,
        repeats=0, completed_prefix_coverage=report), indent=2)+'\n', encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/processed/c1_pilot_v1/bundle.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args()
    print(prepare(args.source, args.output, rehearsal=args.rehearsal))
