# c1_ridge_main_SIMULATED_humanpilot_v1

> **SIMULATED labels.** These numbers test the software against an artificial rule. They are not C1 results.

Ridge per descriptor on 19 `c1_features_v2` features. 102 training sounds, 26 held-out sounds. The penalty is chosen by 5-fold CV inside the training sounds.

| Descriptor | Test MAE [95% CI] | Baseline MAE | R² | Spearman | Outside 1–7 | Shuffled-target R² (p95) | Target SE |
|---|---|---|---|---|---|---|---|
| brightness | 0.50 [0.36, 0.65] | 1.29 | 0.84 | 0.87 | 0 | 0.07 | 0.42 |
| roughness | 0.72 [0.54, 0.91] | 1.18 | 0.64 | 0.82 | 0 | 0.07 | 0.47 |
| percussiveness | 0.69 [0.52, 0.87] | 0.85 | 0.40 | 0.62 | 0 | 0.06 | 0.51 |
| sustainedness | 0.58 [0.44, 0.75] | 0.62 | 0.16 | 0.47 | 0 | 0.11 | 0.63 |

Top weights (standardized features):

- **brightness**: hf_energy_db +0.70, spectral_flatness_db +0.49, log2_rolloff85 +0.30, lf_energy_fraction -0.23
- **roughness**: hf_energy_db +0.77, decay_slope_db_s +0.34, spectral_flatness_db +0.27, log2_centroid +0.24
- **percussiveness**: held_drop_db +0.33, spectral_flux +0.29, decay_slope_db_s +0.25, centroid_sd_oct +0.23
- **sustainedness**: release_time_s +0.14, tail_rel_db +0.13, tail_energy_fraction +0.10, spectral_flatness_db +0.09
