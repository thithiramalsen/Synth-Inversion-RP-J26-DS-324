"""Build the C1 pilot dataset from the genuine survey exports (human ratings only).

Inputs are the raw survey exports, unchanged. Rows enter the analysis when:

* the session is complete and not withdrawn,
* the row is a primary study trial (practice and hidden repeats are not targets),
* the session agrees with the other listeners: mean leave-one-session-out Pearson r
  (session ratings vs the mean of all other complete sessions on the same sounds,
  averaged over the four descriptors) is at least MIN_AGREEMENT.

Every export row is kept in the output; `analysis_include` is set by these rules and
the survey's own flag is preserved as `analysis_include_export`. Rows the researcher
typed in for a listener (data_origin = researcher_entered_rehearsal) are labelled
`human_researcher_entered` in `label_source`.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.build_pilot_dataset ^
        --exports "%USERPROFILE%/Downloads/c1-responses (2).csv" "%USERPROFILE%/Downloads/c1-responses (3).csv" ^
        --output-dir c1_timbre/pilot_data/genuine_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
MIN_AGREEMENT = 0.30


def session_agreement(rows: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-session-out agreement of each session with all other sessions."""
    out = []
    for sid, own in rows.groupby("session_id", sort=False):
        others = rows[rows.session_id != sid]
        r = {}
        for t in TRAITS:
            ref = others.groupby("sample_id")[t + "_v"].mean()
            x = own.set_index("sample_id")[t + "_v"]
            pair = pd.concat([x, ref.reindex(x.index)], axis=1).dropna()
            r[t] = float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair) >= 5 else np.nan
        out.append(dict(session_id=sid, participant_label=own.participant_label.iloc[0], study_id=own.study_id.iloc[0],
                        export=own.export.iloc[0], rated=len(own), **{f"r_{t}": r[t] for t in TRAITS},
                        agreement=float(np.nanmean(list(r.values())))))
    return pd.DataFrame(out).sort_values("agreement", ascending=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exports", type=Path, nargs="+", required=True, help="raw survey response exports")
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--min-agreement", type=float, default=MIN_AGREEMENT)
    args = ap.parse_args()

    frames = []
    for path in args.exports:
        d = pd.read_csv(path, dtype=str, keep_default_na=False)
        d["export"] = path.name
        frames.append(d)
    raw = pd.concat(frames, ignore_index=True).fillna("")
    if raw.duplicated(["session_id", "presentation_id"]).any():
        raise ValueError("The same trial appears in more than one export; pass each export once")
    if (raw.groupby("session_id").export.nunique() > 1).any():
        raise ValueError("A session is split across exports")

    complete = (raw.phase == "complete") & (raw.withdrawn_at == "")
    primary = raw[complete & (raw.kind == "primary")].copy()
    for t in TRAITS:
        primary[t + "_v"] = pd.to_numeric(primary[t].where(primary[t] != "unclear"), errors="coerce")
    agree = session_agreement(primary)
    agree["included"] = agree.agreement >= args.min_agreement
    kept = set(agree.loc[agree.included, "session_id"])

    raw["analysis_include_export"] = raw.analysis_include
    raw["analysis_include"] = np.where(complete & (raw.kind == "primary") & raw.session_id.isin(kept), "True", "False")
    raw["label_source"] = np.where(raw.get("data_origin", "") == "researcher_entered_rehearsal",
                                   "human_researcher_entered", "human_export")

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    raw.drop(columns="export").to_csv(out / "c1_pilot_responses.csv", index=False)
    agree.to_csv(out / "session_agreement.csv", index=False)
    inc = primary[primary.session_id.isin(kept)]
    targets = inc.groupby("sample_id").agg(**{f"{t}_mean": (t + "_v", "mean") for t in TRAITS},
                                           **{f"{t}_n": (t + "_v", "count") for t in TRAITS},
                                           listeners=("session_id", "nunique"))
    targets.round(4).to_csv(out / "c1_pilot_sound_targets.csv")

    sessions = raw.groupby("session_id").agg(phase=("phase", "first"), withdrawn=("withdrawn_at", lambda s: s.iloc[0] != ""))
    summary = dict(
        exports=[dict(file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), rows=len(f))
                 for p, f in zip(args.exports, frames)],
        rows=len(raw), sessions=int(raw.session_id.nunique()),
        complete_sessions=int(((sessions.phase == "complete") & ~sessions.withdrawn).sum()),
        rule=dict(complete_not_withdrawn=True, kind="primary", min_leave_one_out_agreement=args.min_agreement),
        excluded_for_agreement=agree.loc[~agree.included, ["session_id", "participant_label", "export", "agreement"]]
        .round(3).to_dict("records"),
        included_sessions=len(kept), included_evaluations=int(len(inc)), sounds=int(inc.sample_id.nunique()),
        listeners_per_sound=dict(min=int(targets.listeners.min()), median=float(targets.listeners.median()),
                                 max=int(targets.listeners.max())),
        label_source_counts=raw.loc[raw.analysis_include == "True", "label_source"].value_counts().to_dict(),
        note="Human ratings only. Researcher-entered rows are ratings typed in by the researcher for a listener.")
    (out / "selection.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("rows", "complete_sessions", "excluded_for_agreement", "included_sessions",
                                               "included_evaluations", "sounds", "listeners_per_sound",
                                               "label_source_counts")}, indent=2))


if __name__ == "__main__":
    main()
