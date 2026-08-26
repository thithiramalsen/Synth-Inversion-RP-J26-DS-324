from __future__ import annotations

import unittest

import numpy as np

from c2_estimation.pipeline import calculate_metrics, deterministic_split


class DeterministicSplitTests(unittest.TestCase):
    def test_split_is_reproducible_complete_and_disjoint(self) -> None:
        first = deterministic_split(1024, 20260826)
        second = deterministic_split(1024, 20260826)
        for first_part, second_part in zip(first, second, strict=True):
            np.testing.assert_array_equal(first_part, second_part)
        self.assertEqual([len(part) for part in first], [819, 102, 103])
        combined = np.concatenate(first)
        self.assertEqual(len(np.unique(combined)), 1024)
        np.testing.assert_array_equal(np.sort(combined), np.arange(1024))

    def test_different_seed_changes_assignment(self) -> None:
        first = deterministic_split(1024, 20260826)
        second = deterministic_split(1024, 20260827)
        self.assertFalse(np.array_equal(first[0], second[0]))


class MetricTests(unittest.TestCase):
    def test_perfect_predictions(self) -> None:
        targets = np.asarray([[0.0, 0.25], [0.5, 0.5], [1.0, 0.75]], dtype=np.float32)
        rows = calculate_metrics(targets.copy(), targets, ["first", "second"])
        for row in rows:
            self.assertEqual(row["mae"], 0.0)
            self.assertEqual(row["rmse"], 0.0)
            self.assertEqual(row["r_squared"], 1.0)


if __name__ == "__main__":
    unittest.main()
