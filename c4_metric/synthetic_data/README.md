# C4 real CLAP triplet bank and synthetic answer fixtures

**The audio bank is real; the adjacent example answers are synthetic.** The
current C4 survey packages these 200 real triplets separately, with 20 unique
comparisons, two hidden repeats and two practices per listener. It saves new
answers entered by listeners and never imports the simulated response/session
CSVs. See the [current survey protocol](../../survey/C4_REVIEW_PROTOCOL.md).

`generate_dummy_c4.py` uses the actual `restricted_bend_sustain_v4` corpus. It
checks the 131,072-row manifest, samples a deterministic 1,024-sound subset, and
uses LAION CLAP audio embeddings to select a bank of 200 distinct reference/A/B
triplets. Each simulated listener receives 20 different questions selected from
that bank. Assignments are spread so each bank triplet gets roughly the same
number of simulated responses; participants do not all get the same 20.
For each reference, one candidate comes from a near-similarity band and the other
from a moderately-near band. Candidate A/B placement is randomized. The resulting
triplet CSV records actual sample IDs, CLAP scores, parameter distances, and raw
audio paths. It also exports 600 level-matched PCM playback clips to `stimuli/`.

The script then creates 50-100 **simulated** listeners × 20 triplets. Simulated
preferences are random latent labels independent of CLAP scores, with listener
consistency/noise and occasional `cannot_decide` answers. The responses use the
C4 survey rating-export fields, and a second CSV uses the C4 session-export shape
for entry, headphone-screen and closing-feedback answers. Consent and experience
fields are fictional placeholders for software rehearsal only.

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
- `dummy_c4_sessions.csv`: one simulated session row per listener, including C4
  entry, headphone-screen and closing-feedback fields.
- `clap_triplets.csv`: 200 bank comparisons and their actual corpus IDs.
- `stimuli/`: the 600 actual audio clips used in the comparison bank.
- `clap_embedding_cache.npz` and `.json`: embeddings plus sampling/model metadata;
  regenerated only when the manifest, sample pool, seed or model ID changes.
- `generation_metadata.json`: run configuration and synthetic-data warning.

Use `--triplet-bank-size` to change the bank and `--pool-size` to change the
embedded subset from the 131,072 sounds. The bank size must be a multiple of the
20 questions per participant, and the pool must contain at least three times as
many sounds as bank triplets. It does not need to embed the complete corpus.
Leave `--expected-corpus-size 131072` in place so a missing or partial corpus
fails clearly.

## Do not treat this as participant evidence

- Every response and session row says `SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE`
  and has `analysis_include=false`. The simulated consent field is not consent
  from a person. Do not upload
  these rows as survey submissions, combine them with real participant exports,
  or report their statistics as results.
- The real corpus sounds and CLAP-based triplet selection are actual; the choices,
  confidence, and listener behavior are simulated. This output cannot validate
  CLAP or the adapted metric against human listeners.
- CLAP itself selects the stimulus difficulty bands, so agreement with CLAP on
  this set would be selection-conditioned. The proposal also calls for metric
  disagreement and near-tie cases plus held-out anchors; those require a frozen
  multi-metric selection plan and should be separate from a CLAP-only rehearsal.
- The historical hosted review used two practice comparisons and 12 review
  presentations (10 unique plus two repeats). The new `c4_clap_review_v1`
  preparation has its own frozen bank, 100 balanced assignments, 20 unique plus
  two repeats and two practices per person. These simulated CSVs are exports
  from neither hosted version. The prepared app continues to identify review
  responses separately from formal research collection.
- The proposal PDF says the planned target dataset is 65,536 sounds; the current
  repository has a 131,072-render corpus. Align the report, dataset identifier,
  split and ethics materials with your supervisor before describing the final
  research data.
