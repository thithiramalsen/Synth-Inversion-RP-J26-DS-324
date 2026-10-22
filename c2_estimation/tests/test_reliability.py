"""Synthetic tests only; no held-out corpus reads or fitting to test labels."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from c2_estimation.v4.calibration import (features,fit,predict,probability_metrics,
                                         ranking_metrics,risk_curve,paired_brier_bootstrap,load_diagnostics,run)
from c2_estimation.v4.data import NAMES,ROOT
from c2_estimation.v4.diagnostic_batch import measure
from c2_estimation.v4.evidence import read_predictions
from c2_estimation.v4.predict_subsets import select
from c2_estimation.tests.scratch import temporary_directory


class CalibrationTests(unittest.TestCase):
    def test_no_class_balancing_and_single_class_fallback(self):
        x = np.ones((100,2))
        y = np.r_[np.ones(20),np.zeros(80)]
        model = fit(x,y,1.)
        np.testing.assert_allclose(predict(model,x),.2,atol=1e-8)
        self.assertEqual(model["class_weight"],"none")
        for value in (0.,1.):
            constant = fit(x,np.full(100,value),.01)
            np.testing.assert_array_equal(predict(constant,x),value)
            self.assertEqual(constant["solver_status"],"single_class_constant")

    def test_scaler_is_fitted_only_to_supplied_calibration_data(self):
        x = np.array([[-2.,0.],[-1.,0.],[1.,0.],[2.,0.]])
        model = fit(x,np.array([0.,0.,1.,1.]),1.)
        snapshot = json.dumps(model,sort_keys=True)
        self.assertGreater(predict(model,np.array([[10.,0.]]))[0],.5)
        self.assertEqual(snapshot,json.dumps(model,sort_keys=True))
        np.testing.assert_allclose(model["mean"],[0.,0.])
        self.assertEqual(model["std"][1],1.)

    def test_brier_ece_aurc_and_matched_coverage(self):
        y,q,error = np.array([1.,0.]),np.array([.8,.2]),np.array([.01,.2])
        result,bins,_ = probability_metrics(y,q,error)
        self.assertAlmostEqual(result["brier"],.04)
        self.assertAlmostEqual(result["ece_10_equal_frequency"],.2)
        self.assertAlmostEqual(result["aurc_discrete"],.25)
        self.assertAlmostEqual(result["mae_z_at_coverage_0.5"],.01)
        self.assertEqual(sum(b["count"] for b in bins),2)

    def test_failure_ranking_ties_and_undefined_metrics(self):
        perfect = ranking_metrics(np.array([0,0,1,1]),np.array([0.,0.,1.,1.]))
        self.assertEqual(perfect["failure_auroc"],1.)
        self.assertEqual(perfect["failure_average_precision"],1.)
        constant = ranking_metrics(np.array([0,0,1,1]),np.ones(4))
        self.assertEqual(constant["failure_auroc"],.5)
        self.assertEqual(constant["failure_average_precision"],.5)
        self.assertIsNone(ranking_metrics(np.ones(4),np.arange(4))["failure_auroc"])

    def test_whole_audio_paired_bootstrap_and_reproducibility(self):
        y = np.tile(np.array([[1.],[0.],[1.],[0.]]),(1,13))
        probabilities = {"g(U)":np.full((4,13),.5),"g(U,S,R)":y.copy()}
        first = paired_brier_bootstrap(y,probabilities,replicates=100)
        self.assertEqual(first,paired_brier_bootstrap(y,probabilities,replicates=100))
        self.assertEqual(first[1]["point_difference"],-.25)
        self.assertEqual(first[1]["ci95_low"],-.25)
        self.assertEqual(first[1]["ci95_high"],-.25)

    def test_transforms_zero_sensitivity_and_reject_bad_variance(self):
        frame = pd.DataFrame({NAMES[0]+"_total_variance_z":[.01,.1],NAMES[0]+"_S":[0.,2.],"R":[0.,1.]})
        values = features(frame,NAMES[0],("U","S","R"))
        self.assertEqual(values[0,1],0.)
        self.assertEqual(values[0,2],0.)
        frame.loc[0,NAMES[0]+"_total_variance_z"] = 0.
        with self.assertRaises(ValueError):
            features(frame,NAMES[0],("U",))

    def test_no_test_diagnostics_or_prediction_selection(self):
        frame = pd.DataFrame({"split":["train","calibration","validation","test"],
                              "validation_role":["","","reliability",""],"diagnostic_rank":[0,0,0,0]})
        for partition in ("smoke","calibration","reliability-validation"):
            self.assertFalse((select(frame,partition).split == "test").any())
        with self.assertRaises(ValueError):
            select(frame,"test")
        with temporary_directory(prefix="c2-reliability-test-") as folder:
            root = Path(folder)
            (root/"summary.json").write_text(json.dumps({"status":"complete","partition":"test",
                                                       "test_evaluated":True,"predictions_unchanged":True}),encoding="utf-8")
            (root/"run_config.json").write_text("{}",encoding="utf-8")
            with self.assertRaises(ValueError):
                load_diagnostics(root,"calibration")

    def test_end_to_end_development_artifacts(self):
        from argparse import Namespace
        rng = np.random.default_rng(4)
        def fixture(count,split,prefix):
            frame = pd.DataFrame({"sample_id":[prefix+str(i) for i in range(count)],
                "split":split,"validation_role":"reliability" if split == "validation" else "",
                "diagnostic_rank":np.arange(count),"R":rng.uniform(0,1,count)})
            for name in NAMES:
                actual = rng.uniform(.2,.8,count)
                error = rng.uniform(-.1,.1,count)
                frame[name+"_actual_z"] = actual
                frame[name+"_predicted_z"] = actual+error
                frame[name+"_total_variance_z"] = np.square(error)+.001
                frame[name+"_S"] = rng.uniform(0,10,count)
            return frame
        cal,val = fixture(64,"calibration","c"),fixture(32,"validation","v")
        config = {"protocol_sha256":"p","ensemble_config_sha256":"e","member_checkpoints":["m"],
                  "delta_z":.02,"distance_config":{"name":"fake"}}
        with temporary_directory(prefix="c2-calibration-integration-") as folder:
            root = Path(folder)
            for name in ("calibration","validation"):
                (root/name).mkdir()
                (root/name/"summary.json").write_text("{}",encoding="utf-8")
            args = Namespace(calibration=root/"calibration",validation=root/"validation",output=root/"output",tau=.05,bootstrap=100)
            with patch("c2_estimation.v4.calibration.load_diagnostics",side_effect=[(config,{},cal),(config,{},val)]):
                result = run(args)
            self.assertFalse(result["test_evaluated"])
            self.assertEqual(len(result["macro_validation_brier"]),5)
            saved = json.loads((args.output/"calibrators.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["models"]),13)
            self.assertFalse(saved["test_method_locked"])
            self.assertTrue((args.output/"reliability_diagrams.png").exists())
            bins = pd.read_csv(args.output/"reliability_bins.csv")
            self.assertEqual(len(bins),13*5*10)
            probabilities = pd.read_parquet(args.output/"validation_probabilities.parquet")
            self.assertEqual(probabilities.sample_id.tolist(),val.sample_id.tolist())


class ForwardTests(unittest.TestCase):
    def test_frozen_prediction_boundaries_isolation_and_roundtrip(self):
        class FakeRenderer:
            def render(self,z):
                z = np.asarray(z,dtype=np.float64)
                amplitude = .1+.01*z[:9].sum()+.01*z[9]*z[10:].sum()
                return (amplitude*np.sin(np.arange(132300)*.01)).astype(np.float32),z.copy()
        renderer = FakeRenderer()
        z = np.full(13,.5)
        z[0],z[1] = .005,.995
        source = {"sample_id":"fake",**{n+"_z":float(z[j]) for j,n in enumerate(NAMES)}}
        prediction = {n+"_predicted_z":float(z[j]) for j,n in enumerate(NAMES)}
        snapshot = prediction.copy()
        audio,_ = renderer.render(z)
        with patch("c2_estimation.v4.diagnostic_batch.load_audio",return_value=(audio,44100)):
            result = measure(source,prediction,renderer,audit=True)
        self.assertEqual(snapshot,prediction)
        self.assertEqual(result["R"],0.)
        self.assertEqual(result["sensitivities"][0]["mode"],"forward")
        self.assertEqual(result["sensitivities"][1]["mode"],"backward")
        self.assertEqual(result["sensitivities"][2]["mode"],"central")
        self.assertAlmostEqual(result["sensitivities"][0]["actual_step_z"],.02)
        self.assertAlmostEqual(result["sensitivities"][2]["actual_step_z"],.04)
        self.assertTrue(result["prediction_unchanged"])
        self.assertTrue(result["audit"]["true_roundtrip_exact"])


if __name__ == "__main__":
    unittest.main()
