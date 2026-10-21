# C2 live application verification

Record completed 21 October 2026. These are implementation and development checks,
not a human study or an independent test-set evaluation.

## Real inference and preset checks

The three predetermined reliability-validation examples completed fresh inference
on CUDA. Source: `data/processed/c2_v4/live_verification_v1/verification.json`.

| Sample suffix | Runtime (seconds) | Reconstruction distance R |
|---|---:|---:|
| 63764 | 7.586 | 0.098242 |
| 68474 | 6.709 | 0.719541 |
| 49083 | 6.612 | 0.174440 |

All three passed repeat-inference equality, canonical conditioning checks and
comparison with historical batch predictions (maximum z difference 2.285e-7,
below the predeclared absolute tolerance 1e-6). New R/S measurements matched the
unchanged research diagnostic implementation within 1e-10. All four calibrator
formulas matched independently calculated probabilities within 1e-12.

Known true-patch renders reproduced the canonical targets exactly. Repeated renders
were exact, and the inactive-control diagnostic returned zero distance. Each
exported `.vital` file reloaded through Vita with exact predicted-control readbacks
and exact conditioned reconstruction audio. Desktop Vital GUI compatibility has
not been manually checked.

A separate full CPU run on example 63764 completed in 7.592 seconds and passed
the preset export check. Its maximum prediction difference from the CUDA run was
1.788e-7. Source: `data/processed/c2_v4/live_cpu_check_v1/result.json`.
These timings describe these local runs, not a latency guarantee for other machines.

## HTTP and input checks

`python -B -m unittest c2_estimation.live.test_live -v`: five tests passed.
They cover WAV format/length/channel/rate/finite-sample/clipping/silence checks,
the upload-size limit, exact known test-waveform and double-conditioning guards,
source-content integrity, origin/host/header protection, busy submissions,
incomplete-result access, cancellation, completed-result recovery after restart,
interrupted-run reporting and changed-file rejection.

HTTP lifecycle tests use a synthetic worker and isolated temporary result folders.
They do not use a participant database. The sandboxed HTTP-test attempt stalled;
only its matching test processes were stopped, and the tests passed outside the
socket restriction. JavaScript syntax checking also passed.

## Browser checks

The in-app browser exercised fresh example inference and a real file-picker upload
of example 49083's original WAV. The upload completed as job
`c3ac229de41243e6bd70bb9a615196b1`. Both target and reconstructed audio played with
three-second durations and no media errors. Starting reconstruction paused target
playback. The generated spectrogram loaded at 1430 by 442 pixels.

Control selection and switching from U+S+R to U-only updated the inspector and
probabilities. The completed upload reopened after a page reload. The browser
downloaded `C:/Users/Thithira/Downloads/predicted.vital`; its SHA256 matched the
served job's exported preset:

`07302fc30ba3f0a610146dab4c9b651ec9ceb2a17c16b6c4660e34e9a13df521`

Browser console inspection found no errors or warnings after the fix to a helper
name that originally shadowed `window.history`. The page was inspected in the
available narrow browser panel. Native Vital GUI use and perceptual quality were
not assessed by this check.

## Scope and preserved work

Application code is in `c2_estimation/live/`. Outputs use separate ignored folders
under `data/processed/c2_v4/`. The missing ignored v4 base preset was restored from
an existing checksum-matching local copy. Frozen research code, models, data
assignments, calibrators, existing study source and participant databases were
not modified. Only the C2 viewer/runbook documentation was updated to link the app.

Final method locking, reserved-test evaluation and human validation remain pending.
Supported input is the existing restricted v4 domain and strict three-second,
mono, 44.1 kHz WAV contract. Arbitrary-recording calibration is not established.
