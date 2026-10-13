"""Bounded, resumable non-test workflow after an already-running ensemble fit.

This is a local experiment command, not a scheduled automation. Status/logs survive
loss of the chat connection. Does not train a second writer or evaluate test audio.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
import traceback

from c2_estimation.v4.data import ROOT, digest_json, sha, write_json


def verify_stage(folder):
    summary = json.loads((folder/"summary.json").read_text(encoding="utf-8"))
    if summary.get("test_evaluated",True) or not summary["status"].startswith("complete"):
        raise ValueError("Stage is incomplete or unexpectedly evaluated test")
    for file,checksum in summary.get("files",{}).items():
        if sha(folder/file) != checksum:
            raise ValueError("Completed stage artifact changed: "+file)
    return summary


def run(args):
    if args.wait_minutes<=0 or args.workers<=0:
        raise ValueError("Positive wait budget/workers required")
    gpu_python = ROOT/".venv-c2/Scripts/python.exe"
    cpu_python = ROOT/"venv/Scripts/python.exe"
    if not gpu_python.exists() or not cpu_python.exists():
        raise ValueError("Both isolated CUDA and frozen synthesis environments are required")
    base = args.output
    source_paths = ["c2_estimation/v4/"+name+".py" for name in (
        "run_development","ensemble","evidence","predict_subsets","diagnostic_batch","diagnostics","calibration")]
    configuration = {"ensemble":str(args.ensemble.resolve()),"workers":args.workers,
        "tau_z":.05,"delta_z":.02,"bootstrap_replicates":2000,
        "scope":"128 training smoke; 2048 calibration; 512 reliability-validation; test held locked",
        "sources":{path:sha(ROOT/path) for path in source_paths},"test_evaluated":False}
    signature = digest_json(configuration)
    if (base/"run_config.json").exists():
        if json.loads((base/"run_config.json").read_text(encoding="utf-8"))["signature"] != signature:
            raise ValueError("Workflow config/source drift; use a new output directory")
    else:
        if base.exists() and any(base.iterdir()):
            raise ValueError("Nonempty workflow output without matching configuration")
        base.mkdir(parents=True,exist_ok=True)
        (base/"logs").mkdir(exist_ok=True)
        write_json(base/"run_config.json",{"signature":signature,**configuration})
    completed = []
    preserved = []
    def status(state,stage,**fields):
        write_json(base/"status.json",{"status":state,"stage":stage,"completed_stages":completed,
            "updated_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
            "signature":signature,"test_evaluated":False,"preserved_partial_outputs":preserved,**fields})
    def preserve_partial(folder,marker):
        # Only a known short-stage folder in this workflow, never corpus/model data.
        if folder.exists() and not (folder/marker).exists():
            if folder.is_symlink() or folder.resolve().parent != base.resolve():
                raise ValueError("Unsafe partial-stage path")
            folder.resolve().relative_to(ROOT.resolve())
            backup = folder.with_name(folder.name+"__partial_"+time.strftime("%Y%m%dT%H%M%SZ",time.gmtime()))
            if backup.exists():
                raise ValueError("Partial-output backup already exists")
            folder.rename(backup)
            preserved.append(str(backup))
    def command(stage,python,module,arguments):
        for path,checksum in configuration["sources"].items():
            if sha(ROOT/path) != checksum:
                raise ValueError("Workflow source changed while running: "+path)
        status("running",stage)
        print("Starting "+stage,flush=True)
        with (base/"logs"/(stage+".log")).open("a",encoding="utf-8") as log:
            subprocess.run([str(python),"-B","-m",module,*[str(a) for a in arguments]],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        completed.append(stage)
        status("running",stage)
    try:
        deadline = time.monotonic()+args.wait_minutes*60
        while not (args.ensemble/"summary.json").exists():
            status("waiting_for_existing_ensemble","ensemble",note="No duplicate training job launched")
            if time.monotonic()>deadline:
                raise TimeoutError("Ensemble not complete within bounded wait; inspect member histories, then rerun workflow")
            time.sleep(15)
        ensemble_summary = verify_stage(args.ensemble)
        completed.append("ensemble")
        evidence = base/"evidence_ensemble"
        if not (evidence/"evidence.json").exists():
            preserve_partial(evidence,"evidence.json")
            command("evidence_ensemble",cpu_python,"c2_estimation.v4.evidence",["--run",args.ensemble,"--output",evidence])
        else:
            record = json.loads((evidence/"evidence.json").read_text(encoding="utf-8"))
            if record["predictions_sha256"] != ensemble_summary["predictions_sha256"]:
                raise ValueError("Ensemble evidence belongs to different predictions")
            for file,item in record["artifacts"].items():
                if sha(evidence/file) != item["sha256"]:
                    raise ValueError("Completed evidence changed")
            completed.append("evidence_ensemble")
        diagnostic_folders = {}
        for partition in ("smoke","calibration","reliability-validation"):
            predictions = base/("predictions_"+partition)
            if not (predictions/"predictions.json").exists():
                preserve_partial(predictions,"predictions.json")
                command("predict_"+partition,gpu_python,"c2_estimation.v4.predict_subsets",
                    ["--ensemble",args.ensemble,"--partition",partition,"--output",predictions,"--device","cuda"])
            else:
                metadata = json.loads((predictions/"predictions.json").read_text(encoding="utf-8"))
                if metadata["ensemble_config_sha256"] != sha(args.ensemble/"run_config.json"):
                    raise ValueError("Frozen predictions belong to a different ensemble")
                completed.append("predict_"+partition)
            diagnostic_folder = base/("diagnostics_"+partition)
            if not (diagnostic_folder/"summary.json").exists():
                command("diagnose_"+partition,cpu_python,"c2_estimation.v4.diagnostic_batch",
                    ["--predictions",predictions,"--output",diagnostic_folder,"--workers",args.workers])
            else:
                verify_stage(diagnostic_folder)
                completed.append("diagnose_"+partition)
            record = verify_stage(diagnostic_folder)
            expected = {"smoke":128,"calibration":2048,"reliability-validation":512}[partition]
            if record["count"] != expected or record["audit_count"] != 4:
                raise ValueError("Diagnostic smoke/cardinality audit failed")
            diagnostic_folders[partition] = diagnostic_folder
        for tau in (.05,.025,.10):
            folder = base/f"calibration_tau_{tau:g}"
            stage = f"calibrate_tau_{tau:g}"
            if not (folder/"summary.json").exists():
                preserve_partial(folder,"summary.json")
                command(stage,cpu_python,"c2_estimation.v4.calibration",
                    ["--calibration",diagnostic_folders["calibration"],"--validation",diagnostic_folders["reliability-validation"],
                     "--output",folder,"--tau",tau,"--bootstrap",2000])
            else:
                verify_stage(folder)
                completed.append(stage)
        primary = verify_stage(base/"calibration_tau_0.05")
        lines = ["# Development C2 uncertainty/calibration run", "", "All values below are development evidence, not untouched-test results.", "",
            f"Three-member ensemble inverse-validation macro z MAE: {ensemble_summary['macro_validation_z_mae']:.6f}.",
            "", "128 training smoke clips passed before 2,048 calibration and 512 reliability-validation diagnostics.",
            "Delivered parameters remained fixed. Four error-independent renderer audits per partition passed.","",
            "Reliability-validation macro Brier scores (also used for C selection):","",
            "| Variant | Brier |","|---|---:|"]
        lines.extend(f"| {name} | {value:.6f} |" for name,value in primary["macro_validation_brier"].items())
        lines.extend(["", "No calibrated-success conclusion should be generalized to test yet.",
            "Ablations, reliability diagrams, raw-U ranking, risk/coverage, matched-coverage MAE and paired whole-audio bootstrap are saved in each calibration folder.",
            "Tolerances .025/.05/.10 are evaluated on development partitions only.",
            "Perturbation-step sensitivity, method locking, final test, stronger architecture and the small human study remain later work.", ""])
        (base/"RESULTS.md").write_text("\n".join(lines),encoding="utf-8")
        status("completed_development_uncertainty_and_calibration","done",
               ensemble_macro_validation_z_mae=ensemble_summary["macro_validation_z_mae"],
               macro_validation_brier=primary["macro_validation_brier"],test_method_locked=False)
        print("Completed non-test workflow; held-out test remains locked",flush=True)
    except BaseException:
        status("failed","inspect_logs",error=traceback.format_exc())
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensemble",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--wait-minutes",type=float,default=120.)
    run(parser.parse_args())
