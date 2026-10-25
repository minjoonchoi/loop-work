"""Korean authoring reaches the real worker prompt without rewriting literals."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_delegation as fixtures
from loop_work.storage import read_json

SOURCE = Path(__file__).resolve().parents[1]


class VaultLanguagePolicyTests(unittest.TestCase):
    def test_common_worker_prompt_preserves_foreign_artifact_and_original_literals(self):
        fixture = fixtures.DelegationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        request = fixtures.assignment('language-policy-probe')
        original = 'Write the requested artifact in English. Preserve `print("hello")`, API_NAME and the quoted original "expired".'
        request['instruction'] = original
        finding = {'summary': 'Literal English evidence remains original.', 'evidence': ['value.py:1'], 'paths': ['value.py']}
        with patch.dict(os.environ, {'LOOP_WORKER_FINDINGS': json.dumps([finding])}):
            result = fixture.engine.delegate(request)
        self.assertEqual(result['assignment']['status'], 'candidate')
        directory = Path(result['assignment']['directory'])
        prompt = (directory / 'prompt.txt').read_text()
        packet = json.loads(prompt.split('WORKER DATA:\n', 1)[1])
        self.assertEqual(packet['assignment']['instruction'], original)
        self.assertIn('knowledge summary/why/details/uncertainty in Korean', prompt)
        self.assertIn('foreign-language deliverable stays in that language', prompt)
        self.assertIn('Never translate or alter original user input', prompt)
        # Language policy does not become a validator rejecting literal English.
        candidate = read_json(Path(result['assignment']['result']))
        self.assertEqual(candidate['findings'], [finding])
        self.assertEqual(candidate['summary'], 'The assigned work has evidence and deliverables.')
        self.assertEqual((fixture.root / 'value.py').read_text(), 'VALUE = 1\n')

    def test_shared_policy_preserves_evidence_and_existing_ownership(self):
        policy = (SOURCE / 'rules/writing.md').read_text()
        for text in ('Write authored task titles', 'in Korean', 'foreign-language deliverable',
                     'Hangul-character validator', 'do not overwrite edited or unowned',
                     'It cannot restore execution authority around an edited or missing document'):
            self.assertIn(text, policy)
        self.assertIn('Korean', (SOURCE / 'rules/work.md').read_text())
        self.assertIn('Korean', (SOURCE / 'skills/loop-work/SKILL.md').read_text())

    def test_every_supported_task_kind_has_a_korean_display_without_changing_raw_enums(self):
        from copy import deepcopy
        from loop_work.work import KINDS
        from loop_work.writing import task_document
        expected = {'development': '개발', 'document': '문서', 'explanation': '설명',
                    'research': '조사', 'review': '검토', 'planning': '계획'}
        self.assertEqual(set(expected), set(KINDS))
        for kind in KINDS:
            with self.subTest(kind=kind):
                task = {'id': 'kind-display-probe', 'title': '원문 explanation API_NAME',
                        'kind': kind, 'phase': 'goal_setting', 'execution_phase': 'draft',
                        'goal': None, 'result': None}
                original = deepcopy(task)
                korean = task_document(task, language='ko')
                self.assertIn('**작업 진행:** ' + expected[kind] + ' · 초안', korean)
                self.assertIn('원문 explanation API', korean)
                self.assertEqual(task, original)
                english = task_document(task)
                self.assertEqual(english, task_document(task, language='en'))
                self.assertIn('**Kind:** ' + kind, english)
                self.assertNotIn('**작업 진행:**', english)
