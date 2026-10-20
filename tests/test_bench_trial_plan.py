from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import test_benchmark as fixtures
from loop_work import benchmark, bench_check, bench_evolution, cli
from loop_work.storage import LoopError, digest, file_hash, read_json, write_json


def make_plan(spec, output):
    cases = {c['id']: c for c in spec['suite']['cases']}
    rows = []
    for row in benchmark.trial_schedule(spec):
        identity = uuid.uuid4().hex
        rows.append({**row, 'id': identity, 'roots': [str(output / 'trials' / identity / 'workspace' / root)
                     for root in cases[row['case']]['roots']]})
    experiment = {k: spec[k] for k in benchmark.TRIAL_EXPERIMENT_FIELDS}
    value = {'version': 1, 'output': str(output), 'experiment': experiment,
             'experiment_hash': digest(experiment), 'trials': rows}
    return seal(value)


def seal(value):
    value['seal'] = digest({k: v for k, v in value.items() if k != 'seal'})
    return value


class TrialPlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.suite = fixtures.make_suite(self.base / 'suite')
        self.output = self.base / 'output'
        self.models, self.efforts = {'codex': 'fixed'}, {'codex': 'low'}
        self.spec = benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                                      'confined test', self.efforts)
        self.plan = make_plan(self.spec, self.output)
        self.path = self.base / 'trial-plan.json'
        write_json(self.path, self.plan)

    def test_valid_plan_and_cli_flags_preserve_pinned_identifiers(self):
        prepared = benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                    'confined test', self.efforts, trial_plan=self.path, output=self.output)
        self.assertEqual(prepared['trial_plan']['plan'], self.plan)
        self.assertEqual(prepared['planning_protocol'], benchmark.TRIAL_PLAN_PROTOCOL)
        self.assertFalse(self.output.exists())
        for command in ('run', 'check'):
            args = cli.parser().parse_args(['bench', command, '--trial-plan', str(self.path),
                '--suite', str(self.suite), '--candidate', str(fixtures.SOURCE), '--output', str(self.output),
                '--provider', 'codex', '--environment', 'confined test'])
            self.assertEqual(args.trial_plan, self.path)

    def test_invalid_inputs_have_no_provider_output_or_config_side_effects(self):
        variants = []
        for modify in (
            lambda p: p.update(extra=True),
            lambda p: p.update(version=True),
            lambda p: p.update(output=str(self.base / 'wrong-output')),
            lambda p: p['trials'].pop(),
            lambda p: p['trials'].append(copy.deepcopy(p['trials'][0])),
            lambda p: p['trials'].reverse(),
            lambda p: p['trials'][0].update(repeat=True),
            lambda p: p['trials'][1].update(id=p['trials'][0]['id']),
            lambda p: p['trials'][0].update(id='../outside'),
            lambda p: p['trials'][0].update(roots=[str(self.base / 'wrong-root')]),
            lambda p: p['experiment'].update(evaluation={'provider': 'codex', 'model': 'other', 'effort': 'low', 'repeats': 2}),
        ):
            value = copy.deepcopy(self.plan)
            modify(value)
            variants.append(seal(value))
        stale = copy.deepcopy(self.plan)
        stale['seal'] = 'stale'
        variants.append(stale)
        config = self.base / 'untouched-config'
        config.write_text('preserve')
        for value in variants:
            with self.subTest(value=value):
                write_json(self.path, value)
                with patch('loop_work.benchmark.execute') as execute, \
                     patch('loop_work.bench_transport.conversation') as conversation:
                    with self.assertRaises(LoopError):
                        benchmark.run(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                            'confined test', self.output, efforts=self.efforts, trial_plan=self.path)
                execute.assert_not_called()
                conversation.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assertEqual(config.read_text(), 'preserve')

    def test_bounded_nonlinked_plan_and_prevalidated_hash_are_required(self):
        alias = self.base / 'alias.json'
        alias.symlink_to(self.path)
        with self.assertRaises(LoopError):
            benchmark.load_trial_plan(alias, self.spec, self.output)
        with patch('loop_work.benchmark.execute') as execute, self.assertRaisesRegex(LoopError, 'prevalidation'):
            benchmark.run(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                'confined test', self.output, efforts=self.efforts, trial_plan=self.path, trial_plan_hash='stale')
        execute.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_frozen_judge_cannot_be_added_or_dropped_implicitly(self):
        evaluation = {'provider': 'codex', 'model': 'fixed', 'effort': 'low', 'repeats': 2}
        with self.assertRaisesRegex(LoopError, 'judge'):
            benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                'confined test', self.efforts, evaluation, trial_plan=self.path, output=self.output)

    def test_planning_protocol_affects_profile_but_paths_and_ids_do_not(self):
        spec = {**self.spec, 'versions': {'codex': 'fake'},
                'evaluation': {'provider': 'codex', 'model': 'fixed', 'effort': 'low', 'repeats': 2}}
        planned = {**spec, 'planning_protocol': benchmark.TRIAL_PLAN_PROTOCOL, 'trial_plan': {'plan': self.plan}}
        self.assertNotEqual(bench_evolution.profile(spec), bench_evolution.profile(planned))
        other = {**planned, 'trial_plan': {'plan': {'output': 'other', 'trials': []}}}
        self.assertEqual(bench_evolution.profile(planned), bench_evolution.profile(other))


    def legacy_read_fixture(self):
        legacy = copy.deepcopy(self.spec)
        legacy.pop('activation_protocol')
        plan = copy.deepcopy(self.plan)
        plan['experiment'].pop('activation_protocol')
        plan['experiment_hash'] = digest(plan['experiment'])
        seal(plan)
        self.output.mkdir()
        write_json(self.output / 'trial-plan.json', plan)
        legacy['planning_protocol'] = benchmark.TRIAL_PLAN_PROTOCOL
        legacy['trial_plan'] = {'protocol': benchmark.TRIAL_PLAN_PROTOCOL, 'plan': plan,
            'sealed_file_hash': file_hash(self.output / 'trial-plan.json')}
        write_json(self.output / 'manifest.json', legacy)
        write_json(self.output / 'index.json', {'manifest_hash': digest(legacy), 'trials': [], 'complete': False})
        return legacy, plan

    def test_sealed_historical_plan_reads_exact_old_experiment_without_rewriting(self):
        legacy, plan = self.legacy_read_fixture()
        before = {name: file_hash(self.output / name) for name in
                  ('manifest.json', 'index.json', 'trial-plan.json')}
        with patch('loop_work.benchmark.execute') as execute, patch('loop_work.bench_transport.conversation') as conversation:
            _, loaded, index, rows = benchmark.read_run(self.output)
        execute.assert_not_called()
        conversation.assert_not_called()
        self.assertEqual(loaded, legacy)
        self.assertFalse(index['complete'])
        self.assertEqual(rows, [])
        self.assertEqual(before, {name: file_hash(self.output / name) for name in before})
        self.assertNotIn('activation_protocol', plan['experiment'])

    def test_historical_compatibility_cannot_execute_old_plan_or_drop_new_protocol(self):
        legacy, old_plan = self.legacy_read_fixture()
        with self.assertRaisesRegex(LoopError, 'requires an explicit activation protocol'):
            benchmark.validate_trial_plan(old_plan, legacy, self.output)
        with self.assertRaisesRegex(LoopError, 'differs'):
            benchmark.validate_trial_plan(old_plan, self.spec, self.output)
        with self.assertRaisesRegex(LoopError, 'differs'):
            benchmark.validate_trial_plan(self.plan, legacy, self.output, historical=True)
        altered = copy.deepcopy(old_plan)
        altered['experiment']['evaluation'] = {'provider':'codex','model':'changed','effort':'low','repeats':2}
        altered['experiment_hash'] = digest(altered['experiment'])
        seal(altered)
        with self.assertRaisesRegex(LoopError, 'differs'):
            benchmark.validate_trial_plan(altered, legacy, self.output, historical=True)
        write_json(self.path, old_plan)
        with patch('loop_work.benchmark.execute') as execute, patch('loop_work.bench_transport.conversation') as conversation:
            with self.assertRaisesRegex(LoopError, 'differs'):
                benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                    'confined test', self.efforts, trial_plan=self.path, output=self.output)
        execute.assert_not_called()
        conversation.assert_not_called()


class TrialPlanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RunnerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base
        self.suite = self.fixture.suite
        self.models, self.efforts = {'codex': 'fixed-codex'}, {'codex': 'medium'}
        self.actual = {'codex': self.fixture.actual['codex']}
        self.output = self.base / 'planned-run'
        self.spec = benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                                      'confined planned test', self.efforts)
        self.plan = make_plan(self.spec, self.output)
        self.path = self.base / 'plan.json'
        write_json(self.path, self.plan)

    def test_fake_provider_uses_exact_ids_roots_and_sealed_manifest(self):
        # Exercise mode-aware external pins versus the nonexecutable sealed copy.
        self.path.chmod(0o700)
        benchmark.run(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
            'confined planned test', self.output, executables=self.actual, efforts=self.efforts, trial_plan=self.path)
        root, spec, index, rows = benchmark.read_run(self.output)
        self.assertTrue(index['complete'])
        self.assertEqual([r['id'] for r in rows], [r['id'] for r in self.plan['trials']])
        self.assertEqual(spec['trial_plan']['plan'], self.plan)
        self.assertNotEqual(spec['trial_plan']['file_hash'], spec['trial_plan']['content_sha256'])
        self.assertNotEqual(spec['trial_plan']['file_hash'], spec['trial_plan']['sealed_file_hash'])
        for row in self.plan['trials']:
            self.assertTrue(all(Path(p).is_dir() for p in row['roots']))

    def test_plan_file_change_during_provider_call_invalidates_run(self):
        original = benchmark.bench_transport.conversation
        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            self.path.write_text(self.path.read_text() + ' ')
            return value
        with patch('loop_work.bench_transport.conversation', side_effect=changed):
            value = benchmark.run(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                'confined planned test', self.output, executables=self.actual, efforts=self.efforts, trial_plan=self.path)
        self.assertFalse(read_json(self.output / 'index.json')['complete'])
        self.assertFalse(value['passed'])

    def test_full_check_keeps_the_prevalidated_plan_through_run_and_judging(self):
        evaluation = {'provider':'codex','model':'fixed-codex','effort':'medium','repeats':2}
        spec = benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                                 'confined planned test', self.efforts, evaluation)
        write_json(self.path, make_plan(spec, self.output))
        with patch('loop_work.providers.shutil.which', side_effect=self.actual.get):
            value = bench_check.check(self.models, self.efforts, suite=self.suite, candidate=fixtures.SOURCE,
                providers=['codex'], repeats=1, seed=17, environment='confined planned test', output=self.output,
                history=self.base/'history', trial_plan=self.path, executables=self.actual)
        self.assertEqual(value['phase'], 'completed', value.get('failure'))
        _, manifest, index, rows = benchmark.read_run(self.output)
        self.assertTrue(index['complete'])
        self.assertEqual(manifest['trial_plan']['plan'], read_json(self.path))
        self.assertEqual(manifest['evaluation'], evaluation)

    def test_check_dry_run_uses_same_plan_and_frozen_evaluation(self):
        evaluation = {'provider':'codex','model':'fixed-codex','effort':'medium','repeats':2}
        spec = benchmark.prepare(self.suite, fixtures.SOURCE, self.models, ['codex'], 1, 17,
                                 'confined planned test', self.efforts, evaluation)
        write_json(self.path, make_plan(spec, self.output))
        value = bench_check.check(self.models, self.efforts, suite=self.suite, candidate=fixtures.SOURCE,
            providers=['codex'], repeats=1, seed=17, environment='confined planned test', output=self.output,
            history=self.base/'history', trial_plan=self.path, dry_run=True)
        self.assertEqual(value['trial_plan']['plan'], read_json(self.path))
        self.assertFalse(self.output.exists())
