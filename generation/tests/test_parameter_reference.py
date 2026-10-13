"""Label comparison checks: never render or read real dataset audio."""
import unittest
import pandas as pd
from generation.verify_parameter_reference import compare


class ParameterReferenceTests(unittest.TestCase):
    def setUp(self):
        self.reference = pd.DataFrame({"sample_id": ["a", "b", "c"], "sample_index": [0, 1, 2],
                                       "cutoff_normalized": [.3, .5, .85]})

    def test_prefix_is_allowed_and_mismatch_is_rejected(self):
        compare(self.reference, self.reference.iloc[:2].copy())
        changed = self.reference.copy()
        changed.loc[1, "cutoff_normalized"] += 1e-10
        with self.assertRaisesRegex(ValueError, "differ"):
            compare(self.reference, changed)

    def test_reordered_or_empty_rows_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "ordered prefix"):
            compare(self.reference, self.reference.iloc[[1, 0]])
        with self.assertRaisesRegex(ValueError, "No completed"):
            compare(self.reference, self.reference.iloc[:0])


if __name__ == "__main__":
    unittest.main()
