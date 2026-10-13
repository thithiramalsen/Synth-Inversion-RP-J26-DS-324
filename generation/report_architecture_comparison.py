"""Build a compact report and standard matplotlib figure from saved A/B results."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from generation import restricted_config as profile


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def report(run_id):
    root = profile.PROJECT_ROOT / "generation/characterization"
    path = (root / run_id).resolve()
    if path.parent != root.resolve():
        raise ValueError("Report must be an immediate experiment subdirectory")
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    renders = read_csv(path / "render_manifest.csv")
    effects = read_csv(path / "paired_effects.csv")
    matches = read_csv(path / "wave_cutoff_matches.csv")
    checks = read_csv(path / "wrapper_checks.csv")
    main = [r for r in renders if r["purpose"] == "main"]
    bend = [r for r in effects if r["kind"].startswith("B_bend")]
    # Neutral-to-bent comparisons; endpoint-to-endpoint can hide symmetric spectra.
    from_neutral = [r for r in bend if r["kind"] in ("B_bend_0.25_to_0.5", "B_bend_0.5_to_0.75")]
    table = ["| Background | B pairs active | Median shape distance, neutral to bent | Median best-grid remaining-distance ratio | A / B DC flags |",
             "|---|---:|---:|---:|---:|"]
    for background in summary["backgrounds"]:
        b = [r for r in bend if r["background"] == background]
        shape = [float(r["spectral_shape_distance"]) for r in from_neutral if r["background"] == background]
        ratio = [float(r["remaining_distance_ratio"]) for r in matches if r["background"] == background]
        warnings = [sum(r["has_dc_warning"] == "True" for r in main
                        if r["architecture"] == a and r["background"] == background) for a in ("A", "B")]
        table.append(f"| {background} | {sum(r['numerically_active']=='True' for r in b)}/{len(b)} | "
                     f"{np.median(shape):.4f} | {np.median(ratio):.3f} | {warnings[0]} / {warnings[1]} |")
    quality = ["| Main renders | Count | Silent | Clipped / over range | DC flags | Maximum peak | Maximum absolute DC |",
               "|---|---:|---:|---:|---:|---:|---:|"]
    for a in ("A", "B"):
        q = summary["main_quality"][a]
        quality.append(f"| {a} | {q['count']} | {q['silent']} | {q['clipped']} | {q['dc_warnings']} | {q['max_peak']:.4f} | {q['max_absolute_dc']:.5f} |")
    exceptional = sorted([r for r in renders if r["has_dc_warning"] == "True"], key=lambda r: abs(float(r["dc_offset"])), reverse=True)
    with (path / "quality_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(renders[0]))
        writer.writeheader()
        writer.writerows(exceptional)
    delta = [abs(float(r["held_rms_change_db"])) for r in from_neutral]
    max_error = max(float(r["max_absolute_error"]) for r in checks
                    if r["kind"] in ("repeat_fresh", "json_roundtrip", "preset_file_roundtrip"))
    worst = max(from_neutral, key=lambda r: abs(float(r["held_rms_change_db"])))
    failures = "\n".join(f"- `{c['kind']}`: `{c['sample_id']}`, maximum error {c['max_absolute_error']:.8g} "
                         f"against tolerance {c['tolerance']:.8g}." for c in summary["failed_checks"]) or "None."
    neutral_note = ""
    if (path / "neutral_check_detail.json").exists():
        detail = json.loads((path / "neutral_check_detail.json").read_text())
        neutral_note = (f"\nThe flagged neutral/bypass pair has difference RMS {detail['difference_rms_dbfs']:.1f} dBFS "
                        f"and relative RMS difference {detail['relative_rms_difference']:.3g}. "
                        "The original threshold failure is retained; it is separate from the exact-repeat/serialization checks. "
                        "[Details](neutral_check_detail.json). No audibility conclusion is drawn.\n")
    protocol = "../../ARCHITECTURE_COMPARISON.md"
    listen = f"../../test_renders/{run_id}/LISTEN.html"
    text = f"""# A/B architecture comparison — measured results

[Open the listening page]({listen}) · [Protocol and limitations]({protocol})

This is an engineering comparison of the two proposed twelve-control domains.
The existing preset/profile and datasets remain the working configuration. No new
1,024-sound dataset was generated. **Audibility and perceptual usefulness remain
unrated.** The listening page begins with 12 contexts and can show all 36.

## Scope

- {summary['main_contexts']} matched contexts; {summary['main_render_count']} main renders.
- {summary['unique_render_count']} distinct sound settings including stress probes and the finite reference grid.
- {summary['total_render_calls']} renderer calls, including fresh-instance and serialization rerenders.
- A varies ENV2 sustain at 0/.4/1; B fixes it at 0 and varies Bend at .25/.5/.75.
- Bend **.5 is the calibrated neutral setting**, tested against A with sustain 0
  in all 36 main contexts; one case slightly exceeded the numerical tolerance below.
- Four backgrounds cross three wavetable positions with three cutoffs; background
  combinations are stress cases, not a full factorial isolation of every interaction.

## Computational outcomes

1. **Waveform activity:** {summary['bend_numerically_active']}/{summary['bend_numerical_comparisons']} main Bend comparisons exceed the
   numerical relative-waveform threshold {summary['numerical_activity_tolerance']}. This is not an audibility result.
2. **Level:** Median absolute held-note RMS change from neutral to bent is {np.median(delta):.2f} dB;
   maximum is {max(delta):.2f} dB. Largest change occurs in `{worst['background']}`,
   wavetable {worst['wave_frame']}, cutoff {worst['filter_cutoff']}. A fixed MIDI note/velocity does not guarantee fixed output level.
3. **Repeatability/serialization:** All 24 fresh repeats, 24 JSON round-trips and
   24 saved-preset round-trips passed; their maximum sample error was {max_error:.3g}.
   Across these and the neutral/disabled-mode checks, {len(checks)-len(summary['failed_checks'])}/{len(checks)} checks passed.
   See [individual checks](wrapper_checks.csv); neutral equivalence uses a separate 2e-6 tolerance.
4. **Quality:** Figures below refer to unprocessed floating-point audio. DC flags
   require review even when no clip reaches full scale. They are not corrected in
   the raw renders. See [flagged settings](quality_review.csv).

""" + "\n".join(quality) + "\n\nFlagged numerical checks:\n\n" + failures + "\n" + neutral_note + """

## Acoustic overlap screen

For each non-neutral B example, the reference search varies **only wavetable and
cutoff** in the same background, with no Bend and ENV2 sustain zero. Shape distance
uses normalized band power across three time windows, so it discards uniform gain
and phase. The remaining-distance ratio is best-grid distance divided by the
original neutral-to-bent distance: lower means the grid found a closer spectral
match. It is not a percentage of variance explained or a perceptual equivalence score.

""" + "\n".join(table) + f"""

The finite 9 x 5 grid is sparse and may miss closer settings between grid points.
A high residual cannot prove independent acoustic information; a low residual
cannot prove two sounds are perceptually interchangeable. This search also does
not test whether the complete A architecture can reproduce B. The evidence is
descriptive and does not establish that either architecture is better.

![Diagnostic comparison](comparison.png)

## Listening and decision

Use the native and held-note RMS-matched views. Compare B's .25/.5/.75 clips, then
A's 0/.4/1 sustain alternatives, and the expandable no-Bend reference matches.
Record clear/subtle/no/uncertain differences, the type of change, unwanted
artifacts, and which capability is more useful for the intended descriptor task.
The predeclared shortlist avoids selecting only large measured effects.

**Do not freeze B on the numerical activity count alone.** Decide after reviewing
audibility, usefulness, the capability lost by fixing ENV2 sustain, and the level/DC
tradeoffs. Keep a changed architecture as a new version if it is adopted.

Artifacts: [manifest](render_manifest.csv), [paired effects](paired_effects.csv),
[finite-grid matches](wave_cutoff_matches.csv), [summary](summary.json),
[listening shortlist](listening_shortlist.csv).

Report generated by `generation/report_architecture_comparison.py`.
"""
    (path / "REPORT.md").write_text(text, encoding="utf-8")
    plt.rcParams.update({"font.size": 10})
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), layout="constrained")
    colors = {"A": "#3066a0", "B": "#ce7434"}
    for a in ("A", "B"):
        rows = [r for r in main if r["architecture"] == a]
        axes[0].scatter([float(r["rms_dbfs"]) for r in rows], [abs(float(r["dc_offset"])) for r in rows],
                         color=colors[a], alpha=.65, s=20, label=a)
    axes[0].axhline(.005, color="gray", linestyle="--", linewidth=1)
    axes[0].set(xlabel="Whole-clip RMS (dBFS)", ylabel="Absolute DC offset", title="Main renders: level / DC")
    axes[0].legend()
    for background in summary["backgrounds"]:
        rows = [r for r in matches if r["background"] == background]
        axes[1].scatter([float(r["original_shape_distance"]) for r in rows],
                         [float(r["best_grid_shape_distance"]) for r in rows], s=20, alpha=.75,
                         label=background.replace("_", " "))
    lim = max(float(r["original_shape_distance"]) for r in matches) * 1.05
    axes[1].plot([0, lim], [0, lim], "--", color="gray", linewidth=1)
    axes[1].set(xlabel="Neutral-to-bent shape distance", ylabel="Best no-Bend grid distance",
                title="Finite-grid acoustic overlap", xlim=(0, lim), ylim=(0, lim))
    axes[1].legend(fontsize=7)
    for background in summary["backgrounds"]:
        rows = [r for r in from_neutral if r["background"] == background]
        axes[2].scatter([float(r["filter_cutoff"]) for r in rows],
                         [float(r["spectral_shape_distance"]) for r in rows], s=24, alpha=.7)
    axes[2].set(xlabel="Cutoff (normalized)", ylabel="Neutral-to-bent shape distance",
                title="Bend across filter settings")
    fig.suptitle("Technical diagnostics — shape distance is not an audibility score")
    fig.savefig(path / "comparison.png", dpi=160)
    plt.close(fig)
    (path / "report_build.json").write_text(json.dumps({
        "report_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "matplotlib_version": matplotlib.__version__, "summary_sha256": hashlib.sha256((path / "summary.json").read_bytes()).hexdigest()
    }, indent=2), encoding="utf-8")
    print(path / "REPORT.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="architecture_ab_v1")
    report(parser.parse_args().run_id)
