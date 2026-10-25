"""Explicit migration pins sources/payload and preserves original user bytes."""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError,file_hash,write_json
from loop_work.vault_migrate import plan,apply
from unittest.mock import patch


class VaultMigrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name).resolve();self.vault=self.base/'vault';self.vault.mkdir()
        self.kb=KnowledgeBase(self.base/'kb',vault_home=False)
        self.kb.put('project',{'id':'p','name':'인증 서비스'})
        self.task={'id':'t','title':'인증 오류 수정','kind':'document','phase':'working','session_id':'s','project_ids':['p'],
                   'goal':{'outcome':'정확한 원인 설명'},'result':None,'updated_at':'2026-10-25T00:00:00Z'}
        self.kb.put('task',self.task)
        self.old='projects/인증 서비스--p/tasks/인증 오류 수정--t/현재-인증 오류 수정--t.md'
        target=self.vault/self.old;target.parent.mkdir(parents=True)
        meta={'version':2,'kind':'task','id':'t','role':'current','project_id':'p','task_id':'t','knowledge_home':str(self.kb.home),'record':self.task}
        target.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n이전 원문을 보존합니다.\n')
        self.original=target.read_bytes()
        self.manifest={'version':1,'layout_version':2,'vault':str(self.vault),'files':{self.old:file_hash(target)},
                       'paths':{'project:p':'projects/인증 서비스--p','task:p:t':self.old},'documents':{self.old:{'kind':'task','id':'t','role':'current','project_id':'p','task_id':'t'}}}
        write_json(self.kb.home/'vault-owned.json',self.manifest)
        self.note=self.vault/'notes/사용자 메모.md';self.note.parent.mkdir();self.note.write_text('개인 원문')
        self.settings=self.vault/'.obsidian/app.json';self.settings.parent.mkdir();self.settings.write_text('{"user":true}')
        self.output=self.base/'plan.json'

    def test_plan_and_apply_archive_raw_originals_without_database_changes(self):
        db=self.kb.path.read_bytes();source=(self.kb.home/'vault-owned.json').read_bytes()
        planned=plan(self.kb.home,self.vault,self.output)
        self.assertEqual((self.vault/self.old).read_bytes(),self.original)
        self.assertEqual(self.kb.path.read_bytes(),db)
        result=apply(self.output,planned['sha256'])
        self.assertEqual(result['status'],'applied');self.assertFalse((self.vault/self.old).exists())
        self.assertEqual(self.kb.path.read_bytes(),db);self.assertEqual(self.kb.get('task','t'),self.task)
        backup=Path(result['backup']);self.assertEqual((backup/'vault-owned.json').read_bytes(),source)
        self.assertEqual((backup/'original-files'/self.old).read_bytes(),self.original)
        fresh=json.loads((self.kb.home/'vault-owned.json').read_text());self.assertEqual(fresh['layout_version'],3)
        current=fresh['paths']['task:p:t'];meta=json.loads((self.vault/current).read_text().splitlines()[1][11:])
        self.assertEqual(meta['record'],self.task);self.assertEqual(meta['knowledge_home'],str(self.kb.home))
        self.assertEqual(self.note.read_text(),'개인 원문');self.assertEqual(self.settings.read_text(),'{"user":true}')

    def test_edited_missing_reserved_and_unowned_destination_block_replacement_authority(self):
        for change in ('edited','missing','reserved','destination'):
            with self.subTest(change=change):
                original=(self.vault/self.old).read_bytes();manifest=deepcopy(self.manifest)
                if change=='edited':(self.vault/self.old).write_text('사용자 수정')
                elif change=='missing':(self.vault/self.old).unlink()
                elif change=='reserved':manifest['reservations']={'missing.md':'preserved absence'}
                else:
                    from loop_work.vault_layout import slug
                    dest=self.vault/'프로젝트'/slug('인증 서비스','p')/'작업'/slug(self.task['title'],'t')/'진행 현황.md'
                    dest.parent.mkdir(parents=True);dest.write_text('소유하지 않은 문서')
                write_json(self.kb.home/'vault-owned.json',manifest)
                with self.assertRaises((LoopError,OSError)):plan(self.kb.home,self.vault,self.base/(change+'.json'))
                self.assertEqual(json.loads((self.kb.home/'vault-owned.json').read_text())['layout_version'],2)
                (self.vault/self.old).write_bytes(original);write_json(self.kb.home/'vault-owned.json',self.manifest)

    def test_changed_source_plan_or_payload_refuses_apply_before_mutation(self):
        planned=plan(self.kb.home,self.vault,self.output)
        with self.assertRaisesRegex(LoopError,'plan hash'):apply(self.output,'0'*64)
        value=json.loads(self.output.read_text());name=next(iter(value['target_files']))
        payload=Path(value['payload'])/name;payload.write_text('바뀐 payload')
        with self.assertRaisesRegex(LoopError,'payload changed'):apply(self.output,planned['sha256'])
        self.assertEqual((self.vault/self.old).read_bytes(),self.original)
        self.assertFalse(self.output.with_suffix('.json.backup').exists())

    def test_database_steering_after_plan_requires_fresh_plan(self):
        planned=plan(self.kb.home,self.vault,self.output)
        self.kb.put('task',{**self.task,'title':'사용자가 변경한 새 작업명'})
        with self.assertRaisesRegex(LoopError,'Source changed'):apply(self.output,planned['sha256'])
        self.assertEqual((self.vault/self.old).read_bytes(),self.original)

    def test_source_symlink_is_rejected_and_target_not_followed(self):
        target=self.vault/self.old;target.unlink();outside=self.base/'outside.md';outside.write_bytes(self.original);target.symlink_to(outside)
        with self.assertRaises((LoopError,OSError)):plan(self.kb.home,self.vault,self.output)
        self.assertEqual(outside.read_bytes(),self.original)

    def test_human_wiki_prose_and_generated_source_link_survive_reorganization(self):
        from loop_work.wiki import encode
        from urllib.parse import quote
        name='projects/인증 서비스--p/tasks/인증 오류 수정--t/작업-위키--t.md'
        entry={'kind':'task','id':'t','project_id':'p','task_id':'t','path':name,'owned':True}
        prose='사람이 직접 쓴 중요한 문장을 보존합니다.\n\n- [실행 원본 기록](<'+quote(Path(self.old).name)+'>)\n'
        original=encode({'version':1,'kind':'task','id':'t','project_id':'p','task_id':'t','title':'사람이 고친 제목'},prose).encode()
        (self.vault/name).write_bytes(original)
        self.manifest['wiki_documents']={'task:p:t':entry};write_json(self.kb.home/'vault-owned.json',self.manifest)
        planned=plan(self.kb.home,self.vault,self.output);result=apply(self.output,planned['sha256'])
        manifest=json.loads((self.kb.home/'vault-owned.json').read_text())
        target=self.vault/manifest['wiki_documents']['task:p:t']['path'];text=target.read_text()
        self.assertIn('사람이 고친 제목',text);self.assertIn('사람이 직접 쓴 중요한 문장을 보존합니다.',text)
        self.assertIn(quote('진행 현황.md'),text);self.assertNotIn('<'+quote(Path(self.old).name)+'>',text)
        self.assertEqual((Path(result['backup'])/'original-files'/name).read_bytes(),original)
        self.assertFalse((self.vault/name).exists())

    def test_failed_publication_keeps_original_inventory_database_and_audit(self):
        planned=plan(self.kb.home,self.vault,self.output)
        before=(self.kb.home/'vault-owned.json').read_bytes();db=self.kb.path.read_bytes()
        import loop_work.vault_migrate as module
        actual=module._write
        def reject_one(path,content,expected):
            if Path(path).name=='진행 현황.md':
                raise OSError('fixture publication failure')
            return actual(path,content,expected)
        with patch.object(module,'_write',side_effect=reject_one):
            with self.assertRaises(OSError):apply(self.output,planned['sha256'])
        self.assertEqual((self.kb.home/'vault-owned.json').read_bytes(),before)
        self.assertEqual((self.vault/self.old).read_bytes(),self.original)
        self.assertEqual(self.kb.path.read_bytes(),db)
        backup=self.output.with_suffix('.json.backup')
        self.assertEqual(json.loads((backup/'receipt.json').read_text())['status'],'failed')
        self.assertEqual((backup/'original-files'/self.old).read_bytes(),self.original)

    def test_unowned_old_current_cannot_be_bypassed_by_new_layout(self):
        changed=deepcopy(self.manifest);changed['files']={}
        write_json(self.kb.home/'vault-owned.json',changed)
        with self.assertRaisesRegex(LoopError,'replacement authority'):
            plan(self.kb.home,self.vault,self.output)
        changed['paths']={};changed['documents']={};write_json(self.kb.home/'vault-owned.json',changed)
        with self.assertRaisesRegex(LoopError,'Unowned previous execution'):
            plan(self.kb.home,self.vault,self.output)
        self.assertEqual((self.vault/self.old).read_bytes(),self.original)

    @staticmethod
    def _archive_patch(module, callback):
        if hasattr(module,'_move_exclusive'):
            return patch.object(module,'_move_exclusive',side_effect=callback)
        return patch.object(module.os,'rename',side_effect=callback)

    def _explicit_decision_fixture(self, suffix, answered=False, include_request=True):
        from loop_work.work import Work
        from loop_work.human import HumanDesk
        base=self.base/suffix;base.mkdir();project=base/'실제 프로젝트';project.mkdir()
        (project/'README.md').write_text('승인 근거 원문\n')
        vault=base/'vault';vault.mkdir();kb=KnowledgeBase(base/'kb',vault_home=False)
        work=Work(kb);task=work.open('document','실제로 제어할 명시 작업','codex',[project],explicit_skill=True)['task']
        work._stop_internal(task['id'],'사용자의 결정을 기다립니다.')
        task=kb.get('task',task['id']);desk=HumanDesk(kb)
        request=None
        if include_request:
            request=desk.create(task['id'],{'id':'approval-one','kind':'approval','title':'실제 재개 승인',
                                'question':'이 작업을 재개할까요?','options':[],'action':'resume_task'})
            if answered:
                request=desk.respond(request['id'],{'decision':'approve','text':'현재 원문만 승인합니다.'},request['revision'])
        pid=task['project_ids'][0];project_base='projects/실제 프로젝트--'+pid
        prefix=project_base+'/tasks/실제로 제어할 명시 작업--'+task['id']+'/'
        current=prefix+'현재-실제로 제어할 명시 작업--'+task['id']+'.md'
        request_name=prefix+'records/human-request/실제 재개 승인--'+request['id']+'.md' if request else None
        manifest={'version':1,'layout_version':2,'vault':str(vault),'files':{},'paths':{'project:'+pid:project_base,
                  'task:'+pid+':'+task['id']:current},'documents':{}}
        if request:
            manifest['paths']['human-request:'+pid+':'+request['id']]=request_name
        entries=[(current,'task','current',task)]
        if request:
            entries.append((request_name,'human-request','human-request',request))
        for name,kind,role,record in entries:
            path=vault/name;path.parent.mkdir(parents=True,exist_ok=True)
            descriptor={'kind':kind,'id':record['id'],'role':role,'project_id':pid,'task_id':task['id']}
            meta={'version':2,'knowledge_home':str(kb.home),'record':record,**descriptor}
            path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n기존 실행 원문\n')
            manifest['files'][name]=file_hash(path);manifest['documents'][name]=descriptor
        write_json(kb.home/'vault-owned.json',manifest)
        output=base/'plan.json';planned=plan(kb.home,vault,output)
        return {'kb':kb,'vault':vault,'task':task,'request':request,'manifest':manifest,'current':current,
                'request_path':request_name,'output':output,'planned':planned}

    def _board_action(self, fixture, action):
        from loop_work.board import Board
        from loop_work.storage import digest
        board=Board(fixture['kb'],fixture['vault']);task=fixture['task'];request=fixture['request']
        if action=='control':
            row=board.show(task['id'],'task')
            return board.control(task['id'],{'operation_id':'pause-one','kind':'pause','text':'이 작업만 잠시 멈춥니다.',
                  'expected_task_revision':row['control']['task_revision'],'expected_control_version':row['control']['control_version'],
                  'expected_vault_revision':row['vault_revision']})
        try:
            row=board.show(request['id']);revision=row['vault_revision']
        except LoopError:
            # No valid displayed request exists while the old manifest remains.
            # This fresh token is computed from the published current documents,
            # never borrowed from the pre-migration state.
            value=json.loads(fixture['output'].read_text());docs=[];parents=[]
            from loop_work.vault import _export_pin
            for name,entry in sorted(value['target_manifest']['documents'].items()):
                if entry['role'] not in ('current','human-request'):
                    continue
                note={'path':name,'revision':_export_pin(fixture['vault']/name),'role':entry['role']}
                (docs if entry['role']=='human-request' else parents).append(note)
            revision=digest([docs,parents])
        if action=='respond':
            return board.respond(request['id'],{'decision':'approve','text':'명시한 요청만 승인합니다.'},request['revision'],revision)
        return board.execute(request['id'],request['revision'],revision)

    def test_restore_collision_preserves_new_human_note_and_captured_edited_original(self):
        planned=plan(self.kb.home,self.vault,self.output)
        import loop_work.vault_migrate as module
        rename=getattr(module,'_move_exclusive',module.os.rename);link=module.os.link;source=self.vault/self.old
        edited='아카이브 직전 사람이 고친 원문';new='복구 순간 새로 만든 사람 노트'
        def edit_before_capture(src,dst,*args,**kwargs):
            if Path(src)==source:
                source.write_text(edited)
            return rename(src,dst,*args,**kwargs)
        def recreate_before_restore(src,dst,*args,**kwargs):
            if Path(dst)==source:
                source.write_text(new)
            return link(src,dst,*args,**kwargs)
        with self._archive_patch(module,edit_before_capture),patch.object(module.os,'link',side_effect=recreate_before_restore):
            with self.assertRaisesRegex(LoopError,'Original changed during archive'):
                apply(self.output,planned['sha256'])
        self.assertEqual(source.read_text(),new)
        backup=self.output.with_suffix('.json.backup')
        self.assertEqual((backup/'captured-originals'/self.old).read_text(),edited)
        self.assertEqual((backup/'original-files'/self.old).read_bytes(),self.original)
        self.assertEqual(json.loads((self.kb.home/'vault-owned.json').read_text())['layout_version'],2)

    def test_archive_race_never_activates_board_control_respond_or_execute(self):
        import loop_work.vault_migrate as module
        from loop_work.board import Board
        for action in ('control','respond','execute'):
            with self.subTest(action=action):
                good=self._explicit_decision_fixture('normal-'+action,answered=action=='execute')
                apply(good['output'],good['planned']['sha256'])
                self.assertTrue(self._board_action(good,action)['action_committed'])
                bad=self._explicit_decision_fixture('racing-'+action,answered=action=='execute')
                db=bad['kb'].path.read_bytes();task_before=bad['kb'].get('task',bad['task']['id'])
                request_before=bad['kb'].get('human-request',bad['request']['id'])
                rename=getattr(module,'_move_exclusive',module.os.rename);source=bad['vault']/bad['current']
                def race(src,dst,*args,**kwargs):
                    if Path(src)==source:
                        source.write_text('아카이브 경계에서 바뀐 사용자 원문')
                    return rename(src,dst,*args,**kwargs)
                with self._archive_patch(module,race):
                    with self.assertRaisesRegex(LoopError,'Original changed during archive'):
                        apply(bad['output'],bad['planned']['sha256'])
                self.assertEqual(json.loads((bad['kb'].home/'vault-owned.json').read_text())['layout_version'],2)
                row=Board(bad['kb'],bad['vault']).show(bad['task']['id'],'task')
                self.assertFalse(row['writable']);self.assertFalse(row['control']['available'])
                with self.assertRaises(LoopError):self._board_action(bad,action)
                self.assertEqual(bad['kb'].get('task',bad['task']['id']),task_before)
                self.assertEqual(bad['kb'].get('human-request',bad['request']['id']),request_before)
                self.assertEqual(bad['kb'].list('feedback'),[]);self.assertEqual(bad['kb'].list('board-control'),[])
                self.assertEqual(bad['kb'].path.read_bytes(),db)

    def test_payload_changed_after_validation_cannot_change_published_bytes(self):
        planned=plan(self.kb.home,self.vault,self.output);value=json.loads(self.output.read_text())
        name=next(iter(value['target_files']));payload=Path(value['payload'])/name;expected=payload.read_bytes()
        import loop_work.vault_migrate as module
        read=module._read_regular;calls=0
        def race(path,*args,**kwargs):
            nonlocal calls
            result=read(path,*args,**kwargs)
            if Path(path)==payload:
                calls+=1
                if calls==1:payload.write_text('검증 후 바뀐 악성 payload')
            return result
        with patch.object(module,'_read_regular',side_effect=race):
            result=apply(self.output,planned['sha256'])
        self.assertEqual(result['status'],'applied');self.assertEqual(calls,1)
        self.assertEqual((self.vault/name).read_bytes(),expected)
        self.assertNotIn('검증 후 바뀐 악성 payload',(self.vault/name).read_text())
        fixture=self._explicit_decision_fixture('published-destination-race')
        writer=module._write
        def edit_published(path,content,expected_pin):
            actual=writer(path,content,expected_pin)
            if Path(path).name=='진행 현황.md':
                Path(path).write_text('게시 직후 외부에서 변경한 실제 대상 파일')
            return actual
        with patch.object(module,'_write',side_effect=edit_published):
            with self.assertRaisesRegex(LoopError,'Published document changed'):
                apply(fixture['output'],fixture['planned']['sha256'])
        self.assertEqual(json.loads((fixture['kb'].home/'vault-owned.json').read_text())['layout_version'],2)

    def test_omitted_or_deleted_previous_user_requests_cannot_gain_new_authority(self):
        for state in ('described-only','physical-only','entirely-removed','foreign-home','wrong-role'):
            with self.subTest(state=state):
                fixture=self._explicit_decision_fixture('omitted-'+state)
                manifest=fixture['manifest'];name=fixture['request_path']
                if state in ('foreign-home','wrong-role'):
                    path=fixture['vault']/name;parts=path.read_text().split('\n',3);meta=json.loads(parts[1][11:])
                    meta['knowledge_home' if state=='foreign-home' else 'role']='foreign-home' if state=='foreign-home' else 'current'
                    path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3])
                    manifest['files'][name]=file_hash(path)
                else:
                    manifest['files'].pop(name)
                    manifest['paths'].pop(next(key for key in manifest['paths'] if key.startswith('human-request:')))
                    if state!='described-only':manifest['documents'].pop(name)
                    if state=='entirely-removed':(fixture['vault']/name).unlink()
                write_json(fixture['kb'].home/'vault-owned.json',manifest)
                with self.assertRaisesRegex(LoopError,'replacement authority|previous execution'):
                    plan(fixture['kb'].home,fixture['vault'],self.base/(state+'.json'))
                self.assertEqual(json.loads((fixture['kb'].home/'vault-owned.json').read_text())['layout_version'],2)
                self.assertFalse(any(fixture['vault'].glob('프로젝트/*/작업/*/기록/사용자 검토/*.md')))

    def test_backup_directory_files_and_capture_collisions_never_overwrite_people(self):
        import loop_work.vault_migrate as module
        for kind in ('directory','directory-link','file','file-link','capture'):
            with self.subTest(kind=kind):
                fixture=self._explicit_decision_fixture('backup-collision-'+kind,include_request=False)
                kb=fixture['kb'];db=kb.path.read_bytes();before=(kb.home/'vault-owned.json').read_bytes()
                backup=fixture['output'].with_suffix('.json.backup');text='동시에 생성한 사람의 보존할 원문'
                outside=self.base/('outside-'+kind);outside.mkdir()
                outside_note=outside/'vault-owned.json';outside_note.write_text(text)
                preserved=backup/'vault-owned.json'
                if kind in ('directory','directory-link'):
                    mkdir=module.os.mkdir
                    def claim_directory(path,*args,**kwargs):
                        if Path(path)==backup and kwargs.get('dir_fd') is None:
                            if kind=='directory-link':backup.symlink_to(outside,target_is_directory=True)
                            else:
                                mkdir(backup,0o700);(backup/'vault-owned.json').write_text(text)
                        return mkdir(path,*args,**kwargs)
                    context=patch.object(module.os,'mkdir',side_effect=claim_directory)
                elif kind in ('file','file-link') and hasattr(module,'_backup_bytes'):
                    writer=module._backup_bytes
                    def claim_file(root,name,content,*args,**kwargs):
                        if name=='vault-owned.json':
                            if kind=='file-link':(root/name).symlink_to(outside_note)
                            else:(root/name).write_text(text)
                        return writer(root,name,content,*args,**kwargs)
                    context=patch.object(module,'_backup_bytes',side_effect=claim_file)
                elif kind in ('file','file-link'):
                    writer=Path.write_bytes
                    def claim_file(path,content):
                        if path==preserved:
                            if kind=='file-link':path.symlink_to(outside_note)
                            else:path.write_text(text)
                        return writer(path,content)
                    context=patch.object(Path,'write_bytes',claim_file)
                else:
                    move=getattr(module,'_move_exclusive',module.os.rename)
                    def claim_capture(src,dst,*args,**kwargs):
                        Path(dst).write_text(text)
                        return move(src,dst,*args,**kwargs)
                    context=self._archive_patch(module,claim_capture)
                    preserved=backup/'captured-originals'/fixture['current']
                with context:
                    with self.assertRaises((LoopError,OSError)):
                        apply(fixture['output'],fixture['planned']['sha256'])
                self.assertEqual(preserved.read_text(),text)
                self.assertEqual(outside_note.read_text(),text)
                self.assertEqual((fixture['vault']/fixture['current']).read_text().splitlines()[0],'---')
                self.assertEqual((kb.home/'vault-owned.json').read_bytes(),before)
                self.assertEqual(kb.path.read_bytes(),db)

    def test_every_task_current_and_project_replica_requires_previous_owned_source(self):
        good=self._explicit_decision_fixture('present-current',include_request=False)
        apply(good['output'],good['planned']['sha256'])
        self.assertTrue(self._board_action(good,'control')['action_committed'])
        for state in ('only-current','one-project-replica'):
            with self.subTest(state=state):
                fixture=self._explicit_decision_fixture('missing-'+state,include_request=False)
                kb=fixture['kb'];vault=fixture['vault'];task=fixture['task'];manifest=fixture['manifest']
                current=fixture['current']
                if state=='one-project-replica':
                    second='second-project';kb.put('project',{'id':second,'name':'두 번째 프로젝트'})
                    task={**task,'project_ids':task['project_ids']+[second]};kb.put('task',task)
                    old=vault/current;parts=old.read_text().split('\n',3);meta=json.loads(parts[1][11:]);meta['record']=task
                    old.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3]);manifest['files'][current]=file_hash(old)
                    current='projects/두 번째 프로젝트--'+second+'/tasks/실제로 제어할 명시 작업--'+task['id']+'/현재-실제로 제어할 명시 작업--'+task['id']+'.md'
                    target=vault/current;target.parent.mkdir(parents=True);meta['project_id']=second
                    target.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3])
                    manifest['files'][current]=file_hash(target);manifest['documents'][current]={**manifest['documents'][fixture['current']],'project_id':second}
                    manifest['paths']['project:'+second]='projects/두 번째 프로젝트--'+second
                    manifest['paths']['task:'+second+':'+task['id']]=current
                    write_json(kb.home/'vault-owned.json',manifest)
                    self.assertEqual(plan(kb.home,vault,self.base/'all-replicas.json')['status'],'planned')
                # Keep an owned historical document, proving absence is specific
                # to the current replica rather than an empty/uninstalled vault.
                historical=current.rsplit('/',1)[0]+'/interim/history-1-'+'a'*20+'.md'
                target=vault/historical;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('보존할 과거 기록')
                manifest['files'][historical]=file_hash(target)
                manifest['files'].pop(current);manifest['documents'].pop(current)
                manifest['paths'].pop(next(key for key,value in manifest['paths'].items() if value==current))
                (vault/current).unlink();write_json(kb.home/'vault-owned.json',manifest)
                db=kb.path.read_bytes();before=(kb.home/'vault-owned.json').read_bytes()
                with self.assertRaisesRegex(LoopError,'current ownership is missing'):
                    plan(kb.home,vault,self.base/(state+'-refused.json'))
                self.assertEqual(kb.path.read_bytes(),db);self.assertEqual((kb.home/'vault-owned.json').read_bytes(),before)
                self.assertIn('보존할 과거 기록',target.read_text())

    def test_archive_additions_in_old_execution_namespace_block_cutover(self):
        import loop_work.vault_migrate as module
        from loop_work.board import Board
        for kind in ('current','request','delegation','history'):
            with self.subTest(kind=kind):
                fixture=self._explicit_decision_fixture('archive-addition-'+kind,include_request=False)
                kb=fixture['kb'];vault=fixture['vault'];db=kb.path.read_bytes();before=(kb.home/'vault-owned.json').read_bytes()
                prefix=fixture['current'].rsplit('/',1)[0]+'/'
                suffix={'current':'현재-다른 원문--unexpected.md','request':'records/human-request/추가 요청--unexpected.md',
                        'delegation':'delegations/추가 위임--unexpected.md','history':'interim/추가 기록.md'}[kind]
                unexpected=vault/(prefix+suffix);move=getattr(module,'_move_exclusive',module.os.rename);added=False
                def add_during_archive(src,dst,*args,**kwargs):
                    nonlocal added
                    result=move(src,dst,*args,**kwargs)
                    if not added:
                        unexpected.parent.mkdir(parents=True,exist_ok=True);unexpected.write_text('아카이브 중 추가한 실행 원문');added=True
                    return result
                with self._archive_patch(module,add_during_archive):
                    with self.assertRaisesRegex(LoopError,'Unowned previous execution'):
                        apply(fixture['output'],fixture['planned']['sha256'])
                self.assertEqual(unexpected.read_text(),'아카이브 중 추가한 실행 원문')
                self.assertEqual((kb.home/'vault-owned.json').read_bytes(),before);self.assertEqual(kb.path.read_bytes(),db)
                row=Board(kb,vault).show(fixture['task']['id'],'task')
                self.assertFalse(row['writable']);self.assertFalse(row['control']['available'])
                with self.assertRaises(LoopError):self._board_action(fixture,'control')
                self.assertEqual(kb.path.read_bytes(),db)

    def _legacy_v1_fixture(self, suffix):
        legacy=self._explicit_decision_fixture(suffix)
        manifest=legacy['manifest'];pid=legacy['task']['project_ids'][0];task_id=legacy['task']['id']
        prefix='projects/'+pid+'/tasks/'+task_id+'/'
        for old,new in ((legacy['current'],prefix+'current.md'),(legacy['request_path'],prefix+'records/human-request/'+legacy['request']['id']+'.md')):
            source=legacy['vault']/old;parts=source.read_text().split('\n',3);meta=json.loads(parts[1][11:])
            meta={key:meta[key] for key in ('kind','id','knowledge_home','record')};meta['version']=1
            target=legacy['vault']/new;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3]);source.unlink()
            manifest['files'].pop(old);manifest['files'][new]=file_hash(target)
            manifest['documents'][new]=manifest['documents'].pop(old)
            if legacy['current']==old:legacy['current']=new
            if legacy['request_path']==old:legacy['request_path']=new
            for key,name in list(manifest['paths'].items()):
                if name==old:manifest['paths'][key]=new
        write_json(legacy['kb'].home/'vault-owned.json',manifest)
        return legacy

    def test_physical_source_scope_and_stale_envelopes_cannot_gain_authority(self):
        legacy=self._legacy_v1_fixture('valid-v1')
        legacy['output']=self.base/'valid-v1-plan.json';legacy['planned']=plan(legacy['kb'].home,legacy['vault'],legacy['output'])
        apply(legacy['output'],legacy['planned']['sha256'])
        self.assertTrue(self._board_action(legacy,'respond')['action_committed'])
        for kind in ('task','human-request'):
            for change in ('project','task','filename','stale'):
                with self.subTest(kind=kind,change=change):
                    fixture=self._explicit_decision_fixture('identity-'+kind+'-'+change)
                    kb=fixture['kb'];vault=fixture['vault'];manifest=fixture['manifest']
                    source=fixture['current' if kind=='task' else 'request_path']
                    if change=='stale':
                        record=kb.get(kind,fixture['task' if kind=='task' else 'request']['id'])
                        record['title' if kind=='task' else 'question']='권한 근거와 달라진 새 사용자 원문'
                        kb.put(kind,record)
                    else:
                        parts=source.split('/');index={'project':1,'task':3,'filename':len(parts)-1}[change]
                        parts[index]='다른 범위--foreign'+('.md' if change=='filename' else '')
                        replacement='/'.join(parts);target=vault/replacement;target.parent.mkdir(parents=True,exist_ok=True)
                        (vault/source).rename(target)
                        manifest['files'][replacement]=manifest['files'].pop(source)
                        manifest['documents'][replacement]=manifest['documents'].pop(source)
                        for key,name in list(manifest['paths'].items()):
                            if name==source:manifest['paths'][key]=replacement
                        write_json(kb.home/'vault-owned.json',manifest)
                    db=kb.path.read_bytes();before=(kb.home/'vault-owned.json').read_bytes()
                    with self.assertRaisesRegex(LoopError,'replacement authority'):
                        plan(kb.home,vault,self.base/('refused-'+kind+'-'+change+'.json'))
                    self.assertEqual(kb.path.read_bytes(),db);self.assertEqual((kb.home/'vault-owned.json').read_bytes(),before)

    def test_previous_authority_descriptors_metadata_and_manifest_are_not_normalized(self):
        for version in (1,2):
            for kind in ('task','human-request'):
                for mode in ('missing','null','wrong','extra','malformed','metadata-extra'):
                    with self.subTest(version=version,kind=kind,mode=mode):
                        label=f'prior-{version}-{kind}-{mode}'
                        fixture=self._legacy_v1_fixture(label) if version==1 else self._explicit_decision_fixture(label)
                        manifest=fixture['manifest'];name=fixture['current' if kind=='task' else 'request_path']
                        if mode=='missing':manifest['documents'].pop(name)
                        elif mode=='null':manifest['documents'][name]=None
                        elif mode=='wrong':manifest['documents'][name]['project_id']='foreign-project'
                        elif mode=='extra':manifest['documents'][name]['extra']='untrusted'
                        elif mode=='malformed':manifest['documents'][name]=['not','a','descriptor']
                        else:
                            path=fixture['vault']/name;parts=path.read_text().split('\n',3);meta=json.loads(parts[1][11:]);meta['extra']='untrusted'
                            path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3]);manifest['files'][name]=file_hash(path)
                        write_json(fixture['kb'].home/'vault-owned.json',manifest)
                        db=fixture['kb'].path.read_bytes();original=(fixture['kb'].home/'vault-owned.json').read_bytes()
                        output=self.base/(label+'-checked.json')
                        if version==1 and mode=='missing':
                            result=plan(fixture['kb'].home,fixture['vault'],output)
                            self.assertEqual(result['status'],'planned')
                            fixture['output']=output;fixture['planned']=result;apply(output,result['sha256'])
                            self.assertTrue(self._board_action(fixture,'control' if kind=='task' else 'respond')['action_committed'])
                        else:
                            with self.assertRaises(LoopError):plan(fixture['kb'].home,fixture['vault'],output)
                            self.assertEqual(fixture['kb'].path.read_bytes(),db)
                            self.assertEqual((fixture['kb'].home/'vault-owned.json').read_bytes(),original)
        for mode in ('layout-1','layout-null','foreign-mapping','unknown-mapping','duplicate-mapping'):
            with self.subTest(manifest=mode):
                fixture=self._explicit_decision_fixture('manifest-'+mode,include_request=False);manifest=fixture['manifest']
                pid=fixture['task']['project_ids'][0]
                if mode=='layout-1':manifest['layout_version']=1
                elif mode=='layout-null':manifest['layout_version']=None
                elif mode=='foreign-mapping':manifest['paths']['project:'+pid]='projects/foreign--other'
                elif mode=='unknown-mapping':manifest['paths']['unknown:key']=fixture['current']
                else:
                    token='a'*20;task_id=fixture['task']['id'];history=fixture['current'].rsplit('/',1)[0]+'/interim/history-1-'+token+'.md'
                    source=fixture['vault']/fixture['current'];parts=source.read_text().split('\n',3);meta=json.loads(parts[1][11:]);meta['role']='interim'
                    path=fixture['vault']/history;path.parent.mkdir();path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+parts[3])
                    manifest['files'][history]=file_hash(path);manifest['documents'][history]={**manifest['documents'][fixture['current']],'role':'interim'}
                    for sequence in ('1','2'):manifest['paths']['history:'+pid+':'+task_id+':'+sequence+':'+token]=history
                write_json(fixture['kb'].home/'vault-owned.json',manifest)
                with self.assertRaises(LoopError):plan(fixture['kb'].home,fixture['vault'],self.base/(mode+'-checked.json'))

    def test_previous_read_limits_and_divergent_replica_prose_cannot_restore_authority(self):
        from loop_work.board import MAX_MANIFEST,MAX_NOTE,MAX_DOCUMENTS,MAX_TOTAL
        for mode in ('manifest-bytes','note-bytes','replica-count','replica-total','replica-prose'):
            with self.subTest(mode=mode):
                fixture=self._explicit_decision_fixture('limits-'+mode,include_request=False)
                kb=fixture['kb'];vault=fixture['vault'];manifest=fixture['manifest'];name=fixture['current'];path=vault/name
                if mode=='manifest-bytes':manifest['unowned_padding']='x'*MAX_MANIFEST
                elif mode=='note-bytes':
                    path.write_text(path.read_text()+'x'*MAX_NOTE);manifest['files'][name]=file_hash(path)
                else:
                    raw=path.read_text();header,separator,body=raw.partition('\n---\n')
                    if mode=='replica-total':
                        body='동일한 근거 본문'*18000
                        raw=header+separator+body;path.write_text(raw);manifest['files'][name]=file_hash(path)
                    count=MAX_DOCUMENTS if mode=='replica-count' else max(1,MAX_TOTAL//len(raw.encode())) if mode=='replica-total' else 1
                    tid=fixture['task']['id']
                    for index in range(count):
                        relative=name.rsplit('/',1)[0]+'/현재-별도 사본'+str(index)+'--'+tid+'.md'
                        target=vault/relative;target.write_text(raw if mode!='replica-prose' else raw+'다른 사본에만 있는 원문')
                        manifest['files'][relative]=file_hash(target);manifest['documents'][relative]=deepcopy(manifest['documents'][name])
                write_json(kb.home/'vault-owned.json',manifest);db=kb.path.read_bytes();before=(kb.home/'vault-owned.json').read_bytes()
                with self.assertRaises((LoopError,OSError)):
                    plan(kb.home,vault,self.base/(mode+'-refused.json'))
                self.assertEqual(kb.path.read_bytes(),db);self.assertEqual((kb.home/'vault-owned.json').read_bytes(),before)
                self.assertTrue(path.exists())

    def test_plan_and_payload_initial_publication_preserve_racing_notes_and_links(self):
        import loop_work.vault_migrate as module
        for mode in ('plan-file','plan-link','payload-file','payload-link'):
            with self.subTest(mode=mode):
                fixture=self._explicit_decision_fixture('publish-'+mode,include_request=False)
                output=self.base/(mode+'-new-plan.json');payload=output.with_suffix('.json.payload')
                outside=self.base/(mode+'-outside.md');text='동시에 작성한 사람의 원문';outside.write_text(text)
                kb=fixture['kb'];source=(kb.home/'vault-owned.json').read_bytes();db=kb.path.read_bytes();claimed=[]
                writer=module._write;backup=module._backup_bytes if hasattr(module,'_backup_bytes') else None;path_writer=Path.write_text
                json_writer=getattr(module,'write_json',None)
                def claim(target):
                    if claimed:return
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if mode.endswith('link'):target.symlink_to(outside)
                    else:
                        with target.open('w') as stream:stream.write(text)
                    claimed.append(target)
                def plan_race(path,content,expected):
                    if Path(path)==output and mode.startswith('plan-'):claim(Path(path))
                    return writer(path,content,expected)
                def payload_race(root,name,content,*args,**kwargs):
                    if Path(root)==payload and mode.startswith('payload-'):claim(root/name)
                    return backup(root,name,content,*args,**kwargs)
                def old_writer_race(path,content,*args,**kwargs):
                    if Path(path).is_relative_to(payload) and mode.startswith('payload-'):claim(Path(path))
                    return path_writer(path,content,*args,**kwargs)
                def old_plan_race(path,document):
                    if Path(path)==output and mode.startswith('plan-'):claim(Path(path))
                    return json_writer(path,document)
                # Patch the old and new publication boundaries; the same human
                # occupancy must survive either implementation's final write.
                with ExitStack() as patches:
                    patches.enter_context(patch.object(module,'_write',side_effect=plan_race))
                    patches.enter_context(patch.object(Path,'write_text',old_writer_race))
                    if backup:patches.enter_context(patch.object(module,'_backup_bytes',side_effect=payload_race))
                    if json_writer:patches.enter_context(patch.object(module,'write_json',side_effect=old_plan_race))
                    with self.assertRaises((LoopError,OSError)):plan(kb.home,fixture['vault'],output)
                self.assertEqual(len(claimed),1)
                self.assertEqual(claimed[0].read_text(),text);self.assertEqual(outside.read_text(),text)
                self.assertEqual(kb.path.read_bytes(),db);self.assertEqual((kb.home/'vault-owned.json').read_bytes(),source)
