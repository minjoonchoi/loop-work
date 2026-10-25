"""Memory-only writes preserve execution authority; isolated KB/vault fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from loop_work.board import Board
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import digest
from loop_work.work import Work


class MemoryCaptureTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve();self.root=self.base/'인증 프로젝트';self.root.mkdir()
        (self.root/'README.md').write_text('권한 검사 원문\n')
        self.vault=self.base/'vault';self.kb=KnowledgeBase(self.base/'kb',vault_home=self.vault)
        self.location=self.kb.attach(self.root)

    def protected(self):
        # These exact durable records carry task/session/control/budget state.
        kinds=('task','session','feedback','board-control','human-request','delegation','team')
        return {kind:copy.deepcopy(self.kb.list(kind)) for kind in kinds}

    def remember(self,identifier='ordinary-project-decision',session=None):
        entry={'id':identifier,'scope':'project','kind':'decision','status':'confirmed',
               'summary':'사용자는 권한 설명에 허용·거절 근거를 함께 원한다.',
               'evidence':['conversation:fixture-user-message-1'],'basis':'user','applies_to':'이 프로젝트의 권한 설명',
               'paths':[]}
        observed=digest(self.kb.observe([self.location]))
        return self.kb.remember(entry,[self.location],observed,session_id=session)

    def test_ordinary_memory_creates_korean_topic_without_task_session_or_activation(self):
        before=self.protected();topic=self.remember()
        self.assertEqual(self.protected(),before)
        self.assertIsNone(topic['source_task_id']);self.assertIsNone(topic['source_session_id'])
        self.assertEqual(topic['evidence'],['conversation:fixture-user-message-1'])
        self.assertEqual(topic['basis'],'user');self.assertEqual(topic['applies_to'],'이 프로젝트의 권한 설명')
        docs=[p for p in self.vault.rglob('*.md') if '사용자는 권한 설명에' in p.read_text()]
        self.assertTrue(docs);self.assertTrue(any('지식' in p.read_text() for p in docs))
        self.assertEqual(Board(self.kb).list()['tasks'],[])
        self.assertFalse((self.root/'.loop').exists())

    def test_later_explicit_task_selects_memory_without_reowning_or_authorizing_it(self):
        topic=self.remember();before=json.dumps(topic,ensure_ascii=False,sort_keys=True).encode()
        task=Work(self.kb).open('explanation','권한 근거 설명','codex',[self.root],explicit_skill=True)['task']
        context=self.kb.context([self.location],task['session_id'],task['id'],query=topic['id'])
        self.assertEqual([item['id'] for item in context['reusable']],[topic['id']])
        self.assertEqual(json.dumps(self.kb.get('topic',topic['id']),ensure_ascii=False,sort_keys=True).encode(),before)
        self.assertEqual(task['phase'],'goal_setting');self.assertIsNone(task['result'])
        from loop_work.harness import Harness
        from loop_work.orchestration import Orchestration
        Harness(self.kb).on('codex',task['session_id'],task['id'])
        Orchestration(self.kb).feedback(task['session_id'],{'id':'fixture-pause','task_id':task['id'],'kind':'pause',
            'summary':'기억 저장 동안 기존 작업 중지 유지','original_input_ref':'conversation:fixture-user-pause',
            'applies_to':'이 작업','supersedes':[]},0)
        before_state=self.protected();second=self.remember('ordinary-followup',task['session_id'])
        self.assertEqual(self.protected(),before_state)
        self.assertEqual(second['source_session_id'],task['session_id']);self.assertIsNone(second['source_task_id'])
        other=self.base/'다른 프로젝트';other.mkdir();(other/'README.md').write_text('다른 원문')
        other_location=self.kb.attach(other)
        foreign=self.kb.context([other_location],query=topic['id'])
        self.assertEqual(foreign['reusable'],[])
        self.assertEqual(self.kb.get('topic',topic['id'])['basis'],'user')

    def test_draft_memory_stays_unconfirmed_without_authority_or_new_work(self):
        entry={'id':'ordinary-uncertain','scope':'project','kind':'finding','status':'draft',
               'summary':'원인 후보는 아직 확인하지 않았다.','evidence':[],'paths':[]}
        before=self.protected()
        topic=self.kb.remember(entry,[self.location],digest(self.kb.observe([self.location])))
        context=self.kb.context([self.location],query=topic['id'])
        self.assertEqual(context['reusable'],[])
        self.assertEqual([item['id'] for item in context['unconfirmed']],[topic['id']])
        self.assertEqual(self.kb.get('topic',topic['id'])['status'],'draft')
        self.assertIsNone(topic['source_task_id']);self.assertEqual(self.protected(),before)
