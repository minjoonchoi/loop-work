# Writing for people and agents

Write the conclusion first, then the evidence needed to use it. Match the user's
language and technical level. Preserve precise terms, constraints and uncertainty;
explain an unfamiliar term briefly when needed. Simplicity must not change the facts.

## Korean vault records

Write authored task titles, tracking summaries/findings and knowledge `title`, `summary`,
`why`, `details`, `uncertainty` in Korean. Preserve proper names, API names and exact
technical terms. An explicitly requested foreign-language deliverable remains in
that language; keep its separate harness tracking summary in Korean.
Never translate or alter original user input, quotations, evidence, code, commands,
paths, hashes, references or machine JSON keys/enums. Existing English stored facts
are not permission to invent a translated replacement. Do not reject a literal input
or impose a Hangul-character validator: this is an authoring policy, not new authority
or a content-quality shortcut. Assess conclusions against the actual source.

## Record shape

| Record | Required content | Optional content |
| --- | --- | --- |
| Execution status | goal, actual stage, result/evidence, next agent action or blocker | latest material finding |
| Knowledge topic | short title, one conclusion, scope, status, source references, source dependencies | why it matters, up to five distinct details, uncertainty, decision boundary |
| Completed work | delivered result, output reference, each criterion and its evidence | new supported knowledge |

For every newly authored knowledge topic, write a Korean noun-phrase `title` on one
line, at most 60 characters: for example, "회고 개선 적용 결과". A title names the
subject; do not paste the full summary or append execution IDs. Existing records
without a title remain original data; a shortened display excerpt is navigation,
not a newly verified title or conclusion. The full summary stays in the body.

Use `summary` for the conclusion; `why` only for a useful implication; `details` for
distinct supporting facts; `uncertainty` for an actual limit. Omit unused fields rather
than writing "none", boilerplate, or a second summary. Keep each authored summary,
finding and optional topic point on one line, at most 280 characters. Task titles are
at most 120; common goal outcome/deliverable fields at most 400. Put a longer explanation
in the requested deliverable and link it. Never cut evidence to fit a summary.

## Before saving or reporting

1. State what changed or what the evidence establishes. Delete intent announcements,
   praise, repeated recaps, and closers such as "let me know if you need anything".
2. Use one idea per sentence. Name the affected behavior and cause. Avoid abstract
   claims such as "improved robustness" without the actual observable change.
3. Keep source paths, commands and results exact. Distinguish fact, decision, inference
   and unknown; do not replace uncertainty with confidence or invent time estimates.
4. Show at most five items per visible group, with a count and route to the rest.
   Order actual steps; use a table for comparisons. Preserve all underlying evidence.
5. Give the agent's next action only while work remains. Do not turn it into a new
   instruction for the user unless a real user-owned choice is pending before start.

Use an analogy only if it clarifies an unfamiliar mechanism. Do not force childlike
language, medical assumptions, emojis, a fixed recap, or an unnecessary question into
every output. Explanations may be as long as the requested understanding requires;
the bounded fields are navigation records, not a limit on the deliverable itself.

## Progress and interim deliverables

Progress updates identify a new result, blocker or next check condition. If a host
requires an update during unchanged waiting, state that no new result is available
and name the pending check; do not present the same unfinished state as new progress.
A stage fraction describes the recorded workflow stage, not a test pass rate or an
acceptance completion percentage unless those quantities were actually measured.

For long native verification, report bounded stage start/end evidence and the last
completed stage; distinguish timeout, failed check and renderer/native/synthetic/physical
scope. With no new result, name the unchanged wait and next observable condition. Reuse
the compact status record; do not invent progress, percentages or quality gains.

For an interim evaluation, retain its cutoff date, source access limits, unresolved
findings and historical verification units. Separate observations, reported facts and
improvement hypotheses. Add later execution results in a dated section without
replacing the earlier stop history; corrections identify their date, claim and evidence.
Distinguish portable documents from unavailable local audit artifacts and past results
from checks executed for the present task. Do not claim an unmeasured time or quality gain.

## 작업 완료 후 하네스 사용 회고

실제 작업이 완료되면 메인 조정자가 이미 확보한 작업 결과와 사용 근거로 짧은 한국어
회고를 기록한다. 차단·일시정지·중단을 완료로 바꾸지 않는다. 작업 규모에 비례해 쓰고,
전체 역사 재독, 새 모델 검토·질문·작업·세션·바인딩·gate를 만들거나 `harness on/off`를
다시 실행하지 않는다. `board`/`human` 관리 명령과 이 회고 자체에는 회고를 재귀적으로 붙이지 않는다.

1. **관측과 제안을 나눈다.** 실제 도움이 된 점, 불필요하거나 방해됐던 점·나빴던 점 중
   근거가 있는 것만 쓴다. 사용하지 않은 기능이나 측정하지 않은 시간·비용·품질 효과를
   평가하지 않는다. 장단점을 억지로 채우지 말고 새 관측이 없으면 확인된 사용 범위와
   검증·측정 한계만 짧게 남긴다.
2. **수정 제안은 한정한다.** 바꿔야 할 skill/rule의 실제 파일·절/구간, 관측된 문제,
   한정된 변경, 효과를 판정할 검증 조건과 근거를 연결한다. 관측된 사실과 미검증 원인·
   효과 가설을 구분하며, 회고 작성이 자동 스킬 수정·수용 기준 완화·배포를 허가하지 않는다.
3. **기존 지식과 출처를 잇는다.** 유지한 `entrypoint`·`knowledge_home`·실제 session/task ID로
   `knowledge context --path PATH --session SESSION --task TASK`에서 필요한 topic만 찾고
   `knowledge get topic ID`로 관련 기록을 확인한다. 기존 입력 형식과 해당 context의
   `revision`으로 `knowledge remember --path PATH --session SESSION --task TASK --observed REVISION
   --input FILE`을 사용한다. 동일 주제의 기존 topic ID를 우선 재사용하고 없을 때만 회고 topic을
   만든다. 원래 범위·소유권과
   정확한 결과·감사 참조를 보존한다. 관측은 `confirmed`, 미검증 개선 제안은 별도 `hypothesis`
   topic으로 분리한다. 같은 작업의 기록·근거가 이미 있고 새 관측이 없으면 기존 기록을
   확인하며 중복 저장·새 revision을 만들지 않는다. 존재하지 않는 ID·근거를 꾸미지 않는다.
4. **완료 소스와 사람 문서를 보호한다.** 이 문서의 기록 길이·중복·사용자 기록 제한을 지킨다.
   검증한 소스·실행 엔진 밖의 유지된 지식 저장소에 기록하고, 완료 snapshot·규칙·배포물을
   수정하지 않는다. 저장소 위치가 이 조건과 충돌하면 다른 KB로 몰래 바꾸거나 이전하지 말고
   저장 장애를 보고한다. 생성 뷰는 기존 경로로 반영하며 편집된 vault 문서·사람 위키를
   덮어쓰거나 새 복사본으로 우회하지 않는다.
5. **전달 결과를 확인한다.** 저장 뒤 `knowledge get topic ID`와 기존 export 진단으로 읽기
   결과·vault 반영 여부를 확인한다. export가 꺼졌거나 충돌·실패하면 반영됐다고 말하지 않는다.
   저장·출력 실패나 기록 제한은 원래 완료를 취소하거나 gate를 다시 만들 이유가 아니다.
   완료 결과와 회고의 미저장·미전달 위치, 원인·한계를 분리해 보고한다.

## Storage and maintenance

SQLite and development state JSON are authoritative records. Markdown views are
generated deterministically from them, without a second model-written paraphrase.
Update the same topic ID when evidence changes. Do not create daily narrative copies,
repeat task history inside every topic, or save an unchanged fact as a new revision.
If nothing was learned, the task result is enough; the completion-use retrospective
records only confirmed usage scope/limits, without inventing a finding. Keep obsolete
versions in history.

`context` refreshes applicability from dependencies; it never verifies a fact just by
reading it. A topic document's confirmed label is not a freshness guarantee: use the
current context view. `knowledge get` and `work context` regenerate derived views if
needed. Do not hand-edit generated Markdown to change task status or facts.

The scripts reject blank/placeholder-only, oversized or multiline summaries, repeated
topic fields and duplicate evidence references. These checks prevent common bloat;
the agent still checks factual accuracy and useful wording. A word blacklist cannot
establish writing quality, and readability is not another review loop.

## Obsidian reports

Use the single `~/.loop-work/vault` as a derived document workspace. Start at
`안내.md`, then `프로젝트/<짧은 이름--8자리 식별자>/목록.md`. Project knowledge lives
in `지식/`; work lives in `작업/<짧은 이름--8자리 식별자>/`, with `진행 현황.md` and
the separately human-owned `작업 문서.md`. Group dated evidence under `기록/중간/`,
`기록/완료/`, `기록/위임/`, `기록/협업/`, `기록/사용자 검토/`, `기록/피드백/` and
`기록/종료/`. Keep common topics in `공통 지식/` and human notes in `개인 메모/`.
Use one project list instead of duplicate task/topic index documents. Short suffixes
are path disambiguators, never identity or authority. Keep full record IDs in metadata.
A frozen path does not rename on later title changes. The current runtime supports
only layout 3; existing exports require the explicit, preserving conversion tool.

A knowledge document reads as short title, conclusion, useful purpose, observed
support, scope/uncertainty and evidence. Omit sections without actual content. Put
long identifiers and JSON links inside folded original/verification details. Keep
hypotheses, drafts, stale evidence and historical completion explicit beside the
claim. Do not invent a next action to fill a template. A completed task does not
show a machine follow-up command as unfinished work. Human request questions,
all offered choices and responses retain their line boundaries and literal content;
raw machine JSON is folded rather than substituted for the readable explanation.

SQLite and development JSON remain authoritative. A report named complete is not a
completion gate; show blocked, stopped or unverified work as incomplete and preserve
earlier failures. A later result supplements the dated interim record rather than
erasing its cutoff. Conversion preserves historical exports and wiki text in an external backup before
moving managed documents into the new layout. Human notes/settings remain untouched.
It cannot restore execution authority around an edited or missing document.

Preserve human-authored notes and existing `.obsidian` settings. Generated-file ownership
and pins determine which reports may be refreshed; do not overwrite edited or unowned
files. A vault edit alone never grants approval, completes QA or promotes a worker draft.
Export errors are document-delivery problems: retain the committed task result and
continue authorized work while reporting the failed view separately. Distinguish local
`.loop` audit links from portable evidence; never imply that unavailable local logs
were copied into a shareable report.

## References

Adapted principles, not installed hooks or runtime dependencies:

- [ELI5](https://github.com/DreambigOu/ELI5/blob/main/skills/eli5/SKILL.md): audience-appropriate vocabulary, purpose before mechanism, progressive explanation. Read blob `b0644b6cbc4839749aeecf0b340074be9e88f475`.
- [i-have-adhd](https://github.com/ayghri/i-have-adhd/blob/main/skills/i-have-adhd/SKILL.md): visible state/action, small groups, no tangents or repeated recap. Read blob `6c42757ffae37e442adfb52fbba2a8609f1cff00`.

The harness retains exact evidence, its question policy and the user's requested
depth. It does not adopt a five-year-old default audience or unsupported estimates.

## 프로젝트별 사람 편집 위키

생성된 실행 기록과 사람 편집 위키를 구분한다. 새 위키는 실제 작업 정보와 원본 링크를
한국어 개요·작업 설명·기록·결과·근거 구조로 제공하되, 사용자 원문·명령·코드·과거 영문
근거를 자동 번역하지 않는다. 위키의 표시 이름이나 본문을 고쳐도 실행 원본 제목·ID·경로·
프로젝트 정체성·상태·예산·검증·승인은 변경하지 않는다. 최상위 표시 H1은 제목과 함께 저장하고
편집 API의 본문에서는 분리한다. Obsidian의 실제 위키 내용이 표시 원본이다.

자동 exporter는 위키를 최초 생성한 뒤 수정·삭제를 덮어쓰거나 다른 위키로 대체하지 않는다.
기존 current 문서의 소유 pin·권한은 위키 저장으로 갱신하지 않는다. 저장 충돌에서는 초안과
외부 원문·복원 기록을 보존하고 최신 내용을 읽은 뒤 명시적으로 병합한다. 협조하지 않는 외부
writer까지 포함한 완전한 파일시스템 CAS나 여러 파일의 원자적 갱신을 약속하지 않는다.

사람 편집 위키의 최초 스냅샷은 작성 시점과 현재 상태를 반영하지 않는 한계를 명시한다.
빈 체크박스·작성 유도 문장을 관측 지식처럼 남기지 않는다. 이후 목표·완료 기준·실제
결과는 연결된 실행 원본 문서에서 읽으며, 사람 위키의 수정·삭제를 자동 복원하지 않는다.

Ordinary-input memory is selective project knowledge, not a prompt transcript or a
new work result. Preserve original `evidence` references and scoped decision `basis`/
`applies_to`; omit unknown session/task IDs. Korean authored summaries never replace
or translate original user statements. Later task reuse links the topic ID/revision
and sources without promoting its authority or changing its ownership.
