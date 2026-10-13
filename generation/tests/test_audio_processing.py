import unittest

import numpy as np

from generation.audio_processing import DC_POLICY_ID, apply_level, audio_metrics, dc_filter, level_plan
from generation.check_dc_mitigation import condition


class ProcessingTests(unittest.TestCase):
    def test_matches_auditioned_filter_and_rejects_second_pass(self):
        t=np.arange(132300)/44100
        raw=.1*np.sin(2*np.pi*261.6*t)+.04*(t<1.5)
        np.testing.assert_allclose(dc_filter(raw,44100),condition(raw,44100,'highpass_10hz'),rtol=0,atol=0)
        with self.assertRaisesRegex(ValueError,'repeat'):
            dc_filter(raw,44100,input_policy_id=DC_POLICY_ID)
        with self.assertRaises(ValueError):
            dc_filter(raw,48000)

    def test_shared_target_preserves_envelope_and_peak_headroom(self):
        t=np.arange(132300)/44100
        clips=[dc_filter(.3*np.sin(2*np.pi*440*t)*np.exp(-t/tau),44100) for tau in (.04,.6)]
        metrics=[audio_metrics(a) for a in clips]
        plan=level_plan(metrics)
        for clip,gain in zip(clips,plan['gains']):
            matched=apply_level(clip,gain,input_policy_id=DC_POLICY_ID)
            self.assertAlmostEqual(audio_metrics(matched)['held_rms'],plan['target_rms'])
            self.assertLessEqual(np.max(np.abs(matched)),.89+1e-8)
            np.testing.assert_allclose(matched,clip*gain)
        with self.assertRaises(ValueError):
            apply_level(clips[0],1,input_policy_id='held_rms_gain_v1')
        with self.assertRaises(ValueError):
            level_plan([audio_metrics(np.zeros(132300))])
