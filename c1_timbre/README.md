# C1 - Timbre descriptors and parameter influence

For transfer to the C1 component owner, use the
[teammate handoff](C1_TEAMMATE_HANDOFF.md): prepared stimuli/survey, data locations,
the known feature-precision issue, ownership and post-collection analysis steps.
The [current pilot checklist](../survey/C1_PILOT_NEXT_STEPS.md) separates those
modelling tasks from what remains before participant recruitment.

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
and no human pilot data have yet been collected here. A separate versioned
instrument is now implemented at `/pilot`; see the
[rehearsal and launch runbook](../survey/C1_PILOT_RUNBOOK.md). Its production
stimulus pool and 64+3 selection are now prepared; see the
[generation report](../survey/C1_CANDIDATE_GENERATION_REPORT.md). Human audition and
recruitment preparation remain. The old four-bipolar-scale prototype is preserved.

`extract_pilot_features.py` verifies bundle/audio hashes and extracts features
from the exact level-controlled FLOAT pilot signal. It does not filter or
normalize again and does not overwrite the historical feature table. Example:

```powershell
.\venv\Scripts\python.exe -B -m c1_timbre.extract_pilot_features --bundle data/processed/c1_pilot_v1/bundle.json --output data/processed/c1-features.csv
```

This folder contains the first reproducible C1 analysis required for the development checkpoint. It reads every row in the shared manifest, extracts simple audio features, and measures the relationship between normalized filter cutoff and spectral centroid.

**Feature stability finding (8 October 2026):** the
[paired precision audit](../generation/characterization/pcm_precision_v1/REPORT.md)
found that the current unweighted frame summaries and very low spectral floor
can substantially change centroid/MFCC values between FLOAT and PCM playback,
including the prepared 67 study clips. This extractor remains a historical
baseline, not a frozen perceptual feature definition. Energy handling and floors
need an explicit, versioned revision and validation before fitting the descriptor
model. The study sounds and this extractor were not modified by the audit.

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
