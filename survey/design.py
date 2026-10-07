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
