# SIMULATED C1 pilot responses (`c1_pilot_sim_v1`)

**No human produced any rating here.** These files are engineering fixtures made
by [`simulate_pilot_ratings.py`](../../simulate_pilot_ratings.py) while human data
collection awaits approval. They are not perceptual evidence. Do not merge them
with approved responses, count them as participants or report a model trained on
them as a validated C1 result.

Design follows the frozen pilot (`c1_pilot_2026-10-09_20unique_v1`): blocks 01–16
of the deployed bundle complete (3 practice + 20 study sounds each), giving
320 included evaluations and 5 listeners for each of the 64 study sounds. Two extra
sessions on blocks 17/18 are excluded examples: one abandoned and one withdrawn.

| File | Contents |
|---|---|
| `c1_pilot_responses_SIMULATED.csv` | Real C1 export columns, plus `source_sample_id`, `label_source`, `generator_version`, `seed` |
| `c1_sessions_SIMULATED.csv` | One row per session, including excluded ones |
| `c1_sound_targets_SIMULATED.csv` | Per-sound mean/median/SD/valid/unclear counts per descriptor (unclear = missing) |
| `simulation_ground_truth.csv` | The hidden rule: proxy audio features, proxy-only and "true" means, and the 13 parameters |
| `simulation_listeners.csv` | Hidden listener settings (bias, scale use, noise, confusions) |
| `simulation_summary.json` | Seed, hashes, rule description and headline counts |

The ground-truth and listener files exist so pipeline tests can check recovery.
A real study has no such files; keep them out of any model's inputs.

Regenerate (deterministic for a given seed):

```powershell
.\venv\Scripts\python.exe -B c1_timbre/simulate_pilot_ratings.py --seed 20261014 --overwrite
```
