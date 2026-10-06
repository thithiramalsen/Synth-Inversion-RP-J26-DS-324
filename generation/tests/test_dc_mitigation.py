"""Synthetic checks of DC rejection and preservation of a steady pitched signal."""

import unittest

import numpy as np

from generation.check_dc_mitigation import condition


class DcMitigationTests(unittest.TestCase):
    def test_constant_bias_is_rejected_without_attenuating_midi60_body(self):
        rate = 44100
        t = np.arange(rate * 3) / rate
        frequency = 440 * 2 ** ((60 - 69) / 12)
        signal = .2 * np.sin(2 * np.pi * frequency * t)
        for method in ("highpass_10hz", "highpass_20hz"):
            filtered_bias = condition(np.full(t.shape, .1), rate, method)
            self.assertLess(float(np.max(np.abs(filtered_bias[rate:]))), 1e-10)
            corrected = condition(signal + .1, rate, method)
            np.testing.assert_array_equal(corrected, condition(signal + .1, rate, method))
            # Fit DC/sine/cosine after settling to avoid finite-window mean bias.
            basis = np.column_stack((np.ones(rate), np.sin(2 * np.pi * frequency * t[-rate:]),
                                      np.cos(2 * np.pi * frequency * t[-rate:])))
            dc, sine, cosine = np.linalg.lstsq(basis, corrected[-rate:], rcond=None)[0]
            self.assertLess(abs(dc), 1e-10)
            self.assertLess(abs(np.hypot(sine, cosine) - .2), 1e-5)

    def test_mean_subtraction_can_bias_an_originally_silent_tail(self):
        rate = 44100
        audio = np.concatenate((np.full(rate, .1), np.zeros(rate)))
        subtracted = condition(audio, rate, "subtract_clip_mean")
        self.assertAlmostEqual(float(subtracted.mean()), 0.)
        self.assertAlmostEqual(float(subtracted[-1]), -.05)
        for method in ("highpass_10hz", "highpass_20hz"):
            filtered = condition(audio, rate, method)
            self.assertLess(float(np.max(np.abs(filtered[-rate // 2:]))), 1e-9)


if __name__ == "__main__":
    unittest.main()
