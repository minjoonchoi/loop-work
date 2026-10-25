import json
from pathlib import Path
import unittest

import test_board_wiki
from loop_work.vault_layout import id_suffix
from loop_work.human import HumanDesk
from loop_work.storage import LoopError, read_json, write_json, file_hash


class BoardProjectTests(unittest.TestCase):
    def setUp(self):
        test_board_wiki.setup(self)
        other=self.base/'결제 프로젝트'; other.mkdir(); (other/'README.md').write_text('다른 프로젝트 원문')
        self.other=self.work.open('document','다른 프로젝트 비공개 내용','codex',[other],explicit_skill=True)['task']
        self.other_pid=self.other['project_ids'][0]

    def test_project_search_sort_and_display_name_from_vault(self):
        project=self.board.wiki('project',self.pid,self.pid)
        self.board.save_wiki('project',self.pid,test_board_wiki.payload(project,title='가나다 프로젝트'),self.pid)
        rows=self.board.projects()['projects']; self.assertEqual(len(rows),2)
        self.assertEqual([row['display_name'] for row in rows],sorted(row['display_name'] for row in rows))
        filtered=self.board.projects(query='가나다')['projects']; self.assertEqual([row['id'] for row in filtered],[self.pid])
        recent=self.board.projects(sort='updated')['projects']; self.assertEqual(recent[0]['id'],self.pid)
        selected=self.board.list(project_id=self.pid)
        self.assertEqual([row['id'] for row in selected['tasks']],[self.task['id']])
        self.assertNotIn(self.other['title'],json.dumps(selected,ensure_ascii=False))

    def test_abort_and_technical_block_have_distinct_labels_and_original_reasons(self):
        for task, phase, reason in ((self.task,'aborted','사용자 원문: 범위 폐기 / REF-1'),
                                    (self.other,'blocked','원문 오류: compiler exit 2 / log:17')):
            raw=self.kb.get('task',task['id']); raw.update(phase=phase,reason=reason); self.kb.put('task',raw)
        rows={row['id']:row for row in self.board.list()['tasks']}
        for task,label in ((self.task,'중단·폐기'),(self.other,'기술적 차단')):
            row=rows[task['id']]
            self.assertEqual(row['board_state'],'stopped')
            self.assertEqual(row['state_label'],label)
            self.assertEqual(row['state_reason'],self.kb.get('task',task['id'])['reason'])

    def test_recent_projects_include_scoped_task_wiki_web_and_external_edits(self):
        import os
        from datetime import datetime,timezone
        first=self.board.wiki('task',self.task['id'],self.pid)
        other=self.board.wiki('task',self.other['id'],self.other_pid)
        # Pin fixture mtimes to separate seconds; do not rely on filesystem clock precision.
        os.utime(self.vault/first['path'],(2100000000,2100000000))
        os.utime(self.vault/other['path'],(2100000010,2100000010))
        self.assertEqual(self.board.projects(sort='updated')['projects'][0]['id'],self.other_pid)
        saved=self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(self.board.wiki('task',self.task['id'],self.pid)),self.pid)
        os.utime(self.vault/saved['path'],(2100000020,2100000020))
        self.assertEqual(self.board.projects(sort='updated')['projects'][0]['id'],self.pid)
        path=self.vault/other['path']; path.write_text(path.read_text()+'\nObsidian 외부 편집 원문\n')
        os.utime(path,(2100000030,2100000030))
        rows=self.board.projects(sort='updated')['projects']
        self.assertEqual(rows[0]['id'],self.other_pid)
        self.assertEqual(rows[0]['updated_at'],datetime.fromtimestamp(2100000030,timezone.utc).isoformat())
        scoped=self.board.projects(sort='updated',project_id=self.pid)['projects']
        self.assertEqual([row['id'] for row in scoped],[self.pid])
        self.assertEqual(scoped[0]['updated_at'],datetime.fromtimestamp(2100000020,timezone.utc).isoformat())

    def test_foreign_project_show_history_wiki_save_control_and_approval_rejected(self):
        row=self.board.show(self.other['id'],'task',self.other_pid)
        request=HumanDesk(self.kb).create(self.other['id'],{'id':'foreign-request','kind':'approval','title':'외부 질문',
            'question':'다른 프로젝트 원문','options':[],'action':None})
        approval=self.board.show(request['id'],project_id=self.other_pid)
        wiki=self.board.wiki('task',self.other['id'],self.other_pid)
        for call in (lambda:self.board.show(self.other['id'],'task',self.pid),
                     lambda:self.board.document(row['path'],self.pid),
                     lambda:self.board.wiki('task',self.other['id'],self.pid),
                     lambda:self.board.wiki('project',self.other_pid,self.pid),
                     lambda:self.board.save_wiki('task',self.other['id'],test_board_wiki.payload(wiki),self.pid),
                     lambda:self.board.respond(request['id'],{'decision':'approve','text':'범위 밖'},1,approval['revision'],self.pid)):
            with self.assertRaises(LoopError): call()
        history=next(item['path'] for item in row['documents'] if item.get('role')=='interim')
        with self.assertRaises(LoopError): self.board.document(history,self.pid)
        control={'operation_id':'foreign-control','kind':'pause','text':'다른 범위 제어',
                 'expected_task_revision':row['control']['task_revision'],'expected_control_version':row['control']['control_version'],
                 'expected_vault_revision':row['vault_revision']}
        with self.assertRaises(LoopError): self.board.control(self.other['id'],control,self.pid)
        self.assertEqual(self.kb.get('human-request',request['id']),request)
        self.assertEqual(self.kb.list('feedback'),[])

    def test_multiple_project_task_filters_current_history_and_request_before_merge(self):
        other_location=self.kb.attach(self.base/'결제 프로젝트')
        task=self.kb.get('task',self.task['id']); task['project_ids']+= [self.other_pid]; task['locations']+=[other_location['id']]
        self.kb.put('task',task); self.kb.sync_vault()
        request=HumanDesk(self.kb).create(task['id'],{'id':'shared-question','kind':'decision','title':'공유 작업 질문','question':'공유 질문',
            'options':[],'action':None})
        first=self.board.show(task['id'],'task',self.pid)
        second=self.board.show(task['id'],'task',self.other_pid)
        self.assertNotEqual(first['path'],second['path'])
        self.assertTrue(all(id_suffix(self.pid) in item['path'] for item in first['documents']))
        self.assertTrue(all(id_suffix(self.other_pid) in item['path'] for item in second['documents']))
        self.assertEqual(len(first['requests']),1); self.assertEqual(first['requests'][0]['id'],request['id'])
        self.assertNotEqual(first['revision'],second['revision'])
        with self.assertRaises(LoopError): self.board.document(second['path'],self.pid)

    def test_review_precedence_completed_pause_pending_superseded_and_technical_stop(self):
        task=self.kb.get('task',self.task['id']); task.update(phase='completed',result={'evidence_current':True}); self.kb.put('task',task)
        row=self.board.show(task['id'],'task',self.pid); self.assertEqual(row['board_state'],'completed')
        request=HumanDesk(self.kb).create(task['id'],{'id':'review-needed','kind':'decision','title':'사용자 확인','question':'확인할까요?',
            'options':[],'action':None})
        row=self.board.show(task['id'],'task',self.pid)
        self.assertEqual(row['board_state'],'review'); self.assertTrue(row['historical_completed'])
        self.assertTrue(row['review_reasons'])
        replacement=HumanDesk(self.kb).create(task['id'],{'id':'review-replacement','kind':'decision','title':'새 확인','question':'새 질문',
            'options':[],'action':None,'supersedes':[request['id']]})
        HumanDesk(self.kb).respond(replacement['id'],{'decision':'answer','text':'질문을 확인했습니다.'},1)
        self.assertEqual(self.board.show(task['id'],'task',self.pid)['board_state'],'completed')
        task['result']['evidence_current']=False; self.kb.put('task',task)
        self.assertEqual(self.board.show(task['id'],'task',self.pid)['board_state'],'review')
        raw=self.kb.get('task',self.other['id']); raw.update(phase='blocked',reason='기술 환경 확인 필요'); self.kb.put('task',raw)
        self.assertEqual(self.board.show(raw['id'],'task',self.other_pid)['board_state'],'stopped')
        row=self.board.show(raw['id'],'task',self.other_pid)
        self.board.control(raw['id'],{'operation_id':'user-pause','kind':'pause','text':'사람이 확인하려고 멈춥니다.',
            'expected_task_revision':row['control']['task_revision'],'expected_control_version':row['control']['control_version'],
            'expected_vault_revision':row['vault_revision']},self.other_pid)
        self.assertEqual(self.board.show(raw['id'],'task',self.other_pid)['board_state'],'review')

    def test_unresolved_human_requests_remain_review_without_readable_current_markdown(self):
        from loop_work.board import Board
        for status in ('pending','declined','failed','answered'):
            for document in ('missing','stale'):
                with self.subTest(status=status,document=document):
                    fixture=unittest.TestCase(); test_board_wiki.setup(fixture)
                    try:
                        raw=fixture.kb.get('task',fixture.task['id']); raw['phase']='working'; fixture.kb.put('task',raw)
                        request=HumanDesk(fixture.kb).create(raw['id'],{'id':'hidden-human','kind':'approval','title':'비공개 원문 제목',
                            'question':'DB 원문을 문서 대신 노출하면 안 됩니다','options':[],'action':'resume_task'})
                        request.update(status=status,response=None if status=='pending' else {'decision':'reject' if status=='declined' else 'approve','text':'원문 응답'},execution=None)
                        fixture.kb.put('human-request',request)
                        row=fixture.board.show(request['id'],project_id=fixture.pid)
                        path=fixture.vault/row['path']
                        if document=='missing': path.unlink()
                        else:
                            lines=path.read_text().split('\n',3)
                            meta=json.loads(lines[1][len('loop_work: '):]);meta['record']['question']='문서에만 있는 다른 질문'
                            path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+lines[3])
                        before=fixture.kb.get('human-request',request['id'])
                        result=fixture.board.list(project_id=fixture.pid,include_closed=True)
                        task=next(item for item in result['tasks'] if item['id']==raw['id'])
                        self.assertEqual(task['board_state'],'review')
                        self.assertTrue(task['control']['needs_human'])
                        self.assertEqual(fixture.kb.get('human-request',request['id']),before)
                        self.assertTrue(result['warnings'] or task['warnings'] or any(not item['fresh'] for item in result['requests']))
                        if document=='missing':
                            self.assertEqual(result['warnings'],['일부 문서를 읽을 수 없거나 확인할 수 없습니다.'])
                            self.assertNotIn(row['path'],json.dumps(result['warnings'],ensure_ascii=False))
                            self.assertEqual(result['requests'],[])
                            self.assertNotIn(request['question'],json.dumps(result,ensure_ascii=False))
                        else:
                            self.assertTrue(all('Some vault' not in warning for warning in result['warnings']))
                            self.assertEqual(fixture.kb.get('human-request',request['id'])['question'],request['question'])
                    finally: fixture.doCleanups()

    def test_scoped_actions_reject_modified_or_deleted_other_shared_replica(self):
        for action in ('control','respond','execute'):
            for document in ('task','human-request') if action!='control' else ('task',):
                for damage in (('modified','deleted','unchanged','before-claim') if action!='control' else ('modified','deleted','unchanged')):
                    with self.subTest(action=action,document=document,damage=damage):
                        fixture=unittest.TestCase();test_board_wiki.setup(fixture)
                        try:
                            other=fixture.base/'다른 범위 비공개';other.mkdir();(other/'README.md').write_text('비공개 원문')
                            location=fixture.kb.attach(other);other_pid=location['project_id']
                            task=fixture.kb.get('task',fixture.task['id']);task['project_ids'].append(other_pid);task['locations'].append(location['id'])
                            task.update(phase='blocked',previous_phase='goal_setting',reason='재개 대기 원문');fixture.kb.put('task',task)
                            request=HumanDesk(fixture.kb).create(task['id'],{'id':'shared-approval','kind':'approval','title':'재개 승인',
                                'question':'원래 범위로 재개할까요?','options':[],'action':'resume_task'})
                            if action=='execute':
                                HumanDesk(fixture.kb).respond(request['id'],{'decision':'approve','text':'재개 승인 원문'},1)
                            current=fixture.board.show(task['id'],'task',fixture.pid)
                            approval=fixture.board.show(request['id'],project_id=fixture.pid)
                            foreign=fixture.board.show(task['id'],'task',other_pid) if document=='task' else fixture.board.show(request['id'],project_id=other_pid)
                            path=fixture.vault/foreign['path']
                            if damage=='deleted':path.unlink()
                            elif damage=='modified':path.write_text(path.read_text()+'\n다른 프로젝트 비공개 편집\n')
                            scoped=fixture.board.list(project_id=fixture.pid,include_closed=True)
                            self.assertTrue(all(id_suffix(other_pid) not in item['path'] for row in scoped['tasks'] for item in row['documents']))
                            self.assertNotIn('다른 프로젝트 비공개 편집',json.dumps(scoped,ensure_ascii=False))
                            self.assertNotIn(foreign['path'],json.dumps(scoped,ensure_ascii=False))
                            with fixture.kb.connection() as db:
                                before=list(db.execute('SELECT kind,id,body FROM records ORDER BY kind,id'));history=list(db.execute('SELECT * FROM history ORDER BY sequence'))
                            if damage=='before-claim':
                                original_guard=fixture.board._guard;damaged=[False]
                                def interleaving_guard(*args,**kwargs):
                                    value=original_guard(*args,**kwargs)
                                    if not damaged[0]:
                                        path.write_text(path.read_text()+'\n원자 claim 직전 다른 사본 변경\n');damaged[0]=True
                                    return value
                                fixture.board._guard=interleaving_guard
                            def invoke():
                                if action=='control':
                                    return fixture.board.control(task['id'],{'operation_id':'shared-pause','kind':'pause','text':'일시정지 원문',
                                        'expected_task_revision':current['control']['task_revision'],'expected_control_version':current['control']['control_version'],
                                        'expected_vault_revision':current['vault_revision']},fixture.pid)
                                if action=='respond':return fixture.board.respond(request['id'],{'decision':'approve','text':'승인'},1,approval['revision'],fixture.pid)
                                return fixture.board.execute(request['id'],2,approval['revision'],fixture.pid)
                            if damage=='unchanged':
                                self.assertTrue(invoke()['action_committed'])
                                if action=='execute':self.assertEqual(fixture.kb.get('task',task['id'])['phase'],'goal_setting')
                                continue
                            with self.assertRaises(LoopError) as error:invoke()
                            self.assertNotIn(foreign['path'],str(error.exception))
                            with fixture.kb.connection() as db:
                                self.assertEqual(list(db.execute('SELECT kind,id,body FROM records ORDER BY kind,id')),before)
                                self.assertEqual(list(db.execute('SELECT * FROM history ORDER BY sequence')),history)
                            self.assertEqual(path.exists(),damage!='deleted')
                        finally:fixture.doCleanups()

    def test_completed_source_observation_drift_is_review_without_runtime_mutation(self):
        from loop_work.storage import digest
        from loop_work.orchestration import worker_context
        task=self.kb.get('task',self.task['id'])
        locations=[self.kb.get('location',key) for key in task['locations']]
        task.update(phase='completed',result={'feedback_revision':worker_context(self.kb,task['id'])['revision']},
                    completion_observation=digest(self.kb.observe(locations)))
        self.kb.put('task',task)
        self.assertEqual(self.board.show(task['id'],'task',self.pid)['board_state'],'completed')
        (self.project/'README.md').write_text('완료 이후 변경된 소스 원문')
        self.assertEqual(self.board.show(task['id'],'task',self.pid)['board_state'],'review')
        self.assertEqual(self.kb.get('task',task['id']),task)

    def test_historical_completed_without_positive_evidence_stays_in_review(self):
        task=self.kb.get('task',self.task['id']); task.update(phase='completed',result={})
        self.kb.put('task',task)
        row=self.board.show(task['id'],'task',self.pid)
        self.assertEqual(row['board_state'],'review')
        self.assertIn('완료 근거가 없거나',row['review_reasons'][0])
        self.assertTrue(row['historical_completed'])
        self.assertEqual(self.kb.get('task',task['id']),task)


import support


class DevelopmentCompletionBoardTests(support.ProjectTest):
    def setUp(self):
        from loop_work.engine import Engine
        from unittest.mock import patch
        original=Engine.initialize
        def explicit(instance,*args,**kwargs):
            return original(instance,*args,**kwargs,explicit_skill=True)
        with patch.object(Engine,'initialize',explicit):
            super().setUp()

    def test_frozen_engine_and_ignored_rule_drift_require_review_without_mutation(self):
        from unittest.mock import patch
        from loop_work.knowledge import KnowledgeBase
        from loop_work.board import Board
        from loop_work.storage import snapshot
        rule=self.root/'.loop/state/frozen-rule.md';rule.parent.mkdir(parents=True,exist_ok=True);rule.write_text('동결 규칙 원문')
        contract=read_json(self.engine.goal_dir/'contract.json');contract['rules'].append('.loop/state/frozen-rule.md');write_json(self.engine.goal_dir/'contract.json',contract)
        kb=KnowledgeBase(self.engine.knowledge.home,vault_home=Path(self.temp.name).resolve()/'vault');self.engine.knowledge=kb
        self.running();self.assertTrue(self.engine.gate('M1')['passed']);self.assertTrue(self.engine.gate()['passed'])
        task_id=self.engine.refresh()['work_id'];kb.sync_vault();board=Board(kb)
        before=kb.get('task',task_id);state=self.engine.state_path.read_bytes();target=snapshot(self.root)['digest']
        self.assertEqual(board.show(task_id,'task')['board_state'],'completed')
        with patch('loop_work.engine.engine_digest',return_value='different-current-harness'):
            self.assertEqual(board.show(task_id,'task')['board_state'],'review')
        rule.write_text('동결 이후 규칙 변경')
        self.assertEqual(snapshot(self.root)['digest'],target)
        self.assertEqual(board.show(task_id,'task')['board_state'],'review')
        self.assertEqual(self.engine.state_path.read_bytes(),state);self.assertEqual(kb.get('task',task_id),before)


    def test_final_gate_currentness_without_engine_refresh_or_record_mutation(self):
        from loop_work.knowledge import KnowledgeBase
        from loop_work.board import Board
        from loop_work.storage import snapshot
        kb=KnowledgeBase(self.engine.knowledge.home,vault_home=Path(self.temp.name).resolve()/'vault')
        self.engine.knowledge=kb
        self.running()
        self.assertTrue(self.engine.gate('M1')['passed'])
        self.assertTrue(self.engine.gate()['passed'])
        task_id=self.engine.refresh()['work_id']; kb.sync_vault()
        board=Board(kb); original=kb.get('task',task_id)
        before=json.dumps(original,sort_keys=True).encode()
        gate=Path(original['result']['gate']); gate_bytes=gate.read_bytes()
        source=self.root/'value.py'; source_bytes=source.read_bytes()
        def view():
            return board.show(task_id,'task')
        self.assertEqual(view()['board_state'],'completed')
        source.write_text('VALUE = 999\n')
        self.assertNotEqual(snapshot(self.root)['digest'],json.loads(gate_bytes)['snapshot'])
        self.assertEqual(view()['board_state'],'review')
        self.assertTrue(view()['historical_completed'])
        source.write_bytes(source_bytes)
        gate.unlink()
        self.assertEqual(view()['board_state'],'review')
        outside=Path(self.temp.name)/'outside-gate.json'; outside.write_bytes(gate_bytes)
        gate.symlink_to(outside)
        self.assertEqual(view()['board_state'],'review')
        gate.unlink(); gate.write_bytes(gate_bytes)
        self.assertEqual(view()['board_state'],'completed')
        self.assertEqual(json.dumps(kb.get('task',task_id),sort_keys=True).encode(),before)
        self.assertEqual(gate.read_bytes(),gate_bytes)
        for invalid in (b'null',b'[]',b'{}',b'['*2000+b']'*2000):
            gate.write_bytes(invalid)
            self.assertEqual(view()['board_state'],'review')
        gate.write_bytes(gate_bytes)
        stale=kb.get('task',task_id); stale['result']['evidence_current']=False; kb.put('task',stale)
        self.assertEqual(view()['board_state'],'review')
        self.assertFalse(view()['control']['completion_current'])
