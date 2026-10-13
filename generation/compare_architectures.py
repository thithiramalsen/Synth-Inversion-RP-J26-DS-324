"""Small matched A/B engineering experiment; never calls the dataset generator.

Run with the Vita environment: python -m generation.compare_architectures
Existing output directories are refused. Choose a new --run-id for a new run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import product
from pathlib import Path

import numpy as np
import soundfile as sf
import vita
from scipy.signal import stft

from generation import restricted_config as profile
from generation.characterize import rms, write_csv
from generation.vital_setup import apply_parameters, create_synth, set_sample_rate, validate_synth

ROOT = profile.PROJECT_ROOT
RATE = profile.SAMPLE_RATE
MAIN_WAVES = (0., .5, 1.)
MAIN_CUTOFFS = (.30, .575, .85)
BEND_LEVELS = (.25, .50, .75)
SUSTAIN_LEVELS = (0., .4, 1.)
BACKGROUND_SETTINGS = {
    "clean_held": dict(filter_resonance=.20, filter_drive=0., amp_attack=.10,
                       amp_decay=.30, amp_sustain=.80, amp_release=.30,
                       filter_env_amount=.53125, filter_env_attack=.20, filter_env_decay=.30),
    "resonant_held": dict(filter_resonance=.75, filter_drive=0., amp_attack=.10,
                          amp_decay=.30, amp_sustain=.80, amp_release=.30,
                          filter_env_amount=.53125, filter_env_attack=.20, filter_env_decay=.30),
    "driven_pluck": dict(filter_resonance=.20, filter_drive=.75, amp_attack=.05,
                         amp_decay=.20, amp_sustain=.20, amp_release=.15,
                         filter_env_amount=.5625, filter_env_attack=.05, filter_env_decay=.20),
    "resonant_driven_swell": dict(filter_resonance=.75, filter_drive=.75, amp_attack=.35,
                                  amp_decay=.40, amp_sustain=.80, amp_release=.45,
                                  filter_env_amount=.5625, filter_env_attack=.35, filter_env_decay=.40),
}
# These are diagnostic thresholds, never audibility/equivalence thresholds.
ACTIVITY_TOLERANCE = 1e-4
REPEAT_TOLERANCE = 1e-7
NEUTRAL_TOLERANCE = 2e-6
WINDOWS = ((0., .2), (.2, .7), (.7, 1.5))
BAND_EDGES = np.geomspace(40., 16000., 49)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: float) -> str:
    return f"{value:.3f}".replace(".", "p")


def parameters(background: str, wave: float, cutoff: float, sustain: float) -> dict:
    return dict(profile.BASE_VALUES, **dict(BACKGROUND_SETTINGS[background], wave_frame=wave,
                                           filter_cutoff=cutoff, filter_env_sustain=sustain))


def setup(architecture: str, values: dict, bend: float):
    if architecture not in ("A", "B") or not 0 <= bend <= 1:
        raise ValueError("Invalid architecture/Bend value")
    if architecture == "B" and values["filter_env_sustain"] != 0:
        raise ValueError("Configuration B must fix ENV 2 sustain at zero")
    synth = create_synth(profile)
    apply_parameters(synth, profile, values)
    controls = synth.get_controls()
    names = list(synth.get_control_details("osc_1_distortion_type").options)
    mode = names.index("Bend") if architecture == "B" else names.index("None")
    controls["osc_1_distortion_type"].set(mode)
    controls["osc_1_distortion_amount"].set_normalized(bend)
    controls["osc_1_distortion_phase"].set(.5)
    controls["osc_1_distortion_spread"].set(0.)
    controls["osc_1_spectral_morph_type"].set(0.)
    controls["osc_1_spectral_morph_amount"].set(.5)
    controls["osc_1_spectral_morph_spread"].set(0.)
    validate_settings(synth, architecture, values, bend)
    return synth


def validate_settings(synth, architecture: str, values: dict, bend: float) -> None:
    validate_synth(synth, profile)
    controls = synth.get_controls()
    for name, value in values.items():
        actual = controls[profile.PARAMS[name]["control"]].get_normalized()
        if not math.isclose(actual, value, abs_tol=2e-6):
            raise ValueError(f"Parameter did not survive wrapper/serialization: {name}")
    expected_mode = "Bend" if architecture == "B" else "None"
    if synth.get_control_text("osc_1_distortion_type") != expected_mode:
        raise ValueError("Wrong oscillator warp mode")
    for name, expected in (("osc_1_distortion_amount", bend), ("osc_1_distortion_phase", .5),
                           ("osc_1_distortion_spread", 0.), ("osc_1_spectral_morph_type", 0.),
                           ("osc_1_spectral_morph_amount", .5), ("osc_1_spectral_morph_spread", 0.)):
        if not math.isclose(controls[name].value(), expected, abs_tol=2e-6):
            raise ValueError(f"Fixed warp setting mismatch: {name}")


def render_synth(synth) -> np.ndarray:
    audio = np.asarray(synth.render(profile.MIDI_NOTE, profile.VELOCITY,
                                    profile.NOTE_DURATION, profile.RENDER_DURATION))
    if audio.shape != (2, int(RATE * profile.RENDER_DURATION)) or not np.isfinite(audio).all():
        raise ValueError("Invalid/nonfinite render")
    if np.max(np.abs(audio[0] - audio[1])) > 1e-7:
        raise ValueError("Unexpected stereo difference")
    return audio[0].copy()


def metrics(audio: np.ndarray) -> dict:
    peak, level = float(np.max(np.abs(audio))), rms(audio)
    dc = float(np.mean(audio, dtype=np.float64))
    held = rms(audio[:int(1.5 * RATE)])
    return dict(peak=peak, rms=level, rms_dbfs=20 * math.log10(max(level, 1e-12)),
                held_rms=held, dc_offset=dc, dc_to_rms=abs(dc) / max(level, 1e-12),
                is_silent=level < .001, is_clipped=peak >= 1.,
                has_dc_warning=abs(dc) >= .005 or abs(dc) / max(level, 1e-12) >= .2,
                final_50ms_peak=float(np.max(np.abs(audio[-int(.05 * RATE):]))))


def signature(audio: np.ndarray) -> tuple[np.ndarray, dict]:
    """Gain-invariant time/spectral shape; not a perceptual embedding or score."""
    features, centroids = [], []
    for start, end in WINDOWS:
        clip = audio[int(start * RATE):int(end * RATE)].astype(np.float64)
        frequencies, _, z = stft(clip, fs=RATE, window="hann", nperseg=2048, noverlap=1536,
                                 detrend="constant", boundary=None, padded=False)
        power = np.mean(np.abs(z) ** 2, axis=1)
        binned = np.array([power[(frequencies >= low) & (frequencies < high)].sum()
                           for low, high in zip(BAND_EDGES[:-1], BAND_EDGES[1:])])
        # Some low log bands have no FFT bins; these are consistently zero.
        binned /= max(float(binned.sum()), 1e-30)
        features.extend(np.sqrt(binned / len(WINDOWS)))
        useful = (frequencies >= 40) & (frequencies < 16000)
        centroids.append(float(np.sum(frequencies[useful] * power[useful]) /
                               max(float(power[useful].sum()), 1e-30)))
    return np.array(features), {f"centroid_window_{i}_hz": v for i, v in enumerate(centroids)}


def shape_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b) / math.sqrt(2))


def compare_audio(a: np.ndarray, b: np.ndarray, fa: np.ndarray, fb: np.ndarray) -> dict:
    relative = rms(a - b) / max(rms(a), rms(b), 1e-12)
    gain_a, gain_b = rms(a[:int(1.5 * RATE)]), rms(b[:int(1.5 * RATE)])
    matched = rms(a / max(gain_a, 1e-12) - b / max(gain_b, 1e-12))
    return dict(relative_waveform_difference=relative, numerically_active=relative > ACTIVITY_TOLERANCE,
                held_rms_change_db=20 * math.log10(max(gain_b, 1e-12) / max(gain_a, 1e-12)),
                rms_matched_waveform_difference=matched, spectral_shape_distance=shape_distance(fa, fb))


class Experiment:
    def __init__(self, run_id: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,60}", run_id):
            raise ValueError("Use a short lowercase alphanumeric run ID")
        self.report_dir = ROOT / "generation/characterization" / run_id
        self.audio_dir = ROOT / "generation/test_renders" / run_id
        if self.report_dir.exists() or self.audio_dir.exists():
            raise FileExistsError("Existing experiment refused; select a new --run-id")
        self.report_dir.mkdir(parents=True)
        (self.audio_dir / "raw").mkdir(parents=True)
        self.rows, self.pairs, self.checks = [], [], []
        self.cache, self.features, self.waveforms = {}, {}, {}
        self.main_groups = []
        self.render_calls = 0

    def add(self, architecture, background, wave, cutoff, *, sustain=0., bend=.5, purpose="main"):
        # Stabilize shared grid coordinates before caching/naming output files.
        wave, cutoff = round(wave, 9), round(cutoff, 9)
        key = (architecture, background, wave, cutoff, sustain, bend)
        if key in self.cache:
            return self.cache[key]
        values = parameters(background, wave, cutoff, sustain)
        synth = setup(architecture, values, bend)
        actual = {f"{name}_actual_normalized": synth.get_controls()[spec["control"]].get_normalized()
                  for name, spec in profile.PARAMS.items()}
        actual["bend_actual_normalized"] = synth.get_controls()["osc_1_distortion_amount"].get_normalized()
        actual["bend_raw"] = synth.get_controls()["osc_1_distortion_amount"].value()
        audio = render_synth(synth)
        self.render_calls += 1
        sample_id = f"{architecture}_{background}_w{number(wave)}_c{number(cutoff)}_s{number(sustain)}_b{number(bend)}"
        path = self.audio_dir / "raw" / f"{sample_id}.wav"
        # Float WAV preserves over-range output if a clipping check fails.
        sf.write(path, audio, RATE, subtype="FLOAT")
        feature, spectral = signature(audio)
        row = dict(sample_id=sample_id, architecture=architecture, purpose=purpose,
                   background=background, bend_amount=bend, raw_path=path.relative_to(ROOT).as_posix(),
                   audio_sha256=digest(path), **values, **actual, **metrics(audio), **spectral)
        self.rows.append(row)
        self.cache[key], self.features[sample_id], self.waveforms[sample_id] = row, feature, audio
        return row

    def pair(self, a, b, kind):
        result = dict(kind=kind, background=a["background"], wave_frame=a["wave_frame"],
                      filter_cutoff=a["filter_cutoff"], sample_a=a["sample_id"], sample_b=b["sample_id"],
                      **compare_audio(self.waveforms[a["sample_id"]], self.waveforms[b["sample_id"]],
                                      self.features[a["sample_id"]], self.features[b["sample_id"]]))
        self.pairs.append(result)
        return result

    def main_grid(self):
        for background in BACKGROUND_SETTINGS:
            for wave, cutoff in product(MAIN_WAVES, MAIN_CUTOFFS):
                a = [self.add("A", background, wave, cutoff, sustain=x) for x in SUSTAIN_LEVELS]
                b = [self.add("B", background, wave, cutoff, bend=x) for x in BEND_LEVELS]
                self.main_groups.append(dict(background=background, wave=wave, cutoff=cutoff, a=a, b=b))
                for i, j in ((0, 1), (1, 2), (0, 2)):
                    self.pair(a[i], a[j], f"A_sustain_{SUSTAIN_LEVELS[i]}_to_{SUSTAIN_LEVELS[j]}")
                    self.pair(b[i], b[j], f"B_bend_{BEND_LEVELS[i]}_to_{BEND_LEVELS[j]}")
                neutral_error = float(np.max(np.abs(self.waveforms[a[0]["sample_id"]] - self.waveforms[b[1]["sample_id"]])))
                self.checks.append(dict(kind="B_neutral_vs_A_sustain_zero", sample_id=b[1]["sample_id"],
                                        max_absolute_error=neutral_error, tolerance=NEUTRAL_TOLERANCE,
                                        passed=neutral_error <= NEUTRAL_TOLERANCE))
                self.pair(a[1], b[1], "architecture_sustain_removal_only")
            print(f"Main comparisons complete: {background}", flush=True)

    def edge_and_wrapper_checks(self):
        # Low/high cutoff x middle wavetable x all four backgrounds: 16 edge WAVs.
        for background, cutoff, bend in product(BACKGROUND_SETTINGS, (MAIN_CUTOFFS[0], MAIN_CUTOFFS[-1]), (0., 1.)):
            edge = self.add("B", background, .5, cutoff, bend=bend, purpose="Bend_extreme")
            neutral = self.add("B", background, .5, cutoff, bend=.5)
            self.pair(neutral, edge, "B_extreme_vs_neutral")
        # Both architectures, every background, plus Bend boundaries. Each check
        # uses fresh instances; state cannot leak between examples.
        targets = []
        for background in BACKGROUND_SETTINGS:
            targets.append(self.add("A", background, .5, .575, sustain=.4))
            for cutoff, bend in ((.575, .25), (.575, .5), (.575, .75), (.85, 0.), (.85, 1.)):
                targets.append(self.add("B", background, .5, cutoff, bend=bend,
                                        purpose="Bend_extreme" if bend in (0., 1.) else "main"))
        preset_dir = self.audio_dir / "presets"
        preset_dir.mkdir()
        for row in targets:
            values = {name: row[name] for name in profile.PARAMS}
            synth = setup(row["architecture"], values, row["bend_amount"])
            payload = synth.to_json()
            path = preset_dir / f"{row['sample_id']}.vital"
            path.write_bytes(payload.encode("utf-8"))
            reference = self.waveforms[row["sample_id"]]
            for label in ("repeat_fresh", "json_roundtrip", "preset_file_roundtrip"):
                if label == "repeat_fresh":
                    check_synth = synth
                else:
                    check_synth = vita.Synth()
                    set_sample_rate(check_synth, RATE)
                    loaded = (check_synth.load_json(payload) if label == "json_roundtrip"
                              else check_synth.load_preset(str(path)))
                    if not loaded:
                        raise RuntimeError(f"{label} failed: {row['sample_id']}")
                validate_settings(check_synth, row["architecture"], values, row["bend_amount"])
                audio = render_synth(check_synth)
                self.render_calls += 1
                error = float(np.max(np.abs(audio - reference)))
                self.checks.append(dict(kind=label, sample_id=row["sample_id"], max_absolute_error=error,
                                        tolerance=REPEAT_TOLERANCE, passed=error <= REPEAT_TOLERANCE))
        # With warp disabled, amount must have no effect (negative control).
        values = parameters("clean_held", .5, .575, 0.)
        a, b = render_synth(setup("A", values, 0.)), render_synth(setup("A", values, 1.))
        self.render_calls += 2
        error = float(np.max(np.abs(a - b)))
        self.checks.append(dict(kind="disabled_warp_amount_invariance", sample_id="diagnostic",
                                max_absolute_error=error, tolerance=REPEAT_TOLERANCE, passed=error <= REPEAT_TOLERANCE))
        print("Determinism, neutral, disabled-mode and serialization checks complete", flush=True)

    def reference_grid(self):
        matches = []
        for background in BACKGROUND_SETTINGS:
            library = [self.add("A", background, float(w), float(c), purpose="wave_cutoff_reference")
                       for w, c in product(np.linspace(0, 1, 9), np.linspace(.30, .85, 5))]
            matrix = np.array([self.features[r["sample_id"]] for r in library])
            for group in self.main_groups:
                if group["background"] != background:
                    continue
                neutral = group["a"][0]
                for target in (group["b"][0], group["b"][2]):
                    f = self.features[target["sample_id"]]
                    distances = np.linalg.norm(matrix - f, axis=1) / math.sqrt(2)
                    index = int(np.argmin(distances))
                    best = library[index]
                    original = shape_distance(self.features[neutral["sample_id"]], f)
                    matches.append(dict(sample_id=target["sample_id"], background=background,
                                        bend_amount=target["bend_amount"], wave_frame=target["wave_frame"],
                                        filter_cutoff=target["filter_cutoff"], closest_no_bend=best["sample_id"],
                                        closest_wave_frame=best["wave_frame"], closest_cutoff=best["filter_cutoff"],
                                        original_shape_distance=original, best_grid_shape_distance=float(distances[index]),
                                        remaining_distance_ratio=float(distances[index]) / max(original, 1e-12)))
            print(f"Finite wavetable/cutoff reference grid complete: {background}", flush=True)
        return matches

    def playback(self):
        # Common gain preserves native level differences. RMS matching is a second
        # diagnostic view, never written back into the raw renders/training data.
        common_gain = min(1., .90 / max(r["peak"] for r in self.rows))
        wanted = {r["sample_id"]: 10 ** (-24 / 20) / max(r["held_rms"], 1e-12) for r in self.rows}
        cap = min(1., min(.90 / max(r["peak"] * wanted[r["sample_id"]], 1e-12) for r in self.rows))
        for view in ("native", "rms_matched"):
            (self.audio_dir / view).mkdir()
        for row in self.rows:
            sid, audio = row["sample_id"], self.waveforms[row["sample_id"]]
            row["native_gain"] = common_gain
            row["rms_matched_gain"] = wanted[sid] * cap
            # Include reference matches for direct listening comparisons.
            for view, gain in (("native", common_gain), ("rms_matched", row["rms_matched_gain"])):
                sf.write(self.audio_dir / view / f"{sid}.wav", audio * gain, RATE, subtype="PCM_16")
        return dict(native_common_gain=common_gain, rms_matching_window_seconds=[0., 1.5],
                    rms_matched_target_dbfs=-24 + 20 * math.log10(cap), peak_limit=.90,
                    note="RMS matching is not perceptual loudness matching; no DC removal, EQ or compression")

    def save(self, matches, playback):
        main = [r for r in self.rows if r["purpose"] == "main"]
        bend_pairs = [p for p in self.pairs if p["kind"].startswith("B_bend")]
        grouped = {}
        for architecture in ("A", "B"):
            rows = [r for r in main if r["architecture"] == architecture]
            grouped[architecture] = dict(count=len(rows), silent=sum(r["is_silent"] for r in rows),
                clipped=sum(r["is_clipped"] for r in rows), dc_warnings=sum(r["has_dc_warning"] for r in rows),
                max_peak=max(r["peak"] for r in rows), max_absolute_dc=max(abs(r["dc_offset"]) for r in rows))
        summary = dict(created_utc=datetime.now(timezone.utc).isoformat(),
            purpose="Matched engineering comparison, not human perceptual validation or a new training dataset",
            versions={n: version(n) for n in ("vita", "numpy", "scipy", "soundfile")},
            source_hashes={str(p.relative_to(ROOT)): digest(p) for p in
                           (Path(__file__), ROOT / "generation/vital_setup.py", ROOT / "generation/characterize.py",
                            ROOT / "generation/restricted_config.py", ROOT / "generation/params_config.py", profile.BASE_PRESET)},
            current_profile_name=profile.DATASET_NAME, current_parameters=profile.PARAMS,
            current_fixed_controls=profile.FIXED_CONTROLS, current_modulations=profile.MODULATIONS,
            architecture_A_variable_controls=list(profile.PARAMS),
            architecture_B_variable_controls=[n for n in profile.PARAMS if n != "filter_env_sustain"] + ["bend_amount"],
            warp_fixed_settings=dict(mode_A="None", mode_B="Bend", distortion_phase=.5, distortion_spread=0.,
                                     spectral_morph_type=0, spectral_morph_amount=.5, spectral_morph_spread=0.),
            architecture_B_filter_env_sustain=0.,
            sample_rate=RATE, midi_note=profile.MIDI_NOTE, velocity=profile.VELOCITY,
            note_duration=profile.NOTE_DURATION, render_duration=profile.RENDER_DURATION,
            main_wave_positions=MAIN_WAVES, main_cutoffs=MAIN_CUTOFFS, backgrounds=BACKGROUND_SETTINGS,
            A_sustain_levels=SUSTAIN_LEVELS, B_bend_levels=BEND_LEVELS, edge_bend_levels=[0., 1.],
            main_contexts=len(self.main_groups), main_render_count=len(main), unique_render_count=len(self.rows),
            total_render_calls=self.render_calls, main_quality=grouped,
            all_render_quality=dict(silent=sum(r["is_silent"] for r in self.rows),
                clipped=sum(r["is_clipped"] for r in self.rows), dc_warnings=sum(r["has_dc_warning"] for r in self.rows)),
            bend_numerical_comparisons=len(bend_pairs), bend_numerically_active=sum(p["numerically_active"] for p in bend_pairs),
            bend_relative_difference_range=[min(p["relative_waveform_difference"] for p in bend_pairs),
                                           max(p["relative_waveform_difference"] for p in bend_pairs)],
            bend_shape_distance_range=[min(p["spectral_shape_distance"] for p in bend_pairs),
                                       max(p["spectral_shape_distance"] for p in bend_pairs)],
            numerical_activity_tolerance=ACTIVITY_TOLERANCE,
            check_count=len(self.checks), failed_checks=[c for c in self.checks if not c["passed"]],
            serialized_preset_hashes={p.name: digest(p) for p in sorted((self.audio_dir / "presets").glob("*.vital"))},
            finite_reference_grid=dict(wave_positions=9, cutoff_positions=5, backgrounds=4,
                tested_targets=len(matches), median_remaining_distance_ratio=float(np.median([r["remaining_distance_ratio"] for r in matches])),
                limitation="Only a finite no-Bend wave/cutoff grid with ENV2 sustain zero; does not prove independence or whole-architecture equivalence"),
            shape_metric=dict(name="Hellinger distance on normalized log-band power per time window",
                windows=WINDOWS, band_edges_hz=BAND_EDGES.tolist(), fft=2048, hop=512,
                weighting="equal windows", detrend="constant per STFT frame", gain_invariant=True,
                limitation="Not a perceptual distance; phase discarded and low-energy windows normalized"),
            playback=playback, audibility_status="Awaiting listening; no listener data collected",
            decision="Do not select/freeze B solely from computational results")
        write_csv(self.report_dir / "render_manifest.csv", self.rows)
        write_csv(self.report_dir / "paired_effects.csv", self.pairs)
        write_csv(self.report_dir / "wrapper_checks.csv", self.checks)
        write_csv(self.report_dir / "wave_cutoff_matches.csv", matches)
        (self.report_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self.listening_page(matches, summary)
        return summary

    def listening_page(self, matches, summary):
        match_map = {r["sample_id"]: r for r in matches}
        # Predeclared shortlist: each background, low/mid/high cutoff and a rotating
        # wavetable position. All 36 contexts remain available below it.
        shortlist = [g for g in self.main_groups if MAIN_WAVES.index(g["wave"]) == MAIN_CUTOFFS.index(g["cutoff"])]
        order = shortlist + [g for g in self.main_groups if g not in shortlist]
        rows_by_id = {r["sample_id"]: r for r in self.rows}
        cards = []
        for i, group in enumerate(order):
            clips = []
            for label, row in [(f"A: ENV2 sustain {x}", r) for x, r in zip(SUSTAIN_LEVELS, group["a"])] + [
                    (f"B: Bend {x}", r) for x, r in zip(BEND_LEVELS, group["b"])]:
                warning = " · DC flag" if row["has_dc_warning"] else ""
                clips.append(f'<div class="clip"><b>{html.escape(label)}</b><small>{row["rms_dbfs"]:.1f} dBFS RMS{warning}</small>'
                             f'<audio controls preload="none" data-id="{row["sample_id"]}" src="native/{row["sample_id"]}.wav"></audio></div>')
            references = []
            for target in (group["b"][0], group["b"][2]):
                match = match_map[target["sample_id"]]
                ref = rows_by_id[match["closest_no_bend"]]
                references.append(f'<div class="clip"><b>Closest grid match to Bend {target["bend_amount"]}</b>'
                    f'<small>No Bend · wavetable {ref["wave_frame"]:.3f}, cutoff {ref["filter_cutoff"]:.3f}</small>'
                    f'<audio controls preload="none" data-id="{ref["sample_id"]}" src="native/{ref["sample_id"]}.wav"></audio></div>')
            cards.append(f'<section data-short="{str(i < len(shortlist)).lower()}"><h2>{i+1}. {group["background"]}'
                f' · wavetable {group["wave"]} · cutoff {group["cutoff"]}</h2><div class="grid">{"".join(clips)}</div>'
                f'<details><summary>Compare against the closest no-Bend grid matches</summary><div class="grid">{"".join(references)}</div></details>'
                '<label>Bend difference after RMS matching: <select class="rating"><option>Unrated</option><option>Clear</option>'
                '<option>Subtle</option><option>No difference heard</option><option>Unsure / playback issue</option></select></label>'
                '<textarea placeholder="What changed? Brightness, tone, attack, level, artifacts; A versus B preference and why."></textarea></section>')
        page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vital A/B architecture listening comparison</title><style>
body{font:16px system-ui;max-width:1150px;margin:auto;padding:24px;background:#111922;color:#edf3f7}h1{font-size:27px}
p,li{line-height:1.55;color:#d0dae3}section{padding:20px;margin:20px 0;background:#1c2936;border-radius:12px}h2{font-size:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.clip{padding:10px;background:#101b25;border-radius:8px}
small{display:block;margin:6px 0;color:#b5c8d7}audio{width:100%}select,button,textarea{font:inherit;padding:8px;margin:8px;color:#111}
textarea{box-sizing:border-box;width:96%;height:70px}header{position:sticky;top:0;padding:12px;background:#243747;z-index:2}details{margin:16px 0}
</style><h1>Configuration A / Configuration B</h1>
<p>A varies filter-envelope sustain with oscillator warp off. B fixes that sustain at 0 and varies Bend.
All six clips within a card share their other settings. <b>Bend 0.5 is the neutral setting.</b>
Compare A sustain 0 with B Bend 0.5 to check the common reference; compare A sustain 0.4 with A sustain 0 to hear the sustain-removal cost.</p>
<p>Start with the 12-card shortlist. Listen at a comfortable fixed playback volume. First compare B's three settings in native-level view,
then use RMS-matched view to check whether a difference remains beyond overall level. RMS matching is not perceptual loudness matching.
Listen to A's alternatives as well: this is a tradeoff, not a test that B must win. The grid matches are acoustic-screen candidates, not proven sound-alikes.</p>
<header><label>Playback <select id="view"><option value="native">Native levels (common gain)</option><option value="rms_matched">Held-note RMS matched</option></select></label>
<label><input type="checkbox" id="all"> Show all 36 contexts</label><button id="export">Download listening notes</button>
<small>Notes stay in this tab until downloaded. This is an informal engineering review, not a blinded participant study.</small></header>
''' + "".join(cards) + '''<script>
const audios=[...document.querySelectorAll('audio')], sections=[...document.querySelectorAll('section')];
document.getElementById('view').onchange=e=>audios.forEach(a=>{a.pause();a.src=e.target.value+'/'+a.dataset.id+'.wav';a.load()});
audios.forEach(a=>a.onplay=()=>audios.forEach(b=>{if(a!==b)b.pause()}));
function filter(){sections.forEach(s=>s.hidden=!document.getElementById('all').checked&&s.dataset.short!=='true')}
document.getElementById('all').onchange=filter;filter();
document.getElementById('export').onclick=()=>{const data=sections.map(s=>({context:s.querySelector('h2').textContent,
rating:s.querySelector('select').value,notes:s.querySelector('textarea').value}));const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
const a=document.createElement('a');a.href=u;a.download='architecture-listening-notes.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)};
</script></html>'''
        (self.audio_dir / "LISTEN.html").write_text(page, encoding="utf-8")
        write_csv(self.report_dir / "listening_shortlist.csv", [dict(order=i+1, background=g["background"],
            wave_frame=g["wave"], filter_cutoff=g["cutoff"], bend_audibility="unrated", notes="") for i, g in enumerate(shortlist)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="architecture_ab_v1")
    args = parser.parse_args()
    experiment = Experiment(args.run_id)
    experiment.main_grid()
    experiment.edge_and_wrapper_checks()
    matches = experiment.reference_grid()
    playback = experiment.playback()
    summary = experiment.save(matches, playback)
    print(json.dumps({k: summary[k] for k in ("main_render_count", "unique_render_count", "total_render_calls",
                     "main_quality", "bend_numerically_active", "bend_numerical_comparisons", "failed_checks")}, indent=2))
    if summary["failed_checks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
