"""Phase 6 - sanity checks and representation diagnostic (validation targets only).

For each cached representation:
  * self-relevance of a sample to itself (before exclusion) must be 1.0;
  * distribution of top-1 relevance and of relevance at ranks 5 / 50 / 100 (scale, guide §8.3);
  * cache reproducibility: 20 random rows recomputed from audio must equal the cache;
  * DIAGNOSTIC: parameter distance between each val target and its audio top-1 / top-5
    (lower = the representation retrieves patches with closer recipes), with bootstrap CIs.

The diagnostic informs the USER's choice of primary representation; it does not choose.
Writes ``<outputs_dir>/features/diagnostics.json`` and ``representation_diagnostic.csv``.

Usage (repo root):
    python c3_recommendation/scripts/06_feature_diagnostics.py [--n-targets 500]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.audio_io import CorpusAudioReader  # noqa: E402
from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.features import REPRESENTATIONS, FeatureExtractor, FeatureSettings, load_feature_cache  # noqa: E402
from c3.param_space import ParamDistance  # noqa: E402
from c3.relevance import FeatureCosineRelevance  # noqa: E402
from c3.retrieval import pool_from_scores  # noqa: E402
from c3.splits import BANK, VAL, Splits, load_manifest  # noqa: E402
from c3.stats import bootstrap_indices, bootstrap_mean_ci  # noqa: E402

RANKS = (1, 5, 50, 100)
PCTS = (5, 25, 50, 75, 95)


def pct(values) -> dict:
    return {f"p{p}": float(np.percentile(values, p)) for p in PCTS} | {"mean": float(np.mean(values))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--n-targets", type=int, default=None, help="default: splits.n_val_targets_eval")
    parser.add_argument("--n-sanity", type=int, default=200)
    parser.add_argument("--n-recompute", type=int, default=20)
    args = parser.parse_args()

    cfg = load_config(args.config)
    features_dir = cfg.path("outputs_dir") / "features"
    source = make_source(cfg)
    unit = source.params_unit()
    splits = Splits.from_config(cfg, load_manifest(cfg.path("outputs_dir") / "splits"))
    bank_ids = splits.ids(BANK)
    n_targets = args.n_targets or int(cfg["splits.n_val_targets_eval"])
    targets = splits.get_targets(VAL, n_targets, cfg.seed)
    sanity_targets = targets[: args.n_sanity]
    distance = ParamDistance.from_schema(source.schema, method=cfg["param_distance.method"])
    bank_values = unit.loc[bank_ids].to_numpy(np.float64)
    bank_pos = {cid: i for i, cid in enumerate(bank_ids)}
    boot = bootstrap_indices(n_targets, int(cfg["stats.bootstrap_resamples"]), cfg.seed)
    rng = np.random.default_rng(cfg.seed)

    report = {"generated_utc": datetime.now(timezone.utc).isoformat(), "n_targets": n_targets,
              "target_split": VAL, "bank_size": len(bank_ids), "representations": {}}
    diag_rows = []
    reader, extractor = CorpusAudioReader(cfg.path("corpus_dir")), None
    for rep in REPRESENTATIONS:
        array, ids, meta = load_feature_cache(features_dir, rep)
        extractor = extractor or FeatureExtractor(FeatureSettings(**meta["settings"]))
        relevance = FeatureCosineRelevance(rep, array, ids, extractor=extractor)
        relevance.fit(bank_ids)

        self_scores = np.array([relevance.score_ids(t, [t])[0] for t in sanity_targets])
        recompute_rows = rng.choice(len(ids), size=args.n_recompute, replace=False)
        recompute_diff = max(float(np.abs(extractor.extract(*reader.load(ids[i]))[rep] - array[i]).max())
                             for i in recompute_rows)

        rank_rel = {r: [] for r in RANKS}
        top1_dist, top5_mean, top5_min = [], [], []
        for t in targets:
            pool = pool_from_scores(relevance.score_bank(t), bank_ids, max(RANKS))
            for r in RANKS:
                rank_rel[r].append(float(pool["relevance"].iloc[r - 1]))
            vectors = bank_values[[bank_pos[c] for c in pool["candidate_id"].iloc[:5]]]
            d = distance.cdist(unit.loc[t].to_numpy(np.float64), vectors)[0]
            top1_dist.append(d[0]); top5_mean.append(d.mean()); top5_min.append(d.min())

        entry = {
            "dims": int(array.shape[1]), "zero_variance_dims": relevance.describe()["zero_variance_dims"],
            "self_relevance_max_abs_dev_from_1": float(np.abs(self_scores - 1.0).max()),
            "cache_recompute_max_abs_diff": recompute_diff, "cache_recompute_rows": int(args.n_recompute),
            "relevance_at_rank": {str(r): pct(rank_rel[r]) for r in RANKS},
        }
        for name, values in (("top1_param_dist", top1_dist), ("top5_mean_param_dist", top5_mean),
                             ("top5_min_param_dist", top5_min)):
            mean, low, high = bootstrap_mean_ci(np.asarray(values), boot, float(cfg["stats.alpha"]))
            entry[name] = {"mean": mean, "ci_low": low, "ci_high": high, "median": float(np.median(values))}
            diag_rows.append({"representation": rep, "metric": name, "mean": mean, "ci_low": low, "ci_high": high,
                              "median": float(np.median(values)), "n_targets": n_targets})
        report["representations"][rep] = entry

    # Reference points from parameter space (not audio): random bank patch and the true parameter 1-NN.
    random_d = [float(distance.cdist(unit.loc[t].to_numpy(np.float64), bank_values[rng.integers(len(bank_ids))])[0, 0])
                for t in targets]
    report["reference_random_bank_patch_param_dist_mean"] = float(np.mean(random_d))
    phase3 = cfg.path("outputs_dir") / "analysis" / "param_structure.json"
    if phase3.exists():
        report["reference_bank_param_1nn_median_phase3"] = json.loads(phase3.read_text(encoding="utf-8"))["nn1"]["p50"]

    (features_dir / "diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(diag_rows).to_csv(features_dir / "representation_diagnostic.csv", index=False, float_format="%.6f")

    print(f"Validation targets: {n_targets} (sanity on {len(sanity_targets)})   bank {len(bank_ids)}")
    for rep, e in report["representations"].items():
        rr = e["relevance_at_rank"]
        print(f"\n[{rep}] dims {e['dims']}  zero-variance dims {e['zero_variance_dims']}")
        print(f"  self-relevance max |1 - s| = {e['self_relevance_max_abs_dev_from_1']:.2e}   "
              f"cache recompute max diff = {e['cache_recompute_max_abs_diff']:.2e} ({args.n_recompute} rows)")
        print("  relevance by rank (median [p5, p95]): " + "  ".join(
            f"#{r}: {rr[str(r)]['p50']:.4f} [{rr[str(r)]['p5']:.4f}, {rr[str(r)]['p95']:.4f}]" for r in RANKS))
        for name in ("top1_param_dist", "top5_mean_param_dist", "top5_min_param_dist"):
            m = e[name]
            print(f"  {name:22s} mean {m['mean']:.4f}  95% CI [{m['ci_low']:.4f}, {m['ci_high']:.4f}]  median {m['median']:.4f}")
    print(f"\nReference: random bank patch {report['reference_random_bank_patch_param_dist_mean']:.4f}; "
          f"true parameter 1-NN median {report.get('reference_bank_param_1nn_median_phase3', float('nan')):.4f}")
    print("The choice of primary representation is the user's (record it in PREREGISTRATION.md).")


if __name__ == "__main__":
    main()
