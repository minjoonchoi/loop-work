"""Actual isolated fixture/server for the browser gate; never imports user data."""
from pathlib import Path
import json
import os
import signal
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from loop_work.knowledge import KnowledgeBase
from loop_work.work import Work
from loop_work.human import HumanDesk
from loop_work.storage import file_hash, digest, read_json
from loop_work.board_ui import make_server


def main():
    base=Path(sys.argv[1]).resolve()
    if '--reuse' in sys.argv[2:]:
        metadata=json.loads((base/'fixture.json').read_text())
        os.environ['HOME']=str(base/'home')
        knowledge=KnowledgeBase(base/'knowledge',vault_home=base/'vault')
        return serve(knowledge,base,metadata['projects'],metadata['tasks'],metadata.get('hidden'))
    base.mkdir(exist_ok=False)
    home=base/'home';home.mkdir()
    os.environ['HOME']=str(home)
    knowledge=KnowledgeBase(base/'knowledge',vault_home=base/'vault')
    work=Work(knowledge)
    policy={'version':1,'profiles':[{'id':'fixture-codex','provider':'codex','model':'gpt-6.1-sol','effort':'low','capability_rank':100,'cost_rank':1}],
            'requirements':{'low':100,'medium':100,'high':100}}
    projects=[];tasks=[]
    for name in ('인증서비스','결제서비스'):
        project=base/name;project.mkdir();subprocess.run(['git','init','--quiet',str(project)],check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);proof=project/'README.md';proof.write_text('합성 브라우저 검증 fixture입니다. 실제 제품 작업 완료를 주장하지 않습니다.\n',encoding='utf-8')
        location=knowledge.attach(project);projects.append({'id':location['project_id'],'name':name})
        for state,title in [('ready','준비 문서'),('working','진행 문서'),('review','확인 요청 문서'),('completed','완료 기록 문서'),('completed_pending','완료 후 확인 문서'),('stopped','중단 기록 문서'),('blocked','기술 차단 문서')]:
            task=work.open('document',name+' '+title,'codex',[project],explicit_skill=True)['task']
            if state!='ready':
                work.define(task['id'],{'outcome':'합성 fixture 문서의 상태 전이를 확인합니다.','deliverable':'README.md 원문',
                    'criteria':[{'id':'C1','description':'합성 README가 존재합니다.'}],'decisions':[],'open_questions':[],
                    'execution':{'routing':policy}})
                work.start(task['id'])
            if state in ('completed','completed_pending'):
                work.finish(task['id'],{'summary':'합성 fixture의 파일 존재를 확인했습니다.','outputs':[str(proof)],
                    'checks':[{'criterion_id':'C1','satisfied':True,'evidence':str(proof)}]})
            if state=='completed_pending':
                HumanDesk(knowledge).create(task['id'],{'id':'after-completion-'+task['id'],'kind':'decision','title':'완료 후 확인 질문','question':'과거 완료 기록을 확인합니까?','options':['확인'],'action':None})
            elif state=='blocked':work.stop(task['id'],{'version':1,'kind':'external','reason':'합성 컴파일 환경 접근 실패','scope':'task','retryable':True,'evidence':[{'ref':str(proof),'sha256':file_hash(proof)}]})
            elif state=='stopped':work.stop(task['id'],'합성 fixture의 명시적 중단 전이',abort=True)
            elif state=='review':
                HumanDesk(knowledge).create(task['id'],{'id':'question-'+task['id'],'kind':'decision','title':'합성 확인 질문',
                    'question':'문서 표시를 확인할 수 있습니까?','options':['확인 가능','확인 필요'],'action':None})
            tasks.append({'id':task['id'],'project_id':location['project_id'],'expected_state':state,'title':task['title']})
    shared=work.open('document','공유 작업 원래 제목','codex',[base/'인증서비스',base/'결제서비스'],explicit_skill=True)['task']
    tasks.append({'id':shared['id'],'project_id':projects[0]['id'],'shared_project_ids':[p['id'] for p in projects],'expected_state':'shared','title':shared['title']})
    ordinary=work.open('document','일반 대화 참고 정보 작업','codex',[base/'인증서비스'],session_id=knowledge.get('task',tasks[0]['id'])['session_id'])['task']
    request=HumanDesk(knowledge).create(ordinary['id'],{'id':'ordinary-hidden-request','kind':'decision','title':'일반 대화 숨김 질문','question':'일반 대화 원문은 보존합니다.','options':[],'action':None})
    locations=[knowledge.attach(base/'인증서비스')]
    topic=knowledge.remember({'id':'ordinary-memory','scope':'project','kind':'fact','status':'confirmed','summary':'일반 대화 참고 지식','evidence':['README.md:1'],'paths':['README.md']},locations,digest(knowledge.observe(locations)),session_id=ordinary['session_id'])
    desktop_task=next(item for item in tasks if item['project_id']==projects[0]['id'] and item['expected_state']=='review')
    for suffix,title in [('normal','데스크톱 종료 정상 제출'),('race','데스크톱 종료 응답 경쟁')]:
        HumanDesk(knowledge).create(desktop_task['id'],{'id':'desktop-response-'+suffix+'-'+desktop_task['id'],
            'kind':'approval','title':title,'question':'종료 보호 fixture 원문을 확인합니까?','options':[],'action':None})
    execute_task=work.open('document','재개 실행 초안 보존 검증','codex',[base/'인증서비스'],explicit_skill=True)['task']
    work.define(execute_task['id'],{'outcome':'허용된 재개와 미제출 답변을 분리한다.','deliverable':'README.md','criteria':[{'id':'C1','description':'합성 원문 보존'}],'decisions':[],'open_questions':[],'execution':{'routing':policy}})
    work.start(execute_task['id'])
    proof=base/'인증서비스'/'README.md'
    work.stop(execute_task['id'],{'version':1,'kind':'external','reason':'합성 수동 재개 경계','scope':'task','retryable':True,'evidence':[{'ref':str(proof),'sha256':file_hash(proof)}]})
    execute_id='desktop-execute-draft-'+execute_task['id']
    execute_request=HumanDesk(knowledge).create(execute_task['id'],{'id':execute_id,'kind':'approval','title':'원문 답변과 재개 분리','question':'합성 작업을 재개합니까?','options':[],'action':'resume_task'})
    HumanDesk(knowledge).respond(execute_id,{'decision':'approve','text':'이미 승인된 원래 답변'},execute_request['revision'])
    tasks.append({'id':execute_task['id'],'project_id':projects[0]['id'],'expected_state':'execute_draft','title':execute_task['title'],'request_id':execute_id})
    for suffix in ('delay','lost','forged','retry','close_race'):
        pending_task=work.open('document','실행 확인 '+suffix,'codex',[base/'인증서비스'],explicit_skill=True)['task']
        work.define(pending_task['id'],{'outcome':'실제 재개 접수 확인','deliverable':'README.md','criteria':[{'id':'C1','description':'합성 파일 확인'}],'decisions':[],'open_questions':[],'execution':{'routing':policy}})
        work.start(pending_task['id'])
        work.stop(pending_task['id'],{'version':1,'kind':'external','reason':'합성 실행 대기','scope':'task','retryable':True,'evidence':[{'ref':str(proof),'sha256':file_hash(proof)}]})
        rid='execute-'+suffix+'-'+pending_task['id']
        req=HumanDesk(knowledge).create(pending_task['id'],{'id':rid,'kind':'approval','title':'실행 확인 '+suffix,'question':'합성 재개를 허용합니까?','options':[],'action':'resume_task'})
        HumanDesk(knowledge).respond(rid,{'decision':'approve','text':'보존할 승인 원문'},req['revision'])
        tasks.append({'id':pending_task['id'],'project_id':projects[0]['id'],'expected_state':'execute_'+suffix,'title':pending_task['title'],'request_id':rid})
    pending_response=HumanDesk(knowledge).create(desktop_task['id'],{'id':'human-pending-close-'+desktop_task['id'],'kind':'decision','title':'답변 접수 확인','question':'전송 원문을 보존합니까?','options':[],'action':None})
    HumanDesk(knowledge).create(desktop_task['id'],{'id':'human-retry-response-'+desktop_task['id'],'kind':'decision','title':'명시적 원문 재시도','question':'원래 답변을 재확인합니까?','options':[],'action':None})
    history_task=work.open('document','공유 이력 경계','codex',[base/'인증서비스',base/'결제서비스'],explicit_skill=True)['task']
    work.define(history_task['id'],{'outcome':'합성 이력 표시 검증','deliverable':'README.md','criteria':[{'id':'C1','description':'합성 파일 확인'}],'decisions':[],'open_questions':[],'execution':{'routing':policy}})
    work.start(history_task['id'])
    work.finish(history_task['id'],{'summary':'실제 합성 문서 확인','outputs':[str(proof)],'checks':[{'criterion_id':'C1','satisfied':True,'evidence':str(proof)}]})
    tasks.append({'id':history_task['id'],'project_id':projects[0]['id'],'shared_project_ids':[p['id'] for p in projects],'expected_state':'history_scope','title':history_task['title']})
    knowledge.sync_vault()
    manifest=read_json(knowledge.home/'vault-owned.json')
    hidden={'task_id':ordinary['id'],'request_id':request['id'],'session_id':ordinary['session_id'],'topic_id':'ordinary-memory','paths':[name for name,d in manifest['documents'].items() if d.get('task_id')==ordinary['id'] or d.get('id') in (ordinary['id'],'ordinary-memory')]}
    serve(knowledge,base,projects,tasks,hidden)


def serve(knowledge,base,projects,tasks,hidden=None):
    server=make_server(knowledge,port=0)
    metadata={'fixture_only':True,'model_calls':0,'knowledge_home':str(knowledge.home),'vault':str(base/'vault'),
              'projects':projects,'tasks':tasks,'hidden':hidden,'url':server.url,'source':str(ROOT)}
    (base/'fixture.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    print(json.dumps(metadata,ensure_ascii=False),flush=True)
    def stop(_signal,_frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
