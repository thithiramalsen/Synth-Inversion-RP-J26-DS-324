"""Checkpoint and recovery tests use synthetic arrays, never Vital rendering."""
import hashlib
import json
from pathlib import Path
import tempfile
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf
from generation import generate_corpus as runner
from generation.audio_processing import dc_filter, DC_POLICY_ID
from generation.corpus_audio import canonical_float32, load_audio, sample_digest
from generation.repair_corpus_float_policy import LEGACY_SOURCES, validate_transition
from generation.corpus_audio import PROCESSED_FLOAT_POLICY


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "corpus"
        synth = SimpleNamespace(load_preset=lambda path: True, get_controls=lambda: {})
        self.fake = SimpleNamespace(PARAMS={}, SAMPLING_SEED=1, BASE_PRESET=self.root / "unused",
            PILOT_AUDIO_DIR=self.root / "legacy", CONFIG_PATH=self.root / "legacy_config.json",
            PILOT_MANIFEST_CSV=self.root / "legacy.csv", create_synth=lambda: synth,
            create_sobol_samples=lambda count, dimensions, seed: np.empty((count, 0)),
            sha256_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
        self.patches = [patch.object(runner, "ROOT", self.root), patch.object(runner, "OUTPUT", self.output),
                        patch.object(runner, "generator", return_value=self.fake),
                        patch.object(runner, "recipe", return_value={"test": "fixture"}),
                        patch.object(runner, "render_one", side_effect=self.result)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    @staticmethod
    def result(task):
        index, _ = task
        audio = np.full(132300, (index + 1) / 100, dtype=np.float32)
        row = dict(sample_index=index, sample_id=f"{runner.PROFILE}_{index:05d}",
                   audio_policy_id=DC_POLICY_ID, raw_samples_sha256=sample_digest(audio),
                   processed_samples_sha256=sample_digest(canonical_float32(dc_filter(audio, 44100))),
                   is_silent=False, is_clipped=False, has_large_dc_offset=False)
        return row, audio

    def test_stop_resume_orphan_adoption_and_corruption_detection(self):
        def interrupted(task):
            if task[0] == 2:
                raise KeyboardInterrupt()
            return self.result(task)
        with patch.object(runner, "render_one", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                runner.generate(4, 1)
        _, _, rows, _ = runner.inspect(4)
        self.assertEqual(len(rows), 2)
        preserved = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in (self.output / "raw_float").glob("*.wav")}
        orphan, audio = self.result((2, None))
        runner.save_master(orphan, audio)
        orphan_path = self.output / "raw_float" / f"{orphan['sample_id']}.wav"
        orphan_time = orphan_path.stat().st_mtime_ns
        self.assertEqual(runner.inspect(4)[3], 1)
        runner.generate(4, 1)
        _, _, rows, count = runner.inspect(4)
        self.assertEqual((len(rows), count), (4, 0))
        self.assertEqual(orphan_path.stat().st_mtime_ns, orphan_time)
        for name, (content, modified) in preserved.items():
            path = self.output / "raw_float" / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (content, modified))
        self.assertTrue((self.output / "manifest.parquet").is_file())
        self.assertNotIn("audio_path", rows[-1])  # Never masquerade raw as conditioned audio.
        processed, sr = load_audio(rows[-1], self.root, verify=True)
        self.assertEqual((processed.dtype, sr), (np.dtype("float32"), 44100))
        row_path = self.output / "chunks/000002.json"
        payload = json.loads(row_path.read_text())
        payload[0]["processed_samples_sha256"] = "wrong"
        row_path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "waveform mismatch"):
            runner.inspect(4)

    def test_conflicting_orphan_is_never_overwritten(self):
        (self.output / "raw_float").mkdir(parents=True)
        row, audio = self.result((0, None))
        runner.save_master(row, audio)
        path = self.output / "raw_float" / f"{row['sample_id']}.wav"
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "not overwriting"):
            runner.save_master(row, audio * 2)
        self.assertEqual(path.read_bytes(), original)

    def test_float32_subnormals_zeroed_with_sign_and_normal_samples_preserved(self):
        bits = np.array([0, 0x80000000, 1, 0x80000001, 0x007fffff,
                         0x807fffff, 0x00800000, 0x80800000, 0x3f800000], dtype=np.uint32)
        original = bits.copy()
        result = canonical_float32(bits.view(np.float32)).view(np.uint32)
        np.testing.assert_array_equal(result, [0, 0x80000000, 0, 0x80000000,
                                               0, 0x80000000, 0x00800000, 0x80800000, 0x3f800000])
        np.testing.assert_array_equal(bits, original)
        self.assertEqual(sample_digest(canonical_float32(result.view(np.float32))),
                         sample_digest(result.view(np.float32)))

    def test_exclusive_writer_lock(self):
        with runner.exclusive_run():
            with self.assertRaises(OSError):
                with runner.exclusive_run():
                    self.fail("Second writer acquired lock")

    def test_import_prefix_recovers_after_recipe_only_interruption(self):
        legacy_dir = self.fake.PILOT_AUDIO_DIR / "raw_float"
        legacy_dir.mkdir(parents=True)
        old_rows = []
        for index in range(2):
            row, audio = self.result((index, None))
            path = legacy_dir / f"{row['sample_id']}.wav"
            sf.write(path, audio, 44100, subtype="FLOAT")
            row.update(raw_audio_path=path.relative_to(self.root).as_posix(), raw_audio_sha256=runner.sha(path))
            old_rows.append(row)
        self.fake.CONFIG_PATH.write_text("{}")
        self.output.mkdir()
        runner.atomic_json(self.output / "recipe.json", {"test": "fixture"})
        original = {p.name: p.read_bytes() for p in legacy_dir.glob("*.wav")}
        with patch.object(runner, "legacy_prefix", return_value=old_rows):
            runner.generate(4, 1)
        rows = runner.inspect(4)[2]
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(list((self.output / "raw_float").glob("*.wav"))), 2)
        self.assertEqual({p.name: p.read_bytes() for p in legacy_dir.glob("*.wav")}, original)

    def test_reject_shrink_and_missing_checkpoint(self):
        runner.generate(4, 1)
        with self.assertRaisesRegex(ValueError, "shrink"):
            runner.inspect(2)
        chunk = self.output / "chunks/000000.json"
        chunk.rename(self.output / "chunks/000001.json")
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            runner.inspect(4)


class FloatMigrationTests(unittest.TestCase):
    def test_only_the_known_float_policy_transition_is_accepted(self):
        before = {"synthesis": {"seed": 123}, "runner_sources": dict(LEGACY_SOURCES)}
        after = dict(before, runner_sources={"new": "code"}, processed_float32_policy=PROCESSED_FLOAT_POLICY)
        validate_transition(before, after)
        changed = copy.deepcopy(after)
        changed["synthesis"]["seed"] = 456
        with self.assertRaisesRegex(ValueError, "Unrelated"):
            validate_transition(before, changed)
        unknown = dict(before, runner_sources={"unknown": "version"})
        with self.assertRaisesRegex(ValueError, "exact original"):
            validate_transition(unknown, after)

    def test_reported_saved_sound_verifies_without_rendering(self):
        checkpoint = runner.ROOT / "data/raw/corpus_v4/chunks/001280.json"
        if not checkpoint.is_file():
            self.skipTest("Local generated regression sound is not distributed")
        row = next(r for r in json.loads(checkpoint.read_text()) if r["sample_index"] == 1287)
        audio, sr = load_audio(row, runner.ROOT, verify=True)
        self.assertEqual(sr, 44100)
        self.assertEqual(sample_digest(audio), row["processed_samples_sha256"])


if __name__ == "__main__":
    unittest.main()
