"""Small, factual records and deterministic human views of the same data."""

from __future__ import annotations

import json
import re

from .storage import LoopError


def concise(value, field, maximum=280):
    if not isinstance(value, str) or not value.strip():
        raise LoopError(f"{field} needs a concrete statement")
    if "\n" in value or "\r" in value or len(value) > maximum:
        raise LoopError(f"{field} must be one line, at most {maximum} characters; link details separately")
    if (re.fullmatch(r"(?:TODO|TBD|FIXME|\.\.\.|placeholder|작성 예정|추후 작성)[.!?]?", value.strip(), re.I)
            or re.match(r"Replace with\b", value.strip(), re.I)):
        raise LoopError(f"{field} must replace its placeholder with the observed result")
    return value.strip()


def topic_text(entry):
    if "title" in entry:
        concise(entry["title"], "Knowledge title", maximum=60)
    concise(entry.get("summary"), "Knowledge summary")
    for key in ("why", "uncertainty"):
        if key in entry:
            concise(entry[key], key)
    details = entry.get("details", [])
    if not isinstance(details, list) or len(details) > 5:
        raise LoopError("Knowledge details must contain at most five points; link longer material")
    texts = [entry["summary"], *[concise(x, "Knowledge detail") for x in details]]
    for key in ("why", "uncertainty"):
        if key in entry:
            texts.append(entry[key])
    normalized = [" ".join(x.casefold().split()).rstrip(".。") for x in texts]
    if len(set(normalized)) != len(normalized):
        raise LoopError("Knowledge fields repeat the same statement; keep it once")
    evidence = entry.get("evidence", [])
    if isinstance(evidence, list) and all(isinstance(x, str) for x in evidence) and len(set(evidence)) != len(evidence):
        raise LoopError("Knowledge evidence repeats a reference")


def plain(value):
    """Prevent source text from introducing headings, links or HTML in generated views."""
    value = " ".join(str(value).split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+!|])", r"\\\1", value)


def bullets(items, maximum=5, language=None):
    lines = ["- " + plain(item) for item in items[:maximum]]
    if len(items) > maximum:
        lines.append(f"- 연결된 JSON 기록에 {len(items) - maximum}개 항목이 더 있습니다." if language == "ko" else f"- +{len(items) - maximum} more in the linked JSON record.")
    return lines


def task_summary(task):
    result = task.get("result") or {}
    return {**{k: task.get(k) for k in ("id", "kind", "title", "phase", "session_id", "updated_at")},
            "result": {k: result[k] for k in ("summary", "gate", "historical", "evidence_current") if k in result}}


def task_document(task, language=None):
    if language == "ko":
        return _korean_document("task", task)
    goal = task.get("goal") or {}
    result = task.get("result") or {}
    development = task["kind"] == "development"
    outcome = goal.get("target", {}).get("outcome") if development else goal.get("outcome")
    lead = result.get("summary") or outcome or task["title"]
    phase = task["phase"]
    if result.get("evidence_current") is False:
        lead = "Earlier completion is stale: the source or rules changed."
    elif phase == "blocked" and task.get("reason"):
        lead = "Work is blocked: " + task["reason"]
    labels = {"goal_setting": "Setting the goal", "working": "In progress", "completed": "Completed",
              "blocked": "Blocked", "aborted": "Stopped"}
    lines = [f"# {plain(task['title'])}", ""]
    if lead != task["title"]:
        lines.extend([plain(lead), ""])
    lines.append(f"**State:** {labels.get(phase, plain(phase))} · **Kind:** {plain(task['kind'])}")
    if outcome and outcome != lead:
        lines.extend(["", "**Goal:** " + plain(outcome)])
    if development:
        lines.extend(["", "**Development stage:** " + plain(task["execution_phase"])])
        if task.get("progress"):
            lines.extend(["", "**Progress:** " + plain(task["progress"])])
    if result.get("evidence_current") is False:
        lines.extend(["", "**Evidence:** historical; run fresh verification before claiming current completion."])
    if phase == "completed":
        lines.extend(["", "**Result:** recorded completion; a later request must check current evidence."])
    elif task.get("next_action"):
        lines.extend(["", "**Next (agent):** " + plain(task["next_action"])])
    else:
        next_steps = {"goal_setting": "Resolve remaining choices and define completion criteria.",
                      "working": "Delegate the scoped work, inspect its deliverable and check completion criteria.",
                      "blocked": "Resolve the recorded obstacle within the agreed authority, then resume."}
        if phase in next_steps:
            lines.extend(["", "**Next (agent):** " + next_steps[phase]])
    checks = result.get("checks") or (task.get("last_result") or {}).get("checks", [])
    if checks:
        lines.extend(["", "## Checks", "", *bullets([
            f"{c['criterion_id']}: {'passed' if c['satisfied'] else 'unmet'} — {c['evidence']}" for c in checks])])
    refs = result.get("outputs", []) + ([result["gate"]] if result.get("gate") else [])
    if refs:
        lines.extend(["", "## Evidence and output", "", *bullets(refs)])
    if task.get("delegations"):
        lines.extend(["", "## Delegated work", "", *bullets([
            f"{x['assignment_id']}: {x['status']} — {x['error'] or x['summary']} ({x['id']})"
            for x in task["delegations"]])])
    if task.get("notes"):
        note = task["notes"][-1]
        lines.extend(["", "**Latest finding:** " + plain(note.get("text", "")),
                      "", "**Source:** " + plain(note.get("evidence", ""))])
    lines.extend(["", f"[Full record]({task['id']}.json)", ""])
    return "\n".join(lines)


def delegation_document(record, language=None):
    if language == "ko":
        return _korean_document("delegation", record)
    request = record["request"]
    lines = [f"# {plain(request['id'])}", "", plain(record["summary"]), "",
             f"**State:** {plain(record['status'])} · **Worker:** {plain(record['provider'])} · **Attempt:** {record['attempts']}",
             "", "**Assignment:** " + plain(request["instruction"])]
    lines.extend(["", "**Working directory:** " + plain(record["root"])])
    for title, items in (("Read scope", request["read_paths"]), ("Allowed edits", request["write_paths"]),
                         ("Prohibited", request["prohibited"]),
                         ("Deliverables", [x["id"] + ": " + x["description"] for x in request["deliverables"]]),
                         ("Completion criteria", [x["id"] + ": " + x["description"] for x in request["criteria"]]),
                         ("Applied edits", record["applied"])):
        lines.extend(["", "## " + title, "", *(bullets(items) if items else ["None."])])
    if record.get("error"):
        lines.extend(["", "**Obstacle:** " + plain(record["error"])])
    lines.extend(["", "**Evidence directory:** " + plain(record["directory"]), "",
                  "Done applies to this assignment only; parent completion uses its own criteria and gates.", "",
                  f"[Full record]({record['id']}.json)", ""])
    return "\n".join(lines)


def topic_document(topic, language=None):
    if language == "ko":
        return _korean_document("topic", topic)
    lines = [f"# {plain(topic['id'])}", "", plain(topic["summary"]), "",
             f"**Status:** {plain(topic['status'])} · **Scope:** {plain(topic['scope'])} · **Kind:** {plain(topic['kind'])}"]
    for label, key in (("Why it matters", "why"), ("Uncertainty", "uncertainty"), ("Applies to", "applies_to"),
                       ("Decision basis", "basis")):
        if topic.get(key):
            lines.extend(["", f"**{label}:** " + plain(topic[key])])
    if topic.get("details"):
        lines.extend(["", *bullets(topic["details"])])
    if topic.get("evidence"):
        lines.extend(["", "## Evidence", "", *bullets(topic["evidence"])])
    lines.extend(["", "**Recorded:** " + plain(topic["recorded_at"]), "",
                  "Current applicability is computed by knowledge context; confirmed alone does not mean current.", "",
                  f"[Full record]({topic['id']}.json)", ""])
    return "\n".join(lines)


def context_document(context):
    counts = context["counts"]
    lines = ["# Local knowledge", "",
             f"{counts['reusable']} current · {counts['stale']} need rechecking · {counts['unconfirmed']} unconfirmed", "",
             "Use current evidence within its recorded scope. Past results do not verify today's files."]
    activation = context.get("harness")
    if activation:
        state = "on · related inputs for task " + str(activation.get("task_id")) if activation["enabled"] else "off"
        lines.extend(["", f"**Harness:** {state} · session `{plain(activation['session_id'])}`"])
    for key, label in (("reusable", "Current"), ("stale", "Recheck before reuse"),
                       ("unconfirmed", "Drafts and hypotheses"), ("tasks", "Work history")):
        values = context[key]
        if not values:
            continue
        lines.extend(["", "## " + label, ""])
        folder = "task" if key == "tasks" else "topic"
        for item in values[:5]:
            summary = item.get("summary", item.get("title", ""))
            reason = "; ".join(item.get("stale_reasons", []))
            state = item.get("phase", item.get("status", ""))
            lines.append(f"- [{plain(item['id'])}](../{folder}/{item['id']}.md): {plain(summary)} ({plain(reason or state)})")
        remaining = counts[key] - min(len(values), 5)
        if remaining:
            lines.append(f"- {remaining} records outside this view; use knowledge context --query or --offset. Nothing is deleted.")
    lines.extend(["", f"**Revision:** {context['revision']}", "", "[Structured view](./" + context["view_id"] + ".json)", ""])
    return "\n".join(lines)


_KO_STATE = {"goal_setting":"목표 설정", "working":"진행 중", "completed":"완료", "blocked":"장애로 중단", "aborted":"종료", "confirmed":"확인됨", "draft":"초안", "hypothesis":"가설", "superseded":"대체됨", "done":"수용 완료", "candidate":"검토 대기", "rejected":"수정 필요", "interrupted":"중단됨", "pending":"대기", "plan":"계획", "ready":"실행 준비", "running":"실행 중", "answered":"응답됨", "declined":"거절됨", "executed":"실행됨", "failed":"실패", "waiting":"응답 대기", "retired_obligation":"후속 작업으로 대체됨", "claimed":"실행 접수"}
_KO_SCOPE = {'global':'공통', 'project':'프로젝트', 'checkout':'작업 위치', 'session':'대화', 'task':'작업'}
_KO_BASIS = {'user':'사용자 결정', 'repository-rule':'저장소 규칙', 'delegated':'위임된 판단'}


def _literal(text):
    """Render user text literally while retaining its visible line boundaries."""
    return "  \n".join(plain(line) for line in str(text).split("\n"))


def _section(lines, title, text=None, items=None, literal=False):
    if text:
        lines.extend(['', '## ' + title, '', _literal(text) if literal else plain(text)])
    elif items:
        lines.extend(['', '## ' + title, '', *bullets(items, language='ko')])


def _record_details(lines, value, include_json=False):
    """Keep machine identifiers available without making them the reading order."""
    lines.extend(['', '<details>', '<summary>원본 및 검증 정보</summary>', '', '**기록 ID:** ' + plain(value['id'])])
    for label, key in [('기록 시각','recorded_at'), ('생성 시각','created_at'), ('갱신 시각','updated_at'), ('처리 시각','at'), ('작업 ID','task_id'), ('대화 ID','session_id')]:
        if value.get(key):
            lines.extend(['', '**' + label + ':** ' + plain(value[key])])
    if include_json:
        # Escape fence/HTML delimiters inside JSON string values, preserving JSON data.
        encoded = json.dumps(value, ensure_ascii=False, indent=2).replace('`', '\\u0060').replace('<', '\\u003c').replace('>', '\\u003e')
        lines.extend(['', '```json', encoded, '```'])
    lines.extend(['', '[전체 기록](' + value['id'] + '.json)', '', '</details>', ''])


def _korean_document(kind, value):
    """Human reading order; source text and execution authority stay unchanged."""
    from .vault_layout import display_title
    state = value.get('phase', value.get('status', ''))
    state_label = '사용자 중단' if value.get('user_cancelled') and state == 'interrupted' else _KO_STATE.get(state, state)
    lines = ['# ' + plain(display_title(value)), '', '**상태:** ' + plain(state_label)]
    if kind == 'task':
        goal = value.get('goal') or {}
        result = value.get('result') or {}
        outcome = (goal.get('target') or {}).get('outcome') if value.get('kind') == 'development' else goal.get('outcome')
        if result.get('evidence_current') is False:
            lines.extend(['', '> 이전 완료의 근거가 현재 소스나 규칙과 다릅니다. 새 검증 전에는 현재 완료로 사용하지 마세요.'])
        _section(lines, '현재 결과', result.get('summary'))
        _section(lines, '남은 장애', value.get('reason'))
        _section(lines, '목표', outcome)
        kind_labels = {'development':'개발','document':'문서','explanation':'설명','review':'검토','research':'조사','analysis':'분석','planning':'계획'}
        progress = [kind_labels.get(value.get('kind'), value.get('kind',''))]
        if value.get('execution_phase'):
            progress.append(_KO_STATE.get(value['execution_phase'], value['execution_phase']))
        if value.get('progress'):
            progress.append(value['progress'])
        lines.extend(['', '**작업 진행:** ' + ' · '.join(plain(x) for x in progress if x)])
        criteria = goal.get('criteria') or (goal.get('target') or {}).get('acceptance') or []
        _section(lines, '완료 기준', items=[str(c['id']) + ': ' + str(c.get('description') or c.get('scenario','')) for c in criteria])
        checks = result.get('checks') or (value.get('last_result') or {}).get('checks', [])
        _section(lines, '확인한 결과', items=[str(c['criterion_id']) + ': ' + ('충족' if c['satisfied'] else '미충족') + ' — ' + str(c['evidence']) for c in checks])
        if value.get('notes'):
            note = value['notes'][-1]
            _section(lines, '최근 발견', note.get('text'))
            if note.get('evidence'):
                lines.extend(['', '**발견의 근거:** ' + plain(note['evidence'])])
        if value.get('delegations'):
            _section(lines, '위임한 작업', items=[x['assignment_id'] + ': ' + _KO_STATE.get(x['status'], x['status']) + ' — ' + (x.get('error') or x.get('summary') or '') for x in value['delegations']])
        refs = result.get('outputs', []) + ([result['gate']] if result.get('gate') else [])
        _section(lines, '근거와 산출물', items=refs)
        if state == 'completed':
            lines.extend(['', '이 결과는 기록된 완료 시점의 결과입니다. 후속 작업에서는 현재 근거를 다시 확인합니다.'])
        elif state in ('goal_setting','working','blocked'):
            defaults = {'goal_setting':'남은 선택을 해결하고 완료 기준을 정하세요.', 'working':'정해진 범위의 산출물과 완료 기준을 확인하세요.', 'blocked':'합의된 권한 안에서 기록된 장애를 해결한 뒤 재개하세요.'}
            _section(lines, '다음 행동', value.get('next_action') or defaults[state])
    elif kind == 'topic':
        _section(lines, '결론', value.get('summary'))
        _section(lines, '활용 목적', value.get('why'))
        _section(lines, '확인한 내용', items=value.get('details'))
        scope = _KO_SCOPE.get(value.get('scope'), value.get('scope',''))
        labels = {'fact':'사실','decision':'결정','artifact':'산출물','finding':'발견'}
        _section(lines, '적용 범위와 한계', items=[label for label in [
            '적용 범위: ' + scope if scope else '',
            '지식 유형: ' + labels.get(value.get('kind'), value.get('kind','')),
            '적용 대상: ' + str(value['applies_to']) if value.get('applies_to') else '',
            '판단 근거: ' + _KO_BASIS.get(value['basis'], value['basis']) if value.get('basis') else '',
            str(value['uncertainty']) if value.get('uncertainty') else ''] if label])
        if state in ('draft','hypothesis','superseded'):
            limits = {'draft':'초안입니다. 확인된 사실로 재사용하기 전에 근거를 검토하세요.', 'hypothesis':'가설입니다. 효과가 검증됐다는 뜻이 아닙니다.', 'superseded':'대체된 기록입니다. 현재 판단에 그대로 적용하지 마세요.'}
            lines.extend(['', '> ' + limits[state]])
        lines.extend(['', '확인됨 상태만으로 현재 적용 가능성을 보장하지 않습니다. 재사용 전 지식 문맥에서 최신성을 확인하세요.'])
        _section(lines, '근거', items=value.get('evidence'))
    else:
        request = value['request']
        _section(lines, '결과', value.get('summary'))
        _section(lines, '남은 장애', value.get('error'))
        _section(lines, '작업 지시', request['instruction'])
        lines.extend(['', '**작업자:** ' + plain(value.get('provider','')), '', '**시도:** ' + plain(value.get('attempts',''))])
        _section(lines, '적용한 변경', items=value.get('applied'))
        for label, key in [('읽기 범위','read_paths'), ('허용된 수정','write_paths'), ('금지 사항','prohibited')]:
            _section(lines, label, items=request.get(key))
        for label, key in [('산출물','deliverables'), ('완료 기준','criteria')]:
            _section(lines, label, items=[x['id'] + ': ' + x['description'] for x in request.get(key, [])])
        _section(lines, '근거', items=[x for x in [value.get('directory'), value.get('root')] if x])
        lines.extend(['', '수용 완료는 이 위임 작업에만 적용됩니다. 상위 작업의 완료 판정과 품질 검증을 대신하지 않습니다.'])
    _record_details(lines, value)
    return '\n'.join(lines)


def record_document(record, kind, language='ko'):
    """Readable control/coordination records; the folded JSON retains exact input."""
    from .vault_layout import display_title
    state = record.get('status', '')
    kinds = {'team':'협업 기록', 'human-request':'사용자 검토', 'feedback':'사용자 피드백', 'retirement':'작업 의무 대체 기록'}
    if kind not in kinds:
        raise LoopError('Unsupported readable record kind')
    lines = ['# ' + plain(display_title(record)), '', '**기록 종류:** ' + kinds[kind]]
    if state:
        lines.extend(['', '**상태:** ' + plain(_KO_STATE.get(state, state))])
    _section(lines, '요약', record.get('summary'))
    if kind == 'human-request':
        requests = {'decision':'결정 요청', 'approval':'승인 요청', 'manual_action':'수동 확인 요청'}
        lines.extend(['', '**요청 유형:** ' + plain(requests.get(record.get('kind'), record.get('kind','')))])
        if record.get('title') and record['title'] != display_title(record):
            lines.extend(['', '**원래 요청 제목:** ' + plain(record['title'])])
        _section(lines, '확인할 내용', record.get('question'), literal=True)
        if record.get('options'):
            lines.extend(['', '## 선택지', ''])
            for index, option in enumerate(record['options'], 1):
                lines.append(str(index) + '. ' + _literal(option).replace('\n','\n   '))
        response = record.get('response') or {}
        decisions = {'answer':'답변', 'reject':'거절', 'approve':'승인', 'resolved':'확인 완료'}
        if response:
            _section(lines, '사용자 응답', response.get('text'), literal=True)
            lines.extend(['', '**응답 구분:** ' + plain(decisions.get(response.get('decision'), response.get('decision','')))])
        execution = record.get('execution') or {}
        if execution:
            lines.extend(['', '**실행 기록:** ' + plain(_KO_STATE.get(execution.get('state'), execution.get('state','')))])
            _section(lines, '실행 오류', execution.get('error'))
        elif record.get('action'):
            lines.extend(['', '응답과 실행은 별도 단계입니다. 응답만으로 재개 실행이 완료되지 않습니다.'])
        if record.get('superseded_by'):
            lines.extend(['', '다른 요청으로 대체된 기록입니다. 현재 응답 대상은 연결된 원본 기록에서 확인하세요.'])
        evidence = record.get('evidence') or []
        _section(lines, '근거', items=[x.get('ref','') if isinstance(x,dict) else str(x) for x in evidence])
    elif kind == 'feedback':
        _section(lines, '적용 범위', record.get('applies_to'))
        if record.get('basis'):
            lines.extend(['', '**판단 근거:** ' + plain(_KO_BASIS.get(record['basis'], record['basis']))])
        original = record.get('original_input') or {}
        _section(lines, '사용자 원문', original.get('original_text'), literal=True)
        _section(lines, '원문 출처', record.get('original_input_ref'))
        lines.extend(['', '이 기록은 해당 작업의 사용자 지시입니다. 문서를 고쳐도 실행 지시나 적용 범위가 바뀌지 않습니다.'])
    elif kind == 'team':
        _section(lines, '남은 장애', record.get('error'))
        members = record.get('members') or {}
        _section(lines, '협업 작업', items=[str(name) + ': ' + _KO_STATE.get(value.get('status'), str(value.get('status',''))) + (' — ' + str(value['summary']) if value.get('summary') else '') for name,value in members.items()])
        _section(lines, '근거', items=[record['artifact']] if record.get('artifact') else [])
        lines.extend(['', '협업 단위의 수용은 상위 목표의 완료나 최종 품질 검증을 대신하지 않습니다.'])
    elif kind == 'retirement':
        _section(lines, '대체된 작업 의무', record.get('assignment_id'))
        _section(lines, '대체 작업', items=record.get('replacements'))
        _section(lines, '근거', record.get('receipt_ref'))
        lines.extend(['', '기존 작업의 실패 이력과 사용한 예산을 보존합니다. 목표 완료에는 별도의 최신 검증이 필요합니다.'])
    lines.extend(['', '이 문서는 파생 기록입니다. 본문 편집은 승인·완료 권한을 부여하지 않습니다.'])
    _record_details(lines, record, include_json=True)
    return '\n'.join(lines)
