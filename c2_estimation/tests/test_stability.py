"""Synthetic step-size checks; no held-out audio access."""
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from c2_estimation.v4.data import NAMES, ROOT, digest_json, write_json
from c2_estimation.v4.stability import agreement, checked_case, check_measurement, select_pilot
from c2_estimation.tests.scratch import temporary_directory


class StabilityTests(unittest.TestCase):
    def test_selection_uses_ranks_and_rejects_test_or_misalignment(self):
        frame = pd.DataFrame({"sample_id": ["b", "c", "a"], "split": "calibration",
                              "diagnostic_rank": [1, 2, 0], "error": [0, 1, 2]})
        source, prediction = select_pilot(frame, frame.copy(), count=2)
        self.assertEqual(source.sample_id.tolist(), ["a", "b"])
        self.assertEqual(prediction.sample_id.tolist(), ["a", "b"])
        bad = frame.copy()
        bad.loc[0, "split"] = "test"
        with self.assertRaises(ValueError):
            select_pilot(bad, bad, 2)
        with self.assertRaises(ValueError):
            select_pilot(frame, frame.iloc[::-1], 2)

    def test_agreement_handles_scale_change_zero_and_empty(self):
        result = agreement(np.array([0., 1., 2.]), np.array([0., 2., 4.]))
        self.assertAlmostEqual(result["spearman"], 1.)
        self.assertGreater(result["median_abs_log1p_difference"], 0.)
        self.assertEqual(result["exact_zero_first"], 1)
        self.assertIsNone(agreement(np.zeros(3), np.zeros(3))["spearman"])
        self.assertIsNone(agreement(np.array([]), np.array([]))["p95_abs_log1p_difference"])
        with self.assertRaises(ValueError):
            agreement(np.array([-1.]), np.array([0.]))

    def test_case_digest_resume_and_tamper_rejection(self):
        with temporary_directory(prefix="c2-step-test-") as folder:
            path = Path(folder) / "case.json"
            record = {"sample_id": "a", "signature": "s", "S": 3.}
            record["content_sha256"] = digest_json(record)
            write_json(path, record)
            self.assertEqual(checked_case(path, "s", "a"), record)
            record["S"] = 4.
            write_json(path, record)
            with self.assertRaises(ValueError):
                checked_case(path, "s", "a")

    def test_measurement_rejects_changed_base_audio_or_step(self):
        record = {"prediction_unchanged": True, "sample_id": "a", "target_sha256": "t",
                  "rendered_sha256": "p", "R": .3,
                  "sensitivities": [{"parameter": n, "S": 0., "actual_step_z": .04} for n in NAMES]}
        check_measurement(record, record)
        with self.assertRaises(ValueError):
            check_measurement({**record, "rendered_sha256": "different"}, record)
        changed = json.loads(json.dumps(record))
        changed["sensitivities"][0]["actual_step_z"] = 0.
        with self.assertRaises(ValueError):
            check_measurement(changed, record)


if __name__ == "__main__":
    unittest.main()
