import { ArrowUpRight, BarChart3, CheckCircle2, CircleAlert, CircleDashed, FileText, FolderOpen, Layers3, ListTodo, RefreshCw, Search, SquareMousePointer } from "lucide-react";
import { humanKey, humanReceiptMatches, unchangedHumanRequest, type PendingHuman } from "./humanReceipts";
import {
  controlKey,
  controlDraftKey,
  receiptMatches,
  type PendingControl,
} from "./controlReceipts";
import { useLiveReducedMotion } from "./useReduced";
import { useCallback, useEffect, useRef, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { MotionConfig, motion } from "motion/react";
import { listen } from "@tauri-apps/api/event";
import {
  api,
  ApiError,
  bootstrap,
  ready,
  finishClose,
  openObsidian,
  operationId,
} from "./bridge";
import { Button } from "./components/ui/button";
import { Wiki, editors } from "./Wiki";
import { AuditFlow, RuntimeIndicator, StatusChart } from "./Visualizations";
import { states, type Project, type Row, type BoardData } from "./types";
const drafts = new Map<string, string>();
const draftCompositions = new Set<string>();
function setDraft(key: string, value: string) {
  drafts.set(key, value);
  window.dispatchEvent(new CustomEvent("loop-draft", { detail: key }));
}
const pendingOps = new Map<string, PendingControl>();
const committed = new Set<string>();
const pendingHuman = new Map<string, PendingHuman>();
let closePreparing=0, closeMutationSerial=0;
const nativeCloseGuards=new Map<number,()=>void>();
for(const type of ['click','beforeinput','paste','keydown'])document.addEventListener(type,event=>{
 if(closePreparing){event.preventDefault();event.stopImmediatePropagation();}
},true);
for(const type of ['input','change','compositionstart','compositionend'])document.addEventListener(type,()=>{if(closePreparing)closeMutationSerial++;},true);
function closeGuard() {
 closePreparing++; document.documentElement.dataset.closePreparing='true';
 let released=false; return ()=>{if(released)return;released=true;closePreparing--;document.documentElement.dataset.closePreparing=String(closePreparing>0);};
}
function closeBlocker() {
 if(pendingHuman.size) return "사람 요청의 전송 또는 접수 확인이 끝나지 않았습니다. 원문을 보존했습니다.";
 if(pendingOps.size) return "이전 제어 요청의 접수 여부를 확인해야 합니다. 원문을 보존했습니다.";
 if(draftCompositions.size) return "응답 또는 제어 원문의 조합이 진행 중입니다. 입력을 보존했습니다.";
 if([...editors.values()].some(ed=>ed.composing||ed.conflict||ed.uncertain)) return "조합·충돌 또는 저장 응답 확인이 필요합니다.";
 return null;
}
export async function prepareClose() {
 const release=closeGuard(), serial=closeMutationSerial;let timer:ReturnType<typeof setTimeout>|undefined;
 try {
  const initial=closeBlocker();if(initial)return {safe:false,reason:initial};
  const result=await Promise.race([
   Promise.all([...editors.values()].map(ed=>ed.flush())).then(()=>true),
   new Promise<boolean>(resolve=>{timer=setTimeout(()=>resolve(false),3500);}),
  ]);
  if(closeMutationSerial!==serial)return {safe:false,reason:"종료 확인 중 입력이 변경됐습니다. 계속 편집하며 원문을 확인하세요."};
  const final=closeBlocker();if(final)return {safe:false,reason:final};
  if(!result||[...editors.values()].some(ed=>ed.dirty||ed.saving)) return {safe:false,reason:"아직 저장을 확인하지 못했습니다."};
  if([...drafts.values()].some(value=>value.trim())) return {safe:false,reason:"제출하지 않은 원문 입력이 있습니다."};
  return {safe:true};
 } catch {return {safe:false,reason:"저장 확인에 실패했습니다. 초안을 보존했습니다."};}
 finally {if(timer)clearTimeout(timer);release();}
}

function Markdown({ body }: { body: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (host.current) window.LoopMarkdown.render(body, host.current);
  }, [body]);
  return <article ref={host} className="markdown-preview" />;
}
function DraftInput({
  id,
  label,
  disabled = false,
  storageKey = id,
}: {
  id: string;
  label: string;
  disabled?: boolean;
  storageKey?: string;
}) {
  const [value, setValue] = useState(drafts.get(storageKey) || "");
  const [composing,setComposing]=useState(draftCompositions.has(storageKey));
  useEffect(() => {
    setComposing(draftCompositions.has(storageKey));
    const update = () => setValue(drafts.get(storageKey) || "");
    update();
    window.addEventListener("loop-draft", update);
    return () => window.removeEventListener("loop-draft", update);
  }, [id, storageKey]);
  return (
    <label>
      {label}
      <textarea
        id={id}
        disabled={disabled}
        value={value}
        data-composing={composing}
        onCompositionStart={()=>{draftCompositions.add(storageKey);setComposing(true);}}
        onCompositionEnd={()=>{draftCompositions.delete(storageKey);setComposing(false);}}
        onChange={(e) => {
          setDraft(storageKey, e.target.value);
          setValue(e.target.value);
        }}
      />
    </label>
  );
}
export function App() {
  const reduced = useLiveReducedMotion();
  const [bootComplete, setBootComplete] = useState(false);
  const readyAck = useRef(false);
  const [projects, setProjects] = useState<Project[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState("name"),
    [data, setData] = useState<BoardData>({
      tasks: [],
      requests: [],
      warnings: [],
    }),
    [selected, setSelected] = useState<Row | null>(null),
    [tab, setTab] = useState("wiki"),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [showChart, setShowChart] = useState(false),
    [connected, setConnected] = useState(false),
    [projectEditing, setProjectEditing] = useState(false),
    [viewWarning, setViewWarning] = useState(""),
    [historyDoc, setHistoryDoc] = useState<{
      projectId: string;
      taskId: string;
      role: string;
      path: string;
      body: string;
    } | null>(null);
  const historyEpoch=useRef(0);
  const selectionInFlight = useRef<{ epoch: number; projectId: string | undefined } | null>(null);
  const epoch = useRef(0),
    inflight = useRef(false),
    scope = useRef<any>({});
  const current = useRef({ project, selected, busy });
  current.current = { project, selected, busy };
  const scoped = useCallback(
    (path: string, p = project?.id) =>
      path +
      (path.includes("?") ? "&" : "?") +
      "project_id=" +
      encodeURIComponent(p || ""),
    [project?.id],
  );
  const load = useCallback(async () => {
    if (inflight.current || !current.current.project) return;
    inflight.current = true;
    const p = current.current.project.id,
      e = ++epoch.current;
    setLoading(true);
    try {
      const next = await api<BoardData>(
        "/api/board?include_closed=1&project_id=" + encodeURIComponent(p),
      );
      if (e !== epoch.current) return;
      setData(next);
      for (const [key, op] of pendingHuman) {
        if (op.projectId !== p || op.inFlight) continue;
        const row = next.requests.find(r=>r.id===op.requestId) || next.tasks.flatMap(t=>t.requests||[]).find(r=>r.id===op.requestId);
        if (row && row.fresh && !row.modified && humanReceiptMatches(op,row.record)) {
          pendingHuman.delete(key);
          if(op.action==='execute') committed.add(op.requestId);
          if(op.action==='respond' && !draftCompositions.has('response-'+op.requestId) && drafts.get('response-'+op.requestId)===op.payload.response?.text) setDraft('response-'+op.requestId,'');
        }
      }
      setConnected(true);
      setSelected((old) => {
        if (!old) return null;
        const found = next.tasks.find((t) => t.id === old.id);
        if (!found)
          setViewWarning(
            "선택한 작업 문서를 읽을 수 없습니다. 초안은 유지하며 실행 제어를 숨겼습니다.",
          );
        return found || null;
      });
      for (const t of next.tasks) {
        for (const h of t.control?.history || []) {
          for (const [k, v] of pendingOps)
            if (
              v.projectId === p &&
              v.taskId === t.id &&
              receiptMatches(v, h)
            ) {
              pendingOps.delete(k);
              const draftKey = controlDraftKey(p, t.id);
              if (!draftCompositions.has(draftKey) && drafts.get(draftKey) === v.payload.text)
                setDraft(draftKey, "");
            }
        }
      }
    } catch (error) {
      if (e === epoch.current) {
        setError((error as Error).message);
        setViewWarning(
          "조회에 실패해 실행 제어를 숨겼습니다. 초안은 보존됩니다.",
        );
        setProjectEditing(false);
        setSelected(null);
        setConnected(false);
      }
    } finally {
      setLoading(false);
      inflight.current = false;
      if (current.current.project?.id !== p) queueMicrotask(() => load());
    }
  }, []);
  useEffect(() => {
    let dead = false;
    (async () => {
      let b = await bootstrap();
      for (let i = 0; !b.ready && i < 120; i++) {
        await new Promise((r) => setTimeout(r, 250));
        b = await bootstrap();
      }
      return b;
    })()
      .then(async (b) => {
        scope.current = b.scope;
        if (!b.ready)
          throw new Error(
            b.error || "앱 연결 준비 시간이 초과됐습니다. 앱을 다시 여세요.",
          );
        const res = await api<{ projects: Project[] }>(
          "/api/projects?query=&sort=name",
        );
        if (dead) return;
        setProjects(res.projects);
        setProject(res.projects[0] || null);
        setConnected(true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBootComplete(true));
    const cancelled=listen<{request_id:number}>("loop-work-close-cancelled",event=>{
      nativeCloseGuards.get(event.payload.request_id)?.();nativeCloseGuards.delete(event.payload.request_id);
    });
    const unlisten=listen<{request_id:number}>("loop-work-close-request",async event=>{
      const id=event.payload.request_id;if(nativeCloseGuards.has(id))return;
      nativeCloseGuards.set(id,closeGuard());
      try{const result=await prepareClose();await finishClose(id,result.safe,"reason" in result?result.reason:undefined);}
      catch(error){nativeCloseGuards.get(id)?.();nativeCloseGuards.delete(id);setError("종료 확인에 실패했습니다. 계속 편집할 수 있습니다. "+String(error));}
    });
    window.LoopDesktop = { prepareClose };
    return () => {
      dead = true;
      unlisten.then((f) => f());
      cancelled.then(f=>f());
      for(const release of nativeCloseGuards.values())release();nativeCloseGuards.clear();
    };
  }, []);
  useEffect(() => {
    if (bootComplete && !readyAck.current) {
      readyAck.current = true;
      ready().catch((e) => setError(String(e)));
    }
  }, [bootComplete]);
  useEffect(() => {
    const refresh = () =>
      api<{ projects: Project[] }>(
        "/api/projects?query=" + encodeURIComponent(query) + "&sort=" + sort,
      )
        .then((v) => {
          setProjects(v.projects);
          setProject((old) =>
            old ? v.projects.find((p) => p.id === old.id) || old : null,
          );
        })
        .catch((e) => setError(e.message));
    window.addEventListener("wiki-saved", refresh);
    return () => window.removeEventListener("wiki-saved", refresh);
  }, [query, sort]);
  useEffect(() => {
    let dead = false;
    const timer = setTimeout(
      () =>
        api<{ projects: Project[] }>(
          "/api/projects?query=" + encodeURIComponent(query) + "&sort=" + sort,
        )
          .then((v) => {
            if (!dead) setProjects(v.projects);
          })
          .catch((e) => setError(e.message)),
      200,
    );
    return () => {
      dead = true;
      clearTimeout(timer);
    };
  }, [query, sort]);
  useEffect(() => {
    epoch.current++;
    setSelected(null);
    setHistoryDoc(null);
    setData({ tasks: [], requests: [], warnings: [] });
    if (project) load();
  }, [project?.id, load]);
  useEffect(() => {
    const id = setInterval(() => {
      if (
        document.visibilityState === "visible" &&
        !current.current.busy &&
        !(selectionInFlight.current && selectionInFlight.current.epoch === epoch.current && selectionInFlight.current.projectId === current.current.project?.id) &&
        !document.querySelector('[data-composing="true"]')
      )
        load();
    }, 5000);
    return () => clearInterval(id);
  }, [load]);
  async function select(row: Row) {
    if (loading || busy || closePreparing) return;
    const e = ++epoch.current;
    const selection = { epoch: e, projectId: project?.id };
    selectionInFlight.current = selection;
    try {
      const detail = await api<Row>(
        scoped("/api/tasks/" + encodeURIComponent(row.id)),
      );
      if (e === epoch.current) {
        setSelected(detail);
        setHistoryDoc(null);
        setProjectEditing(false);
        setViewWarning("");
        setTab("wiki");
      }
    } catch (error) {
      if (e === epoch.current) {
        setSelected(null);
        setError((error as Error).message);
      }
    } finally {
      if (selectionInFlight.current === selection) selectionInFlight.current = null;
    }
  }
  async function mutate(
    row: Row,
    action: "respond" | "execute",
    decision?: string,
  ) {
    if (!project || !selected || busy || closePreparing) return;
    const requestKey=humanKey(project.id,row.id);
    let op=pendingHuman.get(requestKey);
    const key="response-"+row.id;
    if(op?.inFlight)return;
    if(!op && !row.writable)return;
    if(!op) {
      const submitted=drafts.get(key)||"";
      op={projectId:project.id,taskId:row.record.task_id,requestId:row.id,action,
        path:scoped("/api/requests/"+row.id+"/"+action),
        payload:{expected_revision:row.record.revision,expected_vault_revision:row.vault_revision||row.revision,
          ...(action==='respond'?{response:{decision,text:submitted}}:{})},
        original:structuredClone(row.record),inFlight:false};
    } else if(op.action!==action || (decision && op.payload.response?.decision!==decision)) {setError("이전 요청의 접수 확인을 먼저 완료하세요.");return;}
    const retained=pendingHuman.has(requestKey);
    pendingHuman.set(requestKey,op);op.inFlight=true;setBusy(true);
    const acknowledge=(record:any)=>{
      if(!humanReceiptMatches(op!,record))return false;
      pendingHuman.delete(requestKey);
      if(op!.action==='respond' && !draftCompositions.has(key) && drafts.get(key)===op!.payload.response?.text)setDraft(key,'');
      if(op!.action==='execute')committed.add(row.id);
      return true;
    };
    try {
      if(retained){
        const latest=await api<Row>("/api/requests/"+encodeURIComponent(op.requestId)+"?project_id="+encodeURIComponent(op.projectId));
        if(latest.fresh && !latest.modified && acknowledge(latest.record))return;
        if(!unchangedHumanRequest(op,latest))throw new Error("원래 요청 또는 문서가 변경되어 재전송하지 않았습니다. 원문과 이전 요청을 보존했습니다.");
      }
      // The guard can start while the authenticated read is awaited.
      if(closePreparing)throw new Error("종료 확인 중에는 요청을 전송하지 않습니다. 원문을 보존했습니다.");
      const result=await api<any>(op.path,op.payload);
      if(result.action_committed)acknowledge(result.request);
    } catch(error){
      if(!retained && error instanceof ApiError && error.status>=400 && error.status<500)pendingHuman.delete(requestKey);
      setError((error as Error).message);
    } finally {op.inFlight=false;await load();setBusy(false);}
  }

  async function control(kind: string) {
    if (!project || !selected || busy || closePreparing || !selected.control?.available) return;
    const key = controlDraftKey(project.id, selected.id),
      text = drafts.get(key) || "",
      opKey = controlKey(project.id, selected.id, kind);
    let operation = pendingOps.get(opKey);
    const wasPending = !!operation;
    if (!operation) {
      if (!text.trim() || text.length > 8000) {
        setError("제어 원문은 공백이 아닌 1~8000자여야 합니다.");
        return;
      }
      operation = Object.freeze({
        projectId: project.id,
        taskId: selected.id,
        path: scoped("/api/tasks/" + selected.id + "/control"),
        payload: Object.freeze({
          operation_id: operationId(),
          kind,
          text,
          expected_task_revision: selected.control.task_revision,
          expected_control_version: selected.control.control_version,
          expected_vault_revision: selected.vault_revision || selected.revision,
        }),
      });
      pendingOps.set(opKey, operation);
    }
    setBusy(true);
    try {
      const result = await api<any>(operation.path, operation.payload);
      if (result.action_committed) {
        if (!receiptMatches(operation, result.control))
          throw new Error(
            "제어 접수 영수증이 원래 요청과 다릅니다. 원문을 보존했습니다.",
          );
        if (pendingOps.get(opKey) === operation) pendingOps.delete(opKey);
        if (!draftCompositions.has(key) && drafts.get(key) === operation.payload.text) setDraft(key, "");
      }
      await load();
    } catch (error) {
      // A first definitive 4xx rejection did not commit; an already uncertain
      // operation remains pinned even if its later retry receives a 4xx.
      if (
        !wasPending &&
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        pendingOps.get(opKey) === operation
      )
        pendingOps.delete(opKey);
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <MotionConfig reducedMotion={reduced ? "always" : "never"}>
      <Tooltip.Provider>
        <div className="app-shell">
          <aside className="project-sidebar">
            <div className="brand">
              <span className="brand-icon">
                <Layers3 aria-hidden="true" size={23} strokeWidth={1.8} />
              </span>
              <div>
                Loop Work<small>개발 자동화 하네스</small>
              </div>
            </div>
            <div className="sidebar-section-title">
              프로젝트 <span>{projects.length}</span>
            </div>
            <label htmlFor="project-search" className="sr-only">
              프로젝트 검색
            </label>
            <div className="project-search-field">
              <Search aria-hidden="true" size={16} />
              <input
                id="project-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="프로젝트 이름 검색"
              />
            </div>
            <div className="project-sort-row">
              <label htmlFor="project-sort">정렬</label>
              <select
                id="project-sort"
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                <option value="name">이름순</option>
                <option value="updated">최근 기록순</option>
              </select>
            </div>
            <nav aria-label="프로젝트 목록">
              {projects.map((p) => (
                <Button
                  variant="ghost"
                  className={
                    "project-item " + (project?.id === p.id ? "selected" : "")
                  }
                  data-project-id={p.id}
                  aria-pressed={project?.id === p.id}
                  key={p.id}
                  onClick={() => {
                    epoch.current++;
                    setProject(p);
                  }}
                >
                  <span className="project-name">
                    <FolderOpen aria-hidden="true" size={16} />
                    <span>{p.display_name || p.name}</span>
                  </span>
                  <span className="project-count">{p.task_count}</span>
                </Button>
              ))}
            </nav>
            <div className="sidebar-footer">
              <Button
                variant="outline"
                className="obsidian-button"
                onClick={() => openObsidian().catch((e) => setError(String(e)))}
              >
                <ArrowUpRight aria-hidden="true" size={16} />
                Obsidian에서 열기
              </Button>
              <p className="muted">
                문서는 vault에서 읽습니다.
                <br />
                실행 권한은 하네스가 검증합니다.
              </p>
            </div>
          </aside>
          <main className="work-area">
            <header>
              <div className="workspace-heading">
                <p className="eyebrow">
                  <span className="workspace-marker" />
                  작업 공간
                </p>
                <h1 id="project-name">
                  {project?.display_name ||
                    project?.name ||
                    "프로젝트를 선택하세요"}
                </h1>
              </div>
              <RuntimeIndicator
                connected={connected}
                paused={!!selected?.control?.paused}
              />
              <Button
                id="refresh"
                variant="outline"
                onClick={() => load()}
                disabled={loading}
              >
                <RefreshCw
                  aria-hidden="true"
                  size={15}
                  className={loading ? "icon-spin" : undefined}
                />
                새로고침
              </Button>
              <Dialog.Root open={showChart} onOpenChange={setShowChart}>
                <Dialog.Trigger asChild>
                  <Button variant="outline">
                    <BarChart3 aria-hidden="true" size={15} />
                    상태 집계
                  </Button>
                </Dialog.Trigger>
                <Dialog.Portal>
                  <Dialog.Overlay className="overlay" />
                  <Dialog.Content className="dialog">
                    <Dialog.Title>실제 작업 현황</Dialog.Title>
                    <Dialog.Description>
                      현재 프로젝트와 표시 범위의 집계입니다.
                    </Dialog.Description>
                    <StatusChart tasks={data.tasks} />
                    <Dialog.Close asChild>
                      <Button>닫기</Button>
                    </Dialog.Close>
                  </Dialog.Content>
                </Dialog.Portal>
              </Dialog.Root>
            </header>
            <div id="status" role="status">
              {error && <div className="error">{error}</div>}
            </div>
            <div id="warnings">
              {[...data.warnings, ...(data.vault_status?.errors || [])].map(
                (s, i) => (
                  <p className="error" key={i}>
                    {s}
                  </p>
                ),
              )}
            </div>
            {project && (
              <div className="board-overview">
                <div className="board-heading">
                  <ListTodo aria-hidden="true" size={18} />
                  <h2>작업 보드</h2>
                  <span className="total-count">{data.tasks.length}개</span>
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    setSelected(null);
                    setProjectEditing(true);
                  }}
                >
                  <FileText aria-hidden="true" size={15} />
                  프로젝트 문서 편집
                </Button>
              </div>
            )}
            {project && (
              <div className="workspace">
                <section id="board" className="board" aria-busy={loading}>
                  {states.map(([state, label]) => (
                    <section className="column" data-state={state} key={state}>
                      <h2>
                        <span className="column-label">
                          <span className="state-dot" />
                          {label}
                        </span>
                        <span className="column-count">
                          {
                            data.tasks.filter((t) =>
                              state === "review"
                                ? !t.board_state ||
                                  !states.some((s) => s[0] === t.board_state) ||
                                  t.board_state === "review"
                                : t.board_state === state,
                            ).length
                          }
                        </span>
                      </h2>
                      {data.tasks
                        .filter((t) =>
                          state === "review"
                            ? !t.board_state ||
                              !states.some((s) => s[0] === t.board_state) ||
                              t.board_state === "review"
                            : t.board_state === state,
                        )
                        .map((t) => (
                          <motion.button
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.15 }}
                            layout
                            className={
                              "task-card card " +
                              (selected?.id === t.id ? "selected" : "")
                            }
                            key={t.id}
                            data-task-id={t.id}
                            data-board-state={t.board_state || "review"}
                            disabled={loading || busy}
                            onClick={() => select(t)}
                          >
                            <span className="task-title">
                              {t.display_title || t.record.title}
                            </span>
                            <small className="task-state">
                              <span className="state-dot" />
                              {t.state_label}
                            </small>
                            {t.record.phase === "completed" &&
                              t.board_state !== "completed" && (
                                <small>과거 완료 기록 있음</small>
                              )}
                            {t.state_reason && <small>{t.state_reason}</small>}
                            {t.record.reason && (
                              <small>{t.record.reason}</small>
                            )}
                            {t.review_reasons?.map((x) => (
                              <small key={x}>{x}</small>
                            ))}
                          </motion.button>
                        ))}
                      {!data.tasks.some((t) =>
                        state === "review"
                          ? !t.board_state ||
                            !states.some((s) => s[0] === t.board_state) ||
                            t.board_state === "review"
                          : t.board_state === state,
                      ) && (
                        <div className="column-empty">
                          <CircleDashed aria-hidden="true" size={18} />
                          <span>아직 작업이 없습니다</span>
                        </div>
                      )}
                    </section>
                  ))}
                </section>
                <section id="detail" className="detail">
                  {selected ? (
                    <>
                      <p className="detail-eyebrow">
                        <FileText aria-hidden="true" size={14} />
                        작업 상세
                      </p>
                      <h2>{selected.display_title || selected.record.title}</h2>
                      <p
                        className="detail-state"
                        data-board-state={selected.board_state || "review"}
                      >
                        <span className="state-dot" />
                        {selected.state_label}
                      </p>
                      {selected.state_reason && <p>{selected.state_reason}</p>}
                      <Tabs.Root
                        value={tab}
                        onValueChange={(value) => {
                          historyEpoch.current++;
                          setHistoryDoc(null);
                          setTab(value);
                        }}
                      >
                        <Tabs.List className="tabs">
                          {[
                            ["wiki", "위키 편집"],
                            ["current", "실행 기록"],
                            ["interim", "중간 기록"],
                            ["final", "과거 완료 기록"],
                            ["requests", "질문·답변"],
                            ["flow", "기록 흐름"],
                          ].map(([key, label]) => (
                            <Tabs.Trigger key={key} value={key}>
                              {label}
                            </Tabs.Trigger>
                          ))}
                        </Tabs.List>
                        <Tabs.Content value="wiki">
                          <Wiki
                            kind="task"
                            id={selected.id}
                            projectId={project.id}
                          />
                        </Tabs.Content>
                        <Tabs.Content value="current">
                          <p
                            className="muted evidence-status"
                            data-verified={selected.writable}
                          >
                            {selected.writable ? (
                              <CheckCircle2 aria-hidden="true" size={14} />
                            ) : (
                              <CircleAlert aria-hidden="true" size={14} />
                            )}
                            {selected.writable
                              ? "원본과 현재 근거 확인됨"
                              : "실행 권한 없음 · " +
                                selected.warnings.join(" · ")}
                          </p>
                          <Markdown body={selected.body} />
                          <section className="control-panel">
                            <h3>작업 방향과 일시정지</h3>
                            {[...pendingOps.values()].some(
                              (op) =>
                                op.projectId === project.id &&
                                op.taskId === selected.id,
                            ) && (
                              <p role="status">
                                이전 제어 요청의 접수 확인이 필요합니다. 같은
                                동작은 원래 요청을 재확인하며 새 원문은
                                보존합니다.
                              </p>
                            )}
                            <p>{selected.control?.cancellation}</p>
                            {(selected.control?.workers || []).map((w: any) => (
                              <p key={w.id}>
                                <code>{w.id}</code> ·{" "}
                                {w.user_cancelled
                                  ? "소유 worker 취소 기록"
                                  : (
                                      {
                                        pending: "대기",
                                        running: "실행 중",
                                        done: "채택됨",
                                        rejected: "거절됨",
                                        blocked: "차단됨",
                                        failed: "실패",
                                      } as Record<string, string>
                                    )[w.status] || "상태 확인 필요"}
                              </p>
                            ))}
                            <p>
                              {selected.control?.paused
                                ? "일시정지 요청이 저장됨 · 프로세스 종료 확인과는 별도입니다."
                                : "일시정지 요청 없음"}
                            </p>
                            {selected.control?.block_reason && (
                              <p>{selected.control.block_reason}</p>
                            )}
                            <DraftInput
                              id={"control-text-" + selected.id}
                              storageKey={controlDraftKey(
                                project.id,
                                selected.id,
                              )}
                              label="전달할 원문"
                            />
                            {[
                              ["pause", "일시정지 요청"],
                              ["correction", "방향 수정"],
                              ["constraint", "제약 추가"],
                              ["resume", "피드백 재개"],
                            ].map(([k, label]) => (
                              <Button
                                key={k}
                                variant="outline"
                                disabled={
                                  busy ||
                                  loading ||
                                  !selected.control?.available
                                }
                                onClick={() => control(k)}
                              >
                                {label}
                              </Button>
                            ))}
                            {(selected.control?.history || []).map(
                              (h: any, i: number) => (
                                <details key={i}>
                                  <summary>
                                    {(
                                      {
                                        pause: "일시정지",
                                        resume: "피드백 재개",
                                        correction: "방향 수정",
                                        constraint: "제약 추가",
                                      } as Record<string, string>
                                    )[h.input?.kind] || "제어 기록"}{" "}
                                    · {h.created_at}
                                  </summary>
                                  <pre>{h.original_text}</pre>
                                </details>
                              ),
                            )}
                          </section>
                        </Tabs.Content>
                        {["interim", "final"].map((role) => (
                          <Tabs.Content key={role} value={role}>
                            <p>
                              이력 문서는 현재 실행 권한이나 완료 검증을
                              대신하지 않습니다.
                            </p>
                            {(selected.documents || [])
                              .filter(
                                (d) =>
                                  d.role === role ||
                                  d.path.includes("/" + role + "/"),
                              )
                              .map((d) => (
                                <Button
                                  key={d.path}
                                  variant="outline"
                                  onClick={async () => {
                                    const historyAtRead =
                                        ++historyEpoch.current,
                                      epochAtRead = epoch.current,
                                      taskId = selected.id,
                                      projectId = project.id;
                                    try {
                                      const doc = await api<Row>(
                                        scoped(
                                          "/api/document?path=" +
                                            encodeURIComponent(d.path),
                                        ),
                                      );
                                      if (
                                        historyAtRead ===
                                          historyEpoch.current &&
                                        epochAtRead === epoch.current &&
                                        current.current.selected?.id ===
                                          taskId &&
                                        current.current.project?.id ===
                                          projectId
                                      )
                                        setHistoryDoc({
                                          projectId,
                                          taskId,
                                          role,
                                          path: d.path,
                                          body: doc.body,
                                        });
                                    } catch (e) {
                                      if (epochAtRead === epoch.current)
                                        setError((e as Error).message);
                                    }
                                  }}
                                >
                                  {d.path.split("/").at(-1)}
                                </Button>
                              ))}
                            {historyDoc?.taskId === selected.id &&
                              historyDoc.projectId === project.id &&
                              historyDoc.role === role &&
                              (selected.documents || []).some(
                                (d) =>
                                  d.path === historyDoc.path &&
                                  (d.role === role ||
                                    d.path.includes("/" + role + "/")),
                              ) && <Markdown body={historyDoc.body} />}
                          </Tabs.Content>
                        ))}
                        <Tabs.Content value="requests">
                          {(
                            selected.requests ||
                            data.requests.filter(
                              (r) => r.record.task_id === selected.id,
                            )
                          ).map((r) => (
                            <article className="request" key={r.id}>
                              <h3>{r.record.title}</h3>
                              {pendingHuman.has(humanKey(project.id, r.id)) && (
                                <Button
                                  disabled={busy || loading}
                                  onClick={() =>
                                    mutate(
                                      r,
                                      pendingHuman.get(
                                        humanKey(project.id, r.id),
                                      )!.action,
                                    )
                                  }
                                >
                                  원래 요청 확인·재시도
                                </Button>
                              )}
                              {pendingHuman.has(humanKey(project.id, r.id)) && (
                                <p role="status">
                                  전송 또는 접수 확인 중 · 원래 요청을 확인한
                                  뒤에만 명시적으로 재시도합니다.
                                </p>
                              )}
                              <p>{r.record.question}</p>
                              <p>
                                {(
                                  {
                                    pending: "답변 필요",
                                    answered: "답변 기록",
                                    declined: "거절됨",
                                    executed: "실행됨",
                                    failed: "실행 실패",
                                  } as Record<string, string>
                                )[r.record.status] || "상태 확인 필요"}
                              </p>
                              {(r.record.options || []).map(
                                (option: string) => (
                                  <Button
                                    key={option}
                                    variant="outline"
                                    onClick={() =>
                                      setDraft("response-" + r.id, option)
                                    }
                                  >
                                    {option}
                                  </Button>
                                ),
                              )}
                              <p>{r.record.response?.text}</p>
                              {(r.record.evidence || []).map(
                                (e: any, i: number) => (
                                  <p key={i}>
                                    <code>
                                      {typeof e === "string"
                                        ? e
                                        : e.ref || e.path || "근거"}
                                    </code>
                                    {typeof e === "object" && e.sha256 && (
                                      <small> · {e.sha256}</small>
                                    )}
                                  </p>
                                ),
                              )}
                              {r.record.execution && (
                                <p>
                                  {r.record.execution.state === "executed"
                                    ? "허용된 재개 실행 완료"
                                    : r.record.execution.state === "failed"
                                      ? "실행 실패"
                                      : "실행 확인 중"}{" "}
                                  {r.record.execution.error || ""}
                                </p>
                              )}
                              <DraftInput
                                id={"response-" + r.id}
                                label="응답 원문"
                              />
                              {r.record.status === "pending" && (
                                <>
                                  <Button
                                    disabled={
                                      busy ||
                                      loading ||
                                      !r.writable ||
                                      pendingHuman.has(
                                        humanKey(project.id, r.id),
                                      )
                                    }
                                    onClick={() =>
                                      mutate(
                                        r,
                                        "respond",
                                        r.record.kind === "approval"
                                          ? "approve"
                                          : r.record.kind === "manual_action"
                                            ? "resolved"
                                            : "answer",
                                      )
                                    }
                                  >
                                    {r.record.kind === "approval"
                                      ? "승인 기록"
                                      : r.record.kind === "manual_action"
                                        ? "수동 완료 기록"
                                        : "답변 기록"}
                                  </Button>
                                  <Button
                                    variant="outline"
                                    disabled={
                                      busy ||
                                      loading ||
                                      !r.writable ||
                                      pendingHuman.has(
                                        humanKey(project.id, r.id),
                                      )
                                    }
                                    onClick={() =>
                                      mutate(r, "respond", "reject")
                                    }
                                  >
                                    거절
                                  </Button>
                                </>
                              )}
                              {r.record.status === "answered" &&
                                r.record.action === "resume_task" &&
                                !r.record.execution && (
                                  <Button
                                    disabled={
                                      busy ||
                                      loading ||
                                      !r.writable ||
                                      pendingHuman.has(
                                        humanKey(project.id, r.id),
                                      ) ||
                                      committed.has(r.id)
                                    }
                                    onClick={() => mutate(r, "execute")}
                                  >
                                    허용된 작업 재개 실행
                                  </Button>
                                )}
                              {(r.record.history || []).map(
                                (h: any, i: number) => (
                                  <p key={i}>
                                    {h.at || h.created_at} ·{" "}
                                    {h.text || h.response?.text || "요청 이력"}
                                  </p>
                                ),
                              )}
                            </article>
                          ))}
                        </Tabs.Content>
                        <Tabs.Content value="flow">
                          <AuditFlow task={selected} />
                        </Tabs.Content>
                      </Tabs.Root>
                    </>
                  ) : (
                    <div
                      className={
                        "empty" + (projectEditing ? " project-document" : "")
                      }
                    >
                      {!projectEditing && (
                        <span className="empty-icon">
                          <SquareMousePointer
                            aria-hidden="true"
                            size={25}
                            strokeWidth={1.5}
                          />
                        </span>
                      )}
                      <h2>
                        {projectEditing ? "프로젝트 문서" : "작업을 선택하세요"}
                      </h2>
                      <p>
                        {viewWarning ||
                          "실제 vault 문서의 상태와 근거를 확인합니다."}
                      </p>
                      {projectEditing && (
                        <Wiki
                          kind="project"
                          id={project.id}
                          projectId={project.id}
                        />
                      )}
                    </div>
                  )}
                </section>
              </div>
            )}
          </main>
        </div>
      </Tooltip.Provider>
    </MotionConfig>
  );
}
