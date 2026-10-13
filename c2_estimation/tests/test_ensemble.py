"""Synthetic checks for uncertainty moments, bounded heads and checkpoint resume."""
import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch

from c2_estimation.v4.data import NAMES, ROOT
from c2_estimation.v4.ensemble import GaussianCNN, combine, gaussian_nll, train


class EnsembleTests(unittest.TestCase):
    @unittest.skipUnless(torch.cuda.is_available(), "CUDA training overlay required")
    def test_cuda_gaussian_step_reproduces_exactly(self):
        from c2_estimation.pipeline import set_deterministic_execution
        states = []
        for _ in range(2):
            set_deterministic_execution(29,2)
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
            model = GaussianCNN(torch.device("cuda")).cuda()
            optimizer = torch.optim.Adam(model.parameters(),lr=.001)
            mu,var = model(torch.ones(2,1,64,259,device="cuda"))
            gaussian_nll(mu,var,torch.ones_like(mu)*.4).backward()
            optimizer.step()
            states.append({k:v.detach().cpu().clone() for k,v in model.state_dict().items()})
        for key in states[0]:
            torch.testing.assert_close(states[0][key],states[1][key],rtol=0,atol=0)

    def test_mixture_moments_population_variance(self):
        means = np.stack([np.full((2,13), .2), np.full((2,13), .6)])
        variances = np.stack([np.full((2,13), .01), np.full((2,13), .03)])
        mu, within, between, total = combine(means, variances)
        np.testing.assert_allclose(mu, .4)
        np.testing.assert_allclose(within, .02)
        np.testing.assert_allclose(between, .04)
        np.testing.assert_allclose(total, .06)
        self.assertTrue((combine(means[:1], variances[:1])[2] == 0).all())
        with self.assertRaises(ValueError):
            combine(means, -variances)

    def test_heads_loss_and_gradients(self):
        torch.set_num_threads(2)
        model = GaussianCNN(torch.device("cpu"))
        mu, var = model(torch.zeros(3,1,64,259))
        self.assertEqual(mu.shape, (3,13))
        self.assertTrue(((mu >= 0) & (mu <= 1)).all())
        self.assertTrue((var >= 1e-4).all())
        loss = gaussian_nll(mu, var, torch.ones_like(mu)*.4)
        expected = torch.nn.GaussianNLLLoss()(mu, torch.ones_like(mu)*.4, var)
        torch.testing.assert_close(loss, expected)
        loss.backward()
        self.assertTrue(torch.isfinite(model.mean_head.weight.grad).all())
        self.assertTrue(torch.isfinite(model.variance_head.weight.grad).all())

    def test_epoch_resume_reproduces_ensemble(self):
        with tempfile.TemporaryDirectory(prefix="c2-ensemble-test-", dir=ROOT/"data/processed") as folder:
            root = Path(folder)
            prepared = root/"prepared"
            prepared.mkdir()
            (prepared/"protocol.json").write_text("synthetic", encoding="utf-8")
            from c2_estimation.v4.data import sha
            meta = {"lower": [0.]*13, "upper": [1.]*13}
            frame = pd.DataFrame({"sample_id": [f"s{i}" for i in range(8)],
                "sample_index": range(8), "split": ["train"]*6+["validation"]*2,
                "validation_role": [""]*6+["inverse"]*2, "diagnostic_rank": [-1]*8,
                **{n+"_z": np.linspace(.1,.9,8) for n in NAMES}})
            arrays = [np.random.default_rng(3).normal(size=(8,64,259)).astype(np.float32)]
            cache = {"scope": "synthetic", "signature": "cache", "protocol_sha256": sha(prepared/"protocol.json")}
            args = argparse.Namespace(prepared=prepared, cache=root/"cache", output=root/"one",
                members=2, epochs=2, patience=3, batch_size=3, threads=2, seed=11,
                learning_rate=.001, weight_decay=.0001, variance_floor=1e-4, device="cpu", resume=False)
            with patch("c2_estimation.v4.ensemble.load_prepared", return_value=(meta, frame)), \
                 patch("c2_estimation.v4.ensemble.load_cache", return_value=(cache, frame, arrays)):
                train(args)
                args.output = root/"resumed"
                from c2_estimation.v4.ensemble import atomic_checkpoint
                def interrupted(path, state):
                    atomic_checkpoint(path, state)
                    if path.name == "last_model.pt":
                        raise RuntimeError("simulated loss of connection")
                with patch("c2_estimation.v4.ensemble.atomic_checkpoint", side_effect=interrupted):
                    with self.assertRaises(RuntimeError):
                        train(args)
                args.resume = True
                train(args)
            self.assertEqual((root/"one/validation_predictions.csv").read_bytes(),
                             (root/"resumed/validation_predictions.csv").read_bytes())
            for member in range(2):
                one = torch.load(root/f"one/member_{member:02d}/best_model.pt", weights_only=True)
                resumed = torch.load(root/f"resumed/member_{member:02d}/best_model.pt", weights_only=True)
                for key in one["model"]:
                    torch.testing.assert_close(one["model"][key], resumed["model"][key], rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
