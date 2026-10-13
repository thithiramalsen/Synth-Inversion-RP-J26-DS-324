"""Saved, provenance-tracked C2 EDA and validation evidence; no test outcomes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, load_prepared, sha, write_json
from generation.corpus_audio import load_audio


def grid():
    fig, axes = plt.subplots(4,4, figsize=(15,12), constrained_layout=True)
    for ax in axes.flat[13:]:
        ax.set_visible(False)
    return fig, list(axes.flat[:13])


def save(fig, output, name):
    fig.savefig(output/(name+".png"), dpi=150)
    plt.close(fig)


def read_predictions(run, frame, expected_partition="inverse"):
    config = json.loads((run/"run_config.json").read_text(encoding="utf-8"))
    summary = json.loads((run/"summary.json").read_text(encoding="utf-8"))
    path = run/"validation_predictions.csv"
    if summary["predictions_sha256"] != sha(path):
        raise ValueError("Prediction checksum differs from frozen run")
    predictions = pd.read_csv(path, float_precision="round_trip")
    if predictions.sample_id.duplicated().any():
        raise ValueError("Duplicate predictions")
    source = frame.set_index("sample_id").loc[predictions.sample_id]
    if not ((source.split == "validation") & (source.validation_role == expected_partition)).all():
        raise ValueError("Evidence may only consume inverse-validation predictions")
    actual = source[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float64)
    truth_suffix = "_actual_z" if NAMES[0]+"_actual_z" in predictions else "_true_z"
    exported = predictions[[n+truth_suffix for n in NAMES]].to_numpy(dtype=np.float64)
    if not np.allclose(actual, exported, rtol=0, atol=1e-15):
        raise ValueError("Exported truth differs from canonical actual readbacks")
    predicted = predictions[[n+"_predicted_z" for n in NAMES]].to_numpy(dtype=np.float64)
    if not np.isfinite(predicted).all():
        raise ValueError("Nonfinite delivered predictions")
    return config, summary, predictions, actual, predicted


def build(args):
    protocol, frame = load_prepared(args.prepared)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Evidence output must be new; existing evidence is preserved")
    config, summary, predictions, actual, predicted = read_predictions(args.run, frame)
    if config["protocol_sha256"] != sha(args.prepared/"protocol.json"):
        raise ValueError("Run/protocol mismatch")
    args.output.mkdir(parents=True, exist_ok=True)
    train = frame[frame.split == "train"]
    train_z = train[[n+"_z" for n in NAMES]].to_numpy(dtype=np.float64)
    bins = np.linspace(0,1,21)
    distributions, statistics, shifts = [], [], []
    fig, axes = grid()
    partitions = {
        "train": train,
        "calibration": frame[frame.split == "calibration"],
        "inverse_validation": frame[(frame.split == "validation") & (frame.validation_role == "inverse")],
        "reliability_validation": frame[(frame.split == "validation") & (frame.validation_role == "reliability")],
    }
    for j, name in enumerate(NAMES):
        for partition, rows in partitions.items():
            values = rows[name+"_z"].to_numpy(dtype=np.float64)
            counts, _ = np.histogram(values, bins=bins)
            mass = counts/len(values)
            axes[j].stairs(mass, bins, label=partition, linewidth=1.1)
            distributions.extend({"parameter": name, "partition": partition, "left_z": float(bins[k]),
                                  "right_z": float(bins[k+1]), "count": int(count),
                                  "fraction": float(mass[k])} for k,count in enumerate(counts))
            statistics.append({"parameter": name, "partition": partition, "n": len(values),
                "mean_z": float(values.mean()), "std_z_ddof0": float(values.std()),
                "min_z": float(values.min()), "q05_z": float(np.quantile(values,.05)),
                "median_z": float(np.median(values)), "q95_z": float(np.quantile(values,.95)),
                "max_z": float(values.max()), "vital_lower": protocol["lower"][j],
                "vital_upper": protocol["upper"][j]})
            train_counts, _ = np.histogram(train_z[:,j], bins)
            shifts.append({"parameter": name, "partition": partition,
                "max_absolute_20bin_mass_difference_from_train": float(np.max(np.abs(mass-train_counts/len(train))))})
        axes[j].set(title=name, xlabel="Research coordinate z", ylabel="Fraction in bin", ylim=(0,.10))
    axes[0].legend(fontsize=7)
    fig.suptitle("Actual-readback target distributions by non-test partition (20 fixed bins)")
    save(fig,args.output,"target_distributions_and_split_balance")
    pd.DataFrame(distributions).to_csv(args.output/"target_histogram_bins.csv", index=False)
    pd.DataFrame(statistics).to_csv(args.output/"target_descriptive_statistics.csv", index=False)
    pd.DataFrame(shifts).to_csv(args.output/"split_distribution_balance.csv", index=False)
    correlation = np.corrcoef(train_z, rowvar=False)
    pd.DataFrame(correlation,index=NAMES,columns=NAMES).to_csv(args.output/"training_parameter_correlation.csv")
    fig,ax = plt.subplots(figsize=(10,9),constrained_layout=True)
    im = ax.imshow(correlation, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(13),NAMES,rotation=60,ha="right",fontsize=8)
    ax.set_yticks(range(13),NAMES,fontsize=8)
    ax.set_title("Training-only Pearson correlation of generating controls\nSampling coverage, not acoustic identifiability")
    fig.colorbar(im,ax=ax,label="Pearson r")
    save(fig,args.output,"training_parameter_correlation")
    counts = frame.groupby(["split","validation_role"],dropna=False).size().reset_index(name="count")
    counts.to_csv(args.output/"split_counts.csv",index=False)
    labels = [r.split+("/"+r.validation_role if r.validation_role else "") for r in counts.itertuples()]
    fig,ax = plt.subplots(figsize=(10,4),constrained_layout=True)
    bars = ax.bar(labels,counts["count"],color=["#4477AA" if s != "test" else "#BBBBBB" for s in counts.split])
    ax.bar_label(bars,fmt="%d")
    ax.set(ylabel="Clips",title="Frozen disjoint assignments (test is reserved; count only)")
    ax.tick_params(axis="x",labelrotation=20)
    save(fig,args.output,"experimental_partition_counts")
    audio_rows = []
    # All 128 IDs were assigned before model errors were known; train-only audio EDA.
    for row in train[train.diagnostic_rank >= 0].sort_values("diagnostic_rank").to_dict("records"):
        audio, rate = load_audio(row,ROOT,verify=True)
        audio_rows.append({"sample_id": row["sample_id"], "sample_rate": rate,
            "sample_count": len(audio), "duration_seconds": len(audio)/rate,
            "peak_absolute": float(np.max(np.abs(audio))),
            "rms": float(np.sqrt(np.mean(np.square(audio.astype(np.float64))))),
            "mean_dc": float(audio.astype(np.float64).mean()), "all_finite": bool(np.isfinite(audio).all())})
    audio = pd.DataFrame(audio_rows)
    audio.to_csv(args.output/"training_audio_qa_128.csv",index=False)
    fig,axes = plt.subplots(1,3,figsize=(12,3.5),constrained_layout=True)
    for ax,column,label in zip(axes,("peak_absolute","rms","mean_dc"),("Peak |amplitude|","RMS amplitude","Mean DC after conditioning")):
        ax.hist(audio[column],bins=20,color="#4477AA")
        ax.set(xlabel=label,ylabel="Training clips")
    fig.suptitle("128 preselected training clips; hash-verified canonical conditioning; no loudness normalization")
    save(fig,args.output,"training_audio_quality")
    error = predicted-actual
    mae = np.abs(error).mean(axis=0)
    rmse = np.sqrt(np.square(error).mean(axis=0))
    correct = np.abs(error) <= protocol["tau_z"]
    metrics = []
    fig,axes = grid()
    for j,name in enumerate(NAMES):
        axes[j].hexbin(actual[:,j],predicted[:,j],gridsize=25,extent=(0,1,0,1),mincnt=1,cmap="viridis")
        axes[j].plot([0,1],[0,1],"--",color="#CC6677",lw=1)
        axes[j].set(title=name,xlabel="Actual z",ylabel="Predicted z",xlim=(0,1),ylim=(0,1))
        denominator = np.square(actual[:,j]-actual[:,j].mean()).sum()
        metrics.append({"parameter":name,"n":len(actual),"mae_z":float(mae[j]),"rmse_z":float(rmse[j]),
            "r_squared_z":float(1-np.square(error[:,j]).sum()/denominator) if denominator>0 else None,
            "correct_fraction_tau_05":float(correct[:,j].mean()),
            "training_mean_baseline_mae_z":float(np.abs(actual[:,j]-train_z[:,j].mean()).mean())})
    fig.suptitle("Inverse-validation actual vs delivered prediction (hexbin counts, not confidence)")
    save(fig,args.output,"validation_actual_vs_predicted")
    pd.DataFrame(metrics).to_csv(args.output/"validation_metrics_and_mean_baseline.csv",index=False)
    fig,axes = grid()
    residual_bins = []
    for j,name in enumerate(NAMES):
        values,edges = np.histogram(error[:,j],bins=np.linspace(-1,1,41))
        axes[j].stairs(values,edges,fill=True,color="#4477AA")
        axes[j].axvspan(-protocol["tau_z"],protocol["tau_z"],color="#228833",alpha=.2)
        axes[j].set(title=name,xlabel="Signed error in z",ylabel="Clips")
        residual_bins.extend({"parameter":name,"left_error_z":float(edges[k]),"right_error_z":float(edges[k+1]),
                              "count":int(count)} for k,count in enumerate(values))
    fig.suptitle("Inverse-validation residuals; green band is parameter tolerance ±0.05, NOT perceptual similarity")
    save(fig,args.output,"validation_error_distributions")
    pd.DataFrame(residual_bins).to_csv(args.output/"validation_error_histogram_bins.csv",index=False)
    fig,ax = plt.subplots(figsize=(12,5),constrained_layout=True)
    x = np.arange(13)
    ax.bar(x-.25,mae,width=.25,label="MAE",color="#4477AA")
    ax.bar(x,rmse,width=.25,label="RMSE",color="#EE6677")
    ax.bar(x+.25,[r["training_mean_baseline_mae_z"] for r in metrics],width=.25,label="Train-mean MAE",color="#BBBBBB")
    ax.set_xticks(x,NAMES,rotation=50,ha="right",fontsize=8)
    ax.set(ylabel="Error in research coordinate z",title="Per-control inverse-validation error; macro averages do not replace this table")
    ax.legend()
    save(fig,args.output,"validation_per_parameter_errors")
    binned = []
    fig,axes = grid()
    for j,name in enumerate(NAMES):
        bin_ids = np.minimum((actual[:,j]*10).astype(int),9)
        for k in range(10):
            mask = bin_ids == k
            binned.append({"parameter":name,"left_actual_z":k/10,"right_actual_z":(k+1)/10,
                "count":int(mask.sum()),"mae_z":float(np.abs(error[mask,j]).mean()) if mask.any() else None,
                "correct_fraction":float(correct[mask,j].mean()) if mask.any() else None})
        axes[j].plot(np.arange(10)/10+.05,[r["mae_z"] for r in binned[-10:]],marker="o",color="#4477AA")
        axes[j].set(title=name,xlabel="Actual z bin centre",ylabel="Mean absolute error",ylim=(0,.5))
    fig.suptitle("Validation error by true parameter range; descriptive diagnostics, NOT deployable oracle features")
    save(fig,args.output,"validation_error_by_actual_value")
    pd.DataFrame(binned).to_csv(args.output/"validation_error_by_actual_value.csv",index=False)
    context = []
    depth = actual[:,9]
    for j in (10,11,12):
        for k in range(10):
            mask = (depth >= k/10) & (depth < (k+1)/10)
            context.append({"parameter":NAMES[j],"left_true_env_depth_z":k/10,"right_true_env_depth_z":(k+1)/10,
                "count":int(mask.sum()),"mae_z":float(np.abs(error[mask,j]).mean()) if mask.any() else None})
    pd.DataFrame(context).to_csv(args.output/"filter_envelope_error_by_true_depth.csv",index=False)
    fig,ax = plt.subplots(figsize=(8,4),constrained_layout=True)
    for name in NAMES[10:]:
        selected = [r for r in context if r["parameter"] == name]
        ax.plot(np.arange(10)/10+.05,[r["mae_z"] for r in selected],marker="o",label=name)
    ax.set(xlabel="True filter-envelope amount z bin centre",ylabel="MAE in z",
           title="Envelope error vs generating depth (descriptive inverse-validation analysis)")
    ax.legend(fontsize=8)
    save(fig,args.output,"filter_envelope_error_context")
    history_paths = sorted(args.run.glob("member_*/training_history.csv")) or [args.run/"training_history.csv"]
    fig,axes = plt.subplots(1,2,figsize=(11,4),constrained_layout=True)
    for history_path in history_paths:
        history = pd.read_csv(history_path)
        ensemble = "validation_nll" in history
        first = "train_nll" if ensemble else "train_z_mse"
        second = "validation_nll" if ensemble else "validation_z_mse"
        label = history_path.parent.name
        axes[0].plot(history.epoch,history[first],label=label+" train")
        axes[0].plot(history.epoch,history[second],linestyle="--",label=label+" inverse-val")
        axes[1].plot(history.epoch,history.validation_z_mse,label=label)
    axes[0].set(xlabel="Epoch",ylabel="NLL (constant omitted)" if ensemble else "MSE in z",title="Saved training/model-selection history")
    axes[1].set(xlabel="Epoch",ylabel="Inverse-validation MSE in z",title="Point accuracy through training")
    for ax in axes:
        ax.legend(fontsize=7)
    save(fig,args.output,"learning_curves")
    if NAMES[0]+"_total_variance_z" in predictions:
        fig,axes = grid()
        uncertainty_bins = []
        for j,name in enumerate(NAMES):
            u = predictions[name+"_total_variance_z"].to_numpy()
            order = np.argsort(u,kind="stable")
            for k,ids in enumerate(np.array_split(order,10)):
                uncertainty_bins.append({"parameter":name,"equal_frequency_bin":k,"count":len(ids),
                    "mean_total_variance_z":float(u[ids].mean()),"mean_squared_error_z":float(np.square(error[ids,j]).mean()),
                    "correct_fraction":float(correct[ids,j].mean())})
            rows = uncertainty_bins[-10:]
            axes[j].plot([r["mean_total_variance_z"] for r in rows],[r["mean_squared_error_z"] for r in rows],marker="o")
            limit = max(max(r["mean_total_variance_z"] for r in rows),max(r["mean_squared_error_z"] for r in rows))
            axes[j].plot([0,limit],[0,limit],"--",color="#CC6677")
            axes[j].set(title=name,xlabel="Mean raw variance in bin",ylabel="Mean squared error")
        fig.suptitle("Raw uncertainty diagnostic (10 equal-frequency bins); NOT calibrated correctness probability")
        save(fig,args.output,"raw_uncertainty_vs_squared_error")
        pd.DataFrame(uncertainty_bins).to_csv(args.output/"raw_uncertainty_bins.csv",index=False)
    inherited_path = ROOT/"data/processed/team_handoff_v4_131072/verification.json"
    inherited = json.loads(inherited_path.read_text(encoding="utf-8"))
    non_test = frame[frame.split != "test"]
    offdiagonal = correlation[~np.eye(13,dtype=bool)]
    report = {"status":"complete", "protocol_sha256":sha(args.prepared/"protocol.json"),
        "run_config_sha256":sha(args.run/"run_config.json"),"predictions_sha256":summary["predictions_sha256"],
        "source_sha256":sha(Path(__file__)), "test_evaluated":False,
        "test_use":"assignment count and inherited corpus-integrity audit only; no test audio, predictions or tuning",
        "non_test_missing_parameter_values":int(non_test[[n+"_z" for n in NAMES]].isna().sum().sum()),
        "non_test_duplicate_parameter_vectors":int(non_test[[n+"_z" for n in NAMES]].duplicated().sum()),
        "training_max_absolute_off_diagonal_correlation":float(np.max(np.abs(offdiagonal))),
        "training_audio_qa_count":len(audio),"fresh_audio_hashes_verified":True,
        "inherited_corpus_verification":{"path":str(inherited_path),"sha256":sha(inherited_path),
            "verified_rows":inherited["verified_rows"],"quality_flags":inherited["quality_flags"],
            "caveat":"Existing C1 audit, not a fresh full waveform pass by this EDA script"},
        "normalization":{"train_only_mean":config["feature_mean_train_only"],"train_only_std":config["feature_std_train_only"]},
        "macro_validation_mae_z":float(mae.mean()), "tau_z":protocol["tau_z"],
        "artifacts":{p.name:{"sha256":sha(p),"bytes":p.stat().st_size} for p in sorted(args.output.iterdir()) if p.is_file()}}
    write_json(args.output/"evidence.json",report)
    print(json.dumps(report),flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,default=DEFAULT_PREPARED)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    build(parser.parse_args())
