# C4 synthetic rehearsal data from the real corpus

`generate_dummy_c4.py` uses the actual `restricted_bend_sustain_v4` corpus. It
checks the 131,072-row manifest, samples a deterministic 1,024-sound subset, and
uses LAION CLAP audio embeddings to select 20 distinct reference/A/B triplets.
For each reference, one candidate comes from a near-similarity band and the other
from a moderately-near band. Candidate A/B placement is randomized. The resulting
triplet CSV records actual sample IDs, CLAP scores, parameter distances, and raw
audio paths. It also exports 60 level-matched PCM playback clips to `stimuli/`.

The script then creates 50-100 **simulated** listeners × 20 triplets. Simulated
preferences are random latent labels independent of CLAP scores, with listener
consistency/noise and occasional `cannot_decide` answers. This lets you exercise
response-import and analysis code without building in the answer CLAP predicts.

## Run

Install PyTorch, Transformers 4.50+, and librosa in the project environment. The
generator loads the public `laion/clap-htsat-unfused` checkpoint through the
Hugging Face Transformers CLAP API, pinned by default to commit
`8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`. It applies the repository DC filter
and uses one shared loudness
target and 16-bit PCM encoding before embedding, matching the files it exports for
listening. Pin a local checkpoint directory with `--model-path` when reproducibility across
future package/model changes is required.

```powershell
.\venv\Scripts\python.exe -m pip install torch transformers==4.50.0 librosa
.\venv\Scripts\python.exe c4_metric\synthetic_data\generate_dummy_c4.py --participants 100
.\venv\Scripts\python.exe c4_metric\synthetic_data\generate_dummy_c4.py --participants 50 --seed 17
```

For another frozen checkpoint, pass a local Hugging Face model directory with
`--model-path`, or select its hub commit using `--model-revision <commit-sha>`.

Outputs:

- `dummy_c4_responses.csv`: long-form simulated response table, one row per
  listener × comparison.
- `clap_triplets.csv`: 20 selected comparisons and their actual corpus IDs.
- `stimuli/`: the 60 actual audio clips used in the comparisons.
- `clap_embedding_cache.npz` and `.json`: embeddings plus sampling/model metadata;
  regenerated only when the manifest, sample pool, seed or model ID changes.
- `generation_metadata.json`: run configuration and synthetic-data warning.

Use `--pool-size` to choose a different subset from the 131,072 sounds. It does
not need to embed the complete corpus. Leave `--expected-corpus-size 131072` in
place so a missing or partial corpus fails clearly.

## Do not treat this as participant evidence

- Every response row says `SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE`. Do not upload
  these rows as survey submissions, combine them with real participant exports,
  or report their statistics as results.
- The real corpus sounds and CLAP-based triplet selection are actual; the choices,
  confidence, and listener behavior are simulated. This output cannot validate
  CLAP or the adapted metric against human listeners.
- CLAP itself selects the stimulus difficulty bands, so agreement with CLAP on
  this set would be selection-conditioned. The proposal also calls for metric
  disagreement and near-tie cases plus held-out anchors; those require a frozen
  multi-metric selection plan and should be separate from a CLAP-only rehearsal.
- This does not update the hosted C4 review flow. That flow remains ten unique
  comparisons plus two repeats with 16 review assignment slots. A formal 20-item
  study needs its own versioned protocol, assignments, consent flow, and export.
- The proposal PDF says the planned target dataset is 65,536 sounds; the current
  repository has a 131,072-render corpus. Align the report, dataset identifier,
  split and ethics materials with your supervisor before describing the final
  research data.
