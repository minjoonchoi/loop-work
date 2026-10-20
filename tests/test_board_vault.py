"""Generated Markdown carries board data without becoming execution authority."""
from pathlib import Path
import json
import tempfile
import unittest

from loop_work.knowledge import KnowledgeBase
from loop_work.storage import file_hash, read_json


def metadata(path):
    lines = path.read_text().splitlines()
    if len(lines) < 3 or lines[0] != '---' or not lines[1].startswith('loop_work: ') or lines[2] != '---':
        raise AssertionError('Expected a single JSON value inside YAML frontmatter')
    return json.loads(lines[1].split(': ', 1)[1]), '\n'.join(lines[3:])


class BoardVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.kb = KnowledgeBase(self.base / 'data', vault_home=self.base / 'vault')
        self.task = {'id': 'task-one', 'title': 'A readable task', 'kind': 'document', 'phase': 'working',
                     'session_id': 'session-one', 'project_ids': ['project-one'],
                     'goal': {'outcome': 'Explain current behavior'}, 'result': None}
        self.folder = self.base / 'vault'

    def document(self, role, identifier='task-one'):
        manifest=read_json(self.kb.home/'vault-owned.json')
        name=next(name for name,entry in manifest['documents'].items() if entry['role']==role and entry['id']==identifier)
        return self.base/'vault'/name

    def test_task_metadata_precedes_cutoff_and_matches_exact_committed_record(self):
        self.kb.put('task', self.task)
        current = self.document('current')
        envelope, body = metadata(current)
        self.assertEqual(envelope, {'version': 2, 'kind': 'task', 'id': 'task-one', 'role':'current','project_id':'project-one','task_id':'task-one',
                                    'knowledge_home': str(self.kb.home), 'record': self.kb.get('task', 'task-one')})
        self.assertIn('최종 내보내기 기준', body)
        self.assertIn('A readable task', body)
        self.assertIn('승인이나 품질 검증 통과를 부여하지 않습니다', body)
        manifest = read_json(self.kb.home / 'vault-owned.json')
        relative = current.relative_to(self.base / 'vault').as_posix()
        self.assertEqual(manifest['files'][relative], file_hash(current))
        self.assertFalse(any(entry['role']=='final' for entry in manifest['documents'].values()))

    def test_request_frontmatter_preserves_original_text_and_escaped_newlines(self):
        self.kb.put('task', self.task)
        request = {'id': 'request-one', 'task_id': 'task-one', 'session_id': 'session-one', 'kind': 'approval',
                   'title': 'Explicit approval', 'question': 'Original question\n---\n<script>unsafe()</script>',
                   'options': [], 'action': 'resume_task', 'status': 'answered', 'revision': 2,
                   'response': {'decision': 'approve', 'text': 'User original response\nKeep its scope'},
                   'execution': None, 'history': []}
        with self.kb.connection() as db:
            self.kb.put('human-request', request, db)
        path = self.document('human-request','request-one')
        envelope, body = metadata(path)
        self.assertEqual(envelope['kind'], 'human-request')
        self.assertEqual(envelope['record'], request)
        self.assertEqual(envelope['knowledge_home'], str(self.kb.home))
        self.assertIn('승인·완료 권한을 부여하지 않습니다', body)
        self.assertEqual(len(path.read_text().splitlines()[1:2]), 1)
        self.assertNotIn('\n<script>', path.read_text().splitlines()[1])
        self.assertEqual(request['execution'], None)

    def test_user_edited_metadata_and_body_are_preserved_and_reported(self):
        self.kb.put('task', self.task)
        path = self.document('current')
        original = path.read_text()
        changed = original.replace('A readable task', 'My Obsidian note')
        path.write_text(changed)
        self.kb.put('task', {**self.task, 'title': 'New database title'})
        self.assertEqual(path.read_text(), changed)
        self.assertTrue(self.kb.vault_status()['errors'])
        self.assertEqual(self.kb.get('task', 'task-one')['title'], 'New database title')

    def test_board_reads_actual_generated_and_obsidian_modified_documents(self):
        from loop_work.board import Board
        self.kb.put('task', self.task)
        board = Board(self.kb)
        row = board.list(include_closed=True)['tasks'][0]
        self.assertEqual(row['record'], self.task)
        self.assertTrue(row['fresh']); self.assertTrue(row['writable'])
        self.assertEqual(row['revision'], row['vault_revision'])
        historical = [item for item in row['documents'] if '/interim/' in item['path']]
        self.assertTrue(historical)
        history = board.document(historical[0]['path'])
        self.assertFalse(history['writable'])
        self.assertIn('원본', history['body'])
        path = self.document('current')
        path.write_text(path.read_text() + '\nObsidian user body marker <script>literal</script>\n')
        changed = board.show('task-one', 'task')
        self.assertIn('Obsidian user body marker <script>literal</script>', changed['body'])
        self.assertTrue(changed['modified'])
        self.assertFalse(changed['writable'])
        self.assertTrue(changed['fresh'])  # raw record still matches; body pin does not

    def test_unrelated_malformed_markdown_does_not_block_runtime_export(self):
        notes = self.base / 'vault/notes'; notes.mkdir(parents=True)
        malformed = notes / 'personal.md'; malformed.write_text('---\nloop_work: [invalid YAML\nMy own note')
        self.kb.put('task', self.task)
        self.assertEqual(self.kb.vault_status()['errors'], [])
        self.assertEqual(malformed.read_text(), '---\nloop_work: [invalid YAML\nMy own note')
        self.assertEqual(metadata(self.document('current'))[0]['record']['phase'], 'working')
