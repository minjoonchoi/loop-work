"""Task-scoped entry instructions and no-state missing-argument CLI behavior."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class TaskSkillTests(unittest.TestCase):
    def test_canonical_skill_limits_continuation_to_one_task(self):
        skill = (SOURCE / 'skills/loop-work/SKILL.md').read_text()
        self.assertLess(skill.index('first argument is `board`'), skill.index('## Run one explicit task'))
        self.assertLess(skill.index('first argument is `human`'), skill.index('## Run one explicit task'))
        for text in ('asks once for the missing task prompt', 'create no session',
                     'Unrelated ordinary requests run normally', 'Completion or abort releases',
                     '--task TASK_ID', 'must not silently replace', 'legacy enabled flag'):
            self.assertIn(text, skill)
        metadata = (SOURCE / 'skills/loop-work/agents/openai.yaml').read_text()
        self.assertIn('allow_implicit_invocation: false', metadata)
        self.assertNotIn('every input in this conversation', metadata)
        from scripts.install import BLOCK
        self.assertIn('binds only that task', BLOCK)
        self.assertNotIn('EVERY subsequent input', BLOCK)

    def test_cli_on_missing_task_does_not_create_knowledge(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            kb = base / 'kb'
            env = {**os.environ, 'HOME': str(base), 'LOOP_KB_HOME': str(kb)}
            result = subprocess.run([sys.executable, '-B', str(SOURCE / 'scripts/loop.py'),
                                     '--knowledge-home', str(kb), 'harness', 'on',
                                     '--provider', 'codex'], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--task', result.stderr)
            self.assertFalse(kb.exists())
