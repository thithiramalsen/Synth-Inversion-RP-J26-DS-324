"""Generate a SIMULATED C1 pilot response dataset for engineering only.

No human listened to anything to produce these files. Ratings come from a
documented artificial rule applied to the real study audio, plus simulated
listener offsets, scale use, noise, unclear answers, fatigue and corrections.
They exercise loaders, aggregation, splits, models and reports while ethics
approval is pending. They are not perceptual evidence and must never be merged
with approved human responses or counted as participants.

The design follows the frozen pilot exactly: the deployed bundle's 26 balanced
assignment blocks, 3 practice + 20 unique study sounds per person, a break after
study sound 10, and 16 completed sessions (blocks 01-16 -> 5 listeners for each
of the 64 study sounds). The responses file uses the real C1 export columns so
the same loaders can later read real data.

Example:
    .\\venv\\Scripts\\python.exe -B c1_timbre/simulate_pilot_ratings.py --seed 20261014
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

GENERATOR_VERSION = "c1_pilot_sim_v1"
SIM_STUDY_ID = "c1_pilot_SIMULATED_v1"
LABEL_SOURCE = "simulated"
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
ROOT = Path(__file__).resolve().parents[1]

# Listener-model settings. These are assumptions chosen to look like typical
# 1-7 listening data; the real pilot is what will measure them.
NOISE_SD = dict(brightness=0.75, roughness=1.05, percussiveness=0.70, sustainedness=0.85)
UNCLEAR_RATE = dict(brightness=0.015, roughness=0.06, percussiveness=0.02, sustainedness=0.035)
BIAS_SD = 0.45            # listener offset per descriptor (score units)
SCALE_USE_SD = 0.15       # log-sd of how widely a listener uses the scale
SOUND_EFFECT_SD = 0.40    # perceptual deviation per sound not explained by the proxy features
HALO_SD = 0.25            # per-trial shift shared by all four descriptors
FATIGUE_PER_TRIAL = 0.015 # relative noise increase per study position
LATENT_SPREAD = 1.25      # score units per standard deviation of a proxy
CORRECTION_RATE = 0.03
P_ROUGH_CONFUSES_BRIGHT = 0.20   # listener partly reads "roughness" as treble/harshness
P_SUSTAIN_AS_OPPOSITE = 0.25     # listener partly treats sustainedness as non-percussive


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bundle", type=Path, default=ROOT / "survey/deploy/study/bundle.json")
    p.add_argument("--config", type=Path, default=ROOT / "survey/config/c1_pilot_20_v1.json")
    p.add_argument("--output-dir", type=Path, default=ROOT / "c1_timbre/simulated" / GENERATOR_VERSION)
    p.add_argument("--participants", type=int, default=16, help="completed sessions (blocks issued in order)")
    p.add_argument("--seed", type=int, default=20261014)
    p.add_argument("--no-incomplete", action="store_true",
                   help="omit the abandoned and withdrawn example sessions")
    p.add_argument("--start-date", default="2026-11-02T09:00:00+00:00",
                   help="fictional first session time (ISO 8601)")
    p.add_argument("--study-id", default=SIM_STUDY_ID)
    p.add_argument("--generator-version", default=GENERATOR_VERSION)
    p.add_argument("--file-prefix", default="c1_pilot", help="responses file name prefix")
    p.add_argument("--truth-reference", type=Path, default=None,
                   help="simulation_ground_truth.csv of an earlier simulation; shared sounds keep their truth")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    for name in ("bundle", "config", "output_dir", "truth_reference"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    return args


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- proxy features
def db(x):
    return 20 * np.log10(np.maximum(x, 1e-10))


def rms_envelope(audio, sr, window_s=0.010):
    hop = int(sr * window_s)
    frames = len(audio) // hop
    env = np.sqrt(np.mean(audio[: frames * hop].reshape(frames, hop) ** 2, axis=1))
    return env, hop / sr


def proxy_features(audio: np.ndarray, sr: int) -> dict[str, float]:
    """Energy-gated proxies used ONLY to drive the simulation.

    Frames more than 50 dB below the loudest frame are ignored and spectral bins
    more than 60 dB below each frame's peak are zeroed, so near-silent tails and
    PCM16 quantization cannot dominate (the known baseline-extractor problem).
    """
    n_fft, hop = 2048, 512
    _, _, spec = signal.stft(audio, sr, window="hann", nperseg=n_fft, noverlap=n_fft - hop,
                             boundary=None, padded=False)
    power = np.abs(spec) ** 2
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    frame_energy = power.sum(axis=0)
    keep = db(np.sqrt(frame_energy)) > db(np.sqrt(frame_energy.max())) - 50
    p = power[:, keep]
    p = np.where(p >= p.max(axis=0, keepdims=True) * 1e-6, p, 0.0)
    centroid = (freqs[:, None] * p).sum(axis=0) / np.maximum(p.sum(axis=0), 1e-20)
    weights = frame_energy[keep] / frame_energy[keep].sum()
    log_centroid = float(np.sum(weights * np.log2(np.maximum(centroid, 20.0))))

    env, dt = rms_envelope(audio, sr)
    env_db = db(env)
    peak_i = int(np.argmax(env))
    peak_db = env_db[peak_i]
    attack_s = max(peak_i * dt, 0.002)
    body = env_db[int(0.4 / dt): int(1.4 / dt)]
    held_drop_db = float(np.clip(peak_db - np.median(body), 0, 60))
    tail = env[int(1.6 / dt): int(2.4 / dt)]
    tail_rel_db = float(np.clip(db(np.sqrt(np.mean(tail ** 2))) - peak_db, -80, 0))

    # Amplitude modulation in the roughness range (15-150 Hz) during the held body.
    seg = audio[int(0.2 * sr): int(1.45 * sr)]
    am_env = np.abs(signal.hilbert(seg))
    sos_lp = signal.butter(4, 300, "low", fs=sr, output="sos")
    am_env = signal.sosfiltfilt(sos_lp, am_env)[:: sr // 1000]  # ~1 kHz envelope
    sos_bp = signal.butter(2, [15, 150], "bandpass", fs=1000, output="sos")
    am = signal.sosfiltfilt(sos_bp, am_env)
    am_index = float(np.std(am) / max(np.mean(am_env), 1e-10))

    return dict(log2_centroid=log_centroid, centroid_hz=float(2 ** log_centroid),
                attack_s=float(attack_s), held_drop_db=held_drop_db, tail_rel_db=tail_rel_db,
                am_index=am_index)


def zscore(values, ref):
    ref = np.asarray(ref, float)
    return (np.asarray(values, float) - ref.mean()) / ref.std(ddof=0)


PROXY_KEYS = ("log2_centroid", "am_index", "attack_s", "held_drop_db", "tail_rel_db")


def _combined_proxies(cols: dict, ref: dict) -> dict:
    """Descriptor proxies for `cols`, with every inner z-score relative to `ref`."""
    z = lambda key, f=lambda x: x: zscore(f(cols[key]), f(ref[key]))
    return dict(
        brightness=z("log2_centroid"),
        roughness=z("am_index", lambda x: np.log(x + 1e-3)),
        percussiveness=0.5 * z("attack_s", lambda x: -np.log(x)) + 0.5 * z("held_drop_db"),
        sustainedness=0.7 * z("held_drop_db", lambda x: -x) + 0.3 * z("tail_rel_db"),
    )


def latent_means(features: dict[str, dict], study_ids: list[str], rng, sources=None, reference=None) -> dict[str, dict]:
    """Artificial rule: proxy z-scores -> descriptor means on the 1-7 scale.

    Without `reference`, z-scores are relative to this study's sounds (the pilot
    simulation). With `reference` (rows of an earlier simulation_ground_truth.csv),
    the scale is anchored to that study's sounds and any sound sharing a source ID
    keeps its earlier per-sound effect, so the same sound has the same "truth".
    """
    ids = list(features)
    cols = {k: np.array([features[s][k] for s in ids], float) for k in PROXY_KEYS}
    study_mask = np.array([s in study_ids for s in ids])
    if reference is None:
        ref = {k: v[study_mask] for k, v in cols.items()}
    else:
        ref = {k: np.array([float(r[k]) for r in reference if r["role"] == "study"]) for k in PROXY_KEYS}
    current, ref_comb = _combined_proxies(cols, ref), _combined_proxies(ref, ref)
    known = {r["source_sample_id"]: r for r in reference or []}
    out = {s: {} for s in ids}
    for trait, values in current.items():
        values = zscore(values, ref_comb[trait])  # re-standardize the combined proxies
        sound_effect = rng.normal(0, SOUND_EFFECT_SD, len(ids))
        for i, s in enumerate(ids):
            proxy_mean = 4 + LATENT_SPREAD * values[i]
            effect = sound_effect[i]
            prior = known.get(sources[s]) if sources else None
            if prior is not None:
                effect = float(prior[f"{trait}_true_mean"]) - float(prior[f"{trait}_proxy_mean"])
            out[s][f"{trait}_proxy_mean"] = float(np.clip(proxy_mean, 1.3, 6.7))
            out[s][f"{trait}_true_mean"] = float(np.clip(proxy_mean + effect, 1.2, 6.8))
    return out


# ---------------------------------------------------------------- listeners
def make_listener(rng, index: int) -> dict:
    return dict(
        participant_id=f"SIM_P{index:03d}",
        bias={t: float(rng.normal(0, BIAS_SD)) for t in TRAITS},
        scale_use=float(np.exp(rng.normal(0, SCALE_USE_SD))),
        noise={t: float(NOISE_SD[t] * np.exp(rng.normal(0, 0.2))) for t in TRAITS},
        unclear_propensity=float(np.exp(rng.normal(0, 0.6))),
        rough_bright_mix=float(rng.uniform(0.25, 0.45)) if rng.random() < P_ROUGH_CONFUSES_BRIGHT else 0.0,
        sustain_opposite_mix=float(rng.uniform(0.2, 0.4)) if rng.random() < P_SUSTAIN_AS_OPPOSITE else 0.0,
        replay_rate=float(rng.uniform(0.15, 0.8)),
        pace=float(np.exp(rng.normal(0, 0.25))),
    )


def rate(listener, mu: dict, position: int, practice: bool, rng) -> dict:
    """One trial's four answers: ints 1-7 or 'unclear'."""
    m = dict(mu)
    m["roughness"] = (1 - listener["rough_bright_mix"]) * m["roughness"] + listener["rough_bright_mix"] * m["brightness"]
    m["sustainedness"] = ((1 - listener["sustain_opposite_mix"]) * m["sustainedness"]
                          + listener["sustain_opposite_mix"] * (8 - m["percussiveness"]))
    halo = rng.normal(0, HALO_SD)
    fatigue = 1 + FATIGUE_PER_TRIAL * position
    answers = {}
    for t in TRAITS:
        p_unclear = UNCLEAR_RATE[t] * listener["unclear_propensity"] * (1.5 if practice else 1.0)
        if rng.random() < min(p_unclear, 0.5):
            answers[t] = "unclear"
            continue
        value = (4 + listener["scale_use"] * (m[t] + listener["bias"][t] - 4)
                 + halo + rng.normal(0, listener["noise"][t] * fatigue))
        answers[t] = int(np.clip(np.rint(value), 1, 7))
    return answers


# ---------------------------------------------------------------- sessions
def iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def simulate_session(listener, block, mus, cfg, headphones, start, rng, session_index, fate="complete"):
    """fate: complete | abandoned | withdrawn."""
    sid = f"SIM_S{session_index:03d}"
    activities = cfg["eligibility"]["activities"]
    chosen = list(rng.choice(activities, size=int(rng.integers(1, 3)), replace=False))
    entry = dict(adult=True, consent=True, headphones=True, quiet_environment=True, understands_language=True,
                 activities=chosen, experience_months=int(rng.integers(12, 180)),
                 recent_frequency=str(rng.choice(["Less than monthly", "Monthly", "Weekly", "Daily"], p=[.1, .25, .4, .25])),
                 tools="SIMULATED participant - no real tools reported",
                 example="SIMULATED participant record generated for engineering tests only.")
    t = start + timedelta(seconds=float(rng.uniform(60, 150)))  # consent + volume
    screens = []
    for screen in rng.permutation(np.array(headphones, dtype=object)):
        t += timedelta(seconds=float(rng.uniform(8, 20)))
        correct = bool(rng.random() < 0.97) or len(screens) - sum(s["correct"] for s in screens) >= 1
        answer = screen["correct_interval"] if correct else int(rng.choice(
            [i for i in (1, 2, 3) if i != screen["correct_interval"]]))
        screens.append(dict(screen_id=screen["screen_id"], interval=answer, completed_plays=1,
                            correct=correct, submitted_at=iso(t)))  # at most one miss: cohort passes 5/6

    trials = block["trials"]
    stop_after = len(trials) if fate != "abandoned" else 3 + int(rng.integers(4, 10))
    rows, corrections = [], []
    study_pos = 0
    for order, trial in enumerate(trials[:stop_after]):
        practice = trial["kind"] == "practice"
        if not practice:
            study_pos += 1
        if not practice and study_pos == cfg["break_after_rated"] + 1:
            t += timedelta(seconds=float(rng.uniform(45, 300)))  # break
        plays = 1 + int(rng.poisson(listener["replay_rate"] * (1.4 if practice else 1.0)))
        completed = plays if rng.random() > 0.08 else max(1, plays - 1)
        started = t
        duration = 3.0 * plays + float(rng.lognormal(np.log(28 if not practice else 40), 0.35)) * listener["pace"]
        t += timedelta(seconds=duration)
        answers = rate(listener, mus[trial["sample_id"]], study_pos, practice, rng)
        first = dict(answers)
        revision = []
        if rng.random() < CORRECTION_RATE:
            trait = str(rng.choice(TRAITS))
            if first[trait] != "unclear":
                first[trait] = int(np.clip(first[trait] + rng.choice([-1, 1]), 1, 7))
                if first[trait] != answers[trait]:
                    corrected_at = t + timedelta(seconds=float(rng.uniform(5, 20)))
                    revision.append(dict(correction_id=None, session_id=sid, presentation_id=trial["presentation_id"],
                                         answers_json=json.dumps({**answers, "comment": ""}),
                                         play_count=plays, completed_plays=completed,
                                         started_at=iso(t), submitted_at=iso(corrected_at)))
                    t = corrected_at
        rows.append(dict(sid=sid, trial=trial, order=order, answers=answers, first=first, plays=plays,
                         completed=completed, started=iso(started), submitted=iso(t), revisions=revision))
        corrections.extend(revision)

    completed_at = withdrawn_at = None
    feedback = None
    if fate == "abandoned":
        phase = "rating"
    else:
        t += timedelta(seconds=float(rng.uniform(30, 90)))
        completed_at = iso(t)
        phase = "complete"
        feedback = dict(clarity=str(rng.choice(["Clear", "Some terms unclear", "Difficult to understand"], p=[.6, .35, .05])),
                        length=str(rng.choice(["About right", "Too long", "Could be longer"], p=[.75, .2, .05])),
                        comment="")
        if fate == "withdrawn":
            withdrawn_at = iso(t + timedelta(minutes=float(rng.uniform(2, 60))))
    session = dict(participant_id=listener["participant_id"], session_id=sid, assignment_id=block["assignment_id"],
                   phase=phase, current_index=len(rows), started_at=iso(start), completed_at=completed_at,
                   withdrawn_at=withdrawn_at, entry_json=json.dumps(entry), screen_answers=json.dumps(screens),
                   feedback_json=json.dumps(feedback) if feedback else "", fate=fate)
    return session, rows, corrections


# ---------------------------------------------------------------- main
EXPORT_COLUMNS = ["participant_id", "participant_label", "session_id", "study_id", "bundle_hash", "protocol_hash",
                  "descriptor_ids", "assignment_id", "presentation_id", "sample_id", "kind", "repeat_of", "trial_order",
                  "phase", "analysis_include", "brightness", "roughness", "percussiveness", "sustainedness", "comment",
                  "play_count", "completed_plays", "started_at", "submitted_at", "completed_at", "withdrawn_at",
                  "entry_json", "screen_answers", "feedback_json", "brightness_first", "roughness_first",
                  "percussiveness_first", "sustainedness_first", "comment_first", "revision_count", "corrections_json",
                  # Provenance columns not in the real export; they keep simulated rows identifiable.
                  "source_sample_id", "label_source", "generator_version", "seed"]


def _repeat_summary(included):
    """Within-listener test-retest from hidden repeats (empty when the design has none)."""
    by_key = {(r["session_id"], r["presentation_id"]): r for r in included}
    diffs = []
    for r in included:
        if r["kind"] != "repeat":
            continue
        first = by_key[(r["session_id"], r["repeat_of"])]
        diffs += [abs(r[t] - first[t]) for t in TRAITS if r[t] != "unclear" and first[t] != "unclear"]
    if not diffs:
        return None
    d = np.array(diffs)
    return dict(pairs=len(d), median=float(np.median(d)), within_one=float(np.mean(d <= 1)))


def write_csv(path: Path, rows: list[dict], columns: list[str]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in columns})


def main():
    args = parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise FileExistsError(f"{out} is not empty; pass --overwrite or choose another --output-dir")
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if [d["id"] for d in cfg["descriptors"]] != list(TRAITS):
        raise ValueError("Protocol descriptors differ from this simulator")
    bundle_hash, protocol_hash = sha256_file(args.bundle), sha256_file(args.config)
    blocks = bundle["assignments"]
    if args.participants > len(blocks):
        raise ValueError(f"Only {len(blocks)} assignment blocks exist")

    samples = bundle["samples"]
    audio_dir = args.bundle.parent
    study_ids = sorted({t["sample_id"] for b in blocks for t in b["trials"] if t["kind"] == "primary"})
    features = {}
    for sid, info in sorted(samples.items()):
        path = audio_dir / info["playback_path"]
        if sha256_file(path) != info["playback_sha256"]:
            raise ValueError(f"Audio hash mismatch for {sid}")
        audio, sr = sf.read(path, dtype="float64")
        features[sid] = proxy_features(audio, sr)
    reference = None
    if args.truth_reference:
        with args.truth_reference.open(newline="", encoding="utf-8") as f:
            reference = list(csv.DictReader(f))
    sources = {s: samples[s]["source_sample_id"] for s in samples}
    latent = latent_means(features, study_ids, rng, sources, reference)
    mus = {s: {t: latent[s][f"{t}_true_mean"] for t in TRAITS} for s in latent}

    # Completed sessions use blocks in issue order; optional failures use the next blocks.
    plan = [(blocks[i], "complete") for i in range(args.participants)]
    if not args.no_incomplete:
        extra = blocks[args.participants: args.participants + 2]
        plan[3:3] = [(extra[0], "abandoned")]  # realistic interleaving in time
        plan[9:9] = [(extra[1], "withdrawn")]
    start = datetime.fromisoformat(args.start_date)
    sessions, ratings, corrections, listeners = [], [], [], []
    for n, (block, fate) in enumerate(plan, 1):
        listener = make_listener(rng, n)
        listeners.append(listener)
        start += timedelta(hours=float(rng.uniform(3, 20)))
        s, r, c = simulate_session(listener, block, mus, cfg, bundle["headphones"], start, rng, n, fate)
        s["listener_number"] = n
        sessions.append(s)
        ratings.extend((s, row) for row in r)
        corrections.extend(c)
    for i, c in enumerate(corrections, 1):
        c["correction_id"] = i

    export = []
    for s, row in ratings:
        trial = row["trial"]
        include = s["phase"] == "complete" and not s["withdrawn_at"] and trial["kind"] != "practice"
        export.append(dict(
            participant_id=s["participant_id"], participant_label=f"Listener {s['listener_number']:03d}",
            session_id=s["session_id"], study_id=args.study_id, bundle_hash=bundle_hash, protocol_hash=protocol_hash,
            descriptor_ids=json.dumps(list(TRAITS)), assignment_id=s["assignment_id"],
            presentation_id=trial["presentation_id"], sample_id=trial["sample_id"], kind=trial["kind"],
            repeat_of=trial["repeat_of"] or "", trial_order=row["order"], phase=s["phase"], analysis_include=include,
            **{t: row["answers"][t] for t in TRAITS}, comment="",
            play_count=row["plays"], completed_plays=row["completed"], started_at=row["started"],
            submitted_at=row["submitted"], completed_at=s["completed_at"] or "", withdrawn_at=s["withdrawn_at"] or "",
            entry_json=s["entry_json"], screen_answers=s["screen_answers"], feedback_json=s["feedback_json"],
            **{f"{t}_first": row["first"][t] for t in TRAITS}, comment_first="",
            revision_count=len(row["revisions"]), corrections_json=json.dumps(row["revisions"]),
            source_sample_id=samples[trial["sample_id"]]["source_sample_id"],
            label_source=LABEL_SOURCE, generator_version=args.generator_version, seed=args.seed))
    write_csv(out / f"{args.file_prefix}_responses_SIMULATED.csv", export, EXPORT_COLUMNS)

    session_cols = ["participant_id", "participant_label", "session_id", "study_id", "bundle_hash", "protocol_hash",
                    "assignment_id", "phase", "current_index", "started_at", "completed_at", "withdrawn_at",
                    "entry_json", "screen_answers", "feedback_json", "simulated_fate", "label_source", "seed"]
    write_csv(out / "c1_sessions_SIMULATED.csv",
              [dict(s, participant_label=f"Listener {s['listener_number']:03d}", study_id=args.study_id,
                    bundle_hash=bundle_hash, protocol_hash=protocol_hash, simulated_fate=s["fate"],
                    label_source=LABEL_SOURCE, seed=args.seed) for s in sessions], session_cols)

    # Per-sound targets from included study ratings (unclear = missing).
    included = [r for r in export if r["analysis_include"]]
    primary = [r for r in included if r["kind"] == "primary"]  # hidden repeats are not extra listeners
    target_rows = []
    for sid in study_ids:
        row = dict(sample_id=sid, source_sample_id=samples[sid]["source_sample_id"])
        mine = [r for r in primary if r["sample_id"] == sid]
        row["listener_count"] = len(mine)
        for t in TRAITS:
            vals = np.array([r[t] for r in mine if r[t] != "unclear"], float)
            row.update({f"{t}_mean": round(vals.mean(), 4) if len(vals) else "",
                        f"{t}_median": float(np.median(vals)) if len(vals) else "",
                        f"{t}_sd": round(vals.std(ddof=1), 4) if len(vals) > 1 else "",
                        f"{t}_n_valid": len(vals), f"{t}_n_unclear": len(mine) - len(vals)})
        row.update(label_source=LABEL_SOURCE, generator_version=args.generator_version, seed=args.seed)
        target_rows.append(row)
    write_csv(out / "c1_sound_targets_SIMULATED.csv", target_rows, list(target_rows[0]))

    truth_rows = [dict(sample_id=s, source_sample_id=samples[s]["source_sample_id"],
                       role="study" if s in study_ids else "practice",
                       **{k: round(v, 6) for k, v in features[s].items()},
                       **{k: round(v, 4) for k, v in latent[s].items()},
                       **samples[s]["parameters"]) for s in sorted(samples)]
    write_csv(out / "simulation_ground_truth.csv", truth_rows, list(truth_rows[0]))

    listener_rows = [dict(participant_id=l["participant_id"], fate=s["fate"], assignment_id=s["assignment_id"],
                          scale_use=round(l["scale_use"], 4), unclear_propensity=round(l["unclear_propensity"], 4),
                          rough_bright_mix=round(l["rough_bright_mix"], 4),
                          sustain_opposite_mix=round(l["sustain_opposite_mix"], 4),
                          **{f"bias_{t}": round(l["bias"][t], 4) for t in TRAITS},
                          **{f"noise_sd_{t}": round(l["noise"][t], 4) for t in TRAITS})
                     for l, s in zip(listeners, sessions)]
    write_csv(out / "simulation_listeners.csv", listener_rows, list(listener_rows[0]))

    counts = {}
    for r in primary:
        counts[r["sample_id"]] = counts.get(r["sample_id"], 0) + 1
    summary = dict(
        WARNING="SIMULATED DATA. No human ratings. Engineering fixture only; not perceptual evidence. "
                "Never merge with approved human responses or count as participants.",
        label_source=LABEL_SOURCE, generator_version=args.generator_version, seed=args.seed, study_id=args.study_id,
        created_utc=iso(datetime.now(timezone.utc)), protocol_version=cfg["protocol_version"],
        bundle=str(args.bundle.relative_to(ROOT)), bundle_sha256=bundle_hash,
        protocol=str(args.config.relative_to(ROOT)), protocol_sha256=protocol_hash,
        completed_sessions=sum(s["fate"] == "complete" for s in sessions),
        excluded_sessions={s["session_id"]: s["fate"] for s in sessions if s["fate"] != "complete"},
        included_study_evaluations=len(primary), included_hidden_repeats=len(included) - len(primary),
        repeat_abs_difference=_repeat_summary(included),
        truth_reference=str(args.truth_reference.relative_to(ROOT)) if args.truth_reference else None, unique_study_sounds=len(counts),
        listeners_per_sound=sorted(set(counts.values())),
        unclear_fraction={t: round(sum(r[t] == "unclear" for r in included) / len(included), 4) for t in TRAITS},
        corrections=len(corrections),
        rule=dict(
            brightness="energy-weighted log2 spectral centroid (gated frames, -60 dB bin floor)",
            roughness="log 15-150 Hz amplitude-modulation index of the 0.2-1.45 s body",
            percussiveness="0.5*z(-log attack time) + 0.5*z(peak-to-body level drop)",
            sustainedness="0.7*z(-peak-to-body drop) + 0.3*z(1.6-2.4 s tail level)",
            mapping=f"mean = 4 + {LATENT_SPREAD}*z, plus per-sound effect sd {SOUND_EFFECT_SD}, clipped",
            listener=dict(bias_sd=BIAS_SD, scale_use_log_sd=SCALE_USE_SD, noise_sd=NOISE_SD, halo_sd=HALO_SD,
                          fatigue_per_trial=FATIGUE_PER_TRIAL, unclear_rate=UNCLEAR_RATE,
                          p_rough_confuses_bright=P_ROUGH_CONFUSES_BRIGHT,
                          p_sustain_as_opposite=P_SUSTAIN_AS_OPPOSITE, correction_rate=CORRECTION_RATE),
            rating="round(4 + scale_use*(mean + bias - 4) + halo + noise), clipped to 1-7"),
        audio_source="PCM16 playback files (what participants would hear); hashes checked against the bundle",
    )
    (out / "simulation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("completed_sessions", "excluded_sessions", "included_study_evaluations",
                                               "unique_study_sounds", "listeners_per_sound", "unclear_fraction",
                                               "corrections")}, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
