"""Synthetic paired-audit arithmetic; never evaluates dataset test rows."""
import unittest
import numpy as np
from c2_estimation.v4.audit_results import comparisons, paired_interval


class AuditTests(unittest.TestCase):
    def test_identical_methods_have_zero_paired_difference(self):
        y = np.tile([[0.], [1.]], (8, 13))
        q = np.full_like(y, .5)
        macro, controls = comparisons(y, {v: q for v in ("g(U)", "g(U,R)", "g(U,S,R)")}, 50)
        self.assertEqual(len(macro), 4)
        self.assertEqual(len(controls), 26)
        np.testing.assert_array_equal(macro[["point_difference", "ci95_low", "ci95_high"]], 0.)

    def test_wave_frame_ablation_preserves_primary_and_secondary_comparison(self):
        y = np.zeros((12, 13))
        reference = np.full_like(y, .5)
        full = reference.copy()
        full[:, 0] = 0.
        values = {"g(U)": reference, "g(U,R)": full.copy(), "g(U,S,R)": full}
        macro, _ = comparisons(y, values, 50)
        self.assertAlmostEqual(macro.iloc[0].point_difference, -.25/13)
        self.assertEqual(macro.iloc[1].point_difference, 0.)
        self.assertEqual(macro.iloc[2].point_difference, 0.)
        self.assertEqual(macro.to_dict("records"), comparisons(y, values, 50)[0].to_dict("records"))

    def test_paired_interval_resamples_audio_rows(self):
        result = paired_interval(np.array([-.1, .2]), np.array([[0, 0], [1, 1]]))
        self.assertAlmostEqual(result["point_difference"], .05)
        self.assertAlmostEqual(result["ci95_low"], -.0925)
        self.assertAlmostEqual(result["ci95_high"], .1925)


if __name__ == "__main__":
    unittest.main()
