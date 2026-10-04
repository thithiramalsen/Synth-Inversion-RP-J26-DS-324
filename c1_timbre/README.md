# C1 - Timbre descriptors and parameter influence

The recommended research scope is **human-validated analysis of Vital parameter effects on perceived timbre**. The resolved question, component boundaries, literature corrections, staged experiment and provisional listening budget are in [C1_RESEARCH_DESIGN.md](C1_RESEARCH_DESIGN.md). This is a research design, not a claim that the perceptual study is implemented or completed.

The current implementation is an acoustic development baseline. It reads every row in the supplied manifest, extracts simple audio features, and measures the association between normalized filter cutoff and spectral centroid. It does not isolate a control intervention or measure human brightness ratings.

## Current evidence

As of 26 September 2026, the shared manifest contains 1,024 sounds with eight varied controls. The checked-in C1 feature table and summary still contain 128 sounds from an earlier checkpoint (`r = 0.5197`, `R² = 0.2701`). They are not results over the current full manifest. The discussed 16-control, approximately 135,000-sound study is not present in these C1 artifacts.

The survey currently implements a 20-clip, four-scale internal prototype. A formal descriptor instrument, balanced assignment, perceptual predictor validation and matched control-effect study remain to be implemented.

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

These are development-dataset measurements, not human-participant results. Running against a new manifest overwrites the selected output directory; use a separate versioned output directory to preserve the historical checkpoint. The descriptor listening screen is implemented separately in `survey/`.
