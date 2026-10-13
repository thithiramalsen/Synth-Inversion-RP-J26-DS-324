"""Targeted checks for experiment isolation and interpretation of its metrics."""
import unittest

import numpy as np

from generation import restricted_config as profile
from generation.characterize import render
from generation.compare_architectures import parameters, render_synth, setup, shape_distance, signature


class ShapeMetricTests(unittest.TestCase):
    def test_gain_change_is_not_counted_as_spectral_novelty(self):
        t = np.arange(3 * profile.SAMPLE_RATE) / profile.SAMPLE_RATE
        signal = np.sin(2 * np.pi * 261.63 * t) + .3 * np.sin(2 * np.pi * 523.26 * t)
        a, _ = signature(signal)
        b, _ = signature(signal * .025)
        self.assertLess(shape_distance(a, b), 1e-10)
        c, _ = signature(np.sin(2 * np.pi * 1300 * t))
        self.assertGreater(shape_distance(a, c), .5)


@unittest.skipUnless(profile.BASE_PRESET.exists(), "Local factory-derived preset required")
class ComparisonSetupTests(unittest.TestCase):
    def test_A_preserves_current_architecture_audio(self):
        values = parameters("clean_held", .5, .575, .4)
        expected = render(values)
        actual = render_synth(setup("A", values, .5))
        np.testing.assert_array_equal(expected, actual)

    def test_B_requires_zero_filter_envelope_sustain(self):
        with self.assertRaisesRegex(ValueError, "sustain at zero"):
            setup("B", dict(profile.BASE_VALUES), .5)

    def test_neutral_B_matches_A_without_sustained_cutoff_offset(self):
        values = parameters("clean_held", .5, .575, 0.)
        a = render_synth(setup("A", values, .5))
        b = render_synth(setup("B", values, .5))
        self.assertLess(float(np.max(np.abs(a - b))), 2e-6)


if __name__ == "__main__":
    unittest.main()
