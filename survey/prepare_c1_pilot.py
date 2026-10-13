"""Prepare a versioned pilot bundle from existing audio; never renders the 1,024 pool.

Production: python -B -m survey.prepare_c1_pilot --manifest data/manifests/restricted_bend_sustain_v4.csv
UI rehearsal: python -B -m survey.prepare_c1_pilot --rehearsal-from-diagnostics
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import stft

from generation import bend_sustain_config as profile
from generation.audio_processing import DC_POLICY_ID, LEVEL_POLICY_ID, apply_level, audio_metrics, dc_filter, level_plan, policy_definition
from survey.design import assignments

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def acoustic_features(audio, rate):
    f, _, z = stft(audio, fs=rate, nperseg=2048, noverlap=1024, boundary=None)
    mask = f >= 40
    f, power = f[mask], np.mean(np.abs(z[mask]) ** 2, axis=1)
    power = power / max(power.sum(), 1e-30)
    energy = np.array([np.mean(audio[round(a*rate):round(b*rate)] ** 2)
                       for a, b in ((0, .2), (.2, .7), (.7, 1.5), (1.5, 3.))])
    energy /= max(energy.sum(), 1e-30)
    return [float(np.log(max(np.dot(f, power), 1))), float(power[f < 500].sum()),
            float(power[f >= 3000].sum()), float(np.exp(np.log(power + 1e-15).mean()) / power.mean()),
            *energy.tolist()]


def choose_diverse(candidates, count):
    params = np.array([[r["unit_parameters"][name] for name in profile.PARAMS] for r in candidates])
    acoustic = np.array([r["features"] for r in candidates])
    low, high = np.percentile(acoustic, [5, 95], axis=0)
    acoustic = np.clip((acoustic - low) / np.maximum(high - low, 1e-8), 0, 1)
    vectors = np.column_stack((params / np.sqrt(params.shape[1]), acoustic / np.sqrt(acoustic.shape[1])))
    selected = [int(np.argmin(np.sum((vectors - vectors.mean(axis=0)) ** 2, axis=1)))]
    distances = np.full(len(vectors), np.inf)
    while len(selected) < count:
        distances = np.minimum(distances, np.sum((vectors - vectors[selected[-1]]) ** 2, axis=1))
        distances[selected] = -1
        selected.append(int(np.argmax(distances)))
    return selected


def write_headphone_screen(directory):
    """Woods et al. 2017 geometry, six 3AFC trials, balanced interval orders."""
    rate = 44100
    tone = np.sin(2 * np.pi * 200 * np.arange(rate) / rate) * .08
    ramp = .5 - .5 * np.cos(np.linspace(0, np.pi, round(.1 * rate)))
    tone[:len(ramp)] *= ramp
    tone[-len(ramp):] *= ramp[::-1]
    ordinary = np.column_stack((tone, tone))
    quiet = ordinary * 10 ** (-6 / 20)
    antiphase = np.column_stack((tone, -tone))
    orders = ((0, 1, 2), (2, 0, 1), (1, 2, 0), (1, 0, 2), (0, 2, 1), (2, 1, 0))
    silence = np.zeros((rate // 2, 2))
    screens = []
    for i, order in enumerate(orders):
        pieces = [([quiet, ordinary, antiphase][k]) for k in order]
        audio = np.concatenate((pieces[0], silence, pieces[1], silence, pieces[2]))
        path = directory / f"headphones_{i + 1:02d}.wav"
        sf.write(path, audio, rate, subtype="PCM_16")
        screens.append(dict(screen_id=f"headphones_{i + 1:02d}", path=path.name,
                            correct_interval=order.index(0) + 1, sha256=digest(path)))
    calibration = directory / "volume_reference.wav"
    sf.write(calibration, ordinary, rate, subtype="PCM_16")
    return screens, dict(path=calibration.name, sha256=digest(calibration))


def prepare(manifest: Path, output: Path, *, rehearsal=False):
    if output.exists():
        raise FileExistsError("Existing bundle refused; use a new version/output directory")
    with manifest.open(newline="", encoding="utf-8") as handle:
        source_rows = list(csv.DictReader(handle))
    if not rehearsal:
        config = json.loads(manifest.with_name(manifest.stem + "_config.json").read_text())
        if config["dataset_name"] != profile.DATASET_NAME or config.get("audio_policy_id") != DC_POLICY_ID:
            raise ValueError("Use the selected 13-control, DC-conditioned candidate manifest")
        if config["parameters"] != profile.PARAMS:
            raise ValueError("Candidate parameter schema differs from the selected profile")
    candidates, excluded, seen = [], [], set()
    for row in source_rows:
        path = ROOT / row["raw_path" if rehearsal else "audio_path"]
        if digest(path) != row["audio_sha256"]:
            raise ValueError(f"Changed source WAV: {path}")
        audio, rate = sf.read(path, dtype="float64")
        if rate != 44100 or audio.ndim != 1 or len(audio) != 132300:
            raise ValueError("Candidate must be 3-second mono 44100 Hz")
        if rehearsal:
            raw_metrics = audio_metrics(audio)
            audio = dc_filter(audio, rate)
        else:
            if row.get("audio_policy_id") != DC_POLICY_ID:
                raise ValueError("Candidate lacks DC policy metadata")
            raw_path = ROOT / row["raw_audio_path"]
            if digest(raw_path) != row["raw_audio_sha256"]:
                raise ValueError("Changed preserved raw audio")
            raw, raw_rate = sf.read(raw_path)
            if raw_rate != rate or raw.shape != audio.shape:
                raise ValueError("Raw and conditioned candidate formats differ")
            raw_metrics = audio_metrics(raw)
        m = audio_metrics(audio)
        content_hash = hashlib.sha256(audio.astype("<f4").tobytes()).hexdigest()
        reason = ("raw_clipping" if raw_metrics["clipped"] else
                  "silent" if m["silent"] else "clipping" if m["clipped"] else
                  "DC_warning" if m["dc_warning"] else "nonquiet_tail" if m["tail_peak"] > .001 else
                  "duplicate_audio" if content_hash in seen else None)
        if reason:
            excluded.append(dict(sample_id=row["sample_id"], reason=reason))
            continue
        seen.add(content_hash)
        values = {k: float(row[k if rehearsal else k + "_normalized"]) for k in profile.PARAMS}
        if any(not np.isfinite(v) or not profile.PARAMS[k]["min"] <= v <= profile.PARAMS[k]["max"] for k, v in values.items()):
            raise ValueError("Candidate values fall outside the declared pilot domain")
        unit = {k: (v - profile.PARAMS[k]["min"]) / (profile.PARAMS[k]["max"] - profile.PARAMS[k]["min"])
                for k, v in values.items()}
        candidates.append(dict(sample_id=row["sample_id"], source_path=str(path.relative_to(ROOT)),
                          source_sha256=digest(path), values=values, unit_parameters=unit,
                          audio=audio, metrics=m, features=acoustic_features(audio, rate)))
    needed = 9 if rehearsal else 67
    if len(candidates) < needed:
        raise ValueError(f"Need at least {needed} eligible unique sounds, found {len(candidates)}")
    selected = choose_diverse(candidates, needed)
    clips = [candidates[i] for i in selected]
    plan = level_plan([c["metrics"] for c in clips])
    output.mkdir(parents=True)
    audio_dir = output / "audio"
    audio_dir.mkdir()
    samples = {}
    for i, (clip, gain) in enumerate(zip(clips, plan["gains"])):
        sample_id = f"sound_{i + 1:03d}"
        adjusted = apply_level(clip["audio"], gain, input_policy_id=DC_POLICY_ID)
        float_path = audio_dir / f"{sample_id}_features.wav"
        play_path = audio_dir / f"{sample_id}.wav"
        sf.write(float_path, adjusted, 44100, subtype="FLOAT")
        sf.write(play_path, adjusted, 44100, subtype="PCM_16")
        samples[sample_id] = dict(sample_id=sample_id, source_sample_id=clip["sample_id"],
            source_path=clip["source_path"], source_sha256=clip["source_sha256"],
            parameters=clip["values"], playback_path=f"audio/{play_path.name}",
            playback_sha256=digest(play_path), feature_path=f"audio/{float_path.name}",
            feature_sha256=digest(float_path), gain=gain, gain_db=20*np.log10(gain),
            before_level=clip["metrics"], after_level=audio_metrics(adjusted),
            policy_ids=[DC_POLICY_ID, LEVEL_POLICY_ID])
    study_ids = list(samples)[:-3]
    practice_ids = list(samples)[-3:]
    if rehearsal:
        blocks = [dict(assignment_id="rehearsal", trials=[
            dict(presentation_id=f"rated_{i+1:02d}", sample_id=s, kind="primary", repeat_of=None)
            for i, s in enumerate(study_ids)] + [dict(presentation_id="repeat_01", sample_id=study_ids[0], kind="repeat", repeat_of="rated_01")])]
    else:
        blocks = assignments(study_ids)
    for block in blocks:
        block["trials"] = [dict(presentation_id=f"practice_{i+1:02d}", sample_id=s,
                                kind="practice", repeat_of=None) for i, s in enumerate(practice_ids)] + block["trials"]
    screens, calibration = write_headphone_screen(audio_dir)
    bundle = dict(study_id="c1_rehearsal_v1" if rehearsal else "c1_pilot_v1",
                  schema_version=1, rehearsal=rehearsal, dataset_name=profile.DATASET_NAME,
                  source_manifest=str(manifest), source_manifest_sha256=digest(manifest),
                  preparation_sha256=digest(Path(__file__)), design_sha256=digest(ROOT / "survey/design.py"),
                  dc_policy=policy_definition(), level_policy=plan,
                  selection=dict(method="greedy maximin: equally weighted parameter/acoustic blocks",
                                 candidate_count=len(source_rows), eligible_count=len(candidates),
                                 study_sound_count=len(study_ids), practice_count=3, excluded=excluded,
                                 note="Diversity heuristic, not perceptual or full-domain coverage"),
                  samples=samples, assignments=blocks, headphones=screens,
                  calibration=calibration, headphone_pass_count=5, headphone_trial_count=6)
    (output / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    (output / "QA.md").write_text(
        f"# {'REHEARSAL ONLY' if rehearsal else 'C1 pilot'} audio bundle\n\n"
        f"{len(candidates)} eligible candidates; {len(study_ids)} study and 3 practice sounds. "
        f"{len(excluded)} excluded (reasons in bundle).\n\n"
        f"Fixed held-note RMS target: {plan['target_dbfs']:.2f} dBFS. "
        f"Gain range: {min(s['gain_db'] for s in samples.values()):.2f} to {max(s['gain_db'] for s in samples.values()):.2f} dB. "
        f"Peak ceiling: {plan['peak_ceiling']}. No compression or fading.\n\n"
        "Listen to the level-controlled examples before recruitment. RMS equality does not establish perceptual loudness equality. "
        "The FLOAT feature files and PCM16 playback files represent the same processed signal at different precision. "
        "Do not reapply either policy.\n\n"
        "Headphone screen: six 3AFC 200 Hz trials, 5/6 pass criterion, following Woods et al. (2017), "
        "https://doi.org/10.3758/s13414-017-1361-2 . Keep this stimulus stereo; its intentional level differences must not be normalized.\n",
        encoding="utf-8")
    return output / "bundle.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rehearsal-from-diagnostics", action="store_true")
    args = parser.parse_args()
    rehearsal = args.rehearsal_from_diagnostics
    manifest = args.manifest or (ROOT / "generation/characterization/dc_mitigation_v1/combined_settings.csv" if rehearsal else None)
    if manifest is None:
        parser.error("Provide an existing candidate manifest; this script never renders the candidate pool")
    output = args.output or ROOT / "data/processed" / ("c1_rehearsal_v1" if rehearsal else "c1_pilot_v1")
    print(prepare(manifest, output, rehearsal=rehearsal))
