from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

from loop_work.runtime import snapshot


class PortableVaultTests(unittest.TestCase):
    def test_fixed_runtime_contains_workspace_and_exports_only_selected_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            destination = base / 'runtime'
            result = snapshot(destination)
            self.assertTrue((destination / 'loop_work/vault.py').is_file())
            self.assertTrue((destination / 'loop_work/workspace.py').is_file())
            fake_home = base / 'home'; fake_home.mkdir()
            code = '''from pathlib import Path
import json
from loop_work.knowledge import KnowledgeBase
kb=KnowledgeBase(Path('selected-data'),vault_home=Path('selected-vault'))
kb.put('task',{'id':'portable-task','kind':'document','title':'Portable result','phase':'working','session_id':'session-one','project_ids':['project-one'],'goal':{'outcome':'Explain exact facts'},'result':None})
print(json.dumps(kb.vault_status()))
'''
            env = {**os.environ, 'PYTHONPATH': str(destination), 'HOME': str(fake_home), 'PYTHONDONTWRITEBYTECODE': '1'}
            env.pop('LOOP_KB_HOME', None)
            run = subprocess.run([sys.executable, '-B', '-c', code], cwd=base, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['status'], 'ok')
            self.assertTrue(list((base / 'selected-vault/projects').glob('*--project-one/tasks/*--portable-task/현재-*--portable-task.md')))
            self.assertFalse((fake_home / '.loop-work').exists())
