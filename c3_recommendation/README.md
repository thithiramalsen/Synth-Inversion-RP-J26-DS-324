# C3 - Audio retrieval with parameter-diverse reranking

This directory contains the Thursday Component 3 prototype defined by the TAF scope. Its input is an isolated synthesizer audio clip. It first retrieves acoustically similar `pilot_v1` patches in MFCC space, then reranks the audio-retrieved pool with maximal marginal relevance (MMR) so the final recommendations cover more varied synthesizer parameter settings.

Audio-space retrieval remains the required baseline. C2 predictions are not used as a replacement for that baseline. The prototype also deliberately excludes timbre-description input, determinantal point processes (DPP), and user-preference evaluation; those belong to later work.

## Environment

From the repository root:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r c3_recommendation/requirements.txt
```

## Build and evaluate the Thursday prototype

```powershell
python c3_recommendation/pipeline.py
```

This canonical command:

- validates and builds the candidate patch database from all 1,024 `pilot_v1` rows;
- summarizes every waveform with the mean and standard deviation of 13 MFCC coefficients;
- standardizes candidate audio features and ranks candidates by cosine similarity;
- takes the top 50 audio candidates as the eligible reranking pool;
- returns five baseline recommendations and five MMR recommendations;
- uses fixed MMR `λ = 0.75`, where λ weights audio relevance and `1 - λ` weights the parameter-redundancy penalty;
- evaluates 32 fixed, seeded in-dataset query clips while excluding each exact query patch from its own candidate list; and
- saves a λ sweep from 0.50 to 1.00 to show the audio-similarity/parameter-diversity tradeoff.

Rebuild the candidate database explicitly with:

```powershell
python c3_recommendation/pipeline.py --force-rebuild
```

## Query an isolated audio clip

The clip may have a different sample rate or multiple channels; the pipeline downmixes it to mono and resamples it to 44.1 kHz before extracting MFCCs.

```powershell
python c3_recommendation/pipeline.py --query-audio path/to/isolated_synth.wav
```

The recommendations are written under `c3_recommendation/outputs/query_runs/<clip-name>/`. For an inspectable query drawn from the pilot database:

```powershell
python c3_recommendation/pipeline.py --query-id pilot_v1_00000
```

## Retrieval and reranking definition

The baseline is top-k retrieval by cosine similarity between standardized MFCC summary vectors. It does not use synthesizer parameters to decide which patches enter the retrieval pool.

MMR operates only on that audio-retrieved pool. The first item is the most audio-similar candidate. Each later item maximizes:

```text
λ × normalized audio relevance - (1 - λ) × maximum parameter similarity to an already selected item
```

Parameter distance is Euclidean distance after scaling each of the eight parameters to its configured `pilot_v1` range, divided by `sqrt(8)`. Parameter similarity is one minus this distance. This yields a transparent `[0, 1]` diversity scale without introducing C2 predictions.

## Outputs

The canonical evaluation writes:

- `candidate_patch_database.csv` and `candidate_patch_database_metadata.json` - all 1,024 candidate patches, normalized parameters, MFCC summaries, and a reproducibility signature.
- `evaluation_queries.csv` - the 32 fixed evaluation query clips.
- `baseline_recommendations.csv` - audio-space top-5 results.
- `mmr_recommendations.csv` - parameter-space MMR top-5 results from each top-50 audio pool.
- `query_comparison.csv` - per-query audio similarity and parameter diversity.
- `comparison_summary.json` - aggregate baseline/MMR comparison.
- `lambda_sweep.csv` and `audio_parameter_tradeoff.png` - the relevance/diversity tradeoff across λ values.
- `run_config.json` - manifest hash, candidate-database signature, settings, dependency versions, and explicit scope exclusions.

## Tests

```powershell
python -m unittest discover -s c3_recommendation/tests -v
```

The tests cover deterministic query selection, query exclusion, stable audio ranking, range-normalized parameter distance, the λ=1 equivalence to top-k audio retrieval, and MMR's ability to increase parameter diversity in a controlled example.

## Verified pilot result

The canonical 32-query evaluation produced this aggregate comparison:

| Method | Mean audio similarity | Mean pairwise parameter distance | Minimum pairwise parameter distance |
| --- | ---: | ---: | ---: |
| Audio top-5 baseline | 0.91831 | 0.31961 | 0.20411 |
| Parameter MMR, `λ = 0.75` | 0.90422 | 0.38014 | 0.29043 |
| Absolute change | -0.01409 | +0.06053 | +0.08632 |

At the prototype operating point, MMR increased mean parameter diversity by approximately 18.9% while reducing mean MFCC similarity by approximately 1.5%. The minimum pairwise parameter distance increased by approximately 42.3%, indicating fewer near-duplicate parameter recommendations. The `λ = 1.00` sweep result exactly matches the audio top-k aggregate, providing a direct implementation check that removing the diversity term recovers the baseline.

All 32 exact query patches were excluded from their own candidate lists, leaving zero self-matches across 320 saved baseline/MMR recommendation rows. An inspectable single-query example is saved under `outputs/query_runs/pilot_v1_00045/`.

This should be interpreted as an initial MFCC prototype, not evidence that `λ = 0.75` is optimal for users. Stronger audio embeddings and user-preference evaluation can replace or extend this baseline in the later full implementation; DPP remains intentionally unimplemented.
