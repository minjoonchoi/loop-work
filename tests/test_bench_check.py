from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_work import benchmark, bench_check, bench_evolution
from loop_work.storage import digest, read_json
import test_benchmark as fixtures


class InstallationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.snapshot = benchmark.source_snapshot(fixtures.SOURCE)
        benchmark.export_files(self.source, self.snapshot['files'])
        self.suite = fixtures.make_suite(self.base / 'suite')

    def check(self, **kwargs):
        return bench_check.check({'codex': 'fake-model'}, {'codex': 'low'}, candidate=self.source,
                                 suite=self.suite, repeats=1, output=self.base / 'run',
                                 history=self.base / 'history', executables={'codex': '/never/invoke'}, **kwargs)

    def test_actual_copy_install_imports_and_preserves_local_file(self):
        value = benchmark.installation_preflight(self.source, self.snapshot, self.base / 'preflight')
        self.assertTrue(value['passed'])
        self.assertTrue(value['preserved_user_file'])
        self.assertGreater(value['managed_files'], 50)
        self.assertGreater(value['imported_modules'], 20)
        self.assertEqual(benchmark.source_snapshot(self.source), self.snapshot)

    def minimal_source(self, package, *, omit_runtime=False):
        source = self.base / package
        skill = package.replace('_', '-')
        files = {
            package + '/__init__.py': '', package + '/engine.py': 'VALUE = 42\n',
            'rules/work.md': 'Keep evidence.\n',
            'skills/' + skill + '/SKILL.md': '---\nname: ' + skill + '\n---\nWork.\n',
            'scripts/loop.py': 'import argparse\nargparse.ArgumentParser(description="Copied runtime").parse_args()\n',
        }
        installer = '''from pathlib import Path
SOURCE=Path(__file__).resolve().parent.parent
def managed_files():
    result={'.loop/loop.py':(SOURCE/'scripts/loop.py').read_bytes()}
    for path in (SOURCE/PACKAGE).glob('*.py'):
        if not OMIT_RUNTIME:
            result['.loop/'+PACKAGE+'/'+path.name]=path.read_bytes()
    result['.agents/skills/'+SKILL+'/SKILL.md']=(SOURCE/'skills'/SKILL/'SKILL.md').read_bytes()
    return result
def install(target):
    for name,data in managed_files().items():
        path=target/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
'''
        files['scripts/install.py'] = ('PACKAGE=' + repr(package) + '\nSKILL=' + repr(skill) +
                                      '\nOMIT_RUNTIME=' + repr(omit_runtime) + '\n' + installer)
        benchmark.export_files(source, files)
        return source, benchmark.source_snapshot(source)

    def test_valid_minimal_current_and_legacy_without_desktop_install(self):
        for package in ('loop_work', 'loop_dev'):
            with self.subTest(package=package):
                source, snapshot = self.minimal_source(package)
                value = benchmark.installation_preflight(source, snapshot, self.base / ('proof-' + package))
                self.assertTrue(value['passed'])
                self.assertEqual(value['imported_modules'], 2)
                self.assertEqual(benchmark.source_snapshot(source), snapshot)

    def test_empty_installed_package_cannot_pass(self):
        source, snapshot = self.minimal_source('loop_dev', omit_runtime=True)
        with self.assertRaises(benchmark.SetupPreflightError):
            benchmark.installation_preflight(source, snapshot, self.base / 'empty-package')
        self.assertIn('Copied runtime package is absent or empty',
                      (self.base / 'empty-package/process/stderr.log').read_text())

    def test_timeout_or_cancellation_with_clean_exit_is_not_success(self):
        for flag in ('timed_out', 'cancelled'):
            with self.subTest(flag=flag):
                output = self.base / flag
                with patch.object(benchmark, 'execute', return_value={'exit_code': 0, flag: True}) as execute, \
                        patch('loop_work.bench_report.judge') as judge:
                    value = bench_check.check({'codex': 'model'}, {'codex': 'low'}, candidate=self.source,
                                              suite=self.suite, repeats=1, output=output,
                                              history=self.base / 'history', executables={'codex': '/never/invoke'})
                self.assertEqual(value['phase'], 'preflight')
                self.assertEqual(value['model_calls'], 0)
                self.assertEqual(execute.call_count, 1)
                self.assertTrue(execute.call_args.kwargs['kill_tree'])
                self.assertEqual(execute.call_args.args[0][0], benchmark.sys.executable)
                judge.assert_not_called()

    def test_missing_helper_blocks_before_provider_or_judge_and_keeps_history(self):
        (self.source / 'scripts/verify_tauri_native.py').unlink()
        history = self.base / 'history'
        history.mkdir()
        baseline = b'{"version":1,"baselines":{}}\n'
        (history / 'baselines.json').write_bytes(baseline)
        with patch.object(benchmark, 'execute') as provider, patch('loop_work.bench_report.judge') as judge, \
                patch.object(bench_evolution, 'record') as record:
            value = self.check()
        self.assertEqual(value['phase'], 'preflight')
        self.assertEqual(value['verdict'], 'inconclusive')
        provider.assert_not_called()
        judge.assert_not_called()
        record.assert_not_called()
        self.assertEqual((history / 'baselines.json').read_bytes(), baseline)
        self.assertFalse((self.base / 'run/manifest.json').exists())

    def test_missing_basic_source_is_structured_not_quality_zero(self):
        (self.source / 'scripts/install.py').unlink()
        with patch.object(benchmark, 'execute') as execute:
            value = self.check()
        self.assertEqual(value['phase'], 'preflight')
        self.assertEqual(value['model_calls'], 0)
        self.assertIsNone(value['evolution'])
        execute.assert_not_called()

    def test_export_mismatch_refuses_install(self):
        (self.source / 'rules/work.md').write_text('changed')
        with patch.object(benchmark, 'execute') as execute:
            with self.assertRaisesRegex(benchmark.SetupPreflightError, 'differs'):
                benchmark.installation_preflight(self.source, self.snapshot, self.base / 'preflight')
        execute.assert_not_called()

    def test_real_broken_installer_blocks_provider_and_judge(self):
        path = self.source / 'scripts/install.py'
        path.write_text(path.read_text() + '\nraise RuntimeError("preflight fixture install failure")\n')
        with patch.object(benchmark, 'run_trial') as conversation, patch('loop_work.bench_report.judge') as judge:
            value = self.check()
        self.assertEqual(value['phase'], 'preflight')
        conversation.assert_not_called()
        judge.assert_not_called()
        self.assertIn('preflight fixture install failure',
                      (self.base / 'run/preflight/candidate/process/stderr.log').read_text())

    def test_dry_run_only_prepares_and_cli_absence_precedes_install(self):
        with patch.object(benchmark, 'installation_preflight') as install:
            value = self.check(dry_run=True)
        install.assert_not_called()
        self.assertEqual(value['setup_protocol'], benchmark.SETUP_PROTOCOL)
        self.assertFalse((self.base / 'run').exists())
        with patch.object(benchmark.shutil, 'which', return_value=None), \
                patch.object(benchmark, 'installation_preflight') as install:
            value = bench_check.check({'codex': 'model'}, {'codex': 'low'}, candidate=self.source,
                                      suite=self.suite, repeats=1, output=self.base / 'run',
                                      history=self.base / 'history')
        install.assert_not_called()
        self.assertEqual(value['phase'], 'run')
        self.assertIn('Every configured CLI', value['failure']['error'])

    def test_historical_profile_is_not_retroactively_upgraded(self):
        # Match the required historical profile fields without adding setup.
        spec = {key: 'frozen' for key in bench_evolution.PROFILE_FIELDS}
        before = bench_evolution.profile(spec)
        self.assertNotIn('setup_protocol', before)
        expected = digest(before)
        self.assertEqual(digest(bench_evolution.profile(spec)), expected)
        newer = dict(spec, setup_protocol=benchmark.SETUP_PROTOCOL)
        self.assertNotEqual(digest(bench_evolution.profile(newer)), expected)

    def test_exact_historical_plan_without_setup_keeps_its_seal(self):
        from test_bench_trial_plan import make_plan, seal
        spec = benchmark.prepare(self.suite, self.source, {'codex': 'model'}, ['codex'],
                                 1, 0, 'confined', {'codex': 'low'})
        output = (self.base / 'planned').resolve()
        plan = make_plan(spec, output)
        del spec['setup_protocol']
        del plan['experiment']['setup_protocol']
        plan['experiment_hash'] = digest(plan['experiment'])
        seal(plan)
        original = digest(plan)
        benchmark.validate_trial_plan(plan, spec, output, historical=True)
        self.assertEqual(digest(plan), original)
        with self.assertRaisesRegex(benchmark.LoopError, 'setup protocol'):
            benchmark.validate_trial_plan(plan, spec, output)
        spec['setup_protocol'] = benchmark.SETUP_PROTOCOL
        with self.assertRaisesRegex(benchmark.LoopError, 'differs'):
            benchmark.validate_trial_plan(plan, spec, output)

    def test_exporter_omission_blocks_before_any_execute(self):
        export = benchmark.export_files
        def omit(root, contents):
            export(root, {k: v for k, v in contents.items() if k != 'scripts/verify_tauri_native.py'})
        with patch.object(benchmark, 'export_files', side_effect=omit), \
                patch.object(benchmark, 'execute') as execute, patch('loop_work.bench_report.judge') as judge:
            value = self.check()
        self.assertEqual(value['phase'], 'preflight')
        self.assertEqual(value['model_calls'], 0)
        execute.assert_not_called()
        judge.assert_not_called()


if __name__ == '__main__':
    unittest.main()
