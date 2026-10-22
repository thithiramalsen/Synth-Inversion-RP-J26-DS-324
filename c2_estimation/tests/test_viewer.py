"""Saved-viewer selection and playback checks, without corpus/test reads."""
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
import soundfile as sf
from c2_estimation.v4.build_viewer import select_examples, save_playback
from c2_estimation.v4.data import ROOT
from c2_estimation.tests.scratch import temporary_directory


class ViewerTests(unittest.TestCase):
    def test_fixed_example_selection_rejects_test_and_other_validation_role(self):
        frame = pd.DataFrame({"sample_id": ["c", "a", "b"], "split": "validation",
                              "validation_role": "reliability", "diagnostic_rank": [2, 0, 1]})
        self.assertEqual(select_examples(frame, 2).sample_id.tolist(), ["a", "b"])
        for column, value in (("split", "test"), ("validation_role", "inverse")):
            wrong = frame.copy()
            wrong.loc[0, column] = value
            with self.assertRaises(ValueError):
                select_examples(wrong, 2)

    def test_playback_keeps_gain_and_rejects_clipping(self):
        with temporary_directory(prefix="c2-viewer-test-") as folder:
            path = Path(folder) / "audio.wav"
            audio = (.2*np.sin(np.arange(132300)*.01)).astype(np.float32)
            metadata = save_playback(path, audio)
            played, rate = sf.read(path, dtype="float32")
            self.assertEqual(rate, 44100)
            self.assertEqual(sf.info(path).subtype, "PCM_16")
            self.assertLess(np.max(np.abs(played-audio)), 1/32768 + 1e-7)
            self.assertAlmostEqual(metadata["peak"], .2, places=5)
            with self.assertRaises(ValueError):
                save_playback(path, np.ones(132300, dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
