"""No synth rendering: check storage gate and portable reference integrity."""
import csv
import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from generation.preflight_dataset import GIB, check, storage_required
from generation import export_waveform_reference as exporter
from generation.verify_reproduction import verify


class ReadinessTests(unittest.TestCase):
    def test_storage_includes_both_masters_and_headroom(self):
        config = {"sample_rate": 44100, "render_duration_seconds": 3, "channels": 1}
        audio, total = storage_required(config, 131072, 1024)
        self.assertGreater(audio, 128 * GIB)
        self.assertEqual(total - audio, 10 * GIB)
        self.assertEqual(storage_required(config, 1024, 1024), (0, 0))

    def test_invalid_targets_rejected_before_importing_generator(self):
        for count in (0, -1, 1000):
            with self.assertRaises(ValueError):
                check(count)

    def test_reference_round_trip_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_dir = root / "data/manifests"
            manifest_dir.mkdir(parents=True)
            row = {"sample_id": "restricted_bend_sustain_v4_00000", "sample_index": 0}
            for column, name, checksum in (("audio_path", "processed.wav", "audio_sha256"),
                                           ("raw_audio_path", "raw.wav", "raw_audio_sha256")):
                path = root / name
                # Minimal byte fixture; no Vital engine or real dataset is used.
                with wave.open(str(path), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(44100)
                    handle.writeframes(b"\x00\x00\x01\x00")
                row[column] = name
                row[checksum] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = manifest_dir / "restricted_bend_sustain_v4.csv"
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            config = manifest_dir / "restricted_bend_sustain_v4_config.json"
            config.write_text(json.dumps({"sample_count": 1, "dataset_name": "restricted_bend_sustain_v4"}))
            output = root / "reference.json"
            with patch.object(exporter, "ROOT", root):
                exporter.export(output)
                self.assertEqual(verify(output, root, "candidates"), 0)
                with self.assertRaises(FileExistsError):
                    exporter.export(output)
                path = root / "processed.wav"
                payload = bytearray(path.read_bytes())
                payload[-1] ^= 1
                path.write_bytes(payload)
                self.assertEqual(verify(output, root, "candidates"), 1)
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    exporter.export(root / "must_not_exist.json")
                self.assertFalse((root / "must_not_exist.json").exists())


if __name__ == "__main__":
    unittest.main()
