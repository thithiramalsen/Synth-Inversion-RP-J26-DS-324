"""Read-only paired encoding audit of the v4 candidates and selected pilot clips.

Run from the repository root with the project Python environment. WAV round trips
use BytesIO; only a new audit output directory is written. No synth is rendered,
no source/manifest/bundle is changed, and no perceptual equivalence is claimed.
"""
from __future__ import annotations

import os

# Small FFT/matrix jobs are faster and reproducible without nested BLAS threads.
for _variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_variable] = "1"

import argparse
import csv
import hashlib
import io
import json
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from c1_timbre.feature_extraction import extract_features
from c2_estimation import pipeline as c2
from c3_recommendation import pipeline as c3

RATE = 44100
HELD = 66150
METHODS = ("pcm16_current", "pcm16_nearest", "pcm24_current")
FEATURES = ["spectral_centroid_hz", "spectral_rolloff_85_hz", "rms", "zero_crossing_rate"] + [f"mfcc_{i:02d}" for i in range(1, 14)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def db(value):
    return float(20 * np.log10(max(float(value), 1e-30)))


def rms(value):
    return float(np.sqrt(np.mean(np.square(value, dtype=np.float64))))


def describe(values):
    values = np.asarray(values, dtype=float)
    return {"min": float(values.min()), "median": float(np.median(values)),
            "p95": float(np.quantile(values, .95)), "max": float(values.max())}


def encode(audio, method="pcm16_current"):
    """Use real libsndfile WAV conversion, not an assumed quantizer formula."""
    stream = io.BytesIO()
    if method == "pcm16_nearest":
        # Explicit deterministic round-to-nearest/ties-to-even, no dither.
        payload = np.clip(np.rint(audio * 32768), -32768, 32767).astype(np.int16)
        subtype = "PCM_16"
    else:
        payload = audio
        subtype = "PCM_24" if method == "pcm24_current" else "PCM_16"
    sf.write(stream, payload, RATE, format="WAV", subtype=subtype)
    stream.seek(0)
    result, rate = sf.read(stream, dtype="float64")
    assert rate == RATE and result.shape == audio.shape
    return result


def error_metrics(reference, comparison):
    difference = comparison - reference
    return {"error_rms_dbfs": db(rms(difference)), "error_peak": float(np.max(np.abs(difference))),
            "held_snr_db": db(rms(reference[:HELD]) / max(rms(difference[:HELD]), 1e-30)),
            "error_mean": float(difference.mean()),
            "held_level_change_db": db(rms(comparison[:HELD]) / max(rms(reference[:HELD]), 1e-30))}


def feature_summary(reference, comparison, names):
    std = reference.std(axis=0)
    output = []
    for j, name in enumerate(names):
        difference = np.abs(comparison[:, j] - reference[:, j])
        normalized = difference / max(float(std[j]), 1e-12)
        output.append({"feature": name, "reference_corpus_std": float(std[j]),
                       "absolute_error": describe(difference), "error_in_corpus_std": describe(normalized),
                       "spearman": float(spearmanr(reference[:, j], comparison[:, j]).statistic),
                       "engineering_review": bool(np.quantile(normalized, .95) > .05 or normalized.max() > .1)})
    return output


def logmel_error(reference, comparison):
    difference = np.abs(comparison.astype(float) - reference)
    active = reference > -60
    return {"rmse_db": rms(difference), "max_bin_error_db": float(difference.max()),
            "fraction_bins_over_0p1db": float(np.mean(difference > .1)),
            "fraction_bins_over_1db": float(np.mean(difference > 1)),
            "active_bins_rmse_db": rms(difference[active]) if active.any() else 0.}


def ranked_neighbors(features, mean, std):
    z = (features - mean) / std
    z /= np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)
    similarity = z @ z.T
    np.fill_diagonal(similarity, -np.inf)
    order = np.argsort(-similarity, axis=1, kind="stable")[:, :5]
    return order, similarity


def retrieval_summary(reference, comparison):
    mean = reference.mean(axis=0)
    std = reference.std(axis=0)
    std[std < 1e-12] = 1.
    baseline, similarity = ranked_neighbors(reference, mean, std)
    changed, _ = ranked_neighbors(comparison, mean, std)
    matches = baseline[:, 0] == changed[:, 0]
    overlaps = np.array([len(set(a) & set(b)) / 5 for a, b in zip(baseline, changed)])
    rows = np.arange(len(reference))
    regret = similarity[rows, baseline[:, 0]] - similarity[rows, changed[:, 0]]
    return {"queries": len(reference), "self_matches_excluded": True,
            "scaler": "FLOAT corpus mean/std reused in both arms; descriptive audit, not learned-model evaluation",
            "top1_agreement_fraction": float(matches.mean()), "top5_overlap_fraction": describe(overlaps),
            "mean_top5_overlap_fraction": float(overlaps.mean()),
            "float_similarity_loss_of_changed_top1": describe(regret),
            "engineering_review": bool(matches.mean() < .99 or overlaps.mean() < .98)}


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/restricted_bend_sustain_v4.csv")
    parser.add_argument("--bundle", type=Path, default=ROOT / "data/processed/c1_pilot_v1/bundle.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    manifest_hash, bundle_hash = sha(args.manifest), sha(args.bundle)
    with args.manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    selected = {s["source_sample_id"]: s for s in bundle["samples"].values()}
    largest_gain = max(s["gain"] for s in selected.values())
    c3settings = c3.feature_settings({"sample_rate": RATE})
    c3bank = c3.mel_filterbank(RATE, 2048, c3settings["n_mels"], c3settings["f_min_hz"], c3settings["f_max_hz"])
    c3basis = c3.dct_basis(c3settings["n_mfcc"], c3settings["n_mels"])
    c2bank = c2.create_mel_filterbank(RATE, 2048, 64, 20., 20000.)
    window = np.hanning(2048).astype(np.float32)
    features = {m: {"c1_full": [], "c1_held": [], "c3": []} for m in ("float", *METHODS)}
    c2errors = {m: [] for m in METHODS}
    wave_rows, study_rows, study_features = [], [], {m: [] for m in ("float", *METHODS)}
    verified = []
    probe = np.array([-2., -1., -.1, -1e-10, 0., 1e-10, .1, 32767/32768, 1., 2.])
    self_checks = {m: encode(probe, m).tolist() for m in METHODS}
    assert np.array_equal(encode(np.array([-.5, 0., .5])), [-.5, 0., .5])
    assert encode(np.array([-1e-10]), "pcm16_nearest")[0] == 0.
    assert encode(np.array([2.]))[0] == 32767/32768
    assert encode(np.array([-2.]))[0] == -1.

    for index, row in enumerate(rows):
        path = ROOT / row["audio_path"]
        if sha(path) != row["audio_sha256"]:
            raise ValueError(f"Source hash mismatch: {path}")
        verified.append((path, row["audio_sha256"]))
        audio, rate = sf.read(path, dtype="float64")
        assert rate == RATE and audio.shape == (132300,) and np.isfinite(audio).all()
        assert sf.info(path).subtype == "FLOAT"
        variants = {"float": audio, **{m: encode(audio, m) for m in METHODS}}
        float_logmel = c2.extract_log_mel(audio, window, c2bank, 2048, 512, 80.)
        for method, signal in variants.items():
            for scope, cut in (("c1_full", signal), ("c1_held", signal[:HELD])):
                result = extract_features(cut, RATE, 2048, 512)
                features[method][scope].append([result[name] for name in FEATURES])
            features[method]["c3"].append(c3.extract_mfcc_summary(signal, c3settings, c3bank, c3basis))
            if method == "float":
                continue
            metrics = error_metrics(audio, signal)
            sample = {"sample_id": row["sample_id"], "method": method,
                      "reference_rms_dbfs": db(rms(audio)), "reference_peak": float(np.max(np.abs(audio))),
                      "source_samples_outside_pcm_range": int(np.count_nonzero((audio < -1) | (audio > 1-2**(-15 if method != 'pcm24_current' else -23)))),
                      "encoded_rail_samples": int(np.count_nonzero((signal == -1) | (signal == 1-2**(-15 if method != 'pcm24_current' else -23)))),
                      **metrics,
                      "stress_gain_db": db(largest_gain),
                      "stress_error_rms_dbfs": db(rms((signal-audio)*largest_gain)),
                      "stress_reference_peak": float(np.max(np.abs(audio))*largest_gain),
                      "stress_pcm_headroom_exceeded": bool(np.max(np.abs(audio))*largest_gain >= 1),
                      "last_50ms_nonzero_fraction": float(np.mean(signal[-2205:] != 0))}
            logerror = logmel_error(float_logmel, c2.extract_log_mel(signal, window, c2bank, 2048, 512, 80.))
            c2errors[method].append(logerror)
            sample.update({"c2_"+k: v for k, v in logerror.items()})
            wave_rows.append(sample)
        if row["sample_id"] in selected:
            entry = selected[row["sample_id"]]
            gain = entry["gain"]
            # Current FLOAT-master path versus an early PCM master, then the SAME
            # gain and final participant PCM16 export. No gain refitting allowed.
            reference = audio * gain
            reference_play = encode(reference)
            stored_path = args.bundle.parent / entry["playback_path"]
            stored, _ = sf.read(stored_path)
            assert sha(stored_path) == entry["playback_sha256"]
            assert np.array_equal(reference_play, stored)
            verified.append((stored_path, entry["playback_sha256"]))
            study_features["float"].append(list(extract_features(reference, RATE, 2048, 512).values()))
            for method in METHODS:
                early_pcm = variants[method] * gain
                final_pcm = encode(early_pcm)
                result = {"sound_id": entry["sample_id"], "source_id": row["sample_id"], "method": method, "gain_db": db(gain),
                          "float_reference_peak": float(np.max(np.abs(reference))),
                          "early_pcm_peak": float(np.max(np.abs(early_pcm))),
                          **error_metrics(reference, early_pcm),
                          **{"final_vs_current_playback_"+k: v for k, v in error_metrics(reference_play, final_pcm).items()}}
                study_rows.append(result)
                study_features[method].append(list(extract_features(early_pcm, RATE, 2048, 512).values()))
        if (index + 1) % 64 == 0:
            print(f"Audited {index+1}/{len(rows)} candidates in {time.perf_counter()-started:.1f}s", flush=True)

    summary = {"candidate_count": len(rows), "selected_count": len(selected), "manifest_sha256": manifest_hash,
               "bundle_sha256": bundle_hash, "sample_rate": RATE, "largest_observed_study_gain_db": db(largest_gain),
               "encoder_probe_input": probe.tolist(), "encoder_probe_output": self_checks,
               "method": {"reference": "Existing DC-conditioned FLOAT masters; no new filtering, gain or rendering",
                          "pcm16_current": "Direct soundfile PCM_16 export, matching current code; no added dither",
                          "pcm16_nearest": "Diagnostic explicit round-to-nearest/ties-to-even integer export; no dither",
                          "pcm24_current": "Diagnostic direct soundfile PCM_24 export; no added dither",
                          "gain_stress": "Apply +max observed gain to reference and encoded arrays without clipping; separately count lost headroom. Not a proposed gain policy.",
                          "c1_held": "First 1.5 seconds only as a tail-sensitivity diagnostic; not a replacement feature definition",
                          "engineering_review_thresholds": "Advisory only, not hearing thresholds: feature p95 >0.05 corpus SD or max >0.10 SD; C3 top1 agreement <99% or mean top5 overlap <98%. No automatic dataset acceptance.",
                          "limitations": "No trained 13-control C1/C2 performance or human equivalence tested; no extrapolation guarantee for the full 131072 pool; future descriptors/dither policies need separate validation."},
               "versions": {p: version(p) for p in ("numpy", "scipy", "soundfile", "torch")},
               "python": platform.python_version(), "libsndfile": sf.__libsndfile_version__,
               "implementation_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), ROOT/'c1_timbre/feature_extraction.py', ROOT/'c2_estimation/pipeline.py', ROOT/'c3_recommendation/pipeline.py')},
               "methods": {}}
    arrays = {}
    for method in ("float", *METHODS):
        for scope, entries in features[method].items():
            arrays[f"{method}_{scope}"] = np.asarray(entries)
    for method in METHODS:
        wavs = [r for r in wave_rows if r['method'] == method]
        selected_rows = [r for r in study_rows if r['method'] == method]
        info = {"waveform": {k: describe([r[k] for r in wavs]) for k in ("reference_rms_dbfs", "reference_peak", "error_rms_dbfs", "error_peak", "held_snr_db", "error_mean", "held_level_change_db", "stress_error_rms_dbfs")},
                "clips_outside_pcm_range": sum(r['source_samples_outside_pcm_range'] > 0 for r in wavs),
                "clips_with_encoded_rail_samples": sum(r['encoded_rail_samples'] > 0 for r in wavs),
                "clips_losing_headroom_at_global_stress_gain": sum(r['stress_pcm_headroom_exceeded'] for r in wavs),
                "c2": {k: describe([r[k] for r in c2errors[method]]) for k in c2errors[method][0]},
                "c3_retrieval": retrieval_summary(arrays['float_c3'], arrays[f'{method}_c3']),
                "actual_study_gain": {k: describe([r[k] for r in selected_rows]) for k in ('error_rms_dbfs','held_snr_db','early_pcm_peak','final_vs_current_playback_error_rms_dbfs','final_vs_current_playback_held_snr_db')},
                "actual_study_c1": feature_summary(np.asarray(study_features['float']), np.asarray(study_features[method]), FEATURES)}
        for scope in ("c1_full", "c1_held", "c3"):
            names = c3.feature_names(c3settings['n_mfcc']) if scope == 'c3' else FEATURES
            info[scope] = feature_summary(arrays[f'float_{scope}'], arrays[f'{method}_{scope}'], names)
        summary['methods'][method] = info

    # Verify every inspected production WAV and input manifest/bundle after work.
    assert sha(args.manifest) == manifest_hash and sha(args.bundle) == bundle_hash
    assert all(sha(path) == expected for path, expected in verified)
    summary['verified_input_files_unchanged'] = len(verified) + 2
    summary['elapsed_seconds'] = time.perf_counter() - started
    write_csv(args.output/'waveform_errors.csv', wave_rows)
    write_csv(args.output/'selected_playback_errors.csv', study_rows)
    np.savez_compressed(args.output/'paired_features.npz', sample_ids=np.array([r['sample_id'] for r in rows]), **arrays)
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(f"Finished: {args.output/'summary.json'} ({summary['elapsed_seconds']:.1f}s)", flush=True)


if __name__ == '__main__':
    main()
