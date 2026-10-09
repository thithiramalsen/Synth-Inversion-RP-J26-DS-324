"""Deterministic interface-review stimuli; not a main-study sampling design."""
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[2]


def build(source):
    practice = sorted({t['sample_id'] for t in source['assignments'][0]['trials'] if t['kind'] == 'practice'})
    pool = sorted(set(source['samples']) - set(practice))
    rng = random.Random(41009)
    picked = rng.sample(pool, 30)
    canonical = [dict(triplet_id=f'triplet_{i+1:02d}', reference=picked[3*i],
                      candidate_1=picked[3*i+1], candidate_2=picked[3*i+2]) for i in range(10)]
    blocks = []
    for pair in range(8):
        order = canonical.copy()
        random.Random(41009 + pair).shuffle(order)
        for side in range(2):
            def trial(t, kind, number, reverse=False, repeat_of=None):
                swap = bool((pair + int(t['triplet_id'].split('_')[-1]) + side) % 2) ^ reverse
                return dict(presentation_id=f'p_{number:02d}', triplet_id=t['triplet_id'],
                            reference=t['reference'], candidate_a=t['candidate_2' if swap else 'candidate_1'],
                            candidate_b=t['candidate_1' if swap else 'candidate_2'], kind=kind, repeat_of=repeat_of)
            trials = []
            for i in range(2):
                t = dict(triplet_id=f'practice_{i+1}', reference=practice[i],
                         candidate_1=practice[(i+1)%3], candidate_2=practice[(i+2)%3])
                trials.append(trial(t, 'practice', len(trials)+1))
            for i, t in enumerate(order):
                trials.append(trial(t, 'primary', len(trials)+1))
                if i in (7, 9):
                    original = order[0 if i == 7 else 3]
                    original_id = next(p['presentation_id'] for p in trials if p['triplet_id'] == original['triplet_id'])
                    trials.append(trial(original, 'repeat', len(trials)+1, True, original_id))
            blocks.append(dict(assignment_id=f'c4_review_{pair*2+side+1:02d}', trials=trials))
    return dict(study_id='c4_review_v1', rehearsal=True, seed=41009,
                purpose='Supervisor/interface review only; not representative sampling or metric evaluation.',
                selection='30 distinct sounds sampled without replacement from the 64 C1 primary playback assets; independent of metric scores.',
                assignments=blocks, canonical_triplets=canonical,
                samples={s: source['samples'][s] for s in sorted(set(picked + practice))},
                headphones=source['headphones'], calibration=source['calibration'])


if __name__ == '__main__':
    path = ROOT/'survey/deploy/study/bundle.json'
    payload = build(json.loads(path.read_text(encoding='utf-8')))
    payload['source_bundle_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (path.parent/'c4_bundle.json').write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
