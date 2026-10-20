"""Reviewer availability uses the same managed transport as invocation."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from loop_work import providers, bench_transport
from loop_work.storage import LoopError


class ProviderSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / 'real'
        self.bin.mkdir()
        for provider in ('codex', 'claude'):
            executable = self.bin / provider
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o700)

    def managed(self, models):
        return bench_transport.prepare_transport(
            self.root / 'transport', models, 4,
            {p: str(self.bin / p) for p in models},
            efforts={p: 'low' for p in models})

    def test_both_managed_wrappers_select_opposite_without_path(self):
        env = self.managed({'codex': 'fixed-codex', 'claude': 'fixed-claude'})
        with patch.dict(os.environ, {**env, 'PATH': '/unavailable'}):
            with patch.object(providers.shutil, 'which', side_effect=AssertionError('PATH used')):
                selection = providers.review_selection('codex')
                self.assertEqual(selection['provider'], 'claude')
                self.assertEqual(selection['mode'], 'cross_provider')
                self.assertEqual(selection['available'], {'claude': True, 'codex': True})
                self.assertTrue(Path(providers.command('claude', self.root, self.root)[0]).is_absolute())

    def test_single_provider_catalog_ignores_extra_wrapper(self):
        env = self.managed({'codex': 'fixed'})
        profile = Path(env['LOOP_BENCH_PROFILE'])
        # prepare_transport creates both wrappers; only catalog entries count.
        self.assertTrue((profile.parent / 'bin/claude').is_file())
        with patch.dict(os.environ, {**env, 'PATH': str(self.bin)}):
            selection = providers.review_selection('codex')
            self.assertEqual(selection['mode'], 'same_provider_fresh')
            self.assertFalse(selection['available']['claude'])

    def test_configured_missing_or_nonexecutable_wrapper_blocks(self):
        env = self.managed({'codex': 'fixed', 'claude': 'fixed'})
        wrapper = Path(env['LOOP_BENCH_PROFILE']).parent / 'bin/claude'
        with patch.dict(os.environ, {**env, 'PATH': str(self.bin)}):
            wrapper.chmod(0o600)
            with self.assertRaisesRegex(LoopError, 'no direct CLI fallback'):
                providers.review_selection('codex')
            wrapper.unlink()
            with self.assertRaisesRegex(LoopError, 'no direct CLI fallback'):
                providers.review_selection('codex')

    def test_normal_mode_follows_installed_cli_availability(self):
        with patch.dict(os.environ, {'LOOP_BENCH_PROFILE': '', 'PATH': str(self.bin)}):
            self.assertEqual(providers.review_selection('codex')['provider'], 'claude')
            (self.bin / 'claude').unlink()
            selection = providers.review_selection('codex')
            self.assertEqual(selection['mode'], 'same_provider_fresh')
            self.assertEqual(selection['available'], {'claude': False, 'codex': True})
            with self.assertRaisesRegex(LoopError, 'Required CLI is not installed'):
                providers.executable_for('claude')

    def test_selected_opposite_failure_is_not_reselected(self):
        env = self.managed({'codex': 'fixed', 'claude': 'fixed'})
        with patch.dict(os.environ, {**env, 'PATH': '/unavailable'}):
            selection = providers.review_selection('codex')
            # Simulate an installed provider refusing authentication. Selection
            # remains opposite and structured_call must expose its failure.
            failed = {'exit_code': 1, 'timed_out': False}
            with patch.object(providers, 'execute', return_value=failed) as execute:
                with self.assertRaisesRegex(LoopError, 'claude call failed'):
                    providers.structured_call(selection['provider'], self.root,
                        self.root / 'call', 'review', 1, providers.REVIEW_SCHEMA)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(selection['provider'], 'claude')


if __name__ == '__main__':
    unittest.main()
