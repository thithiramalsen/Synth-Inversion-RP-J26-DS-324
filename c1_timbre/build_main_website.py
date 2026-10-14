"""Build the static C1 main-study demo website from a plan_main_study output.

The site needs no server code: participants' answers stay in their own browser
and can be copied as CSV. It demonstrates the main-study protocol and design. It
is not the research collection system (that is the survey backend, after ethics
approval).

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.build_main_website --version c1_main_v1_simpilot_dryrun

When the real selection exists, rerun with its --version; the sounds, assignments
and design numbers are all replaced from that run's files.

Output: data/processed/<version>/website/
    index.html     full page for local viewing (python -m http.server)
    artifact.html  the same page without the document wrapper, for publishing

With --publish-dir c1_timbre/main_study/site the deployable files are also copied
into the repository so a Render static site can serve them.
    app.js, study.json, audio/
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "c1_timbre/main_study/website_template"
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="c1_main_v1_simpilot_dryrun")
    ap.add_argument("--publish-dir", type=Path, default=None,
                    help="also copy the deployable site here (e.g. c1_timbre/main_study/site for Render)")
    args = ap.parse_args()
    plan = ROOT / "c1_timbre/main_study" / args.version
    data = ROOT / "data/processed" / args.version
    out = data / "website"
    bundle = json.loads((data / "bundle.json").read_text(encoding="utf-8"))
    decisions = json.loads((plan / "decisions.json").read_text(encoding="utf-8"))
    pilot = json.loads((plan / "pilot_analysis.json").read_text(encoding="utf-8"))
    protocol = json.loads((plan / "c1_main_protocol_DRAFT.json").read_text(encoding="utf-8"))
    selected = pd.read_csv(plan / "selected_sounds.csv").set_index("main_sound_id")
    dist = pd.read_csv(plan / "distribution_comparison.csv").set_index("variable")

    if out.exists():
        shutil.rmtree(out)
    (out / "audio").mkdir(parents=True)

    sounds = {}
    for sid, s in bundle["samples"].items():
        shutil.copy2(data / s["playback_path"], out / "audio" / Path(s["playback_path"]).name)
        entry = dict(file=s["playback_path"], role=s["role"], source=s["source_sample_id"],
                     pilot=s.get("pilot_sound_id"), gain_db=round(s["gain_db"], 1),
                     params={k: round(v, 3) for k, v in s["parameters"].items()})
        if sid in selected.index:
            row = selected.loc[sid]
            entry.update(pred={t: round(float(row["pred_" + t]), 2) for t in TRAITS},
                         weak_support=bool(row["weak_support"]))
        sounds[sid] = entry
    for h in bundle["headphones"]:
        shutil.copy2(data / "audio" / h["path"], out / "audio" / h["path"])
    shutil.copy2(data / "audio" / bundle["calibration"]["path"], out / "audio" / bundle["calibration"]["path"])

    keys = ["protocol_version", "title", "descriptors", "scale", "information", "experience_question",
            "experience_tools_label", "experience_tools_placeholder", "resume_instructions", "target_participants",
            "assignment_capacity", "break_after_rated", "hidden_repeats", "unique_sounds_per_person"]
    config = {k: protocol[k] for k in keys if k in protocol}
    config["activities"] = protocol["eligibility"]["activities"]
    ranges = [dict(variable=v, corpus_p05=dist.loc[v, "corpus_p05"], corpus_median=dist.loc[v, "corpus_median"],
                   corpus_p95=dist.loc[v, "corpus_p95"], selected_min=dist.loc[v, "selected_min"],
                   selected_median=dist.loc[v, "selected_median"], selected_max=dist.loc[v, "selected_max"],
                   ks=dist.loc[v, "ks_distance"])
              for v in ["pred_" + t for t in TRAITS] + ["log2_centroid", "log_am_rough_15_150", "held_drop_db", "log_attack_s"]]
    design = dict(
        status=decisions["status"], pilot_label_source=decisions["pilot_label_source"],
        n_sounds=decisions["n_sounds"], n_participants=decisions["n_participants"], n_anchors=decisions["n_anchors"],
        unique_per_person=decisions["unique_per_person"], hidden_repeats=decisions["hidden_repeats"],
        presentations_per_person=decisions["presentations_per_person"], break_after=decisions["break_after_rated"],
        min_listeners=decisions["min_listeners_per_sound"], extra_listener_sounds=decisions["sounds_with_extra_listener"],
        median_minutes=decisions["predicted_median_session_min"], capacity=decisions["assignment_capacity"],
        spares=decisions["spare_blocks"], prefix_coverage=decisions["prefix_coverage"],
        reliability=decisions["expected_reliability_of_sound_means"], descriptor_status=decisions["descriptor_status"],
        wording_review=decisions["wording_review_recommended"], eligible=decisions["eligible_candidates"],
        exclusions=decisions["corpus_exclusions"], weak_support_selected=decisions["selected_weak_support"],
        session_options=decisions["session_options"],
        pilot=dict(participants=pilot["completed_participants"], sounds=pilot["sounds"], evaluations=pilot["evaluations"],
                   unclear={t: pilot["descriptors"][t]["unclear_rate"] for t in TRAITS},
                   cv_r2={t: pilot["model"][t]["cv"]["r2_vs_train_mean"] for t in TRAITS}),
        ranges=ranges)
    study = dict(version=args.version, built_utc=f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
                 study_id="c1_main_v1", bundle_version=bundle.get("version"), config=config, sounds=sounds,
                 assignments=bundle["assignments"], headphones=bundle["headphones"],
                 volume=f"audio/{bundle['calibration']['path']}", design=design)
    (out / "study.json").write_text(json.dumps(study, separators=(",", ":"), default=float), encoding="utf-8")

    page = (TEMPLATE / "page.html").read_text(encoding="utf-8")
    shutil.copy2(TEMPLATE / "app.js", out / "app.js")
    (out / "artifact.html").write_text(page, encoding="utf-8")
    (out / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>[hidden]{display:none!important}body{margin:0}</style>\n</head>\n<body>\n'
        + page + "\n</body>\n</html>\n", encoding="utf-8")
    if args.publish_dir:
        dest = args.publish_dir if args.publish_dir.is_absolute() else ROOT / args.publish_dir
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(out, dest, ignore=shutil.ignore_patterns("artifact.html"))
        print(f"Copied deployable site to {dest}")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"Wrote {out} ({len(list(out.rglob('*')))} files, {size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
