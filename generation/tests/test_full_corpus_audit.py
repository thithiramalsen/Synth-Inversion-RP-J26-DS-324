"""Use existing local regression records; mutate only dictionaries, never files."""
import copy
import json
import unittest
from generation import audit_full_corpus as auditor
from generation import generate_corpus as runner


class FullAuditRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = runner.OUTPUT / "chunks/000000.json"
        if not path.is_file():
            raise unittest.SkipTest("Local generated regression data is not distributed")
        cls.row = json.loads(path.read_text(encoding="utf-8"))[0]
        auditor.initialize(131072)

    def test_valid_record_and_raw_file_hash_corruption(self):
        self.assertEqual(auditor.verify_chunk([self.row]), 1)
        altered = dict(self.row, raw_audio_sha256="wrong")
        with self.assertRaisesRegex(ValueError, "Master file changed"):
            auditor.verify_chunk([altered])

    def test_parameter_and_qa_corruption_rejected(self):
        cases = [("wave_frame_sample_01", self.row["wave_frame_sample_01"] + .01, "Sobol"),
                 ("wave_frame_normalized", self.row["wave_frame_normalized"] + .01, "Parameter mismatch"),
                 ("wave_frame_display", "incorrect", "display mismatch"),
                 ("is_clipped", not self.row["is_clipped"], "QA flag mismatch")]
        for field, value, message in cases:
            altered = copy.deepcopy(self.row)
            altered[field] = value
            with self.assertRaisesRegex(ValueError, message):
                auditor.verify_chunk([altered])


if __name__ == "__main__":
    unittest.main()
