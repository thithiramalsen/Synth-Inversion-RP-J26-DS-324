"""The rehearsal Blueprint must create a distinct, persistent hosted service."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'PyYAML is not installed in this test environment')
class RehearsalBlueprintTests(unittest.TestCase):
    def test_both_researcher_studies_use_the_existing_service_and_packaged_bundles(self):
        import yaml
        shared = yaml.safe_load((ROOT/'survey/deploy/render.researcher-rehearsal.yaml').read_text())
        self.assertEqual(len(shared['services']), 1)
        service = shared['services'][0]
        self.assertEqual(service['name'], 'synth-c1-researcher-rehearsal')
        self.assertEqual(service['dockerCommand'], 'python survey/backend/c1_researcher_rehearsal.py --postgres --host 0.0.0.0')
        self.assertFalse((ROOT/'survey/deploy/render.c4-researcher-rehearsal.yaml').exists())
        ignore = (ROOT/'.dockerignore').read_text()
        for bundle in ('c1_researcher_rehearsal_v1.json', 'c1_researcher_rehearsal_v2.json', 'c4_researcher_rehearsal_v1.json'):
            self.assertIn('!survey/deploy/study/'+bundle, ignore)

    def test_service_and_secrets_do_not_target_participant_deployment(self):
        import yaml
        source = ROOT/'survey/deploy/render.researcher-rehearsal.yaml'
        rehearsal = yaml.safe_load(source.read_text())
        participant = yaml.safe_load((ROOT/'render.yaml').read_text())
        self.assertEqual(len(rehearsal['services']), 1)
        service = rehearsal['services'][0]
        self.assertNotIn(service['name'], {row['name'] for row in participant['services']})
        self.assertEqual(service['runtime'], 'docker')
        self.assertEqual(service['plan'], 'free')
        self.assertEqual(service['healthCheckPath'], '/api/health')
        self.assertIn('c1_researcher_rehearsal.py --postgres --host 0.0.0.0', service['dockerCommand'])
        env = {row['key']:row for row in service['envVars']}
        self.assertFalse(env['SURVEY_REHEARSAL_DATABASE_URL']['sync'])
        self.assertTrue(env['SURVEY_REHEARSAL_ADMIN_TOKEN']['generateValue'])
        self.assertEqual(env['SURVEY_DATABASE_URL']['value'], '')
        self.assertFalse(env['SURVEY_RESEARCHER_PASSWORD_HASH']['sync'])
        self.assertNotIn('databases', rehearsal)
        self.assertNotIn('disks', service)
        dockerfile = ROOT/service['dockerfilePath']
        self.assertTrue(dockerfile.is_file())
        self.assertIn('COPY survey/backend/*.py', dockerfile.read_text())
        self.assertIn('!survey/deploy/study/c1_researcher_rehearsal_v1.json', (ROOT/'.dockerignore').read_text())


if __name__ == '__main__':
    unittest.main()
