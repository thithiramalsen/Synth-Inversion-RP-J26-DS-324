# C2 output organization

Open `D:/VSCode/GitHub/Synth-Inversion-RP/C2.code-workspace` using **File > Open
Workspace from File** in VS Code. It shows C2 and shared generation/corpus metadata,
with other components and legacy compatibility aliases hidden **only in this
workspace**. No global VS Code settings or other components are changed. Open the
repository normally to return to the unfiltered view. Shared corpus files remain
shared; a reference in this workspace is not permission to modify them.

Current artifacts keep their existing paths under `data/processed/c2_v4/`:

| Area | Locations |
|---|---|
| Protected assignments | `protocol_v1/` |
| Full features and trained models | `features_full_v1/`, `baseline_full_v1/`, `ensemble_full_v1/` |
| Diagnostics and reliability | `development_uncertainty_v1/`, `step_stability_v1/` |
| Results and EDA | `results_audit_v1/`, `evidence_baseline_full_v1/` |
| Demonstration applications | `live_app_v1/`, `viewer_v1/`, `worked_example_full_v1/` |
| Existing study bundles/runtimes | `human_study_bundle_v1/`, `human_study_rehearsal_v1/`, `researcher_self_review_v1/`, `participant_preview_v1/` |
| Recorded software checks | `checks/<original-name>/` |
| Earlier development runs | `archive/development/<original-name>/` |
| Leftover synthetic test fixtures | `archive/test_fixtures/<original-name>/` |
| Unused hosting draft | `archive/drafts/<original-name>/` |
| Organization audit | `organization_v1/` |

`checks/` contains verification evidence, not new research results. Archiving an
earlier experiment does not invalidate or replace it. No audio, labels, checkpoints,
calibrators, result files or response databases are rewritten by the organizer.
Actual study runtimes and their databases are not moved. Archived `responses.sqlite3`
files belong only to explicitly named synthetic test-fixture folders.

## Compatibility and safety

The exact moves are listed in `output_layout.json`. Each old path is retained as
a Windows directory junction to its new location. Existing commands, result URLs,
relative audio links and historical saved paths can therefore still work. Old
records retain their original path strings and hashes. New documentation uses the
organized locations. Do not edit frozen JSON/hashes to cosmetically rewrite paths.

Junctions are aliases to the same data, not duplicate copies or independent backups.
Do not delete files through an old alias to "remove duplicates". Do not recursively
delete the archive or a compatibility junction as part of casual cleanup. Keep the
alias and target together when moving/backing up the checkout, or consult the move
map to restore original paths. New machines need to materialize their own ignored
data and may rerun the organizer; junctions are not stored in Git.

The helper is C2-only, dry-run by default, refuses merges/overwrites and unresolved
ancestor links, and records file-size/SHA-256 inventories before and after each move:

```powershell
Set-Location D:\VSCode\GitHub\Synth-Inversion-RP
.\c2_estimation\tools\organize_outputs.ps1
# Apply only after inspecting the dry run, with C2 experiments/apps idle:
.\c2_estimation\tools\organize_outputs.ps1 -Apply
```

Completed moves are idempotent. Windows/sandbox permissions must allow directory
junction creation; if it fails, that move is restored to its original location.
No command deletes old experiment evidence. The organizer is not a training,
synthesis, test-evaluation, deployment or participant-export command.

New synthetic fixture tests use `data/processed/c2_v4/_scratch/tests/` rather
than leaving more folders in `data/processed/`. The shared helper avoids inherited
Windows TEMP permission problems and cleans each disposable directory normally.
Use `python -B -m c2_estimation.tests.run` from the pinned environment for core and
application checks together. It redirects only the app test modules' temporary
directory binding within the test process. Those original test files are part of
study fingerprints, so they remain byte-for-byte unchanged. Running their legacy
standalone commands bypasses this scoped wrapper. No environment package upgrades
or production path changes are needed for this layout.
