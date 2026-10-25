from pathlib import Path
import json
import hashlib
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
            selected_vault = base / 'selected-vault'
            settings = selected_vault / '.obsidian/app.json'; settings.parent.mkdir(parents=True)
            settings.write_text('{"human_setting":true}\n')
            unowned = selected_vault / '개인 메모/원문 메모.md'; unowned.parent.mkdir()
            unowned.write_text('사용자가 직접 쓴 English/API_NAME 원문\n')
            preserved = {path:(path.read_bytes(), path.stat().st_ino, path.stat().st_mode) for path in (settings,unowned)}
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
            manifest_path = base / 'selected-data/vault-owned.json'
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest['layout_version'], 3)
            project_suffix = hashlib.sha256(b'project-one').hexdigest()[:8]
            task_suffix = hashlib.sha256(b'portable-task').hexdigest()[:8]
            expected = '프로젝트/프로젝트--' + project_suffix + '/작업/Portable result--' + task_suffix + '/진행 현황.md'
            self.assertEqual(manifest['paths']['task:project-one:portable-task'], expected)
            current = selected_vault / expected
            self.assertTrue(current.is_file())
            metadata = json.loads(current.read_text().splitlines()[1][len('loop_work: '):])
            self.assertEqual(metadata['version'], 3)
            self.assertEqual(metadata['project_id'], 'project-one')
            self.assertEqual(metadata['task_id'], 'portable-task')
            self.assertEqual(metadata['record']['kind'], 'document')
            self.assertEqual(metadata['record']['phase'], 'working')
            self.assertEqual(metadata['record']['title'], 'Portable result')
            self.assertEqual(metadata['record']['goal']['outcome'], 'Explain exact facts')
            self.assertIn('Explain exact facts', current.read_text())
            self.assertEqual(preserved, {path:(path.read_bytes(), path.stat().st_ino, path.stat().st_mode) for path in preserved})
            self.assertFalse((fake_home / '.loop-work').exists())

            # A copied runtime must not bypass an edited document by exporting its
            # renamed task to a second friendly path, or touch unowned notes/settings.
            original = '사람이 직접 고친 portable 문서와 API_NAME 원문\n'
            current.write_text(original)
            update_code = '''from pathlib import Path
import json
from loop_work.knowledge import KnowledgeBase
kb=KnowledgeBase(Path('selected-data'),vault_home=Path('selected-vault'))
task=kb.get('task','portable-task')
kb.put('task',{**task,'title':'바뀐 표시 제목'})
print(json.dumps(kb.vault_status()))
'''
            updated = subprocess.run([sys.executable, '-B', '-c', update_code], cwd=base, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertTrue(json.loads(updated.stdout)['errors'])
            self.assertEqual(current.read_text(), original)
            self.assertEqual(list(selected_vault.rglob('진행 현황.md')), [current])
            updated_manifest = json.loads(manifest_path.read_text())
            self.assertEqual(updated_manifest['paths']['task:project-one:portable-task'], expected)
            self.assertEqual(preserved, {path:(path.read_bytes(), path.stat().st_ino, path.stat().st_mode) for path in preserved})
            self.assertFalse((fake_home / '.loop-work').exists())
