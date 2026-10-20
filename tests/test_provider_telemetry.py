from pathlib import Path
import tempfile
import unittest
from loop_work.providers import profile_observation


class ProviderTelemetryTests(unittest.TestCase):
    def test_requested_is_not_backend_attestation(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'stdout';p.write_text('not json\n{"type":"turn.completed","usage":{"input_tokens":12,"cached_input_tokens":7,"output_tokens":3}}\n')
            value=profile_observation('codex','requested','low',['/fixed/codex','--model','actual','-c','model_reasoning_effort="high"','-'],p)
            self.assertEqual(value['requested_profile']['model'],'requested')
            self.assertEqual(value['local_resolved_profile'],{'provider':'codex','model':'actual','effort':'high'})
            self.assertIsNone(value['backend_attested_profile']);self.assertEqual(value['support_status'],'unknown')
            self.assertIsNone(value['cost']);self.assertEqual(value['usage'][0]['cached_input_tokens'],7)

    def test_missing_usage_stays_unknown_and_future_effort_not_attested(self):
        with tempfile.TemporaryDirectory() as directory:
            value=profile_observation('claude','fixed','future',['/cli','--model','fixed','--effort','future'],Path(directory)/'absent')
            self.assertIsNone(value['usage']);self.assertIsNone(value['cli_version']);self.assertEqual(value['support_status'],'unknown')
