"""Offline integration test for audio -> frozen CLAP vectors -> C4 triplet loss."""
from __future__ import annotations

import csv
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
import torch

from c4_metric.cache_embeddings import extract
from c4_metric.c3_adapter import AdaptedScorer
from c4_metric.train import smoke_test, train


class FakeClapProcessor:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return cls()

    def __call__(self, *, audios, sampling_rate, return_tensors, padding):
        if sampling_rate != 48_000 or return_tensors != "pt" or not padding:
            raise AssertionError("Unexpected CLAP processor configuration")
        features = []
        for audio in audios:
            audio = np.asarray(audio, dtype=np.float32)
            spectrum = np.abs(np.fft.rfft(audio))
            features.append([audio.mean(), audio.std(), spectrum.mean(), spectrum.max()])
        return {"input_features": torch.tensor(features, dtype=torch.float32)}


class FakeClapModel:
    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        return cls()

    def to(self, device):
        generator = torch.Generator().manual_seed(731)
        self.projection = torch.randn((4, 512), generator=generator, dtype=torch.float32).to(device)
        return self

    def eval(self):
        return self

    def requires_grad_(self, value):
        if value:
            raise AssertionError("Frozen CLAP must not require gradients")
        return self

    def __call__(self, *, input_features):
        return types.SimpleNamespace(audio_embeds=input_features @ self.projection)


class ClapTrainingFlowTests(unittest.TestCase):
    def test_audio_cache_flows_through_triplet_training(self):
        fake_transformers = types.ModuleType("transformers")
        fake_transformers.ClapAudioModelWithProjection = FakeClapModel
        fake_transformers.ClapProcessor = FakeClapProcessor

        with tempfile.TemporaryDirectory(prefix=".tmp-c4-clap-flow-", dir=Path(__file__).resolve().parents[2]) as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.csv"
            triplet_path = root / "triplets.csv"
            cache_path = root / "clap_embeddings.npz"
            audio_rows = []
            # Three disjoint triplets make explicit train/validation/test partitions.
            triplets = []
            for group, split in enumerate(("train", "validation", "test")):
                ids = [f"g{group}_audio_{slot}" for slot in range(3)]
                for slot, sample_id in enumerate(ids):
                    rate = 44_100
                    time = np.arange(rate // 4, dtype=np.float32) / rate
                    waveform = (0.2 * np.sin(2 * np.pi * (180 + 90 * (group * 3 + slot)) * time)).astype(np.float32)
                    audio_path = root / f"{sample_id}.wav"
                    sf.write(audio_path, waveform, rate)
                    audio_rows.append({"sample_id": sample_id,
                                       "audio_path": f"{root.name}/{audio_path.name}"})
                triplets.append({"anchor_id": ids[0], "positive_id": ids[1],
                                 "negative_id": ids[2], "split": split,
                                 "data_status": "human_response", "vote_status": "preference"})

            for path, rows in ((manifest_path, audio_rows), (triplet_path, triplets)):
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            with patch.dict(sys.modules, {"transformers": fake_transformers}):
                metadata = extract(triplet_path, manifest_path, cache_path,
                                   model_id="laion/clap-htsat-unfused",
                                   revision="8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
                                   batch_size=4, local_files_only=True)
                with np.load(cache_path, allow_pickle=False) as cache:
                    matrix = cache["embeddings"]
                self.assertEqual(matrix.shape, (9, 512))
                self.assertEqual(matrix.dtype, np.float32)
                np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)
                self.assertEqual(metadata["data_status"], "human_response")
                self.assertEqual(metadata["embedding_dimension"], 512)

                smoke = smoke_test(triplet_path, cache_path, margin=0.2)
                self.assertEqual(smoke["status"], "passed")
                self.assertTrue(smoke["gradients_finite"])
                self.assertTrue(smoke["optimizer_updated_parameters"])
                result = train(triplet_path, cache_path, root / "training",
                               output_dim=8, batch_size=1, epochs=2, patience=2, seed=41)

            self.assertEqual(result["encoder_model"], "laion/clap-htsat-unfused")
            self.assertEqual(result["embedding_dimension"], 512)
            self.assertEqual(result["train_triplets"], 1)
            self.assertEqual(result["validation_triplets"], 1)
            checkpoint = torch.load(root / "training" / "best_model.pt", map_location="cpu",
                                    weights_only=False)
            self.assertEqual(checkpoint["input_dim"], 512)
            self.assertEqual(checkpoint["encoder_model"], "laion/clap-htsat-unfused")
            with patch("c4_metric.c3_adapter._clap_embeddings",
                       return_value=matrix[:2].astype(np.float64)) as encoder:
                scorer = AdaptedScorer(root / "training" / "best_model.pt", device="cpu")
                score = scorer.score(root / "g0_audio_0.wav", root / "g0_audio_1.wav")
                encoder.assert_called_once()
                self.assertTrue(np.isfinite(score.similarity))
                self.assertEqual(score.method, "c4")


if __name__ == "__main__":
    unittest.main()
