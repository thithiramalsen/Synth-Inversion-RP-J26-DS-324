"""Deterministic overlapping assignments; equal exposure is not a full BIBD."""
import random
from collections import Counter


def assignments(sample_ids: list[str], seed: int = 20261007) -> list[dict]:
    if len(sample_ids) != 64 or len(set(sample_ids)) != 64:
        raise ValueError("The pilot requires 64 distinct study sounds")
    rng = random.Random(seed)
    blocks = []
    for _ in range(8):
        order = list(sample_ids)
        rng.shuffle(order)
        blocks.extend([order[:32], order[32:]])
    result = []
    repeated = Counter()
    for i, block in enumerate(blocks):
        rng.shuffle(block)
        trials = [dict(presentation_id=f"rated_{j + 1:02d}", sample_id=s,
                       kind="primary", repeat_of=None) for j, s in enumerate(block)]
        chosen = set()
        for repeat_index, position in enumerate((14, 21, 28, 35)):
            eligible = [t for j, t in enumerate(trials[:position])
                        if t["kind"] == "primary" and j <= position - 8 and t["sample_id"] not in chosen]
            rng.shuffle(eligible)
            source = min(eligible, key=lambda t: repeated[t["sample_id"]])
            chosen.add(source["sample_id"])
            repeated[source["sample_id"]] += 1
            trials.insert(position, dict(presentation_id=f"repeat_{repeat_index + 1:02d}",
                         sample_id=source["sample_id"], kind="repeat", repeat_of=source["presentation_id"]))
        result.append(dict(assignment_id=f"block_{i + 1:02d}", trials=trials))
    coverage = Counter(t["sample_id"] for b in result for t in b["trials"] if t["kind"] == "primary")
    if set(coverage.values()) != {8}:
        raise RuntimeError("Unbalanced design")
    # All participants must be connected through shared sounds.
    visited = {0}
    while True:
        expanded = visited | {j for j, b in enumerate(blocks)
                              if any(set(b) & set(blocks[k]) for k in visited)}
        if expanded == visited:
            break
        visited = expanded
    if len(visited) != 16:
        raise RuntimeError("Disconnected assignment design")
    return result


def short_assignments(sample_ids: list[str], count: int = 26, seed: int = 20261009) -> list[dict]:
    """20 unique sounds; no hidden repeats; every completed prefix has exposure difference <= 1.

    Issue blocks in order. Missing/incomplete blocks must be filled before
    claiming the prefix coverage. Co-occurrence is a tie-break heuristic, not a BIBD.
    """
    if len(sample_ids) != 64 or len(set(sample_ids)) != 64 or not 1 <= count <= 64:
        raise ValueError('Need 64 distinct study sounds and 1–64 assignments')
    rng = random.Random(seed)
    coverage, pairs = Counter(), Counter()
    result = []
    for block_index in range(count):
        selected = []
        for _ in range(20):
            remaining = [s for s in sample_ids if s not in selected]
            rng.shuffle(remaining)
            sample = min(remaining, key=lambda s: (coverage[s], sum(pairs[tuple(sorted((s,t)))] for t in selected)))
            selected.append(sample)
            coverage[sample] += 1
        for i, first in enumerate(selected):
            for second in selected[i+1:]:
                pairs[tuple(sorted((first, second)))] += 1
        rng.shuffle(selected)
        trials = [dict(presentation_id=f'rated_{j+1:02d}', sample_id=s, kind='primary', repeat_of=None)
                  for j, s in enumerate(selected)]
        result.append(dict(assignment_id=f'block_{block_index+1:02d}', trials=trials))
        if max(coverage[s] for s in sample_ids)-min(coverage[s] for s in sample_ids) > 1:
            raise RuntimeError('Prefix coverage is unbalanced')
    return result
