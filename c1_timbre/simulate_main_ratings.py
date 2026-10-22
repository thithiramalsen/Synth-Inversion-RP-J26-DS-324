"""Generate the SIMULATED C1 main-study response dataset (engineering only).

No human produced these ratings. This runs the pilot simulator
(simulate_pilot_ratings.py) on the main-study package, so both simulations use one
artificial rating rule and listener model:

* 30 completed sessions on blocks 01-30: 3 practice + 22 unique study sounds
  + 2 hidden repeats each, break after 12 (5-6 listeners for each of 128 sounds)
* one abandoned and one withdrawn session on the next blocks (excluded)
* "true" sound means on the simulated pilot's scale; sounds shared with the pilot
  (16 anchors + 3 practice) keep their pilot truth

Replace the output with the real survey export once human ratings exist.

    .\\venv\\Scripts\\python.exe -B c1_timbre/simulate_main_ratings.py
    .\\venv\\Scripts\\python.exe -B c1_timbre/simulate_main_ratings.py --seed 7 --output-dir c1_timbre/simulated/c1_main_sim_seed7
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from c1_timbre import simulate_pilot_ratings as simulator  # noqa: E402

PLAN_VERSION = "c1_main_v1_simpilot_dryrun"
DEFAULTS = dict(
    bundle=ROOT / "data/processed" / PLAN_VERSION / "bundle.json",
    config=ROOT / "c1_timbre/main_study" / PLAN_VERSION / "c1_main_protocol_DRAFT.json",
    output_dir=ROOT / "c1_timbre/simulated/c1_main_sim_v1",
    truth_reference=ROOT / "c1_timbre/simulated/c1_pilot_sim_v1/simulation_ground_truth.csv",
    participants=30,
    seed=20261115,
    start_date="2027-01-11T09:00:00+00:00",
)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan-version", default=PLAN_VERSION,
                   help="plan_main_study.py --version whose bundle and protocol to use")
    p.add_argument("--output-dir", type=Path, default=DEFAULTS["output_dir"])
    p.add_argument("--participants", type=int, default=DEFAULTS["participants"])
    p.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    p.add_argument("--start-date", default=DEFAULTS["start_date"])
    p.add_argument("--truth-reference", type=Path, default=DEFAULTS["truth_reference"],
                   help="pilot simulation_ground_truth.csv (keeps anchors consistent with the pilot)")
    p.add_argument("--no-incomplete", action="store_true", help="omit the abandoned/withdrawn example sessions")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    bundle = ROOT / "data/processed" / args.plan_version / "bundle.json"
    config = ROOT / "c1_timbre/main_study" / args.plan_version / "c1_main_protocol_DRAFT.json"
    for path in (bundle, config, args.truth_reference):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run plan_main_study.py / simulate_pilot_ratings.py first")

    argv = ["--bundle", str(bundle), "--config", str(config), "--output-dir", str(args.output_dir),
            "--participants", str(args.participants), "--seed", str(args.seed), "--start-date", args.start_date,
            "--study-id", "c1_main_SIMULATED_v1", "--generator-version", "c1_main_sim_v1", "--file-prefix", "c1_main",
            "--truth-reference", str(args.truth_reference)]
    if args.no_incomplete:
        argv.append("--no-incomplete")
    if args.overwrite:
        argv.append("--overwrite")
    sys.argv = [simulator.__file__, *argv]
    simulator.main()


if __name__ == "__main__":
    main()
