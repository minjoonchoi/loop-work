from pathlib import Path
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from loop_work import providers, bench_transport, benchmark
from loop_work.storage import LoopError, write_json


class ManagedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_resolver_ignores_reconstructed_path_and_has_no_fallback(self):
        write_json(self.root / 'profile.json', {'models': {'codex': 'fixed'}})
        wrapper = self.root / 'bin' / 'codex'
        wrapper.parent.mkdir()
        wrapper.write_text('#!/bin/sh\nexit 0\n')
        wrapper.chmod(0o700)
        with patch.dict(os.environ, {'LOOP_BENCH_PROFILE': str(self.root / 'profile.json'), 'PATH': '/unavailable'}):
            self.assertEqual(providers.executable_for('codex'), str(wrapper))
            with self.assertRaises(LoopError):
                providers.executable_for('claude')
            wrapper.unlink()
            with self.assertRaisesRegex(LoopError, 'no direct CLI fallback'):
                providers.executable_for('codex')

    def test_reconciliation_detects_missing_duplicate_and_unfinished_calls(self):
        directory = self.root / 'workspace/app/.loop/state/task/delegations/unit'
        directory.mkdir(parents=True)
        (directory / 'prompt.txt').write_text('assignment')
        write_json(directory / 'process.json', {'argv': ['/real/codex', 'exec', '-']})
        row = {'provider': 'codex', 'prompt_hash': hashlib.sha256(b'assignment').hexdigest(),
               'status': 'completed', 'exit_code': 0, 'response_valid': True,
               'runtime_receipt': str(directory / 'process.json')}
        self.assertFalse(bench_transport.reconcile_calls(self.root, [])['complete'])
        self.assertTrue(bench_transport.reconcile_calls(self.root, [row])['complete'])
        self.assertFalse(bench_transport.reconcile_calls(self.root, [row, row])['complete'])
        write_json(self.root / 'calls/one.json', {**row, 'status': 'running'})
        self.assertFalse(bench_transport.usage(self.root)['calls_complete'])
        write_json(self.root / 'calls/one.json', row)
        self.assertTrue(bench_transport.usage(self.root)['calls_complete'])

    def test_direct_same_prompt_cannot_mask_missing_managed_call(self):
        directory = self.root / 'knowledge/runs/work/unit'
        directory.mkdir(parents=True)
        (directory / 'prompt.txt').write_text('same prompt')
        write_json(directory / 'process.json', {'argv': ['/real/codex', 'exec', '-']})
        direct = {'provider': 'codex', 'prompt_hash': hashlib.sha256(b'same prompt').hexdigest(),
                  'context': {'role': 'nested'}}
        value = bench_transport.reconcile_calls(self.root, [direct])
        self.assertFalse(value['complete'])
        self.assertEqual(value['ledger_only_untyped_calls'], 1)
        self.assertTrue(any('exactly one linked call' in error for error in value['errors']))

    def test_fingerprint_detects_linked_content_and_restored_bytes(self):
        target = self.root / 'actual-config'
        target.write_text('A')
        link = self.root / 'config-link'
        link.symlink_to(target)
        before = benchmark.configuration_identity(link)
        target.write_text('B')
        changed = benchmark.configuration_identity(link)
        self.assertNotEqual(before['content_sha256'], changed['content_sha256'])
        target.write_text('A')
        restored = benchmark.configuration_identity(link)
        self.assertEqual(before['content_sha256'], restored['content_sha256'])
        self.assertNotEqual(before, restored)
        self.assertEqual(before['link_metadata'], restored['link_metadata'])
        self.assertNotEqual(before['target_metadata'], restored['target_metadata'])
        # A read alone changes no fingerprint: access time is excluded.
        self.assertEqual(restored, benchmark.configuration_identity(link))

    def test_ledger_only_direct_nested_is_counted_without_runtime_receipt(self):
        for role in ('nested', 'structured'):
            row = {'provider': 'codex', 'prompt_hash': 'direct-' + role,
                   'context': {'role': role}}
            value = bench_transport.reconcile_calls(self.root, [row])
            self.assertTrue(value['complete'])
            self.assertEqual(value['ledger_only_untyped_calls'], 1)
        row['context']['role'] = 'worker'
        self.assertFalse(bench_transport.reconcile_calls(self.root, [row])['complete'])

    def test_common_work_structured_call_uses_wrapper_and_reconciles(self):
        binary = self.root / 'real-codex'
        binary.write_text("""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
payload = sys.stdin.read()
pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps({'answer': 'checked'}))
print(json.dumps({'type':'thread.started','thread_id':'fake-session'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
""")
        binary.chmod(0o700)
        env = bench_transport.prepare_transport(self.root, {'codex': 'fixed'}, 5,
                    {'codex': str(binary)}, efforts={'codex': 'low'})
        # Mimic the common-work directory used by knowledge/runs delegates.
        directory = self.root / 'knowledge/runs/work-id/assignment-id'
        with patch.dict(os.environ, {**env, 'PATH': os.environ.get('PATH', '')}):
            result = providers.structured_call('codex', self.root, directory, 'bounded writing', 5,
                    {'type':'object','properties':{'answer':{'type':'string'}}},
                    model='fixed', effort='low')
        self.assertEqual(result, {'answer': 'checked'})
        value = bench_transport.usage(self.root)
        self.assertTrue(value['calls_complete'], value['accounting'])
        self.assertEqual(value['accounting']['managed_receipts'], 1)
        self.assertEqual(value['accounting']['ledger_only_untyped_calls'], 0)
        # Duplicating a managed structured ledger row cannot masquerade as
        # another legitimate direct structured call.
        ledger = next((self.root / 'calls').glob('*.json'))
        duplicate = ledger.parent / 'duplicate.json'
        duplicate.write_bytes(ledger.read_bytes())
        self.assertFalse(bench_transport.usage(self.root)['calls_complete'])
        duplicate.unlink()
        # A lost ledger entry must invalidate the same real runtime receipt.
        ledger.unlink()
        self.assertFalse(bench_transport.usage(self.root)['calls_complete'])

    def test_absent_config_tracks_nearest_ancestor_and_symlink_identity(self):
        target = self.root / 'parent'
        target.mkdir()
        link = self.root / 'parent-link'
        link.symlink_to(target, target_is_directory=True)
        config = link / 'missing/deeper/config'
        before = benchmark.configuration_identity(config)
        self.assertEqual(before['ancestor_path'], str(link))
        self.assertEqual(before['resolved_ancestor'], str(target))
        self.assertIn(str(link), before['ancestor_links'])
        self.assertEqual(before, benchmark.configuration_identity(config))
        config.parent.mkdir(parents=True)
        config.write_text('temporary')
        self.assertEqual(config.read_text(), 'temporary')
        config.unlink()
        config.parent.rmdir()
        config.parent.parent.rmdir()
        restored = benchmark.configuration_identity(config)
        self.assertEqual(before['status'], restored['status'])
        self.assertNotEqual(before, restored)
        self.assertEqual(before['ancestor_links'], restored['ancestor_links'])
        link.unlink()
        link.symlink_to(target, target_is_directory=True)
        self.assertNotEqual(restored, benchmark.configuration_identity(config))

    def test_absent_config_observation_race_fails_closed(self):
        config = self.root / 'missing-config'
        original = Path.lstat
        calls = 0

        def racing_lstat(path):
            nonlocal calls
            if path == config:
                calls += 1
                if calls == 2:
                    config.write_text('appeared')
            return original(path)

        with patch.object(Path, 'lstat', racing_lstat):
            with self.assertRaisesRegex(LoopError, 'appeared while fingerprinting'):
                benchmark.configuration_identity(config)

    def test_global_profile_observation_keeps_strict_whole_file_hash(self):
        with patch('loop_work.benchmark.profile_fingerprint', return_value={'config': 'new', 'instructions': 'same'}):
            observation = benchmark.profile_observation({'config': 'old', 'instructions': 'same'}, 'turn-after')
        self.assertEqual(observation['changed_paths'], ['config'])
        self.assertEqual(observation['fingerprint']['config'], 'new')
