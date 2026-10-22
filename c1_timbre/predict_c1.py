"""Predict the four C1 descriptors for sounds with a trained C1 model.

Inputs (choose one):
    --wav FILE [FILE ...]   audio files (mono 44.1 kHz; the study protocol is a 3 s render)
    --wav-dir DIR           every .wav in a folder
    --corpus-ids ID [...]   v4 corpus sample IDs (features read from the corpus feature table)
    --corpus                all 131,072 corpus sounds (from the corpus feature table)

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.predict_c1 --wav my_sound.wav
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.predict_c1 --corpus-ids restricted_bend_sustain_v4_00042
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.predict_c1 --corpus --output data/processed/c1_predictions/corpus.parquet

Each prediction carries:
* raw scores and display scores (clipped to 1-7, the declared display rule)
* support: standardized feature distance to the nearest training sound, and a
  weak-support flag when it exceeds the training set's own 95th-percentile
  nearest-neighbour distance (a diagnostic, not a calibrated confidence)
* domain warnings when the audio departs from the study render protocol
* model, feature-version and label-source provenance

Predictions are model output, never human labels. A model trained on SIMULATED
ratings reproduces the simulator's artificial rule.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from c1_timbre.c1_model import load_models
from c1_timbre.features_v2 import FEATURE_NAMES, FEATURE_VERSION, SR, extract

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ("brightness", "roughness", "percussiveness", "sustainedness")
DEFAULT_RUN = ROOT / "c1_timbre/models/c1_ridge_main_SIMULATED_humanpilot_v1"
CORPUS_FEATURES = ROOT / "data/processed/c1_features_v2/corpus_features.parquet"
RENDER_FRAMES = 132300
SUPPORT_QUANTILE = 0.95


class Predictor:
    def __init__(self, run_dir: Path = DEFAULT_RUN, model_file: str = "model_final_all_sounds.json"):
        self.run_dir = Path(run_dir)
        self.models, self.card = load_models(self.run_dir / model_file)
        names = self.card["descriptors"][TRAITS[0]]["features"]
        if names != FEATURE_NAMES or self.card["provenance"]["feature_version"] != FEATURE_VERSION:
            raise ValueError("Model was trained on a different feature definition")
        train = pd.read_csv(self.run_dir / "features.csv", index_col="sample_id")[FEATURE_NAMES].to_numpy()
        self.mu, self.sd = train.mean(0), np.maximum(train.std(0), 1e-12)
        self.train_z = (train - self.mu) / self.sd
        nn = [np.sort(np.sqrt(((self.train_z - z) ** 2).mean(1)))[1] for z in self.train_z]
        self.threshold = float(np.quantile(nn, SUPPORT_QUANTILE))
        self.label_source = self.card["provenance"]["label_source"]
        self.simulated = any(s != "human_export" for s in self.label_source)

    def predict_features(self, feats: pd.DataFrame) -> pd.DataFrame:
        X = feats[FEATURE_NAMES].to_numpy(dtype=float)
        out = pd.DataFrame(index=feats.index)
        for t in TRAITS:
            raw = self.models[t].predict(X)
            out[f"{t}_raw"] = raw
            out[t] = np.clip(raw, 1, 7)
        z = (X - self.mu) / self.sd
        dist = np.empty(len(z))
        for i in range(0, len(z), 4096):
            block = z[i:i + 4096]
            dist[i:i + 4096] = np.sqrt(((block[:, None, :] - self.train_z[None]) ** 2).mean(2)).min(1)
        out["support_distance"] = dist
        out["weak_support"] = dist > self.threshold
        out["model_run"] = self.run_dir.name
        out["feature_version"] = FEATURE_VERSION
        out["label_source"] = ",".join(self.label_source)
        out["prediction_type"] = "model_prediction_not_human_label"
        return out


def audio_features(paths):
    rows, notes = {}, {}
    for p in paths:
        audio, sr = sf.read(p, dtype="float64", always_2d=True)
        warn = []
        if audio.shape[1] > 1:
            audio = audio.mean(1, keepdims=True)
            warn.append("stereo averaged to mono")
        audio = audio[:, 0]
        if sr != SR:
            raise ValueError(f"{p}: {sr} Hz; resample to {SR} Hz first")
        if len(audio) != RENDER_FRAMES:
            warn.append(f"length {len(audio) / SR:.2f} s differs from the 3 s study render")
        if np.max(np.abs(audio)) <= 0:
            raise ValueError(f"{p}: silent audio")
        rows[str(p)] = extract(audio, sr)
        notes[str(p)] = "; ".join(warn)
    return pd.DataFrame.from_dict(rows, orient="index"), notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--wav", nargs="+", type=Path)
    src.add_argument("--wav-dir", type=Path)
    src.add_argument("--corpus-ids", nargs="+")
    src.add_argument("--corpus", action="store_true")
    ap.add_argument("--model-run", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--output", type=Path, help="CSV or Parquet; printed to the console when omitted")
    args = ap.parse_args()

    pred = Predictor(args.model_run)
    notes = {}
    if args.wav or args.wav_dir:
        paths = args.wav or sorted(args.wav_dir.glob("*.wav"))
        feats, notes = audio_features(paths)
    else:
        corpus = pd.read_parquet(CORPUS_FEATURES).set_index("sample_id")
        feats = corpus if args.corpus else corpus.loc[args.corpus_ids]
        feats = feats[feats.feature_error == ""] if "feature_error" in feats else feats
    result = pred.predict_features(feats)
    if notes:
        result["domain_warning"] = pd.Series(notes)
    result.index.name = "input"

    if pred.simulated:
        print("NOTE: this model was trained on SIMULATED ratings; predictions follow an artificial rule.\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        (result.to_parquet if args.output.suffix == ".parquet" else result.to_csv)(args.output)
        print(f"Wrote {len(result)} predictions to {args.output}  (weak support: {int(result.weak_support.sum())})")
    else:
        show = result[list(TRAITS) + ["weak_support"] + (["domain_warning"] if notes else [])]
        with pd.option_context("display.width", 160, "display.max_colwidth", 60):
            print(show.round(2).to_string())


if __name__ == "__main__":
    main()
