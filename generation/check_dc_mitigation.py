"""Bounded DC-conditioning experiment; leaves datasets and source WAVs untouched.

python -B -m generation.check_dc_mitigation
Compares the saved A/B renders and 18 diagnostic settings with both Bend/sustain.
Nothing here enables conditioning in the dataset generator or inference pipeline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import product
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, sosfreqz

from generation import bend_sustain_config as profile
from generation.compare_architectures import BACKGROUND_SETTINGS, number, render_synth
from generation.vital_setup import apply_parameters, create_synth

ROOT = profile.PROJECT_ROOT
METHODS = ("raw", "subtract_clip_mean", "highpass_10hz", "highpass_20hz")


def condition(audio: np.ndarray, sample_rate: int, method: str) -> np.ndarray:
    """Mono, float64, causal SOS filtering with zero initial state; no gain changes."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Expected nonempty finite mono audio")
    if method == "raw":
        return audio.copy()
    if method == "subtract_clip_mean":
        return audio - audio.mean()
    if method not in ("highpass_10hz", "highpass_20hz"):
        raise ValueError(f"Unknown conditioning method: {method}")
    cutoff = 10 if method == "highpass_10hz" else 20
    sos = butter(2, cutoff, btype="highpass", fs=sample_rate, output="sos")
    return sosfilt(sos, audio)


def diagnostics(audio: np.ndarray, rate: int) -> dict:
    mean = float(np.mean(audio))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    ratio = abs(mean) / max(rms, 1e-15)
    size = round(.05 * rate)
    rolling_sum = np.cumsum(np.concatenate(([0.], audio)))
    rolling_mean = (rolling_sum[size:] - rolling_sum[:-size]) / size
    return dict(mean=mean, dc_to_rms=ratio, rms=rms,
                peak=float(np.max(np.abs(audio))),
                dc_flag=abs(mean) >= .005 or ratio >= .2,
                clipped=bool(np.max(np.abs(audio)) >= 1),
                max_abs_50ms_mean=float(np.max(np.abs(rolling_mean))),
                held_mean=float(np.mean(audio[:round(1.5 * rate)])),
                final_50ms_peak=float(np.max(np.abs(audio[-size:]))),
                final_sample=float(audio[-1]))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dc_mitigation_v1")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,60}", args.run_id):
        raise ValueError("Use a short lowercase alphanumeric run ID")
    report = ROOT / "generation/characterization" / args.run_id
    output = ROOT / "generation/test_renders" / args.run_id
    if report.exists() or output.exists():
        raise FileExistsError("Existing experiment refused; use a new run ID")
    source = ROOT / "generation/characterization/architecture_ab_v1/render_manifest.csv"
    with source.open(newline="", encoding="utf-8") as handle:
        original = list(csv.DictReader(handle))
    for row in original:
        if sha(ROOT / row["raw_path"]) != row["audio_sha256"]:
            raise ValueError(f"Original A/B audio changed: {row['sample_id']}")
    report.mkdir(parents=True)
    (output / "raw_combined").mkdir(parents=True)
    sources = [dict(sample_id=r["sample_id"], group="previous_AB", background=r["background"],
                    raw_path=r["raw_path"], audio_sha256=r["audio_sha256"]) for r in original]
    combined = []
    # Diagnostic corners, not a coverage claim or training/study sample.
    for background, bend, sustain in product(("driven_pluck", "resonant_driven_swell"),
                                              (.25, .5, .75), (0., .4, 1.)):
        values = dict(profile.BASE_VALUES, **dict(BACKGROUND_SETTINGS[background],
                      wave_frame=.5, filter_cutoff=.575, bend_amount=bend,
                      filter_env_sustain=sustain))
        synth = create_synth(profile)
        apply_parameters(synth, profile, values)
        audio = render_synth(synth)
        sample_id = f"C_{background}_b{number(bend)}_s{number(sustain)}"
        path = output / "raw_combined" / f"{sample_id}.wav"
        sf.write(path, audio, profile.SAMPLE_RATE, subtype="FLOAT")
        row = dict(sample_id=sample_id, group="combined_13", background=background,
                   raw_path=path.relative_to(ROOT).as_posix(), audio_sha256=sha(path))
        sources.append(row)
        combined.append(dict(row, **values))
    write_csv(report / "combined_settings.csv", combined)
    write_csv(report / "sources.csv", sources)
    rows = []
    for source_row in sources:
        audio, rate = sf.read(ROOT / source_row["raw_path"], dtype="float64")
        if rate != profile.SAMPLE_RATE or len(audio) != round(profile.RENDER_DURATION * rate):
            raise ValueError(f"Unexpected audio format: {source_row['sample_id']}")
        for method in METHODS:
            processed = condition(audio, rate, method)
            rows.append(dict(sample_id=source_row["sample_id"], group=source_row["group"],
                             method=method, **diagnostics(processed, rate)))
    write_csv(report / "metrics.csv", rows)
    aggregates = []
    for group, method in product(("previous_AB", "combined_13", "all"), METHODS):
        selected = [r for r in rows if r["method"] == method and (group == "all" or r["group"] == group)]
        aggregates.append(dict(group=group, method=method, count=len(selected),
                         dc_flags=sum(r["dc_flag"] for r in selected),
                         clipping_flags=sum(r["clipped"] for r in selected),
                         max_abs_mean=max(abs(r["mean"]) for r in selected),
                         max_dc_to_rms=max(r["dc_to_rms"] for r in selected),
                         max_peak=max(r["peak"] for r in selected),
                         max_abs_50ms_mean=max(r["max_abs_50ms_mean"] for r in selected),
                         max_final_50ms_peak=max(r["final_50ms_peak"] for r in selected)))
    write_csv(report / "aggregates.csv", aggregates)
    # Objective selection only; audio is not yet judged by a listener.
    raw = [r for r in rows if r["method"] == "raw"]
    by_id = {r["sample_id"]: r for r in sources}
    selection_rules = [
        ("Largest full-clip DC magnitude", max(raw, key=lambda r: abs(r["mean"]))),
        ("Largest DC/RMS ratio", max(raw, key=lambda r: r["dc_to_rms"])),
        ("Pluck with largest DC", max((r for r in raw if by_id[r["sample_id"]]["background"] == "driven_pluck"), key=lambda r: abs(r["mean"]))),
        ("Combined 13 controls, largest DC", max((r for r in raw if r["group"] == "combined_13"), key=lambda r: abs(r["mean"]))),
        ("Combined 13 controls, sustain 1, slow attack", next(r for r in raw if r["sample_id"] == "C_resonant_driven_swell_b0p750_s1p000")),
        ("Low-DC reference", min(raw, key=lambda r: abs(r["mean"]))),
    ]
    cards, demos = [], []
    seen = set()
    (output / "listen").mkdir()
    for label, selected in selection_rules:
        sample_id = selected["sample_id"]
        if sample_id in seen:
            continue
        seen.add(sample_id)
        audio, rate = sf.read(ROOT / by_id[sample_id]["raw_path"], dtype="float64")
        controls = []
        for method in ("raw", "highpass_10hz", "highpass_20hz"):
            path = output / "listen" / f"{sample_id}_{method}.wav"
            sf.write(path, condition(audio, rate, method), rate, subtype="PCM_16")
            demos.append(dict(sample_id=sample_id, selection=label, method=method,
                               path=path.relative_to(ROOT).as_posix(), sha256=sha(path), gain=1.))
            controls.append(f'<div>{method}<br><audio controls preload="none" src="listen/{path.name}"></audio></div>')
        cards.append(f'<section><h2>{html.escape(label)}</h2><p>{sample_id}</p><div class="row">{"".join(controls)}</div></section>')
    write_csv(report / "listening_examples.csv", demos)
    (output / "LISTEN.html").write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>DC correction check</title><style>body{background:#151a21;color:#e9edf2;font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px}section{border-top:1px solid #445;padding:20px 0}h2{font-size:19px}.row{display:flex;gap:20px;flex-wrap:wrap}p{overflow-wrap:anywhere;color:#b8c9db}</style>
<h1>DC correction: short listening check</h1><p>Original, causal 10 Hz high-pass, causal 20 Hz high-pass. Same gain (1.0), no loudness normalization. All are PCM16 playback copies; original float files are preserved. Compare clicks, attack, body, and tail. Listening does not measure DC or prove descriptor equivalence.</p>'''
        + "".join(cards) + '</html>', encoding="utf-8")
    responses = {}
    for cutoff in (10, 20):
        sos = butter(2, cutoff, btype="highpass", fs=profile.SAMPLE_RATE, output="sos")
        frequencies = [0., 20., 50., 440 * 2 ** ((profile.MIDI_NOTE - 69) / 12)]
        _, response = sosfreqz(sos, worN=frequencies, fs=profile.SAMPLE_RATE)
        responses[str(cutoff)] = dict(sos=sos.tolist(), magnitude_db={str(f):
            (None if abs(h) == 0 else float(20 * np.log10(abs(h)))) for f, h in zip(frequencies, response)})
    preserved = all(sha(ROOT / r["raw_path"]) == r["audio_sha256"] for r in original)
    if not preserved:
        raise RuntimeError("Original WAV preservation check failed")
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                   profile=profile.DATASET_NAME, previous_audio_count=len(original),
                   combined_diagnostic_render_count=len(combined), source_audio_preserved=preserved,
                   libraries={name: version(name) for name in ("vita", "numpy", "scipy", "soundfile")},
                   source_hashes={p: sha(ROOT / p) for p in ("generation/check_dc_mitigation.py",
                       "generation/bend_sustain_config.py", "generation/bend_config.py", "generation/restricted_config.py",
                       "generation/compare_architectures.py", "generation/vital_setup.py")},
                   preset_sha256=sha(profile.BASE_PRESET), methods=METHODS,
                   filter_design="second-order Butterworth highpass, float64 SOS, causal, zero initial state, no padding or gain",
                   dc_flag="abs(full_clip_mean) >= 0.005 OR abs(full_clip_mean)/RMS >= 0.20; engineering screen, not audibility",
                   responses=responses, aggregates=aggregates)
    (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = ["# DC-mitigation engineering check", "",
             f"Saved A/B renders: {len(original)}. New combined Bend/sustain diagnostic settings: {len(combined)}.",
             "No new 1,024-sound dataset was generated. Source float WAVs are preserved and hash-verified.", "",
             "## Measurements", "", "| Group | Method | Clips | DC flags | Clipping | Max absolute mean | Max peak | Max final 50 ms peak |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in aggregates:
        lines.append(f"| {r['group']} | {r['method']} | {r['count']} | {r['dc_flags']} | {r['clipping_flags']} | {r['max_abs_mean']:.7g} | {r['max_peak']:.7g} | {r['max_final_50ms_peak']:.7g} |")
    lines += ["", "The flag is abs(mean) >= .005 or abs(mean)/RMS >= .20. A full-clip mean is a finite-window diagnostic, not proof of a stationary DC component or an audibility test. `metrics.csv` also records held-note mean, maximum absolute sliding 50 ms mean, and ending samples; envelope transients and ordinary low-frequency signal can contribute to these measurements.",
              "", "## Processing and limits", "",
              "Both high-pass candidates are second-order Butterworth filters, designed at 44,100 Hz and applied causally in float64 with SOS and zero initial state. The same filter applies to every sample, with no gain normalization, fades, padding or selective correction. Summary JSON records coefficients and steady-state magnitude at DC, 20 Hz, 50 Hz and MIDI 60's fundamental. Those responses do not establish transparency for attacks/tails.",
              "", "Subtracting a clip's mean is a diagnostic comparison only: it shifts any otherwise silent tail by that mean. A high-pass filter instead rejects a constant component while also affecting slow changes/transients; it can ring or alter peak level. Check those effects rather than assuming zero mean alone is sufficient.",
              "", "The 18 new renders hold wavetable .5 and cutoff .575, cross Bend .25/.5/.75 with filter-envelope sustain 0/.4/1 under driven-pluck and resonant-driven-swell backgrounds. They test combined controls at a few settings, not full 13-dimensional coverage. Prior A/B conclusions cannot simply be assigned to the combined architecture.",
              "", "## Listening and adoption", "",
              f"Open `generation/test_renders/{args.run_id}/LISTEN.html` for a small set of original/10 Hz/20 Hz comparisons. Selection rules and hashes are in `listening_examples.csv`. Playback copies share gain 1.0 and PCM16 encoding. No human listening result has been recorded by this script.",
              "", "Before adopting: listen for clicks and unwanted changes to attack, body and release on these examples; freeze one conditioning policy/version; apply it consistently to study playback, model feature inputs, reference/re-synthesized audio and incoming inference audio. Preserve raw audio, compute QA before and after filtering, and re-check ranges/descriptor behavior on the final architecture. No conditioning has been added to production generation/training/inference by this experiment.",
              "", "References: [Smith, DC Blocker](https://www.dsprelated.com/freebooks/filters/DC_Blocker.html); [SciPy Butterworth design](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html); [SciPy SOS filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html).", ""]
    (report / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(dict(report=str(report / "REPORT.md"), aggregates=aggregates), indent=2))


if __name__ == "__main__":
    main()
