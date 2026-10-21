"""Freeze the real-audio CLAP bank into a separate C4 review instrument.

No simulated response/session CSV is read. Source clips are copied unchanged;
existing bundle/audio outputs are accepted only when their bytes already match.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import shutil

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / 'survey/deploy/study/c4_bundle.json'
DEFAULT_BANK = ROOT / 'c4_metric/synthetic_data/clap_triplets.csv'
DEFAULT_OUTPUT = DEFAULT_SOURCE.with_name('c4_clap_bundle.json')
SEED = 20261019
STUDY_ID = 'c4_clap_review_v1'
ROLES = ('reference', 'candidate_a', 'candidate_b')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _relative_path(base, relative):
    base = Path(base).resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() != '.wav':
        raise ValueError(f'Unexpected playback asset path: {relative}')
    return path


def _digest(value):
    if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Missing or invalid playback SHA256')
    return value


def _practice_ids(source):
    practice = sorted({t[role] for t in source['assignments'][0]['trials']
                       if t['kind'] == 'practice' for role in ROLES})
    if len(practice) != 3 or any(s not in source['samples'] for s in practice):
        raise ValueError('The source must contain three separate practice sounds')
    return practice


def build(source, bank_rows, *, provenance=None, seed=SEED):
    """Return a deterministic 100-assignment design without touching files.

    Each consecutive block of ten assignments covers all 200 canonical triplets.
    Counterbalancing alternates each triplet's canonical candidates across rounds.
    """
    if len(bank_rows) != 200:
        raise ValueError('The frozen C4 CLAP bank must contain exactly 200 triplets')
    practice = _practice_ids(source)
    canonical, samples, seen_triplets = [], {}, set()
    for row in bank_rows:
        triplet_id = row['triplet_id']
        if not triplet_id or triplet_id in seen_triplets:
            raise ValueError('Triplet IDs must be present and unique')
        seen_triplets.add(triplet_id)
        item = copy.deepcopy(row)
        item.update(reference=row['reference_sample_id'],
                    candidate_1=row['candidate_a_sample_id'],
                    candidate_2=row['candidate_b_sample_id'])
        for name in ('clap_similarity_a', 'clap_similarity_b',
                     'candidate_parameter_distance_a', 'candidate_parameter_distance_b'):
            item[name] = float(row[name])
            if not math.isfinite(item[name]):
                raise ValueError('Triplet metric scores must be finite')
        for role in ROLES:
            sid = row[f'{role}_sample_id']
            if not sid or '/' in sid or '\\' in sid or sid in samples or sid in practice:
                raise ValueError('The bank must contain 600 globally distinct study sound IDs')
            filename = Path(row[f'{role}_playback_path']).name
            if filename != sid + '.wav':
                raise ValueError('Playback filename must match its sample ID')
            samples[sid] = dict(sample_id=sid, source_sample_id=sid,
                                playback_path='clap_audio/' + filename,
                                playback_sha256=_digest(row[f'{role}_playback_sha256']),
                                source_playback_path=row[f'{role}_playback_path'],
                                source_raw_audio_path=row[f'{role}_raw_audio_path'])
        if row['clap_nearer_sample_id'] not in (item['candidate_1'], item['candidate_2']):
            raise ValueError('CLAP-nearer identity is not a candidate')
        canonical.append(item)
    for sid in practice:
        samples[sid] = copy.deepcopy(source['samples'][sid])

    assignments = []
    for round_index in range(10):
        order = list(range(200))
        random.Random(seed + 7919 * round_index).shuffle(order)
        for slot in range(10):
            selected = order[slot * 20:(slot + 1) * 20]
            trials = []

            def append_triplet(item, kind, swap=False, repeat_of=None):
                a, b = ('candidate_2', 'candidate_1') if swap else ('candidate_1', 'candidate_2')
                trial = dict(presentation_id=f'p_{len(trials) + 1:02d}',
                             triplet_id=item['triplet_id'], reference=item['reference'],
                             candidate_a=item[a], candidate_b=item[b], kind=kind,
                             repeat_of=repeat_of)
                if kind != 'practice':
                    trial.update(canonical_candidate_1=item['candidate_1'],
                                 canonical_candidate_2=item['candidate_2'],
                                 clap_similarity_a=item['clap_similarity_b' if swap else 'clap_similarity_a'],
                                 clap_similarity_b=item['clap_similarity_a' if swap else 'clap_similarity_b'],
                                 clap_nearer_sample_id=item['clap_nearer_sample_id'],
                                 selection_method=item['selection_method'],
                                 candidate_parameter_distance_a=item['candidate_parameter_distance_b' if swap else 'candidate_parameter_distance_a'],
                                 candidate_parameter_distance_b=item['candidate_parameter_distance_a' if swap else 'candidate_parameter_distance_b'])
                trials.append(trial)
                return trial

            for p in range(2):
                item = dict(triplet_id=f'practice_{p + 1}', reference=practice[p],
                            candidate_1=practice[(p + 1) % 3], candidate_2=practice[(p + 2) % 3])
                append_triplet(item, 'practice', bool(round_index % 2))
            primary = []
            for position, bank_index in enumerate(selected):
                item = canonical[bank_index]
                swap = bool((bank_index + round_index) % 2)
                primary.append(append_triplet(item, 'primary', swap))
                if position in (9, 19):
                    earlier = primary[0 if position == 9 else 9]
                    earlier_index = selected[0 if position == 9 else 9]
                    earlier_swap = bool((earlier_index + round_index) % 2)
                    append_triplet(canonical[earlier_index], 'repeat', not earlier_swap,
                                   earlier['presentation_id'])
            number = round_index * 10 + slot + 1
            assignments.append(dict(assignment_id=f'c4_clap_{number:03d}',
                                    coverage_round=round_index + 1, slot_in_round=slot + 1,
                                    trials=trials))
    return dict(study_id=STUDY_ID, rehearsal=True, seed=seed,
                purpose='C4 CLAP-bank interface review; all review records remain excluded from research analysis.',
                selection='Frozen 200-triplet real-audio CLAP bank from a seeded 1,024-sound subset of the 131,072-sound corpus.',
                selection_caveat='Near 5–20% and moderately near 20–40% bands use the remaining unused eligible candidate pool at each selection, not fixed percentiles of all 1,023 other subset sounds. Sounds are globally used once in the bank.',
                design=dict(target_completed_min=50, target_completed_max=100,
                            assignment_capacity=100, assignments_per_round=10,
                            unique_comparisons=20, repeat_comparisons=2,
                            practice_comparisons=2, total_presentations=24,
                            canonical_triplets=200, distinct_study_sounds=600,
                            minimum_intervening_repeat_positions=6,
                            replication_at_50_complete_round_assignments=5,
                            replication_at_100_complete_round_assignments=10,
                            coverage_condition='Complete every assignment in each consecutive ten-assignment round. Incomplete rounds or missing sessions reduce realized coverage.',
                            side_policy='Canonical A/B alternates per triplet across rounds; hidden repeats reverse its earlier display.'),
                provenance=copy.deepcopy(provenance or {}),
                assignments=assignments, canonical_triplets=canonical,
                samples={sid: samples[sid] for sid in sorted(samples)},
                headphones=copy.deepcopy(source['headphones']),
                calibration=copy.deepcopy(source['calibration']))


def build_from_files(*, source_path=DEFAULT_SOURCE, bank_path=DEFAULT_BANK,
                     cache_metadata_path=None, generation_metadata_path=None,
                     corpus_manifest_path=None, project_root=ROOT,
                     expected_bank_sha256=None):
    """Read only the real triplet bank and its provenance, never response CSVs."""
    source_path, bank_path = Path(source_path), Path(bank_path)
    bank_hash = sha256(bank_path)
    if expected_bank_sha256 is not None and bank_hash != expected_bank_sha256:
        raise ValueError('Source triplet bank SHA256 mismatch')
    cache_metadata_path = Path(cache_metadata_path or bank_path.with_name('clap_embedding_cache.json'))
    generation_metadata_path = Path(generation_metadata_path or bank_path.with_name('generation_metadata.json'))
    source = json.loads(source_path.read_text(encoding='utf-8'))
    cache = json.loads(cache_metadata_path.read_text(encoding='utf-8'))
    run = json.loads(generation_metadata_path.read_text(encoding='utf-8'))
    if (run['full_corpus_size'] != 131072 or run['clap_pool_size'] != 1024
            or len(cache['sample_ids']) != 1024 or len(set(cache['sample_ids'])) != 1024
            or cache['manifest_sha256'] != run['corpus_manifest_sha256']):
        raise ValueError('Inconsistent corpus or CLAP-subset provenance')
    with bank_path.open(newline='', encoding='utf-8-sig') as handle:
        bank = list(csv.DictReader(handle))
    bank_ids = {row[f'{role}_sample_id'] for row in bank for role in ROLES}
    if not bank_ids.issubset(cache['sample_ids']):
        raise ValueError('Bank sound is absent from the recorded CLAP subset')
    provenance = dict(source_bank_csv_sha256=bank_hash,
                      source_bundle_sha256=sha256(source_path),
                      source_clap_cache_metadata_sha256=sha256(cache_metadata_path),
                      source_generation_metadata_sha256=sha256(generation_metadata_path),
                      corpus_manifest_sha256_recorded=cache['manifest_sha256'],
                      corpus_size=131072, clap_pool_size=1024,
                      clap_model=cache['model'], clap_model_revision=cache['revision'],
                      selection_seed=cache['seed'], embedding_dimension=cache['embedding_dimension'],
                      selection_rank_pool='remaining_unused_candidates',
                      near_rank_percentiles=[5, 20], moderate_rank_percentiles=[20, 40])
    if corpus_manifest_path is not None:
        provenance['corpus_manifest_sha256_current'] = sha256(corpus_manifest_path)
    bundle = build(source, bank, provenance=provenance)
    bundle['source_bundle_sha256'] = provenance['source_bundle_sha256']
    assets = []
    for row in bank:
        for role in ROLES:
            sid = row[f'{role}_sample_id']
            assets.append((_relative_path(project_root, row[f'{role}_playback_path']),
                           bundle['samples'][sid]['playback_path'], row[f'{role}_playback_sha256']))
    for sid in _practice_ids(source):
        asset = source['samples'][sid]
        assets.append((_relative_path(source_path.parent, asset['playback_path']),
                       asset['playback_path'], asset['playback_sha256']))
    for asset in source['headphones'] + [source['calibration']]:
        relative = 'audio/' + asset['path']
        assets.append((_relative_path(source_path.parent, relative), relative, asset['sha256']))
    return bundle, assets


def materialize(bundle, assets, output_path=DEFAULT_OUTPUT, *, check_only=False):
    """Verify all inputs/outputs before any copy, and never overwrite unequal files."""
    output_path = Path(output_path).resolve()
    payload = (json.dumps(bundle, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    if output_path.exists() and output_path.read_bytes() != payload:
        raise FileExistsError('Bundle already exists with different bytes; use a new version/path')
    destinations = {}
    for source, relative, expected in assets:
        source = Path(source)
        destination = _relative_path(output_path.parent, relative)
        if relative in destinations and destinations[relative] != expected:
            raise ValueError('Conflicting playback destination')
        destinations[relative] = expected
        if sha256(source) != expected:
            raise ValueError(f'Source playback hash mismatch: {source.name}')
        if destination.exists() and sha256(destination) != expected:
            raise FileExistsError(f'Playback already exists with different bytes: {relative}')
    if check_only:
        return dict(study_id=bundle['study_id'], verified_assets=len(destinations),
                    assignments=len(bundle['assignments']), bundle_sha256=hashlib.sha256(payload).hexdigest(),
                    output_written=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for source, relative, expected in assets:
        destination = _relative_path(output_path.parent, relative)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Path(source).open('rb') as reader, destination.open('xb') as writer:
            shutil.copyfileobj(reader, writer)
        if sha256(destination) != expected:
            raise ValueError(f'Copied playback hash mismatch: {relative}')
    if not output_path.exists():
        with output_path.open('xb') as handle:
            handle.write(payload)
    return dict(study_id=bundle['study_id'], verified_assets=len(destinations),
                assignments=len(bundle['assignments']), bundle_sha256=hashlib.sha256(payload).hexdigest(),
                output_written=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--bank', type=Path, default=DEFAULT_BANK)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--cache-metadata', type=Path)
    parser.add_argument('--generation-metadata', type=Path)
    parser.add_argument('--corpus-manifest', type=Path,
                        help='Explicit local-manifest audit for a separate output version; omitted from the reproducible default package')
    parser.add_argument('--expected-bank-sha256')
    parser.add_argument('--check', action='store_true', help='Verify inputs and existing outputs without writing')
    args = parser.parse_args()
    bundle, assets = build_from_files(source_path=args.source, bank_path=args.bank,
                                     cache_metadata_path=args.cache_metadata,
                                     generation_metadata_path=args.generation_metadata,
                                     corpus_manifest_path=args.corpus_manifest,
                                     expected_bank_sha256=args.expected_bank_sha256)
    print(json.dumps(materialize(bundle, assets, args.output, check_only=args.check), indent=2))


if __name__ == '__main__':
    main()
