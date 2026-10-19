# C4 - Human-aligned perceptual similarity prototype

The current C4 survey is prepared with a **200-triplet real-audio CLAP bank**,
20 unique comparisons plus two hidden repeats and two practices per listener,
and 100 balanced assignments for a target of 50–100 completed listeners. See
the [current protocol](../survey/C4_REVIEW_PROTOCOL.md). The bank lives in
`synthetic_data/clap_triplets.csv`; the adjacent synthetic response/session CSVs
are separate software fixtures and are never imported as participant answers.

The MFCC instructions below describe the historical local development prototype.

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

## CLAP rehearsal data from the current full corpus

The separate [synthetic data guide](synthetic_data/README.md) documents a seeded
sample from the 131,072-render corpus, CLAP-selected real sound triplets, and
simulated responses for software rehearsal. Those response rows are synthetic;
they are not survey submissions or research results. The hosted survey now uses
a separately frozen copy of the real sound bank. The ten-triplet internal
instrument above remains historical.
