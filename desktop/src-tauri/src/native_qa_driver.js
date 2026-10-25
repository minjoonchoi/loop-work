// Loaded only by the explicit native-qa feature from an isolated external plan.
// No Tauri shim or API proxy: every API operation uses the shipping Rust command.
(async()=>{
 const invoke=(name,args)=>window.__TAURI_INTERNALS__.invoke(name,args);
 const checks=[],measurements={},cancelEvents=[];
 const selectionTrace=[];let selectionTraceDropped=0;
 const observeSelection=(phase,targetId,card)=>{try{
  const row={at_ms:Math.round(performance.now()),phase,target_id:targetId,selected_id:document.querySelector('.task-card.selected')?.dataset.taskId||null,
   card_connected:card?.isConnected??null,card_disabled:card?.disabled??null,board_busy:document.getElementById('board')?.getAttribute('aria-busy')??null,
   close_preparing:document.documentElement.dataset.closePreparing??null,wiki_save_state:document.querySelector('.wiki-editor')?.dataset.saveState??null,
   selection_get_poll_order:'not_observable: Tauri IPC and React epoch are not exposed'};
  const previous=selectionTrace.at(-1);if(previous&&phase==='selection_wait'&&JSON.stringify({...previous,at_ms:0})===JSON.stringify({...row,at_ms:0}))return;
  if(selectionTrace.length>=32){selectionTrace.shift();selectionTraceDropped++;}selectionTrace.push(row);
 }catch(_){/* Fixture diagnostics must not change the original verdict. */}};
 const domState=()=>({selectedTask:document.querySelector('.task-card.selected')?.dataset.taskId,tabs:Array.from(document.querySelectorAll('[role=tab]')).map(n=>({text:n.textContent,selected:n.getAttribute('aria-selected'),controls:n.getAttribute('aria-controls')})),panels:Array.from(document.querySelectorAll('[role=tabpanel]')).map(n=>({id:n.id,state:n.dataset.state,hidden:n.hidden,width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height})),flowNodes:document.querySelectorAll('.react-flow__node').length,flowEdges:document.querySelectorAll('.react-flow__edge-path').length});
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const ensure=(x,message)=>{if(!x)throw new Error(message)};
 const until=async(fn,message,ms=15000)=>{const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await sleep(100)}throw new Error(message)};
 const api=async(path,body)=>{const r=await invoke('board_request',{request:{method:body===undefined?'GET':'POST',path,...(body===undefined?{}:{body})}});return r};
 const action=action=>invoke('native_qa_action',{action});
 const button=(label,root=document)=>Array.from(root.querySelectorAll('button')).find(n=>n.textContent.trim()===label&&!n.disabled);
 const click=async(label,root=document)=>{const b=await until(()=>button(label,root),'버튼 없음: '+label);if(b.getAttribute('role')==='tab'){b.focus();b.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));b.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',bubbles:true}));await until(()=>b.getAttribute('aria-selected')==='true','탭 활성화 실패: '+label)}else b.click();await sleep(100)};
 const input=(node,text)=>{ensure(node,'입력 필드 없음');const proto=node.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(node,text);node.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:text}));};
 const check=async(name,fn)=>{await action('progress:'+name+':start');const start=Date.now();const evidence=await fn();checks.push({name,passed:true,milliseconds:Date.now()-start,...(evidence?{evidence}:{})});await action('progress:'+name+':done')};
 const q='?project_id='+encodeURIComponent(fixture.project_id),path='/api/tasks/'+fixture.edit_task+'/wiki'+q;
 const wiki=async()=>{const r=await api(path);ensure(r.status===200,'실제 위키 조회 실패');return r.body};
 const saved=async(expected={})=>until(async()=>{const actual=await wiki();return document.querySelector('.wiki-editor')?.dataset.saveState==='saved'&&(!expected.marker||actual.body_markdown.includes(expected.marker))&&(!expected.title||actual.title===expected.title)},'실제 원문 및 위키 저장 완료 없음',25000);
 const cards=()=>Array.from(document.querySelectorAll('[data-task-id]'));
 const confirmations=async()=>((await action('status')).events||[]).filter(x=>x.event==='confirmation_callback'&&x.accepted===false);
 const pixels=canvas=>{ensure(canvas?.width&&canvas.height,'실제 canvas 크기 없음');const copy=document.createElement('canvas');copy.width=canvas.width;copy.height=canvas.height;const ctx=copy.getContext('2d');ctx.drawImage(canvas,0,0);const data=ctx.getImageData(0,0,copy.width,copy.height).data;let hash=2166136261,visible=0;for(let i=0;i<data.length;i++){hash=Math.imul(hash^data[i],16777619);if(i%4===3&&data[i])visible++}return {hash:hash>>>0,visible,width:copy.width,height:copy.height}};
 try{
 await action('progress:driver_start:start');
 await invoke('plugin:event|listen',{event:'loop-work-close-cancelled',target:{kind:'Any'},handler:window.__TAURI_INTERNALS__.transformCallback(event=>cancelEvents.push(event.payload))});
 await action('progress:driver_listen_ready:done');
 await check('real_native_bootstrap_and_explicit_task_states',async()=>{
  const b=await invoke('bootstrap');ensure(b.ready&&(b.scope.project_id===null||b.scope.project_id===fixture.project_id),'native requested scope mismatch');const projects=await api('/api/projects');ensure(projects.status===200&&projects.body.projects.length===1&&projects.body.projects[0].id===fixture.project_id,'effective backend project scope mismatch');ensure((await api('/api/board?project_id=not-the-installed-target')).status>=400,'effective backend foreign scope accepted');
  const row=await until(()=>document.querySelector('[data-project-id="'+fixture.project_id+'"]'),'실제 프로젝트 표시 없음');row.click();
  await until(()=>cards().length===fixture.expected_task_ids.length&&document.querySelector('#board')?.getAttribute('aria-busy')==='false','실제 작업 카드 목록 불일치');
  const r=await api('/api/board?include_closed=1'+q.replace('?','&'));ensure(r.status===200,'보드 API 실패');const actual=r.body.tasks.map(t=>t.id).sort();ensure(JSON.stringify(actual)===JSON.stringify([...fixture.expected_task_ids].sort()),'보드 ID와 원본 fixture 불일치');
  ensure(!cards().some(n=>n.dataset.taskId===fixture.hidden_task),'ordinary 작업 노출');ensure((await api('/api/tasks/'+fixture.hidden_task+q)).status!==200,'숨긴 작업 직접 조회 허용');
  for(const state of ['ready','working','review','completed','stopped'])ensure(document.querySelector('.column[data-state="'+state+'"] .task-card'),'상태 열 실제 카드 없음: '+state);
  return {tasks:actual.length,hidden_task_rejected:true,scope:b.scope};
 });
 await check('native_echarts_pixels_and_real_counts',async()=>{
  await click('상태 집계');await sleep(600);const chart=document.querySelector('[role="dialog"] canvas');const p=pixels(chart);ensure(p.visible>0,'ECharts 실제 픽셀 없음');const r=await api('/api/board?include_closed=1'+q.replace('?','&'));const cells=Array.from(document.querySelectorAll('[role="dialog"] tbody td')).map(n=>Number(n.textContent));ensure(cells.reduce((a,b)=>a+b,0)===r.body.tasks.length,'집계 수치 불일치');await click('닫기');return {...p,total:cells.reduce((a,b)=>a+b,0)};
 });
 await check('native_offline_rive_actual_frames_and_live_reduced_motion',async()=>{
  await until(()=>document.querySelector('.runtime-indicator')?.dataset.riveReady==='true','Rive 실제 준비 실패');const frames=[];for(let i=0;i<8;i++){await sleep(160);frames.push(pixels(document.querySelector('.runtime-indicator canvas')))}ensure(frames.every(p=>p.visible>0)&&new Set(frames.map(p=>p.hash)).size>1,'Rive 시각 효과 변화 없음');
  window.__loopNativeQaReduced(true);await until(()=>document.querySelector('.runtime-indicator')?.dataset.reducedMotion==='true','live reduced-motion 반영 실패');await sleep(250);const a=pixels(document.querySelector('.runtime-indicator canvas'));await sleep(300);const b=pixels(document.querySelector('.runtime-indicator canvas'));ensure(a.hash===b.hash,'reduced-motion 시 픽셀 정지 안 됨');window.__loopNativeQaReduced(false);return {distinct_frames:new Set(frames.map(p=>p.hash)).size,reduced_frozen:true,preference_source:'QA-only matchMedia change; OS settings unchanged'};
 });
 const card=await until(()=>cards().find(n=>n.dataset.taskId===fixture.edit_task&&!n.disabled),'편집 작업 카드 없음');card.click();await until(()=>document.querySelector('.wiki-editor input[aria-label="위키 표시 이름"]'),'실제 위키 편집기 없음');
 await check('native_flow_real_nodes_and_drawn_edges',async()=>{await click('기록 흐름');const nodes=await until(()=>document.querySelectorAll('.react-flow__node').length>1&&document.querySelector('.react-flow__edge-path'),'실제 Flow 렌더 없음');const r=await api('/api/tasks/'+fixture.edit_task+q);const count=1+(r.body.documents||[]).length+(r.body.requests||[]).length;ensure(document.querySelectorAll('.react-flow__node').length===count,'Flow 원본 관계 수 불일치');ensure(Array.from(document.querySelectorAll('.react-flow__node')).every(n=>n.getBoundingClientRect().width>0),'Flow 노드 배치 없음');const paths=Array.from(document.querySelectorAll('.react-flow__edge-path'));ensure(paths.every(p=>p.getTotalLength()>0),'Flow 선 geometry 없음');await click('위키 편집');return {nodes:count,drawn_edges:paths.length};});
 await click('Markdown 원문');
 await check('native_rust_bridge_actual_dom_save_and_cas',async()=>{const before=await wiki();const marker='네이티브 WebView 실제 저장 · '+fixture.marker;input(document.querySelector('.wiki-editor .markdown-source'),before.body_markdown+'\n\n'+marker+'\n');await saved({marker});const after=await wiki();ensure(after.body_markdown.includes(marker),'실제 API 저장 결과 없음');ensure(after.revision!==before.revision,'CAS revision 변화 없음');const conflict=await api(path,{operation_id:crypto.randomUUID(),expected_revision:before.revision,title:before.title,body_markdown:'덮어쓰면 안 되는 오래된 본문'});ensure(conflict.status===409,'오래된 CAS 저장 차단 안 됨');ensure((await wiki()).revision===after.revision,'CAS 실패가 본문 변경');return {revision_changed:true,stale_write_status:conflict.status,marker};});
 await check('native_controls_preserve_exact_original_text',async()=>{await click('실행 기록');const text='네이티브 제어 원문\n같은 문장 · '+fixture.marker;input(document.getElementById('control-text-'+fixture.edit_task),text);await click('일시정지 요청');await until(async()=>{const r=await api('/api/tasks/'+fixture.edit_task+q);return r.body.control?.paused},'pause 실제 기록 없음');input(document.getElementById('control-text-'+fixture.edit_task),text);await click('피드백 재개');await until(async()=>{const r=await api('/api/tasks/'+fixture.edit_task+q);return r.body.control&&!r.body.control.paused},'resume 실제 기록 없음');const r=await api('/api/tasks/'+fixture.edit_task+q);const history=r.body.control.history;ensure(JSON.stringify(history).includes(text.replaceAll('\n','\\n')),'제어 원문 보존 안 됨');return {pause_resume:true,original:text};});
 await check('native_original_human_answer_and_separate_explicit_execute',async()=>{
  const card=await until(()=>cards().find(n=>n.dataset.taskId===fixture.respond_task&&!n.disabled),'응답 작업 없음');card.click();await until(()=>document.querySelector('.task-card.selected')?.dataset.taskId===fixture.respond_task,'응답 작업 전환 실패');await click('질문·답변');const field=await until(()=>document.getElementById('response-'+fixture.respond_id),'응답 입력 없음');const text='네이티브 사람 응답 원문\n'+fixture.marker;input(field,text);await click('답변 기록',field.closest('.request'));
  await until(async()=>{const r=await api('/api/requests/'+fixture.respond_id+q);return r.body.record?.response?.text===text},'실제 응답 원문 보존 실패');
  const blocked=await api('/api/tasks/'+fixture.blocked_task+q);ensure(blocked.body.record.phase==='blocked','수동 확인 전 blocked 상태 아님');const request=await api('/api/requests/'+fixture.execute_id+q);const row=request.body;
  const responded=await api('/api/requests/'+fixture.execute_id+'/respond'+q,{expected_revision:row.record.revision,expected_vault_revision:row.vault_revision,response:{decision:'resolved',text:'수동 해소 원문 '+fixture.marker}});ensure(responded.status===200&&responded.body.action_committed,'수동 응답 실패');ensure((await api('/api/tasks/'+fixture.blocked_task+q)).body.record.phase==='blocked','응답만으로 자동 재개됨');
  const current=(await api('/api/requests/'+fixture.execute_id+q)).body;const executed=await api('/api/requests/'+fixture.execute_id+'/execute'+q,{expected_revision:current.record.revision,expected_vault_revision:current.vault_revision});ensure(executed.status===200&&executed.body.action_committed,'명시 실행 실패');ensure((await api('/api/tasks/'+fixture.blocked_task+q)).body.record.phase===fixture.resume_phase,'허용된 원래 단계 재개 상태 불일치');
  const edit=await until(()=>cards().find(n=>n.dataset.taskId===fixture.edit_task&&!n.disabled),'편집 작업 복귀 없음');edit.click();await until(()=>document.querySelector('.task-card.selected')?.dataset.taskId===fixture.edit_task&&document.querySelector('.wiki-editor'),'편집 문맥 복귀 실패');await click('Markdown 원문');return {original_text:text,response_did_not_resume:true,separate_execute:true};
 });
 await check('native_window_close_hide_and_same_window_reopen',async()=>{await action('window_close');await until(async()=>!(await action('status')).visible,'원래 창이 hide 되지 않음');await action('window_reopen');ensure((await action('status')).visible,'원래 창 복원 실패');ensure(document.querySelector('.wiki-editor'),'복원 뒤 편집 문맥 소실');return {programmatic_native_close:true,shared_reopen_handler:true,physical_dock_click:false};});
 await check('native_dirty_composition_quit_cancel_preserves_draft',async()=>{const title=document.querySelector('.wiki-editor input[aria-label="위키 표시 이름"]');const original=(await wiki()).title;const draft='입력 조합 중인 원문 '+fixture.marker;title.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));input(title,draft);const count=(await confirmations()).length;await action('request_quit');await until(async()=>(await confirmations()).length>count,'조합 중 종료 보호 없음');ensure(title.value===draft,'조합 원문 소실');ensure((await wiki()).title===original,'조합 중 자동 저장 발생');title.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));await saved({title:draft});return {draft_preserved:true,actual_dialog_callback_cancel:true,physical_gui_input_verified:false};});
 await check('native_committed_lost_response_poll_and_same_operation_recovery',async()=>{await action('drop_next_wiki_response');const before=await wiki();const marker='응답 유실 실제 저장 '+fixture.marker;input(document.querySelector('.markdown-source'),before.body_markdown+'\n\n'+marker);await until(()=>document.querySelector('.wiki-editor')?.dataset.saveState==='uncertain','실제 저장 후 유실 상태 없음');const committed=await wiki();await sleep(5500);await click('지금 저장');await saved();const after=await wiki();ensure(after.body_markdown.includes(marker),'유실 응답 재확인 후 본문 소실');ensure(after.revision===committed.revision,'유실 재시도가 중복 commit을 만들었습니다.');return {real_http_before_lost_ack:true,poll_before_retry:true,marker};});
 await check('native_hung_save_quit_deadline_preserves_draft',async()=>{await action('delay_next_wiki_response');const before=await wiki();const marker='응답 지연 종료 보호 '+fixture.marker;input(document.querySelector('.markdown-source'),before.body_markdown+'\n\n'+marker);await until(()=>document.querySelector('.wiki-editor')?.dataset.saveState==='saving','지연 저장 진입 없음');await sleep(1200);const count=(await confirmations()).length,start=Date.now();await action('request_quit');await until(async()=>(await confirmations()).length>count,'지연 저장 종료 보호 없음',8000);ensure(Date.now()-start<7200,'종료 보호가 유한하지 않음');ensure(document.querySelector('.markdown-source').value.includes(marker),'지연 저장 초안 소실');const closeElapsed=Date.now()-start;await saved({marker});return {bounded_close_ms:closeElapsed,real_http_then_delay:true,draft_preserved:true};});
 await check('native_close_actual_flush_await_blocks_empty_execute_until_matching_cancel',async()=>{
  const item=fixture.close_race_case;ensure(item?.id&&item.task_id,'독립 종료 경합 fixture 없음');
  const req='/api/requests/'+item.id,taskPath='/api/tasks/'+item.task_id+q,wikiPath='/api/tasks/'+item.task_id+'/wiki'+q;
  const initial=(await api(req+q)).body,original='종료 경합 수동 해소 원문 · '+fixture.marker;
  const response=await api(req+'/respond'+q,{expected_revision:initial.record.revision,expected_vault_revision:initial.vault_revision,response:{decision:'resolved',text:original}});
  ensure(response.status===200&&response.body.action_committed,'경합 수동 해소 응답 실패');
  ensure((await api(taskPath)).body.record.phase==='blocked','응답만으로 경합 작업 자동 실행');
  const answered=(await api(req+q)).body.record;
  const card=await until(()=>cards().find(n=>n.dataset.taskId===item.task_id&&!n.disabled),'경합 작업 카드 없음');card.click();
  await until(()=>document.querySelector('.task-card.selected')?.dataset.taskId===item.task_id&&document.querySelector('.wiki-editor'),'경합 작업 위키 선택 실패');
  await click('Markdown 원문');const before=(await api(wikiPath)).body,marker='종료 준비의 실제 flush 저장 · '+fixture.marker;
  await action('delay_next_wiki_response');const count=(await confirmations()).length;
  // No awaited IPC or timer between dirty input and native quit. prepareClose,
  // not the one-second autosave timer, starts the actual held POST here.
  input(document.querySelector('.markdown-source'),before.body_markdown+'\n\n'+marker);
  const quit=action('request_quit');await quit;
  await until(()=>document.documentElement.dataset.closePreparing==='true'&&document.querySelector('.wiki-editor')?.dataset.saveState==='saving','종료 준비의 실제 flush/saving 상태 없음');
  await until(async()=>(await api(wikiPath)).body.body_markdown.includes(marker),'실제 close flush POST200 접수 없음');
  ensure((await confirmations()).length===count,'경합 입력 시도 전에 종료 확인이 끝났습니다.');
  const ticket=(await action('status')).events.filter(e=>e.event==='close_requested').at(-1).id;
  const questions=Array.from(document.querySelectorAll('[role=tab]')).find(n=>n.textContent.trim()==='질문·답변');ensure(questions,'경합 질문 탭 없음');
  questions.focus();questions.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));questions.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',bubbles:true}));await sleep(100);
  const tabActivated=questions.getAttribute('aria-selected')==='true';let executeAttempted=false,disabledAtAttempt=null;
  if(tabActivated){
   const field=await until(()=>document.getElementById('response-'+item.id),'경합 원래 응답 필드 없음');ensure(field.value==='','경합 실행은 초안이 비어 있어야 합니다.');
   const execute=Array.from(field.closest('.request').querySelectorAll('button')).find(n=>n.textContent.trim()==='허용된 작업 재개 실행');ensure(execute,'경합 실제 실행 버튼 없음');
   disabledAtAttempt=execute.disabled;execute.click();executeAttempted=true;
  }else{
   const activeWiki=Array.from(document.querySelectorAll('[role=tab]')).find(n=>n.textContent.trim()==='위키 편집');ensure(activeWiki?.getAttribute('aria-selected')==='true'&&document.querySelector('.markdown-source')?.value.includes(marker),'종료 준비 중 편집 문맥 소실');
  }
  await sleep(150);const whileClosing=(await api(req+q)).body.record;
  ensure(!whileClosing.execution&&(await api(taskPath)).body.record.phase==='blocked','종료 준비 중 실제 빈 입력 실행이 차단되지 않았습니다.');
  await until(async()=>(await confirmations()).length>count,'실제 flush 대기 경합의 종료 확인 없음',8000);
  const callback=(await confirmations()).at(-1);ensure(callback.request_id===ticket&&callback.accepted===false,'동일 종료 ticket 실제 취소 callback 없음');
  ensure(callback.elapsed_ms>=3300&&callback.elapsed_ms<5000,'실제 3.5초 flush await 뒤 native 확인 시간 근거 불일치');
  await until(()=>cancelEvents.some(e=>e.request_id===ticket)&&document.documentElement.dataset.closePreparing==='false','동일 ticket 실제 취소 이벤트/UI 해제 없음',2500);
  await click('질문·답변');const field=await until(()=>document.getElementById('response-'+item.id),'취소 후 원래 응답 필드 없음');ensure(field.value==='','취소 후 빈 입력 상태 변경');
  await click('허용된 작업 재개 실행',field.closest('.request'));
  await until(async()=>(await api(req+q)).body.record.execution?.state==='executed','취소 후 원래 요청 명시 실행 실패');
  const executed=(await api(req+q)).body.record;
  ensure(executed.revision===answered.revision+2&&executed.response?.text===original,'원래 실행 payload/계보/응답 원문 변경');
  ensure((await api(taskPath)).body.record.phase===item.expected_phase,'취소 후 원래 단계 복원 실패');
  await click('위키 편집');await until(()=>document.querySelector('.markdown-source'),'경합 저장 초안 복구 없음');
  await until(async()=>document.querySelector('.wiki-editor')?.dataset.saveState==='saved'&&(await api(wikiPath)).body.body_markdown.includes(marker),'경합 뒤 실제 위키 저장/초안 보존 실패',25000);
  await until(async()=>(await window.LoopDesktop.prepareClose()).safe===true,'경합 해소 후 종료 안전성 확인 실패',15000);
  return {actual_close_started_dirty_flush:true,actual_flush_await_ms:callback.elapsed_ms,real_wiki_post_200_then_delivery_delay:true,tab_activated_during_close:tabActivated,execute_attempted:executeAttempted,disabled_at_attempt:disabledAtAttempt,empty_response_draft:true,execute_blocked_before_cancel:true,same_ticket_cancel_event_received:true,explicit_execute_after_cancel:true,terminal_revision_delta:2,original_response_preserved:true,wiki_marker_preserved:true,physical_gui_input_verified:false};
 });
 ensure(Array.isArray(fixture.execute_cases)&&fixture.execute_cases.length===2,'독립 빈 입력 실행 fixture 2개가 필요합니다.');
 for(const item of fixture.execute_cases){
  await check('native_empty_draft_execute_'+item.mode+'_ack_quit_cancel_and_reconciliation',async()=>{
   const taskPath='/api/tasks/'+item.task_id+q,requestPath='/api/requests/'+item.id;
   const initial=(await api(requestPath+q)).body;
   const original='합성 수동 해소 원문 · '+item.mode+' · '+fixture.marker;
   const answer=await api(requestPath+'/respond'+q,{expected_revision:initial.record.revision,expected_vault_revision:initial.vault_revision,response:{decision:'resolved',text:original}});
   ensure(answer.status===200&&answer.body.action_committed,'실제 수동 해소 응답 실패');
   ensure((await api(taskPath)).body.record.phase==='blocked','응답만으로 자동 실행됨');
   const answered=(await api(requestPath+q)).body.record;
   const card=await until(()=>cards().find(n=>n.dataset.taskId===item.task_id&&!n.disabled),'빈 입력 실행 작업 없음');card.click();
   await until(()=>document.querySelector('.task-card.selected')?.dataset.taskId===item.task_id,'빈 입력 실행 작업 선택 실패');
   await click('질문·답변');
   const field=await until(()=>document.getElementById('response-'+item.id),'빈 입력 실행 원문 필드 없음');
   ensure(field.value==='','실행 전 사용자 초안이 비어 있지 않습니다.');
   await until(()=>button('허용된 작업 재개 실행',field.closest('.request')),'실제 명시 실행 버튼 없음');
   await action(item.mode==='delay'?'delay_next_execute_response':'drop_next_execute_response');
   const count=(await confirmations()).length;
   await click('허용된 작업 재개 실행',field.closest('.request'));
   await until(async()=>{const r=await api(requestPath+q);return r.body.record.execution?.state==='executed'},'응답 지연 전 실제 실행 접수/완료 없음');
   const committed=(await api(requestPath+q)).body.record;
   ensure(committed.revision===answered.revision+2,'실제 claim/terminal 실행 계보 불일치');
   ensure(committed.response?.text===original,'실행이 원래 응답 원문을 변경했습니다.');
   ensure(document.getElementById('response-'+item.id)?.value==='','종료 보호가 사용자 초안에 의존합니다.');
   if(item.mode==='drop')await until(async()=>(await action('status')).board_hold_state===2,'실제 periodic board GET200 보류 관찰 없음',10000);
   await action('request_quit');
   await until(async()=>(await confirmations()).length>count,'빈 입력 실행 접수 불확실성의 실제 종료 보호 없음',8000);
   const confirmation=(await confirmations()).at(-1);
   ensure(confirmation.accepted===false,'실제 종료 확인 취소 실패');
   if(item.mode==='drop')ensure((await action('status')).board_hold_state===2,'실제 sheet 취소 전에 접수 확인 응답이 이미 전달되었습니다.');
   ensure((await action('status')).visible,'취소 후 native 창이 사라졌습니다.');
   await until(async()=>(await window.LoopDesktop.prepareClose()).safe===true,'실제 terminal 계보 재확인 후 종료 보호 해제 없음',25000);
   const final=(await api(requestPath+q)).body.record;
   ensure(final.revision===committed.revision&&JSON.stringify(final.execution)===JSON.stringify(committed.execution),'재확인이 실행을 중복 접수했습니다.');
   ensure(final.response?.text===original,'재확인 뒤 원문 응답 변경');
   ensure((await api(taskPath)).body.record.phase===item.expected_phase,'원래 작업 단계 복원 실패');
   ensure(document.getElementById('response-'+item.id)?.value==='','빈 입력 실행 확인 뒤 초안 생성/소실 혼동');
   return {real_post_committed_before_fault:true,empty_response_draft:true,original_response_preserved:true,terminal_revision_delta:2,execute_not_reposted:true,actual_sheet_cancel_callback:true,board_get_held_before_cancel:item.mode==='drop',reconciled_close_safe:true,physical_gui_input_verified:false};
  });
 }
 for(const kind of ['response','control']){
  await check('native_empty_'+kind+'_ime_before_quit_preserved_until_compositionend',async()=>{
   const taskId=kind==='response'?fixture.respond_task:fixture.edit_task;
   observeSelection('card_wait_start',taskId,null);
   const card=await until(()=>cards().find(n=>n.dataset.taskId===taskId&&!n.disabled),'IME 대상 작업 카드 없음');
   observeSelection('before_click',taskId,card);card.click();observeSelection('after_click',taskId,card);
   await until(()=>{observeSelection('selection_wait',taskId,card);return document.querySelector('.task-card.selected')?.dataset.taskId===taskId},'IME 대상 작업 선택 실패');
   observeSelection('selection_confirmed',taskId,card);
   await click(kind==='response'?'질문·답변':'실행 기록');
   const fieldId=kind==='response'?'response-'+fixture.respond_id:'control-text-'+taskId;
   const field=await until(()=>document.getElementById(fieldId),'빈 committed IME 원문 필드 없음');
   ensure(field.value==='','IME 검사는 committed 원문이 빈 상태여야 합니다.');
   ensure((await window.LoopDesktop.prepareClose()).safe===true,'조합 시작 전 다른 미해결 종료 보호가 있습니다.');
   const recordPath=kind==='response'?'/api/requests/'+fixture.respond_id+q:'/api/tasks/'+taskId+q;
   const original=(await api(recordPath)).body;
   const stable=row=>JSON.stringify(kind==='response'?row.record:{record:row.record,control_version:row.control?.control_version,history:row.control?.history});
   const before=stable(original),count=(await confirmations()).length;
   field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:''}));
   await action('request_quit');
   const ticket=(await action('status')).events.filter(e=>e.event==='close_requested').at(-1).id;
   await until(async()=>(await confirmations()).length>count,'빈 committed '+kind+' 조합의 실제 종료 확인 없음',8000);
   const callback=(await confirmations()).at(-1);ensure(callback.request_id===ticket&&callback.accepted===false,'IME 동일 ticket 실제 취소 callback 없음');
   await until(()=>cancelEvents.some(e=>e.request_id===ticket)&&document.documentElement.dataset.closePreparing==='false','IME 실제 취소 이벤트/UI 해제 없음',2500);
   ensure((await action('status')).visible&&document.getElementById(fieldId)===field&&field.value==='','취소 뒤 원문 입력 필드/빈 값 소실');
   const stillComposing=await window.LoopDesktop.prepareClose();
   ensure(stillComposing.safe===false,'compositionend 전 활성 IME 보호가 소실되었습니다.');
   ensure(stable((await api(recordPath)).body)===before,'IME/종료 확인이 원문을 자동 제출하거나 실행했습니다.');
   field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:''}));
   await until(async()=>(await window.LoopDesktop.prepareClose()).safe===true,'빈 compositionend 이후 종료 보호 해제 없음',5000);
   ensure(field.value===''&&stable((await api(recordPath)).body)===before,'빈 조합 종료가 DB 원문/제어/실행을 변경했습니다.');
   return {field_kind:kind,committed_value_empty:true,synthetic_composition_started_before_quit:true,actual_sheet_cancel_callback:true,same_ticket_cancel_event:true,field_and_active_composition_preserved:true,compositionend_empty_close_safe:true,no_automatic_submission_or_execution:true,physical_gui_input_verified:false,native_os_ime_verified:false};
  });
 }
 await check('native_actual_unresponsive_webview_six_second_timeout_and_stale_ack',async()=>{const count=(await confirmations()).length;await action('unresponsive_then_quit');const all=await until(async()=>{const c=await confirmations();return c.length>count?c:null},'native six-second timeout 없음',12000);const last=all.at(-1);ensure(last.elapsed_ms>=5800&&last.elapsed_ms<7300,'native timeout elapsed 불일치');await sleep(300);ensure((await confirmations()).length===count+1,'같은 종료 요청의 확인 중복');return {elapsed_ms:last.elapsed_ms,stale_ack_did_not_quit:true,actual_dialog_callback_cancel:true,physical_gui_input_verified:false};});
 await invoke('native_qa_report',{report:{passed:true,checks,measurements,real_tauri_ipc:true,api_proxy_shim:false}});
 }catch(error){try{await invoke('native_qa_report',{report:{passed:false,checks,dom_state:domState(),selection_trace:{events:selectionTrace,dropped_events:selectionTraceDropped,fixture_only:true},error:String(error?.message||error)+'\n'+String(error?.stack||''),real_tauri_ipc:true,api_proxy_shim:false}})}catch(_){console.error('native QA 결과 저장 실패')}}
})();
