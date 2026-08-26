# C1 - Timbre descriptors and parameter influence

This folder contains the first reproducible C1 analysis required for the development checkpoint. It reads every row in the shared manifest, extracts simple audio features, and measures the relationship between normalized filter cutoff and spectral centroid.

## Run

From the repository root:

```powershell
python c1_timbre/feature_extraction.py
```

If the analysis dependencies are missing:

```powershell
python -m pip install -r c1_timbre/requirements.txt
```

The script does not hard-code the number of samples. To use another manifest or output directory:

```powershell
python c1_timbre/feature_extraction.py --manifest data/manifests/pilot_v1.csv --output-dir c1_timbre/outputs
```

## Outputs

- `outputs/c1_audio_features.csv` - sample ID, cutoff value, spectral centroid, 85% rolloff, RMS, zero-crossing rate, and 13 mean MFCC coefficients.
- `outputs/cutoff_vs_centroid.png` - checkpoint-ready scatter plot with a fitted trend line.
- `outputs/cutoff_vs_centroid_summary.csv` - sample count, Pearson correlation, R-squared, slope, intercept, and relationship direction.

These are development-dataset measurements, not human-participant results. The descriptor listening screen is implemented separately in `survey/`.
