"""Calibration-only logistic fitting; reliability-validation C selection/ablations.

This development module refuses test rows. Test evaluation must be a separate,
method-locked run. Success labels measure generating-parameter recovery, not sound
similarity. Raw variance is used only as a ranking baseline, never as q.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import rankdata

from c2_estimation.v4.data import NAMES, SEED, digest_json, sha, write_json

VARIANTS = {"g(U)":("U",), "g(U,S)":("U","S"), "g(U,R)":("U","R"), "g(U,S,R)":("U","S","R")}
C_GRID = (.01,.1,1.,10.)
COVERAGES = (.1,.25,.5,.75,1.)


def features(frame,name,columns):
    result = []
    for column in columns:
        values = frame["R" if column == "R" else name+("_total_variance_z" if column == "U" else "_S")].to_numpy(dtype=np.float64)
        if not np.isfinite(values).all() or (values<0).any() or (column == "U" and (values<=0).any()):
            raise ValueError("Invalid U/S/R feature")
        result.append(np.log(np.maximum(values,1e-12)) if column == "U" else np.log1p(values))
    return np.column_stack(result)


def labels(frame,name,tau):
    error = np.abs(frame[name+"_predicted_z"].to_numpy(dtype=np.float64)-frame[name+"_actual_z"].to_numpy(dtype=np.float64))
    if not np.isfinite(error).all():
        raise ValueError("Invalid correctness labels")
    return (error<=tau).astype(float),error


def fit(x,y,c):
    """Mean binomial NLL + ||w||²/(2*C*n); intercept unpenalized; no class weights."""
    x,y = np.asarray(x,dtype=np.float64),np.asarray(y,dtype=np.float64)
    if x.ndim != 2 or len(x) != len(y) or not len(y) or c<=0 or not np.isfinite(x).all() or not np.isin(y,[0.,1.]).all():
        raise ValueError("Invalid logistic calibration input")
    mean,std = x.mean(axis=0),x.std(axis=0)
    std = np.where(std<1e-12,1.,std)
    model = {"mean":mean.tolist(),"std":std.tolist(),"C":c,"count":len(y),
             "success_count":int(y.sum()),"class_weight":"none","constant_probability":None}
    if np.unique(y).size == 1:
        model.update(constant_probability=float(y[0]),weights=[0.]*x.shape[1],intercept=0.,solver_status="single_class_constant")
        return model
    standardized = (x-mean)/std
    n = len(y)
    def objective(parameters):
        w,b = parameters[:-1],parameters[-1]
        logits = standardized@w+b
        penalty = np.dot(w,w)/(2*c*n)
        loss = np.mean(np.logaddexp(0,logits)-y*logits)+penalty
        residual = expit(logits)-y
        gradient = np.r_[standardized.T@residual/n+w/(c*n),residual.mean()]
        return loss,gradient
    initial = np.r_[np.zeros(x.shape[1]),np.log(y.mean()/(1-y.mean()))]
    result = minimize(objective,initial,jac=True,method="L-BFGS-B",
                      options={"maxiter":1000,"ftol":1e-12,"gtol":1e-8})
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError("Logistic fit failed: "+str(result.message))
    model.update(weights=result.x[:-1].tolist(),intercept=float(result.x[-1]),
                 solver_status=str(result.message),objective=float(result.fun))
    return model


def predict(model,x):
    if model["constant_probability"] is not None:
        return np.full(len(x),model["constant_probability"],dtype=np.float64)
    standardized = (np.asarray(x)-np.array(model["mean"]))/np.array(model["std"])
    return expit(standardized@np.array(model["weights"])+model["intercept"])


def ranking_metrics(failure,score):
    failure,score = np.asarray(failure),np.asarray(score)
    positives = int(failure.sum())
    negatives = len(failure)-positives
    if not positives or not negatives:
        return {"failure_auroc":None,"failure_average_precision":None,"ranking_status":"single_class_undefined"}
    ranks = rankdata(score,method="average")
    auc = (ranks[failure==1].sum()-positives*(positives+1)/2)/(positives*negatives)
    order = np.argsort(-score,kind="stable")
    ordered = failure[order]
    ends = np.r_[np.flatnonzero(np.diff(score[order]))+1,len(score)]
    tp = np.cumsum(ordered)[ends-1]
    precision = tp/ends
    ap = np.sum(np.diff(np.r_[0,tp])/positives*precision)
    return {"failure_auroc":float(auc),"failure_average_precision":float(ap),"ranking_status":"defined"}


def risk_curve(y,score,error):
    # Larger score means more likely success. Stable input order is preassigned diagnostic rank.
    order = np.argsort(-np.asarray(score),kind="stable")
    counts = np.arange(1,len(y)+1)
    risk = np.cumsum(1-np.asarray(y)[order])/counts
    mae = np.cumsum(np.asarray(error)[order])/counts
    return counts/len(y),risk,mae


def probability_metrics(y,q,error):
    if not np.isfinite(q).all() or np.any((q<0)|(q>1)):
        raise ValueError("Invalid correctness probabilities")
    ordered = np.argsort(q,kind="stable")
    bins = []
    for k,ids in enumerate(np.array_split(ordered,min(10,len(y)))):
        bins.append({"bin":k,"count":len(ids),"mean_q":float(q[ids].mean()),"observed_success":float(y[ids].mean()),
                     "min_q":float(q[ids].min()),"max_q":float(q[ids].max())})
    ece = sum(b["count"]*abs(b["mean_q"]-b["observed_success"]) for b in bins)/len(y)
    coverage,risk,mae = risk_curve(y,q,error)
    result = {"brier":float(np.square(q-y).mean()),"ece_10_equal_frequency":float(ece),
              "aurc_discrete":float(risk.mean()),"success_count":int(y.sum()),"failure_count":int((1-y).sum()),
              **ranking_metrics(1-y,1-q)}
    for c in COVERAGES:
        i = max(1,int(np.ceil(len(y)*c)))-1
        result[f"risk_at_coverage_{c:g}"] = float(risk[i])
        result[f"mae_z_at_coverage_{c:g}"] = float(mae[i])
    return result,bins,(coverage,risk,mae)


def load_diagnostics(folder,partition):
    summary = json.loads((folder/"summary.json").read_text(encoding="utf-8"))
    config = json.loads((folder/"run_config.json").read_text(encoding="utf-8"))
    if summary["status"] != "complete" or summary["partition"] != partition or summary["test_evaluated"] or not summary["predictions_unchanged"]:
        raise ValueError("Diagnostics incomplete, wrong partition, or test data")
    for file,checksum in summary["files"].items():
        if sha(folder/file) != checksum:
            raise ValueError("Diagnostic result changed: "+file)
    frame = pd.read_parquet(folder/"diagnostics.parquet")
    if frame.sample_id.duplicated().any() or len(frame) != summary["count"]:
        raise ValueError("Duplicate/missing diagnostic rows")
    expected_split = "calibration" if partition == "calibration" else "validation"
    if not (frame.split == expected_split).all() or (partition != "calibration" and not (frame.validation_role == "reliability").all()):
        raise ValueError("Calibration and reliability-validation must remain separate")
    frame = frame.sort_values("diagnostic_rank").reset_index(drop=True)
    return config,summary,frame


def paired_brier_bootstrap(y,probabilities,reference="g(U)",replicates=2000,seed=SEED):
    if replicates<1:
        raise ValueError("Positive bootstrap count required")
    indices = np.random.default_rng(seed).integers(0,len(y),size=(replicates,len(y)))
    reference_loss = np.square(probabilities[reference]-y).mean(axis=1)
    result = []
    for variant,q in probabilities.items():
        loss = np.square(q-y).mean(axis=1)
        differences = (loss-reference_loss)[indices].mean(axis=1)
        result.append({"variant":variant,"reference":reference,"metric":"macro Brier difference (variant-reference)",
            "point_difference":float((loss-reference_loss).mean()),"ci95_low":float(np.quantile(differences,.025)),
            "ci95_high":float(np.quantile(differences,.975)),"bootstrap_unit":"whole audio (13 controls together)",
            "replicates":replicates,"seed":seed})
    return result


def run(args):
    if args.tau<=0 or args.tau>1:
        raise ValueError("Invalid correctness tolerance")
    cc,cs,cal = load_diagnostics(args.calibration,"calibration")
    vc,vs,val = load_diagnostics(args.validation,"reliability-validation")
    for key in ("protocol_sha256","ensemble_config_sha256","member_checkpoints","delta_z","distance_config"):
        if cc[key] != vc[key]:
            raise ValueError("Calibration/validation diagnostic settings differ")
    if set(cal.sample_id)&set(val.sample_id):
        raise ValueError("Partitions overlap")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Calibration output must be new")
    args.output.mkdir(parents=True,exist_ok=True)
    models,candidates,metrics,bin_rows,risk_rows = {},[],[],[],[]
    probabilities = {key:np.zeros((len(val),13)) for key in ("g0",*VARIANTS)}
    actual_labels = np.zeros((len(val),13))
    raw_rows = []
    figures,axes = plt.subplots(4,4,figsize=(15,12),constrained_layout=True)
    risk_fig,risk_axes = plt.subplots(4,4,figsize=(15,12),constrained_layout=True)
    for ax in list(axes.flat)[13:]+list(risk_axes.flat)[13:]:
        ax.set_visible(False)
    for j,name in enumerate(NAMES):
        cy,_ = labels(cal,name,args.tau)
        vy,error = labels(val,name,args.tau)
        actual_labels[:,j] = vy
        models[name] = {"g0_probability":float(cy.mean())}
        probabilities["g0"][:,j] = cy.mean()
        for variant,columns in VARIANTS.items():
            cx,vx = features(cal,name,columns),features(val,name,columns)
            options = []
            for c in C_GRID:
                model = fit(cx,cy,c)
                q = predict(model,vx)
                brier = float(np.square(q-vy).mean())
                candidates.append({"parameter":name,"variant":variant,"C":c,"validation_brier":brier})
                options.append((brier,c,model,q))
            _,_,model,q = min(options,key=lambda o:(o[0],o[1]))
            models[name][variant] = {"features":list(columns),**model}
            probabilities[variant][:,j] = q
        for variant in probabilities:
            q = probabilities[variant][:,j]
            m,bins,curve = probability_metrics(vy,q,error)
            metrics.append({"parameter":name,"variant":variant,"tau_z":args.tau,**m})
            bin_rows.extend({"parameter":name,"variant":variant,**b} for b in bins)
            axes.flat[j].plot([b["mean_q"] for b in bins],[b["observed_success"] for b in bins],marker="o",markersize=3,label=variant)
            coverage,risk,mae = curve
            risk_axes.flat[j].plot(coverage,risk,label=variant)
            risk_rows.extend({"parameter":name,"variant":variant,"coverage":float(c),"risk":float(r),"mae_z":float(e)} for c,r,e in zip(coverage,risk,mae,strict=True))
        u = val[name+"_total_variance_z"].to_numpy(dtype=np.float64)
        coverage,risk,mae = risk_curve(vy,-u,error)
        raw = {"parameter":name,"variant":"raw-U ranking (not q)","aurc_discrete":float(risk.mean()),**ranking_metrics(1-vy,u)}
        for c in COVERAGES:
            i = max(1,int(np.ceil(len(vy)*c)))-1
            raw[f"risk_at_coverage_{c:g}"] = float(risk[i])
            raw[f"mae_z_at_coverage_{c:g}"] = float(mae[i])
        raw_rows.append(raw)
        risk_rows.extend({"parameter":name,"variant":"raw-U ranking (not q)","coverage":float(c),"risk":float(r),"mae_z":float(e)} for c,r,e in zip(coverage,risk,mae,strict=True))
        risk_axes.flat[j].plot(coverage,risk,linestyle="--",label="raw-U")
        axes.flat[j].plot([0,1],[0,1],"--",color="gray",lw=1)
        axes.flat[j].set(title=name,xlabel="Predicted correctness q",ylabel="Observed correctness",xlim=(0,1),ylim=(0,1))
        risk_axes.flat[j].set(title=name,xlabel="Coverage",ylabel="Failure risk",xlim=(0,1),ylim=(0,1))
    axes.flat[0].legend(fontsize=7)
    risk_axes.flat[0].legend(fontsize=7)
    figures.suptitle("Reliability-validation diagrams (10 equal-frequency bins); same data selected C, not final test")
    risk_fig.suptitle("Reliability-validation risk/coverage; stable preassigned-rank tie breaks; not final test")
    figures.savefig(args.output/"reliability_diagrams.png",dpi=150)
    risk_fig.savefig(args.output/"risk_coverage.png",dpi=150)
    plt.close(figures)
    plt.close(risk_fig)
    for file,rows in (("candidate_C_scores.csv",candidates),("parameter_metrics.csv",metrics),
                      ("reliability_bins.csv",bin_rows),("risk_coverage.csv",risk_rows),
                      ("raw_uncertainty_ranking.csv",raw_rows),
                      ("paired_brier_bootstrap.csv",paired_brier_bootstrap(actual_labels,probabilities,replicates=args.bootstrap))):
        pd.DataFrame(rows).to_csv(args.output/file,index=False)
    delivered = val[["sample_id","diagnostic_rank"]].copy()
    for j,name in enumerate(NAMES):
        delivered[name+"_correct"] = actual_labels[:,j]
        for variant,q in probabilities.items():
            delivered[name+"_"+variant] = q[:,j]
    delivered.to_parquet(args.output/"validation_probabilities.parquet",index=False)
    configuration = {"status":"development_calibrators_fitted", "tau_z":args.tau,
        "C_grid":list(C_GRID),"C_selection":"per-control/per-variant minimum reliability-validation Brier; smallest C breaks ties",
        "primary_variant":"g(U,S,R)","primary_reference":"g(U)",
        "transforms":{"U":"ln(max(total_variance_z,1e-12))","S":"ln(1+S)","R":"ln(1+R)"},
        "scaling":"mean/std fitted calibration rows only; zero std replaced by 1",
        "objective":"mean binomial NLL + ||w||^2/(2*C*n); intercept unpenalized; no class balancing",
        "variance_type":"total equal-weight ensemble mixture variance in z^2",
        "ece":"10 equal-frequency bins sorted by q; stable preassigned-rank tie breaks; split ties permitted",
        "aurc":"arithmetic mean of prefix failure risk over coverages k/n, k=1..n",
        "average_precision":"noninterpolated step precision weighted by recall increments; score ties grouped",
        "bootstrap":"2000 default paired whole-audio percentile Brier difference intervals; validation only",
        "bootstrap_replicates":args.bootstrap,
        "test_evaluated":False,"test_method_locked":False,
        "validation_caveat":"Validation used to select C; bootstrap is descriptive, not unbiased final inference",
        "diagnostic_config":cc,"calibration_summary_sha256":sha(args.calibration/"summary.json"),
        "validation_summary_sha256":sha(args.validation/"summary.json"),
        "source_sha256":sha(Path(__file__)),"models":models}
    configuration["signature"] = digest_json(configuration)
    write_json(args.output/"calibrators.json",configuration)
    result = {"status":"complete_development_calibration", "calibration_count":len(cal),"validation_count":len(val),
        "tau_z":args.tau,"test_evaluated":False,"test_method_locked":False,
        "macro_validation_brier":{key:float(np.square(q-actual_labels).mean()) for key,q in probabilities.items()},
        "files":{p.name:sha(p) for p in args.output.iterdir() if p.is_file()}}
    write_json(args.output/"summary.json",result)
    print(json.dumps(result),flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration",type=Path,required=True)
    parser.add_argument("--validation",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--tau",type=float,default=.05)
    parser.add_argument("--bootstrap",type=int,default=2000)
    run(parser.parse_args())
