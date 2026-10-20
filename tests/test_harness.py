from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work.engine import Engine
from loop_work.harness import Harness
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import HARNESS_SKILL_FILES, LoopError, read_json, rule_manifest
from loop_work.work import Work
from scripts import install as installer
from support import ProjectTest, use_fake_routing


SOURCE = Path(__file__).resolve().parents[1]


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        use_fake_routing(self, self.base)
        self.root = self.base / 'documents'
        self.root.mkdir()
        self.kb = KnowledgeBase(self.base / 'knowledge')
        self.harness = Harness(self.kb)
        self.work = Work(self.kb)

    def opened(self, provider='codex', session_id=None):
        return self.work.open('planning','Plan the requested result',provider,[self.root],session_id)['task']

    def test_no_task_or_invalid_binding_has_no_mutation_and_legacy_is_inactive(self):
        before=self.kb.list('session')
        with self.assertRaisesRegex(LoopError,'task_id'):
            self.harness.on('codex')
        self.assertEqual(self.kb.list('session'),before)
        legacy=self.kb.session('codex')
        self.kb.put('session',{**legacy,'harness':{'enabled':True}})
        self.assertFalse(self.harness.status(legacy['id'])['enabled'])
        task=self.opened()
        before={kind:self.kb.list(kind) for kind in ('session','task')}
        for call in (lambda:self.harness.on('claude',task_id=task['id']),
                     lambda:self.harness.on('codex','unknown',task['id']),
                     lambda:self.harness.on('codex',task_id='missing')):
            with self.assertRaises(LoopError): call()
        self.assertEqual(before,{kind:self.kb.list(kind) for kind in before})

    def test_completion_releases_only_bound_task_and_new_task_needs_explicit_on(self):
        task=self.opened(); enabled=self.harness.on('codex',task_id=task['id'])
        self.assertEqual(enabled['scope'],'task'); self.assertEqual(enabled['inputs'],'related')
        other=self.opened(session_id=task['session_id'])
        with self.assertRaisesRegex(LoopError,'Another unfinished'):
            self.harness.on('codex',task_id=other['id'])
        self.work.define(task['id'],{'outcome':'Describe the plan.','deliverable':'A concrete plan.',
            'criteria':[{'id':'C1','description':'State the plan.'}],'decisions':[],'open_questions':[]})
        self.work.start(task['id'])
        result=self.work.finish(task['id'],{'summary':'The plan is recorded.','outputs':['conversation:answer'],
            'checks':[{'criterion_id':'C1','satisfied':True,'evidence':'The answer states the plan.'}]})
        self.assertTrue(result['passed'])
        status=self.harness.status(task['session_id'])
        self.assertFalse(status['enabled']); self.assertEqual(status['task_id'],task['id'])
        self.assertEqual(status['release_reason'],'completed')
        self.assertFalse(self.work.context(other['id'])['knowledge']['harness']['enabled'])
        self.assertTrue(self.harness.on('codex',task_id=other['id'])['enabled'])

    def test_binding_is_idempotent_and_off_preserves_task_goal_and_budget(self):
        task=self.opened('claude'); enabled=self.harness.on('claude',task_id=task['id'])
        history=self.kb.history('session',task['session_id'])
        self.assertEqual(self.harness.on('claude',task['session_id'],task['id']),enabled)
        self.assertEqual(self.kb.history('session',task['session_id']),history)
        self.kb.put('worker-budget',{'id':task['id'],'calls':3})
        off=self.harness.off(task['session_id'])
        self.assertFalse(off['enabled']); self.assertEqual(self.harness.off(task['session_id']),off)
        self.assertEqual(self.kb.get('task',task['id']),task)
        self.assertEqual(self.kb.get('worker-budget',task['id'])['calls'],3)
        self.assertTrue(self.harness.on('claude',task_id=task['id'])['enabled'])

    def test_source_and_installed_cli_bind_explicit_task_outside_project(self):
        installer.install(self.root)
        other=self.base/'elsewhere'; other.mkdir()
        for entrypoint in (SOURCE/'scripts/loop.py',self.root/'.loop/loop.py'):
            task=self.opened()
            def run(*args):
                process=subprocess.run([sys.executable,str(entrypoint),'--knowledge-home',str(self.kb.home),*args],
                    cwd=other,capture_output=True,text=True)
                self.assertEqual(process.returncode,0,process.stderr)
                return json.loads(process.stdout)
            on=run('harness','on','--provider','codex','--task',task['id'])
            self.assertTrue(on['enabled']); self.assertEqual(on['task_id'],task['id'])
            self.assertEqual(Path(on['entrypoint']),entrypoint.resolve())
            self.assertFalse(run('harness','off',on['session_id'])['enabled'])
        self.assertEqual(list(other.iterdir()),[])

    def test_installed_skill_changes_stale_dependent_knowledge(self):
        installer.install(self.root)
        (self.root / 'guide.md').write_text('Observed explanation.\n')
        locations = [self.kb.attach(self.root)]
        entry = {'id': 'guide', 'kind': 'fact', 'scope': 'project', 'status': 'confirmed',
                 'summary': 'The guide explains the result.', 'evidence': ['guide.md:1'], 'paths': ['guide.md']}
        before = self.kb.context(locations)
        self.kb.remember(entry, locations, before['revision'])
        skill = self.root / '.agents/skills/loop-work/agents/openai.yaml'
        skill.write_text(skill.read_text() + '\n# changed policy\n')
        self.assertIn('rules_or_branch_changed', self.kb.context(locations)['stale'][0]['stale_reasons'])


class SkillInstallationTests(ProjectTest):
    def test_explicit_provider_discovery_and_shared_body_survive_upgrade(self):
        (self.root / '.claude/skills/unrelated').mkdir(parents=True)
        unrelated = self.root / '.claude/skills/unrelated/SKILL.md'
        unrelated.write_text('Keep this skill.\n')
        settings = self.root / '.claude/settings.json'
        settings.write_text('{"hooks": {}}\n')
        legacy = {name: value for name, value in installer.managed_files().items() if name not in HARNESS_SKILL_FILES}
        old_block = installer.START + '\nOld ordinary-request entry\n' + installer.END + '\n'
        with patch.object(installer, 'managed_files', return_value=legacy), patch.object(installer, 'BLOCK', old_block):
            installer.install(self.root)
        installer.install(self.root)
        canonical = (SOURCE / 'skills/loop-work/SKILL.md').read_text()
        self.assertEqual((self.root / HARNESS_SKILL_FILES[0]).read_text(), canonical)
        claude = (self.root / HARNESS_SKILL_FILES[2]).read_text()
        self.assertEqual(claude.replace('disable-model-invocation: true\n', '', 1), canonical)
        self.assertIn('allow_implicit_invocation: false', (self.root / HARNESS_SKILL_FILES[1]).read_text())
        manifest = read_json(self.root / '.loop/install.json')
        self.assertTrue(set(HARNESS_SKILL_FILES).issubset(manifest['files']))
        self.assertNotIn('route EVERY subsequent input', (self.root / 'AGENTS.md').read_text())
        self.assertNotIn('Old ordinary-request entry', (self.root / 'AGENTS.md').read_text())
        self.assertEqual(unrelated.read_text(), 'Keep this skill.\n')
        self.assertEqual(settings.read_text(), '{"hooks": {}}\n')
        before = {name: (self.root / name).read_bytes() for name in HARNESS_SKILL_FILES}
        installer.install(self.root)
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in HARNESS_SKILL_FILES})

    def test_same_name_skill_conflicts_and_local_edits_abort_before_managed_writes(self):
        for index, name in enumerate(HARNESS_SKILL_FILES):
            root = Path(self.temp.name) / ('collision-' + str(index))
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_text('My existing skill\n')
            with self.assertRaisesRegex(LoopError, 'Local changes'):
                installer.install(root)
            self.assertEqual(path.read_text(), 'My existing skill\n')
            self.assertFalse((root / '.loop/loop.py').exists())
            self.assertFalse((root / 'AGENTS.md').exists())
        installer.install(self.root)
        path = self.root / HARNESS_SKILL_FILES[1]
        path.write_text('My edited policy\n')
        before = (self.root / '.loop/install.json').read_bytes()
        with self.assertRaisesRegex(LoopError, 'Local changes'):
            installer.install(self.root)
        self.assertEqual((self.root / '.loop/install.json').read_bytes(), before)
        self.assertEqual(path.read_text(), 'My edited policy\n')

    def test_symlinked_skill_directory_and_invalid_parent_fail_preflight(self):
        for alias in (True, False):
            root = Path(self.temp.name) / ('alias' if alias else 'file-parent')
            (root / '.agents').mkdir(parents=True)
            if alias:
                (root / 'other').mkdir()
                (root / '.agents/skills').symlink_to(root / 'other', target_is_directory=True)
            else:
                (root / '.agents/skills').write_text('Existing file\n')
            with self.assertRaisesRegex(LoopError, 'symlinked|not a directory'):
                installer.install(root)
            self.assertFalse((root / '.loop/loop.py').exists())

    def test_ignored_skill_policy_changes_invalidate_frozen_development(self):
        installer.install(self.root)
        with (self.root / '.gitignore').open('a') as stream:
            stream.write('.agents/\n.claude/\n')
        self.assertTrue(set(HARNESS_SKILL_FILES).issubset(rule_manifest(self.root, [])))
        self.running()
        path = self.root / HARNESS_SKILL_FILES[1]
        path.write_text(path.read_text() + '\n# altered policy\n')
        with self.assertRaisesRegex(LoopError, 'Frozen'):
            self.engine.gate('M1')
        self.assertEqual(self.state()['phase'], 'blocked')

    def test_development_completion_releases_binding_and_preserves_session_identity(self):
        state=self.state(); harness=Harness(self.engine.knowledge)
        task_id=self.engine.refresh()['work_id']
        enabled=harness.on('claude',state['session_id'],task_id)
        self.running()
        self.assertTrue(self.engine.gate('M1')['passed'])
        self.assertTrue(self.engine.gate()['passed'])
        status=harness.status(state['session_id'])
        self.assertFalse(status['enabled']); self.assertEqual(status['release_reason'],'completed')
        other=Engine(self.root,'next-goal',self.engine.knowledge)
        other.initialize('Another goal','claude',state['session_id'])
        self.assertFalse(read_json(other.state_dir/'context.json')['session']['harness']['enabled'])
        task=other.refresh()['work_id']
        self.assertTrue(harness.on('claude',state['session_id'],task)['enabled'])
