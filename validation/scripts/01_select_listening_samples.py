from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MANIFEST_PATH = (
    PROJECT_ROOT
    / "data"
    / "manifests"
    / "pilot_v1.csv"
)

REVIEW_AUDIO_DIR = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "audio"
    / "pilot_v1_review"
)

OUTPUT_SHEET = (
    PROJECT_ROOT
    / "validation"
    / "listening"
    / "pilot_v1_listening_sheet.csv"
)

RANDOM_SEED = 20260803

PARAMETER_COLUMNS = {
    "wave_frame": "wave_frame_normalized",
    "filter_cutoff": "filter_cutoff_normalized",
    "filter_resonance": "filter_resonance_normalized",
    "filter_drive": "filter_drive_normalized",
    "amp_attack": "amp_attack_normalized",
    "amp_decay": "amp_decay_normalized",
    "amp_sustain": "amp_sustain_normalized",
    "amp_release": "amp_release_normalized",
}


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found:\n{MANIFEST_PATH}"
        )

    dataframe = pd.read_csv(MANIFEST_PATH)

    required_columns = {
        "sample_id",
        "audio_path",
        "rms_dbfs",
        "dc_to_rms_ratio",
        "has_large_dc_offset",
        *PARAMETER_COLUMNS.values(),
    }

    missing_columns = required_columns - set(dataframe.columns)

    if missing_columns:
        raise KeyError(
            "Missing manifest columns:\n"
            + "\n".join(sorted(missing_columns))
        )

    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()

    def add_first_available(
        candidates: pd.DataFrame,
        reason: str,
    ) -> bool:
        for _, row in candidates.iterrows():
            sample_id = str(row["sample_id"])

            if sample_id in selected_ids:
                continue

            selected_ids.add(sample_id)

            selected.append(
                {
                    "sample_id": sample_id,
                    "selection_reason": reason,
                    "source_audio_path": str(
                        row["audio_path"]
                    ),
                }
            )

            return True

        return False

    def add_group(
        candidates: pd.DataFrame,
        count: int,
        reason: str,
    ) -> None:
        added = 0

        for _, row in candidates.iterrows():
            if added >= count:
                break

            sample_id = str(row["sample_id"])

            if sample_id in selected_ids:
                continue

            selected_ids.add(sample_id)

            selected.append(
                {
                    "sample_id": sample_id,
                    "selection_reason": reason,
                    "source_audio_path": str(
                        row["audio_path"]
                    ),
                }
            )

            added += 1

    # 16 parameter-boundary sounds:
    # one low and one high example for each parameter.
    for parameter_name, column_name in PARAMETER_COLUMNS.items():
        add_first_available(
            dataframe.sort_values(
                column_name,
                ascending=True,
            ),
            reason=f"{parameter_name}_low",
        )

        add_first_available(
            dataframe.sort_values(
                column_name,
                ascending=False,
            ),
            reason=f"{parameter_name}_high",
        )

    # Eight quietest unique sounds.
    add_group(
        dataframe.sort_values(
            "rms_dbfs",
            ascending=True,
        ),
        count=8,
        reason="quietest",
    )

    # Eight loudest unique sounds.
    add_group(
        dataframe.sort_values(
            "rms_dbfs",
            ascending=False,
        ),
        count=8,
        reason="loudest",
    )

    # Eight strongest DC-offset cases.
    add_group(
        dataframe.sort_values(
            "dc_to_rms_ratio",
            ascending=False,
        ),
        count=8,
        reason="high_dc_to_rms",
    )

    # Eight random normal controls.
    normal_controls = dataframe[
        dataframe["has_large_dc_offset"] == False  # noqa: E712
    ].sample(
        frac=1.0,
        random_state=RANDOM_SEED,
    )

    add_group(
        normal_controls,
        count=8,
        reason="random_normal_control",
    )

    # Safety fallback in case category overlap prevented 48 samples.
    if len(selected) < 48:
        remaining = dataframe[
            ~dataframe["sample_id"].astype(str).isin(
                selected_ids
            )
        ].sample(
            frac=1.0,
            random_state=RANDOM_SEED + 1,
        )

        add_group(
            remaining,
            count=48 - len(selected),
            reason="random_fill",
        )

    if len(selected) != 48:
        raise RuntimeError(
            f"Expected 48 samples, selected {len(selected)}."
        )

    REVIEW_AUDIO_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_SHEET.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Clear any previous review-set WAVs.
    for old_wav in REVIEW_AUDIO_DIR.glob("*.wav"):
        old_wav.unlink()

    output_rows: list[dict[str, object]] = []

    for item in selected:
        source_path = Path(
            str(item["source_audio_path"])
        )

        if not source_path.is_absolute():
            source_path = PROJECT_ROOT / source_path

        if not source_path.exists():
            raise FileNotFoundError(
                f"Selected audio not found:\n{source_path}"
            )

        destination_path = (
            REVIEW_AUDIO_DIR
            / source_path.name
        )

        shutil.copy2(
            source_path,
            destination_path,
        )

        output_rows.append(
            {
                "sample_id": item["sample_id"],
                "selection_reason": item[
                    "selection_reason"
                ],
                "review_audio_path": str(
                    destination_path.relative_to(
                        PROJECT_ROOT
                    )
                ),
                "reviewer": "",
                "audible": "",
                "click_or_pop": "",
                "abrupt_cutoff": "",
                "unexpected_noise": "",
                "extremely_quiet": "",
                "valid_synth_sound": "",
                "comments": "",
            }
        )

    output_dataframe = pd.DataFrame(output_rows)

    output_dataframe.to_csv(
        OUTPUT_SHEET,
        index=False,
    )

    print("=" * 70)
    print("LISTENING REVIEW SET CREATED")
    print("=" * 70)
    print(f"Selected samples: {len(output_dataframe)}")
    print(f"Audio folder: {REVIEW_AUDIO_DIR}")
    print(f"Review sheet: {OUTPUT_SHEET}")
    print()
    print(
        output_dataframe[
            "selection_reason"
        ].value_counts()
    )


if __name__ == "__main__":
    main()