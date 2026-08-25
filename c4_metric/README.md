# C4 - Human-aligned perceptual similarity prototype

This folder contains the reproducible triplet selection and MFCC baseline used by the local C4 listening survey.

## 1. Generate the development triplets

Run C1 feature extraction first so the shared development MFCC vectors exist, then select ten triplets:

```powershell
python c1_timbre/feature_extraction.py
python c4_metric/select_triplets.py
```

`select_triplets.py` reads the full feature CSV, chooses ten seeded anchors, ranks every other sound by cosine similarity, selects one candidate from approximately the 6th-25th rank percentile and another from approximately the 26th-60th percentile, and randomizes which is displayed as Candidate A or B.

The generated `development_triplets.csv` also freezes the selection seed, MFCC similarities/distances, and the MFCC baseline choice. Regenerating with the same feature file and seed produces the same result.

## 2. Run the local survey

Follow `survey/README.md`, select **C4 perceptual triplets**, and complete the ten internal development trials. Each trial requires playback of the reference and both candidates, an A/B choice, and confidence from 1-5.

Export the results from the local researcher page or:

```text
http://localhost:8000/api/admin/export/c4_triplets
```

These responses must be described as internal/development testing data, not research-participant data.

## 3. Check the MFCC baseline

```powershell
python c4_metric/mfcc_baseline.py path/to/c4_triplets_responses.csv
```

This reports how often the simple MFCC-distance baseline agrees with the internal human choices. Later work can compare MFCC against stronger metrics such as CLAP, CDPAM, STFT-based distances, and the learned triplet metric.
