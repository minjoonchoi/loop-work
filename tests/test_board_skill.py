"""Single-skill board routing and side-effect-free CLI discovery."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class BoardSkillTests(unittest.TestCase):
    def test_board_routes_before_activation_and_preserves_human_compatibility(self):
        skill = (SOURCE / 'skills/loop-work/SKILL.md').read_text()
        selection = skill.split('## Select the argument first', 1)[1].split('## Run one explicit task', 1)[0]
        self.assertIn('first argument is `board`', selection)
        self.assertIn('rules/board.md', selection)
        self.assertIn('A bare `board` means `board open`', selection)
        self.assertIn('Stop this mode', selection)
        self.assertNotIn('python3 "SKILL_DIR/loop.py" harness on', selection)
        self.assertIn('first argument is `human`', selection)
        self.assertIn('rules/human.md', selection)
        self.assertIn('allow_implicit_invocation: false',
                      (SOURCE / 'skills/loop-work/agents/openai.yaml').read_text())

    def test_board_rule_keeps_document_source_and_action_authority_distinct(self):
        rule = (SOURCE / 'rules/board.md').read_text()
        for required in ('vault Markdown', 'SQLite/development JSON', 'board start',
                         'actual person', 'committed but vault export failed',
                         'Never execute again', 'recency/provider/cwd'):
            self.assertIn(required, rule)

    def test_board_help_has_no_session_goal_browser_or_knowledge_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            kb = home / 'kb'
            env = {**os.environ, 'HOME': str(home), 'LOOP_KB_HOME': str(kb)}
            result = subprocess.run([sys.executable, '-B', str(SOURCE / 'scripts/loop.py'),
                '--knowledge-home', str(kb), 'board', 'open', '--help'], cwd=home,
                env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            for option in ('--session', '--task', '--port', '--vault'):
                self.assertIn(option, result.stdout)
            for retired in ('--web', '--no-open'):
                self.assertNotIn(retired, result.stdout)
            board_help = subprocess.run([sys.executable, '-B', str(SOURCE / 'scripts/loop.py'),
                '--knowledge-home', str(kb), 'board', '--help'], cwd=home,
                env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(board_help.returncode, 0, board_help.stderr)
            self.assertNotIn('serve', board_help.stdout)
            self.assertFalse(kb.exists())
            self.assertEqual(list(home.iterdir()), [])

    def test_legacy_human_help_remains_available_without_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            kb = home / 'kb'
            result = subprocess.run([sys.executable, '-B', str(SOURCE / 'scripts/loop.py'),
                '--knowledge-home', str(kb), 'human', '--help'], cwd=home,
                env={**os.environ, 'HOME': str(home), 'LOOP_KB_HOME': str(kb)},
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            for command in ('list', 'show', 'request', 'respond', 'execute'):
                self.assertIn(command, result.stdout)
            self.assertNotIn('serve', result.stdout)
            self.assertFalse(kb.exists())
            self.assertEqual(list(home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
