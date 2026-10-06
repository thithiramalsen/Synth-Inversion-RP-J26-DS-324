# C1 - Timbre descriptors and parameter influence

## Current research configuration

The selected research architecture now contains **13 controls with Oscillator 2 off**:
the existing eight plus Bend amount and filter-envelope amount, attack, decay and
sustain (`restricted_bend_sustain_v4`); see the
[selection record](../generation/decisions/2026-10-07_bend_and_sustain.md).
The versioned configuration, provisional bounds and technical evidence are in
[generation/README.md](../generation/README.md). The existing 1024-render
`pilot_v1` remains the eight-control rendering/pipeline test. The saved C1 feature
table below contains only the earlier 128 sounds; it is not thirteen-control or
human-participant evidence.

The selected combined profile and preserved A/B comparison profiles are separate from
the descriptor survey. Technical activity does not establish perceptual coverage,
and the current survey prototype has not been converted into the formal pilot.

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
