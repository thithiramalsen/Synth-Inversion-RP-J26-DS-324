# c1_ridge_main_SIMULATED_v1

> **SIMULATED labels.** These numbers test the software against an artificial rule. They are not C1 results.

Ridge per descriptor on 19 `c1_features_v2` features. 102 training sounds, 26 held-out sounds. The penalty is chosen by 5-fold CV inside the training sounds.

| Descriptor | Test MAE [95% CI] | Baseline MAE | R² | Spearman | Outside 1–7 | Shuffled-target R² (p95) | Target SE |
|---|---|---|---|---|---|---|---|
| brightness | 0.42 [0.30, 0.56] | 1.03 | 0.81 | 0.83 | 0 | 0.13 | 0.49 |
| roughness | 0.57 [0.42, 0.74] | 1.16 | 0.77 | 0.92 | 2 | 0.09 | 0.56 |
| percussiveness | 0.47 [0.33, 0.63] | 1.11 | 0.77 | 0.88 | 0 | 0.08 | 0.45 |
| sustainedness | 0.56 [0.45, 0.67] | 1.10 | 0.76 | 0.85 | 0 | 0.09 | 0.42 |

Top weights (standardized features):

- **brightness**: log2_centroid +0.41, hf_energy_db +0.32, lf_energy_fraction -0.29, log2_rolloff85 +0.25
- **roughness**: log_am_rough_15_150 +0.88, log_am_fluct_4_15 +0.21, log_attack_s +0.20, log_peak_time_s -0.16
- **percussiveness**: log_peak_time_s -0.87, held_drop_db +0.74, tail_rel_db -0.32, centroid_sd_oct +0.22
- **sustainedness**: held_drop_db -0.67, tail_rel_db +0.42, log2_rolloff85 +0.36, temporal_centroid_s +0.34
