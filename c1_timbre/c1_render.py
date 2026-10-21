"""Render one v4 patch for C1 with the frozen corpus generator.

    patch (13 controls) -> render -> dc_highpass_10hz_v1 once -> audio

This reuses the exact code path that produced the 131,072-sound corpus
(generation.generate_corpus.render_one): the frozen v4 generator, a fresh synth
per render, the frozen preset and fixed controls, MIDI 60, velocity 0.8, 1.5 s
hold and a 3 s render. Output equals generation.corpus_audio.load_audio for the
same patch. Nothing is written to the corpus.

Controls can be given in two equivalent coordinates:
* unit       position within the declared range, 0 = min, 1 = max (control-effect
             steps are fractions of this range)
* normalized Vital's 0-1 normalized value (must lie inside the declared range)

Verify reproduction against stored corpus masters:
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.c1_render --verify 8
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

from generation.audio_processing import DC_POLICY_ID, dc_filter
from generation.corpus_audio import canonical_float32, sample_digest
from generation.generate_corpus import ROOT, generator

MANIFEST = ROOT / "data/raw/corpus_v4/manifest.parquet"


def controls():
    """Ordered control names with their declared normalized bounds."""
    g = generator()
    return {name: (float(spec["min"]), float(spec["max"])) for name, spec in g.PARAMS.items()}


def to_unit(normalized: dict[str, float]) -> dict[str, float]:
    return {k: (v - lo) / (hi - lo) for k, (lo, hi) in controls().items() for v in [normalized[k]]}


def render_unit(unit: dict[str, float]):
    """Render a patch given unit positions for all 13 controls.

    Returns (processed, raw, recorded): processed is the DC-conditioned audio used
    for C1 features (canonical float32, identical to load_audio); raw is the
    unconditioned render; recorded holds the values Vital actually applied.
    """
    g = generator()
    names = list(g.PARAMS)
    missing = set(names) - set(unit)
    if missing:
        raise ValueError(f"Missing controls: {sorted(missing)}")
    vector = np.array([unit[n] for n in names], dtype=float)
    if np.any(vector < -1e-12) or np.any(vector > 1 + 1e-12):
        bad = [n for n, v in zip(names, vector) if not -1e-12 <= v <= 1 + 1e-12]
        raise ValueError(f"Outside the declared range: {bad}")
    synth = g.create_synth()
    if not synth.load_preset(str(g.BASE_PRESET)):
        raise RuntimeError("Cannot load the frozen preset")
    g.apply_fixed_controls(synth)
    recorded = g.apply_sampled_parameters(synth, np.clip(vector, 0, 1), names)
    stereo = g.render_sample(synth)
    if g.calculate_audio_metrics(stereo)["stereo_difference_rms"] > 1e-10:
        raise ValueError("Unexpected stereo difference")
    raw = stereo[0].copy()
    processed = canonical_float32(dc_filter(raw, g.SAMPLE_RATE))
    return processed, raw, recorded


def render_normalized(normalized: dict[str, float]):
    return render_unit(to_unit(normalized))


def corpus_unit(sample_id: str) -> dict[str, float]:
    """The exact unit values a corpus sound was rendered from."""
    names = list(controls())
    row = pd.read_parquet(MANIFEST, columns=["sample_id"] + [f"{n}_sample_01" for n in names]).set_index("sample_id").loc[sample_id]
    return {n: float(row[f"{n}_sample_01"]) for n in names}


def verify(count: int, seed: int = 20261014):
    """Re-render random corpus sounds; compare with the stored hashes."""
    man = pd.read_parquet(MANIFEST, columns=["sample_id", "raw_samples_sha256", "processed_samples_sha256", "audio_policy_id"])
    picks = man.sample(count, random_state=seed)
    ok = 0
    for r in picks.itertuples():
        t0 = time.perf_counter()
        processed, raw, _ = render_unit(corpus_unit(r.sample_id))
        same_raw = sample_digest(raw) == r.raw_samples_sha256
        same_processed = sample_digest(processed) == r.processed_samples_sha256
        ok += same_raw and same_processed and r.audio_policy_id == DC_POLICY_ID
        print(f"{r.sample_id}: raw {'match' if same_raw else 'DIFFERS'}, processed {'match' if same_processed else 'DIFFERS'} "
              f"({time.perf_counter() - t0:.2f} s)")
    print(f"\n{ok}/{count} corpus sounds reproduced bit-exactly")
    return ok == count


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", type=int, default=8, help="number of random corpus sounds to re-render")
    raise SystemExit(0 if verify(ap.parse_args().verify) else 1)
