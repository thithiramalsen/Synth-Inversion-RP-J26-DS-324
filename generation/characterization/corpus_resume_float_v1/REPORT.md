# Resume failure: processed FLOAT underflow

On 13 October 2026, resuming the single-master v4 corpus failed at sample 01287.
The raw WAV file hash and raw sample hash both matched. Independent in-memory
rerendering also reproduced the saved raw and processed hashes.

The renderer leaves float32 flush-to-zero enabled in its worker, while a fresh
resume reader can preserve subnormal float32 values. One subnormal processed
sample in 01287 therefore caused a hash mismatch despite an intact raw master.
Explicit conversion of subnormals to signed zero matched the saved hash.

The adapter and worker now share `canonical_float32`, with policy
`float32_subnormal_signed_zero_v1`. It preserves all normal float32 values and
zero signs. Only processed values below the float32 normal range are zeroed.
Raw master samples, synth recipe, parameters, DC filter and checkpoint rows are
unchanged. Hash validation remains strict.

The guarded repair accepts only the exact original runner fingerprints and
rejects unrelated synthesis/runtime/storage changes. Before updating recipe.json,
it verifies every saved raw file, both waveform hashes and all parameter rows,
then saves the original recipe and a verification report.

Verification results:

- Saved rows verified: 15744.
- Original-reader hash discrepancies resolved: 2.
- Maximum observed affected subnormal magnitude: 1.0877163143677488e-38.
- All checkpoint JSON hashes remained unchanged.
- First uncheckpointed master (15744) independently reproduced exactly in memory.
- Eleven focused tests passed, including the actual 01287 regression, signed-zero
  handling, corruption rejection, guarded migration and stop/resume preservation.
- Full generation was not restarted by the repair.

The original recipe and detailed per-checkpoint hashes are retained at
`data/processed/corpus_float_repair_20261013T085620956455Z/`.
The updated teammate archive is
`data/processed/candidate_reproduction_v4/candidate_recipe_v4_parallel_single_master_ftz_v2.zip`.
