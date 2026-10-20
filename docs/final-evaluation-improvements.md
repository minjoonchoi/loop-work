# 최종 평가에서 도출한 하네스 개선 기록

## 2026-10-20 추가 기록: human desk 구현, 최종 수용은 미완료

**현재 변경은 미완료·미커밋·미푸시다.** fresh 독립 검토 3회가 모두 revise여서 사용자 AGENTS.md의 **“After three failed fixes, stop and name the doubtful assumption.”** 규칙에 따라 추가 코드·테스트 수정과 모델 호출을 중단했다. 이미 실행 중이던 수정 후 전체 suite는 끝까지 실행해 **481 tests/482.671초, OK·exit 0**으로 완료했으며 source/runtime/all-tests pins는 불변이었다. 이 통과가 아래 미해결 의미 결함을 해소하거나 최종 수용을 뜻하지 않는다. 아래 2026-10-19 중단 기록을 포함한 기존 이력은 해당 시점의 기록으로 유지한다. 이 추가 기록은 변경의 수용·품질 승격이나 완료 보고가 아니다.

### 추가 기능과 실제 확인

`human` CLI, `$loop-human` / `/loop-human`, localhost UI를 추가했다. 사람의 원문 응답과 revision·이력을 같은 세션/작업에 보존하고, pending·declined 요청을 실제 작업 제어에 반영한다. 응답과 실행을 분리해 승인/해결된 `resume_task`만 명시적으로 수동 실행한다. 원래 목표·무결성·pause·call/time 예산을 유지하며 임의 명령·모델 dispatch·QA 완료·자동 병합·외부 권한을 만들지 않는다. `supersedes`는 같은 작업의 이전 요청을 명시 대체하되 새 pending 응답부터 시작하고 승인을 승계하지 않는다. 스킬 사용이 loop-work의 활성화/해제나 작업 교체를 뜻하지 않는다.

두 제공자의 연결/복사 설치, 구형 v2 업그레이드, 비소유 파일 보존을 검증하고 스킬/UI 자산을 runtime copy와 source seal에 포함했다. 기본 목록은 실제 처리가 필요한 pending·declined·failed·미실행 허용 resume 요청을 표시하며 처리 이력은 별도로 조회한다. 개발 상태 조회만으로 요청이 stale이 되는 결함과 feedback 저장 응답의 human blocker/revision 누락도 실제 재현 후 수정했다.

최신 전달 후보 source `f2e09c988c8b1dcf219d0a51db15d83daf9d22248ed1c7d44de2896ec304916a`에서 실제 브라우저로 `resolved` 기록→수동 resume 실행을 확인했다. `browser-delivery-result.json`에는 executed/revision 4, 두 작업의 목표 불변, calls 2 유지, delegation 0이 남는다. source는 전체 suite 시작 pin과 같았다. 데스크톱/모바일 화면을 보존했고 폭 390px에서 DOM document width도 390px임을 assertion으로 확인했다. 최초 Browser bootstrap 실패 후 이미 캐시된 Playwright를 사용했으며 새 설치·전역 설정 변경·로그인은 수행하지 않았다. 이전 후보의 응답·명시 대체 흐름과 실패 기록도 별도로 보존했다. 데모 응답은 fixture 입력이며 실제 사용자 승인이나 외부 확인을 대신하지 않는다.

### 통과·실패·미확인 범위

| 검증 | 기록과 한계 |
|---|---|
| 국소 검증 | human/orchestration 34 tests, historical/v2/lifecycle 49 tests 통과 뒤 핵심 7개를 독립 재실행해 7 PASS/6.167초와 source/test pins 불변 확인. 12개 history probe는 JSON 읽기 12회, cycle 차단, legacy의 기록된 pin 정상 허용/변조 차단 확인. 후속 handoff/completion 수정은 담당자 A73/B43 tests 및 human/HTTP28 tests 통과. 겹치는 suite·반복 실행이며 합산하지 않음 |
| 첫 완료 전체 suite | **479 tests/481.883초, exit 1: failures 2·errors 2.** source/test pins는 불변. 앞선 `full-tests.log`, `full-tests-final.log` 두 실행의 exit 130 중단도 보존하며 성공 근거로 쓰지 않음 |
| 전체 suite 회귀 정정 | 구형 설치 fixture가 현재 human 어댑터를 가상의 loop-dev 소유권에 포함한 문제를 실제 과거 exact layout으로 고정. installer 검사는 완화하지 않았고 비소유 human 파일 보존/위조 소유권 거절 추가. rename10·설치 관련37 tests 통과. 별도 team_cli 기대 문구는 실제 조기 무결성 오류에 맞춤 |
| 수정 후 전체 suite | `python3 -m unittest discover -s tests -v`: **481 tests/482.671초, OK·exit 0**. driver elapsed 482.769초, source/runtime/all-tests pins 불변. source `f2e09c988c8b1dcf219d0a51db15d83daf9d22248ed1c7d44de2896ec304916a`; `full-suite-corrected` 로그·summary 보존. 세 번째 리뷰 실패를 이 결과로 무효화하거나 완료로 바꾸지 않음 |
| 도구·평가 경계 | skill-creator quick_validate는 PyYAML 부재로 미실행이며 설치하지 않음. 실제 모델 before/after 품질·속도 개선, live full benchmark 및 bench gate 통과는 미검증 |

### 독립 검토 3회와 중단 이유

세 번 모두 fresh Codex `gpt-6.1-sol`/`high`, 실제 1호출씩이며 source/runtime/test 및 host pins가 검토 전후 같았다. 같은 제공자의 독립 호출이며 backend 설정 인증이나 반대 제공자 교차 검증으로 확대하지 않는다.

| 회차 | 결과 | 발견과 후속 상태 |
|---|---|---|
| 1 | revise, major 2, 158.435초 | 과거 attempt의 result/assessment/dispatch/raw/body pin 누락과 human 응답/resume authority race. 공통 validator 및 실제 전이 transaction 재검사를 구현하고 국소 회귀 확인 |
| 2 | revise, major 2, 130.543초 | prerequisite handoff와 completion guard의 validator 호출 누락. 실제 producer 및 같은 task retained workers에 연결하고 효과 경계 callgraph를 감사. 다른 task의 지식을 전역 차단하지 않음 |
| 3 | **revise, major 1, 153.127초** | 공개 knowledge remember에서 기존 worker-derived draft를 동일 ID로 confirmed로 승격하는 한정 경로가 여전히 원 producer의 손상된 assessment/dispatch/history를 검사하지 않음. 미해결로 보존 |

마지막 finding은 실제 accepted finding draft를 만든 뒤 assessment를 변조하고, 원래 session/task·ID·내용·근거를 유지한 채 confirmed로 저장하는 경로로 재현했다. **자동승격은 아니며 명시적인 `remember(status=confirmed)` 입력이 필요하다.** 그러나 현재 observed_revision은 source fingerprint 일치만 확인하므로 독립적인 내용 재검증이나 producer 의존성 해소를 증명하지 않는다. 이 판정은 기존 worker-derived 동일 ID의 lineage 보호로 한정한다. 모든 독립 수동 사실까지 같은 task의 모든 worker 손상 때문에 차단하는 광범위한 guard는 과도하다.

의심되는 가정은 **일반 수동 지식 입력과 worker 유래 draft의 동일 ID 승격을 같은 경로로 취급하면서도 출처 의존성과 독립 재검증을 구분할 수 있다는 것**이다. 향후에는 해당 draft의 producer provenance와 의존 pin만 확인하거나, 독립 재검증의 명시적 provenance/receipt를 구분하는 좁은 설계가 필요하다. 이번에는 추가 수리를 시도하지 않는다. 전체 suite 통과가 나오더라도 이 의미 결함이나 세 차례 revise를 해소한 것으로 간주하지 않는다.

감사 근거는 로컬 `/Users/minjoon/orca/projects/loop-work-benchmarks/human-desk-20261020/`의 `independent-review{,-2,-3}/summary.json`, `browser-delivery-result.json`, 전달 화면 두 장, 전체 suite 로그와 `knowledge-promotion-same-provenance.json`에 보존한다. 이 산출물은 별도 전달 없이는 다른 checkout에서 열리거나 재현된다고 보장하지 않는다.

---


기준일: 2026-10-19. 외부 제품 저장소의 `docs/loop-work-final-evaluation.md`와 `docs/loop-work-improvement-proposal.md`에서 제기한 입력 계약 충돌, 불필요한 상향·반복, 완료 barrier 문제를 다룬다. 두 원문과 이전 평가 기록은 수정하지 않았다. 이 문서는 설치된 전역 설정이나 제품 SDK를 변경했다는 기록이 아니다.

## 최신 상태: 재개 후 다시 미완료·중단

사용자 명시 재개 후에도 완료 fresh 리뷰 3회가 모두 revise여서, 같은 AGENTS.md의 **“After three failed fixes, stop and name the doubtful assumption.”** 지침을 다시 적용했다. 추가 코드·테스트 수정, 모델 호출, 전체 suite, commit·push를 중단했다. **현재 변경은 미커밋·미푸시이며 재개 후 전체 suite 실행은 0회다.** 앞선 전체 suite 2회의 exit 130 중단은 그대로 보존한다.

최신 독립 리뷰는 **major 2건·105.149초**다. 완료 team 재사용이 모든 accepted member의 assessment pin을 확인하지 않는 경로, dispatch pin 검사가 freshness의 OR 분기 뒤에 있어 unrelated source/parent drift와 `--recover`가 변조 검사를 건너뛰는 경로가 남았다. 의심되는 가정은 **immutable artifact pin 검증과 context freshness 판정을 조건 분기 안에서 함께 처리해도 모든 실행·재사용·전달 경계의 무결성이 보장된다는 것**이다. 변조 검증이 staleness의 short-circuit·reuse 선택에 종속되면 안 된다는 문제가 해결되지 않았다.

전체 완료 리뷰는 6회 모두 revise이며, 별도 명시 중단 1회를 포함한 실제 review 호출은 7회다. 최신 source 후보는 `7cb38b129984b616ec2b5be7e9abe17f659e61aa50d0f1a413257c2d0ebd641f`이고 수용·승격되지 않았다. 마지막 리뷰의 host/source/runtime/test pins는 불변이었으며 실제 1호출과 receipt-ledger가 일치했다. 전체 품질 향상·최종 검증 통과·benchmark gate 승격을 주장하지 않는다.

## 재개 전 중단 기록: 미완료

사용자가 이 대화에 제공한 AGENTS.md 작업 지침의 **“After three failed fixes, stop and name the doubtful assumption.”** 규칙을 적용해 중단했다. 의심되는 가정은 **retirement freshness에서 입력의 원래 absence와 authorized own write가 만든 정상 결과를 하나의 guard로 처리해도 된다는 것**이다. 수리 과정에서 stale 입력 차단과 정상 contribution 보존 사이의 false positive가 반복됐다.

최신 완료 독립 리뷰는 **revise: major 1건·minor 1건**이다. 원래 없던 파일을 같은 assignment의 수용된 write가 정상 생성해도 retirement가 막히는 문제가 남았다. `tests/test_assignment_v2.py`의 ledger 변경 검사는 새 append-only prefix 오류에도 옛 `immutable` 문구를 기대하며, 이 테스트 정합성 문제도 미해결이다.

코드 수정·추가 모델 호출·전체 suite 실행·commit·push를 중단했다. 변경은 **미커밋·미푸시** 상태다. 아래 controlled 통과 기록은 보존하지만 최종 완료나 품질 승격으로 사용하지 않는다. 이 상태 기록만 마지막으로 갱신했다.

## 변경 범위

- **명시적 v2 제출 계약:** worker 소유 검증과 orchestrator 소유 후속 검증을 구분한다. 후자는 worker 응답에서 pending이며, 실제 수용에는 모든 assignment·goal check의 참값과 정확한 증거가 필요하다. v1은 기존 의미를 유지한다. 입력·fixture 교정은 연결된 revision으로 같은 work unit의 profile·attempts·calls·시간 기점을 계승한다. 이전 실패와 누적 correction은 지우지 않는다.
- **원인과 다음 행동:** worker 출력 품질 실패, 입력·fixture 오류, transport·freshness 장애를 구분한다. 응답과 실행 guard가 attempt·call·time cap 및 profile ceiling을 반영한다. stale evidence의 정상 복구는 같은 profile을 유지하며, pin 변조는 별도 오류다. reviewer는 현재와 revision history의 high complexity·risk·uncertainty를 보존한다. rank는 가격이나 실측 능력이 아니다.
- **정확한 부분 수정:** opt-in v2 patch는 UTF-8 byte offset과 mode-aware base/result fingerprint를 검사한다. 중첩·중복 위치·UTF-8 경계 손상·오래된 base를 거절하고, 기존 파일별 atomic 쓰기 경로를 사용한다. 여러 파일 전체의 crash atomic transaction을 보장하지 않는다.
- **수용된 대체와 완료 책임:** retirement는 거절된 assignment의 상태·이력·예산을 보존하며, 현재 수용된 대체 contribution과 criterion coverage를 연결한다. 현재 근거 pin과 피드백을 재검사한다. 정당한 consumer의 무관한 파일 수정과, 분석이 의존한 소스의 변경을 구분한다. retirement가 fresh 개발 gate·final review·finish를 대신하지 않는다. 수동 block의 근거 검증은 외부 host hook·자동 재개 보장과 별개다.
- **관측층 분리:** process receipt에 requested profile, 실제 argv에서 읽은 local profile, 관측 가능한 CLI JSON usage를 구분해 기록한다. backend attestation·CLI version·모델별 지원·가격·금액은 근거가 없으면 unknown/null이다. 추가 인증·설정·버전 CLI 호출은 하지 않는다. versioned support catalog와 그에 근거한 unsupported effort 차단은 미구현·미실행이다.

## 고정 controlled 비교

수정 전 source snapshot은 `8238e375ac688bb4db91688da9b4ec47b562ed8518981cfa603077fb0949e2b0`, 첫 controlled 비교 snapshot은 `4b69a84db93cdc0f3accfec60555d11df4eb0e27d8a3a0832eeca7ceae3d4c38`이다. test pins·사전 기준·driver·실패 결과를 별도로 보존했다. 이 snapshot의 controlled 사례는 통과했지만 후속 독립 리뷰에서 거절됐으므로 최종 수용·승격된 소스가 아니다. 아래는 실제 모델 대신 격리된 provider stub을 사용한 진단이며, 실제 모델의 품질·속도 비교가 아니다.

| 고정 사례 | 수정 전 | 수정 후 | 판정 범위 |
|---|---|---|---|
| attempt 3회·calls 소진·시간 만료·profile ceiling, 네 사례 | 모두 응답이 상향 재시도를 권고했지만 실제 guard는 추가 호출 0건으로 차단 | 모두 중단 사유를 표시하고 추가 호출 0건 | 안내와 guard의 정합성 개선. 전체 stub 호출 합계는 전후 각각 6건으로 동률이며 호출 감소를 입증하지 않음 |
| input·fixture 원인별 v2 revision | v2 미지원, provider stub 호출 0건 | 두 원인 모두 같은 profile로 attempts 1→2→3, history revisions 1·2 보존, revision 4 호출 차단 | 새 계약의 동작 확인. 미지원 기능을 이전 모델 품질 실패로 세지 않음 |
| UTF-8 문서 4개, 총 38,444 bytes의 도입부 네 수정 | whole changes 배열 JSON 39,797 bytes | patch changes 배열 JSON 1,005 bytes | 결과 bytes와 비대상 prefix/suffix 동일. **제안 JSON 크기**만의 측정이며 모델 token·실행시간 절감률이 아님 |
| 실제 Python compile과 후속 proof | 고의 compile 실패 뒤 proof 0건 | 수정 후 compile 성공 뒤 proof 1건 | fixture 원인은 동일 profile 교정, worker 원인은 상향 정책과 대조. compile exit 분기는 진단 runner가 실행했으며 새 자동 compiler hook을 의미하지 않음 |

정적 통합 감사에서 별도로 발견한 세 결함도 반례를 보존했다. 구조적으로 invalid인 worker 결과를 provider 실패로 재분류해 같은 profile을 재호출하는 경로, 변경된 분석 근거를 retirement가 수용하는 경로, revision에서 high demand·금지사항을 낮추는 경로다. 수정 후 앞의 두 실제 통합 반례는 각각 origin 오류와 stale evidence 오류로 차단됐고, demand history 보존 회귀도 추가됐다.

## 리뷰 수정 후 재검증

두 번째 controlled 비교 snapshot은 `c979aa9887902a34dff41643a8eeb243bffc66bfb1706f6c3fda3842a25e1865`이다. 같은 cap·lineage driver와 patch/compile fixture를 다시 실행해 기존 표의 결과를 확인했다. 새 결과는 `after-review-fixes-manifest.json`과 `controlled-comparison/comparison-after-review-fixes.json`에 별도로 보존했다. 이전 결과를 덮어쓰지 않았다.

독립 리뷰 finding 다섯 개를 실제 통합 여섯 사례로 추가 재현했다(시간 만료의 candidate/done을 각각 검사). 거절된 이전 소스는 0/6, 수정 소스는 6/6 통과했다. 만료 후 현재 candidate/done은 호출 0건으로 재사용되고, stale rejection의 원래 attempt bytes와 rejected history는 유지된다. 외부 receipt만 수용 근거로 제시한 분석도 scoped read source가 바뀌면 retirement가 차단된다. `.git/info/exclude` 변경 뒤 ignored target은 첫 쓰기 전에 거절되어 파일이 생기지 않는다. valid retired obligation의 preview는 상향 재시도를 지시하지 않는다. 이 추가 회귀는 최초 고정 기준을 바꾼 결과가 아니라 리뷰 발견을 별도로 검사한 결과다. 이 소스 역시 두 번째 fresh 리뷰에서 거절됐으므로 최종 수용·승격된 소스가 아니다. 후속 검증과 중단 상태는 아래에 보존한다.

## 보존한 실패와 한계

처음 문서 fixture가 35KB 조건에 못 미친 측정 실패, time fixture가 사후 state 변경으로 freshness까지 건드린 실행, 마지막 오류 문구 호환 수정 전 intermediate snapshot을 보존했다. 시간 사례는 state를 바꾸지 않고 clock만 전진시키는 동일 driver로 다시 확인했다. 독립 리뷰 준비 중 `engine_digest` API 인자 오류는 모델 호출 전에 발생했으며 호출 0건으로 기록했다. 이 결과들을 성공으로 덮거나 삭제하지 않았다.

로컬 감사 파일은 sibling 디렉토리 `../loop-work-benchmarks/routing-improvement-20261019-06dc04b5/`에 있다. 핵심 파일은 `manifest.json`, `after-final-manifest.json`, `controlled-comparison/criteria.json`, `controlled-comparison/comparison.json` 및 후속 `controlled-comparison/comparison-after-review-fixes.json`이다. 이 디렉토리는 저장소 배포물에 포함되지 않으므로 다른 checkout에서 재현하려면 별도 전달이 필요하다.

새 Git root들의 trust 준비는 승인되지 않았다. 전역 Codex 설정·auth·hooks·CODEX_HOME은 변경하지 않았다. 따라서 실제 provider를 사용한 두 goal type·holdout·반복 full benchmark와 `bench gate`는 미검증이며, benchmark-validated 승격을 주장하지 않는다. controlled 진단의 개선을 실제 모델 품질 향상·전체 사용자 대기시간 절감·최적 모델 선택·비용 절감으로 확대하지 않는다.

## 중단 시점 검증 상태

| 항목 | 확인된 결과 |
|---|---|
| 완료 독립 리뷰 3회 | 모두 revise. 첫째 major 5건·133.346초, 둘째 major 3건/minor 1건·134.375초, 셋째 major 1건/minor 1건·123.687초. 각 완료 호출은 host/source/runtime/test pins 불변·receipt-ledger 일치 |
| 별도 중단 리뷰 1회 | 33.426초, 실제 1호출·unfinished 1·calls_complete=false. 새 source 경계 발견으로 명시 중단, 소스 변동도 기록. 수용 근거로 사용하지 않음. 총 실제 review 호출은 4회 |
| 전체 unittest suite 2회 | 둘 다 SIGINT·exit 130으로 중단. `/tmp/loop-final-improvements-tests-20261019.log`와 `/tmp/loop-final-improvements-reviewfixes-tests-20261019.log` 보존. 최종 전체 suite 통과 결과 없음, 추가 실행 중단 |
| 최신 미해결 사항 | 정상 accepted own-file creation의 retirement 차단, ledger prefix 오류에 대한 옛 immutable 테스트 기대. 코드·테스트 추가 수정하지 않음 |
| 전달 상태 | commit·push 미실행. benchmark gate·최종 품질 승격 없음 |

완료 리뷰는 모두 `gpt-6.1-sol/high`, read-only·ephemeral·same-provider fresh 조건이었다. 요청 profile 및 local 관측이며 backend 실효값 인증이 아니다.

첫 독립 검토는 시간 소진 후 zero-call 재사용, stale rejection 이력 보존, retirement 분석의 읽기 의존성, apply 직전 ignored write fence, orchestration의 typed/retired retry 안내를 지적했다. 최초 controlled 사례 통과가 이 경계들의 정확성까지 입증하지 못했음을 기록한다. 첫 검토 원문과 실패 판정은 후속 성공으로 덮어쓰지 않는다.

두 번째 독립 검토는 absent-base patch의 잘못된 execution 실패 분류, 설치된 skill symlink의 retirement rule 검증, 높아진 revision demand에 대한 기존 profile 적격성, 누적 ledger의 순서 보존을 지적했다. 이 리뷰 원문과 거절 소스도 별도로 보존하며 최종 통과로 표현하지 않는다.

추가 확인된 absence 경계는 명시적 read path가 처음에는 없었지만 같은 위치에 ignored 파일·symlink가 생긴 경우다. 기존 visible inventory만으로는 둘 다 없어 보였다. 해당 두 반례를 보존하고 수정 후 모두 retirement 차단을 확인했다. directory scope는 과거에 실제 관측된 membership만 비교하며, 과거 hidden tree 목록을 만들거나 hidden 내용을 추가 scan하지 않는다. B 담당자의 `/tmp` 감사 결과와 로그도 sibling 감사 영역으로 복사했다.

세 번째 완료 리뷰를 받은 후보 snapshot은 `5c2183d37c028462e9f1bcaeef794f0438c925c6d132b7b9da524b47395c022d`이며 `after-visibility-fix-manifest.json`·`controlled-comparison/comparison-final.json`에 기록했다. 같은 cap·lineage·patch/compile 및 추가 회귀 12사례(리뷰1 6·리뷰2 4·absence 2)를 다시 통과했다. 앞선 `8e2f55bf…` 후보의 fresh 리뷰는 새 경계 발견으로 33.426초에 명시 중단했다. 실제 1호출·unfinished 1·calls_complete=false이며 소스 변동도 기록돼 그 결과는 수용 근거로 사용하지 않는다. 이전 완료 리뷰 2회와 이 중단 호출을 보존한 뒤 새 경로에서 fresh 리뷰를 재시작했다.

세 번째 완료 fresh 리뷰도 revise였다: 123.687초·실제 1회, major 1건과 minor 1건이다. 명시적 absent read와 write scope가 겹친 파일을 수용된 contribution이 정상 생성했는데도 retirement가 차단되는 경계와, ledger prefix 오류에 대해 옛 immutable 문구를 기대하는 통합 테스트를 지적했다. 해당 소스는 최종 수용·승격되지 않았으며 추가 수정·전체 suite·commit·push는 3회 실패 중단 규칙에 따라 수행하지 않는다. host/source/runtime/test pins는 검토 전후 동일했고 이 리뷰의 receipt-ledger도 일치했다. 완료 리뷰는 3회 모두 revise이며, 별도 중단 호출 1회를 포함한 실제 review 호출은 4회다.

중단 후 최종 문서 확인은 `git diff --check -- docs/final-evaluation-improvements.md`로 한정했다. 이후 재개 여부는 이 미완료 상태와 의심 가정을 먼저 확인한 뒤 결정해야 한다.

## 사용자 명시 재개 이후 — 보존한 진행·실패 기록

사용자의 명시적 재개 지시에 따라 앞의 중단과 실패 이력을 보존한 별도 `resumed/` 감사 영역에서 진행했다. 재개 소스 `93d1e52ada8fc54e693a5bf133983564b0144f6b4d7d314eaf3d9b5f29e1b6fe`에서 정상 accepted own-file creation과 tampered output 차단, 기존 12반례·cap·lineage·patch/compile을 재확인했다. 원래 마지막 major와 ledger 테스트 문구 문제는 수정됐지만, 재개 후 첫 fresh 리뷰는 major 2건으로 revise였다(126.331초·실제 1회, host/source/runtime/test pins 불변·계측 일치).

새 finding은 assessment 전에 exact absent read가 ignored 파일·symlink로 바뀌는 경우와, accepted write-only output이 같은 bytes를 유지한 채 ignored가 되는 경우다. 이는 기존 retirement read 경계와 다른 promotion/output 경계이며 해결 완료로 표시하지 않는다. 이 재개 리뷰까지 완료 리뷰는 4회 모두 revise, 별도 중단 1회를 포함한 실제 review 호출은 총 5회다. 재개 후 전체 suite는 아직 실행하지 않았고 commit·push도 미실행이다. 재개 후 결과는 앞의 중단 당시 상태를 소급 변경하지 않는다.

## 재개 후 controlled 검증과 마지막 미해결 사항

재개 후 마지막 후보와 test pins는 `resumed/delivery-manifest.json`, 동일 controlled 결과는 `resumed/delivery-final/comparison.json`, 마지막 fresh 리뷰는 `resumed/independent-review-delivery/summary.json`에 보존했다. 직전 `894c7b6a…` 거절 소스와 새 3그룹의 실제 6반례는 `resumed/delivery-patch-pins-before-canonical/result.json`에 남았다. 이후 후보에서는 해당 고정 반례들이 통과했지만, 마지막 리뷰가 다른 무결성 경로를 추가 발견했으므로 전체 통과로 확대하지 않는다.

정상 accepted own creation과 변조된 own output 차단, ledger prefix 테스트 문구, retirement의 read/write visibility·directory kind 경계는 각각 targeted/controlled 재검증에서 해소를 확인했다. 최신 리뷰의 PATCH·OBSERVATION coverage도 true였다. 이전 리뷰에서 retirement lifecycle 세부 수정이 확인된 사실은 유지한다. 다만 **최신 LIFECYCLE coverage 전체는 completed-team assessment 무결성 문제로 false**이므로 전체 lifecycle 통과라고 표시하지 않는다.

누적 finding을 확인한 추가 진단에는 prerequisite·peer delivery의 declared-path freshness, newly ignored patch base의 pre-read fence, accepted result/assessment 변조와 source drift 조합, done write-only delete 이후 empty directory, writable read의 미수정 경로와 directory kind 전이가 포함된다. 고정 사례의 통과, 제안 changes JSON 39,797→1,005 bytes, cap 비교의 stub 호출 전후 각각 6건 동률은 그 범위에서만 유지한다. 실제 모델 결과 품질·전체 작업 시간·비용 절감은 입증되지 않았다.

첫 patch-read spy가 `/var`와 `/private/var` 별칭을 다른 경로로 취급한 초기 측정도 보존했다. canonical identity로 고친 동일 측정은 거절 소스의 ignored base `read_bytes` 1회를 재현했고, 수리 후보의 0회를 확인했다. 잘못된 초기 spy의 0회를 성공 근거로 사용하지 않았다.

이번 재개에서도 전역 설정·auth·trust·hooks를 변경하지 않았고 live full benchmark·bench gate를 실행하지 않았다. full suite는 fresh 리뷰 PASS를 선행 조건으로 두었으나 PASS가 없었으므로 실행하지 않았다. 추가 코드·테스트·모델·full suite·commit·push는 중단 상태다. 앞선 중단, 모든 source/test pins, independent 리뷰와 거절·중단·측정 실패는 삭제하거나 성공으로 덮지 않는다.


## 2026-10-20 사용자 정정: 별도 human 스킬 대신 인자 분기

사용자는 별도 스킬이 아니라 기존 `loop-work`의 인자/subcommand를 요청했다. 이에 앞서
추가했던 agent 작성 `skills/loop-human/` 3파일을 폐기하고, `$loop-work human` /
`/loop-work human`에서 활성화보다 먼저 분기하도록 canonical skill을 정정했다. 세부
사람 처리 지침은 필요한 때에만 읽는 `rules/human.md`로 옮겼다. 기존
`human list|show|request|respond|execute|serve` CLI는 유지한다. 별도 스킬 설치나 자동 검색을
요구하지 않으며 기존 explicit-only 정책, 활성화·knowledge home·세션·작업을 보존한다.
사람 처리함만 사용하는 호출은 harness를 켜거나 끄지 않고 새 목표를 만들지 않는다.

이 정정은 앞선 별도 스킬 구현·설치 검증 기록을 소급 삭제하지 않는다. 해당 기록은 당시
경과이며 현재 인터페이스의 권고가 아니다. 응답 원문·답변과 실행의 분리·기존 권한과
예산은 유지한다. 이전 미해결 knowledge finding과 세 번의 실패 후 중단은 여전히 미해결이며,
이번 인자 통합이 그 수정이나 최종 수용·품질 개선을 입증하지 않는다. 전역 설치·설정·로그인,
commit·push는 수행하지 않았다. 초기 문서·스킬 정정 단계에서는 새 모델 검토를
수행하지 않았으며, 이후 이 좁은 정정 범위의 검증을 아래와 같이 확정했다.

이번 인자 통합·설치 정정 범위의 최종 검증은 다음과 같다. 전체 명령은
`python3 -m unittest discover -s tests -v`이며, source·runtime·전체 test pins는 전후 동일했다.

| 구분 | 확인 결과와 범위 |
| --- | --- |
| 전체 suite | 484 tests, 483.091초, OK / exit 0. 별도 driver 경과 시간은 483.191초다. 두 시간은 같은 실행에서 측정 범위가 다르며 품질 판정에는 사용하지 않는다. |
| fresh 독립 검토 | 같은 제공자의 새 Codex CLI 호출, 요청 모델 `gpt-6.1-sol` / effort `high`, 52.239초, PASS / findings 없음. ARGUMENTS·INSTALL·RUNTIME coverage 모두 true. managed call 1건과 receipt·ledger 1건이 일치하며 host·source·runtime·test pins가 유지됐다. 정적 범위 검토이며 모델의 실제 backend 설정이나 전체 하네스 품질 인증은 아니다. |
| 국소 회귀 | focused 24 tests PASS / 5.992초. related 37개는 36 PASS·1 FAIL / 10.110초였고, 기존 fixture의 문자열 치환이 no-op이어서 의도한 관리 문구 변조가 없던 문제였다. 실제 관리 문구를 바꾸고 변경 여부 assertion을 추가한 뒤 해당 1개 PASS / 0.045초. 제품 guard를 완화하지 않았다. 중복 suite·재실행이므로 수치를 합산하지 않는다. |
| 추가 확인과 한계 | 별도 read-only skill-forward/integration 점검에서 구체 finding 없음. 실행 검증은 아니며 추가 모델 호출로 세지 않는다. 도움말·논리적 runtime 링크·diff 검사는 통과했다. `quick_validate.py`는 PyYAML 부재로 실패했으며 설치하지 않았다. YAML 검증 통과로 표시하지 않는다. |

확인한 source는 `164df229569fd1717c5b8fdd9682c22a790e1140f59b8c2e124099aa3a146355`,
engine digest는 `31a0d4e20463223313901800d695e0cd2a02b70f851e17dab19d3b367c8f5c3c`다.
감사 자료는 로컬
`/Users/minjoon/orca/projects/loop-work-benchmarks/human-subcommand-20261020/`의
`full-suite-summary.json`, `full-suite.log`, `independent-review/summary.json`,
`local-checks-reported.json`에서 직접 확인했다. 국소 실행의 독립 raw 로그 파일은 저장되지
않았으며 worker 도구 대화와 이를 출처로 명시한 typed summary만 있다. 존재하지 않는
원본 로그 링크를 만들지 않는다. 이 로컬 산출물은 별도 전달 없이는 다른 checkout에서
열리지 않는다.

이번 PASS는 단일 스킬의 human 인자·설치 정정 범위에 한정한다. 이전 knowledge major 1건과
세 번의 revise 후 중단 기록은 그대로 미해결이다. 전체 결과 품질·속도 개선이나 benchmark
검증 완료를 뜻하지 않으며 live benchmark·bench gate, 실제 전역 설치, commit·push는
수행하지 않았다.

## 2026-10-20 후속: Obsidian workspace 범위 완료

**이번 Obsidian setup·vault 기능 범위는 구현·전체 회귀·fresh 독립 검토를 완료했다.** 이전 worker-derived draft의 동일 ID knowledge 승격 major 1건과 원래 세 차례 revise 후 중단 기록은 미해결로 그대로 보존한다. 전체 하네스의 완료·모델 품질/속도 개선·live benchmark·bench gate 통과를 뜻하지 않는다. commit·push도 현재 보류 중이다.

### 구현과 권한 경계

사용자의 명시 요청에 따라 기본 `make install`은 Obsidian을 확인하고 없으면 기존 Homebrew로 설치하며 `~/.loop-work/vault` 하나를 준비한다. 앱이 있으면 brew를 건너뛰고, 없으면 절대 brew 경로·argv·실제 종료 결과와 앱 재탐지로 판정한다. Homebrew 자체·Python 패키지·SDK·전역 훅은 설치하지 않는다. 저수준 설치·벤치마크·runtime은 이 앱 setup을 자동 실행하지 않는다.

새 기본 지식 홈은 `~/.loop-work/data`다. 명시 knowledge-home/환경 선택을 우선하고 기존 shared DB는 원래 경로에서 재사용하며 자동 이동·병합하지 않는다. 임시/custom DB는 공유 vault 자동 출력 대상이 아니다. 설치 초기 backfill도 기존 DB의 기록/history를 읽으며 빈 DB·세션·목표를 새로 만들지 않는다. uninstall은 앱·vault·data·작업 기록을 보존한다.

DB commit 뒤 선택된 기록을 프로젝트/작업별 current·interim·final snapshot으로 출력한다. SQLite·개발 JSON이 원본이고 보고서는 cutoff 뷰다. final 파일이나 사람 노트가 승인·QA·현재 source freshness를 만들지 않는다. 기록된 stale 상태와 역사적 완료를 구분하고 원본 context로 현재 근거를 재확인한다. 관리 pin이 맞는 파일만 갱신하며 편집된/비소유 노트·`.obsidian`은 보존한다. 앱/안전 경로 실패와 문서 출력 실패를 분리해 export 충돌·조회 오류는 경고/진단으로 남기고 스킬 설치·저장된 작업을 막지 않는다. 로컬 audit 링크는 원본 파일 없이 이식 가능한 근거가 아니다.

### 실패와 수정 근거

| 단계 | 결과와 정정 |
|---|---|
| 초기 setup fixture | `workspace-setup-tests.log`: 10 tests 중 2 failures. installer 오류 exit 2를 단독 helper의 exit 1로 잘못 기대한 테스트를 정정했다. 실패 원문은 보존 |
| 선행 설치 관련 검증 | 52 PASS/12.877초였지만 완전히 격리된 실행은 아니었다. 기존 make subprocess 한 곳이 실제 home을 상속해 root 확인 전에 workspace setup을 수행했다. DB 행 변경이 발생했다고 주장할 근거는 없음 |
| 격리 정정 | 해당 make subprocess를 임시 home으로 격리했다. 별도 init subprocess는 이미 ProjectTest의 임시 LOOP_KB_HOME을 상속했으며 명시 flag 추가는 격리 강화다. 이를 두 번째 실제 home 경계로 세지 않음. 후속 관련 12 PASS/1.490초 보존 |
| exporter/backfill 경계 | old render의 늦은 current 덮기, lock-busy 실패 진단 유실, backfill constructor/조회 오류를 국소 반례로 보완했다. serialized-export 14 PASS/0.106초, vault 15 PASS/0.133초, backfill 직접 회귀 1 PASS/0.009초의 원문 로그 보존 |
| 첫 동결 후보 | source `37573384704459ebdba6bd03c3178ac375a87e3be3d4c2f4637434d385c32c58`는 **512 tests/489.604초 OK·exit 0**(driver 489.722초), pins 불변이었으나 같은 source의 첫 fresh 검토는 **199.625초·revise major 3건**이었다. 전체 테스트 통과가 의미 검토의 실패를 무효화하지 않음 |

첫 fresh 검토는 setup의 LOOP_KB_HOME 선택 누락, 같은 source revision에서 older success가 newer conflict를 덮는 진단 순서, 사용하지 않는 새 경로 충돌로 intact legacy DB의 runtime까지 차단하는 문제를 찾았다. 이 실패를 보존하고 새 후보에서 환경/명시 fake-home 선택을 분리하고, export attempt 순서와 source revision을 함께 유지하며, 실제 선택 DB와 미사용 workspace 충돌을 구분했다. 수정 후 국소 A14 tests/0.122초·B17 tests/0.180초 통과를 별도 기록했다. 단계별·중복 suite 수치는 합산하지 않는다.

### 최종 검증과 실제 사용 확인

최종 source는 `d4a79b30892140ebb9d83385761c01db9b284ff8e520aada3600d0deb4cb9939`, engine digest는 `8942e8e79172d7d46d8a947503a23f053ecfc7cab5a794c28a097ab100c1fbeb`다.

| 검증 | 최종 결과 |
|---|---|
| 전체 회귀 | `python3 -m unittest discover -s tests -v`: **517 tests/488.286초 OK·exit 0**, driver 488.386초. source/runtime/all-tests pins 불변. `full-suite-reviewfixes-summary.json`·log 보존 |
| Fresh 독립 검토 | Codex `gpt-6.1-sol`/`high`, same-provider fresh **PASS·findings 0·159.127초**. SETUP·VAULT·PRESERVATION·RUNTIME 모두 true. 실제 1호출과 receipt-ledger 일치, source/runtime/all-tests/host pins 불변. 정적 source 검토이며 실제 provider 성능 시험은 아님 |
| 실제 host setup | 기존 `/Applications/Obsidian.app`을 재사용해 brew 설치를 건너뛰었다. `~/.loop-work/vault`·`.obsidian`·README 준비와 선택 기록 **97개→Markdown 242개, export errors 0**을 확인. 실제 missing-app 다운로드 branch는 실행하지 않았으며 mock 검증 범위 |
| 반복·보존 확인 | 최종 source r5는 **exit 0·0.742초**, Markdown pins 불변. 앞선 r3는 source의 revision 표시 갱신으로 MD pins가 달랐고 r4는 불변이었던 사실도 보존. 최종 517개 실행 뒤에도 초기 실제 DB pin·records·history 불변, Markdown 242개 유지, verified pins current 확인 |

실제 DB는 기존 `~/.local/share/loop-work/knowledge.sqlite3`의 records 113·history 709를 유지했다. 97개는 exporter가 선택한 기록 수이며 전체 DB record 수와 단위가 다르다. Obsidian 전역 vault registry는 등록하지 않았고 사용자는 폴더를 직접 연다. root의 실제 사용자 홈 setup과, 임시 home/subprocess로 확인한 `make install` 동작을 구분한다. 이번에 실제 전역 discovery 링크 설치를 수행한 것은 아니다. setup 소요 시간은 관찰값이며 하네스 속도 향상이나 모델 비용 절감률로 사용하지 않는다.

근거는 로컬 `/Users/minjoon/orca/projects/loop-work-benchmarks/obsidian-workspace-20261020/`의 `starting-and-corrections.json`, 초기 실패·격리 정정·국소 회귀 로그, 두 전체 suite 결과, `independent-review{,-2}/summary.json`, `live-setup-r3/r4/r5-summary.json`, `final-preservation-check.json`에 보존한다. 별도 전달 없이는 다른 checkout에서 열리거나 재현된다고 보장하지 않는다. 이 범위의 통과로 이전 미해결 knowledge lineage나 과거 실패 기록을 지우지 않는다.

## 2026-10-21 — Obsidian 작업 보드: 보드 범위 구현·검증 완료

`$loop-work board serve`와 `/loop-work board serve`를 기존 단일 스킬에 추가했다.
board 분기는 활성화 처리보다 먼저 실행하며 기존 entrypoint·KB·세션·작업 바인딩을 보존한다.
기존 `human` CLI는 호환 경로로 유지한다.
localhost 서버를 준비한 뒤 기본 브라우저 열기를 시도하고, `--no-open`으로 생략할 수 있다.
브라우저 열기 실패는 서버를 종료시키지 않는다.

### 데이터·권한 경계

보드의 표시 데이터와 본문은 실제 Obsidian vault Markdown에서 읽는다.
current/interim/final 문서를 표시하고, runtime 소유 inventory 밖의 vault-only 작업도 읽기 전용으로 발견한다.
사용자 편집 노트·무소유 파일은 보존한다.
SQLite/JSON은 실행·권한·검증 authority이며, 문서 편집은 승인·QA·완료를 만들지 않는다.
승인 응답과 resume 실행은 분리하고 원문 응답, source/control/budget/evidence 검사를 유지한다.
runtime/vault revision과 실제 mutation transaction의 검사를 거쳐 실행한다.
이미 commit된 응답·실행의 export 오류는 별도 진단이며 같은 action을 재실행하는 근거가 아니다.
scoped 서버는 다른 작업의 ID·경로·오류를 포함하는 전역 진단을 반환하지 않는다.

### 현재 검증

| 구분 | 실제 확인 결과 |
|---|---|
| 독립 검토 7 | fresh Codex `gpt-6.1-sol/high`, same-provider, PASS, findings 0, 126.102초 |
| 검토 무결성 | source/runtime/tests·host 핀 불변, 실제 call 1, managed receipt 1/ledger 1, accounting complete |
| 검토 범위 | BOARD/VAULT/ACTIONS/INSTALL 충족으로 정적 검토. 검토자 자체의 tests/browser 실행은 없음 |
| 브라우저 | 실제 fixture에서 경합 양방향과 refresh 실패, 본문 표시·script 비실행, 승인/별도 실행 흐름 확인 |
| Portable | copied skill entrypoint, 명시 KB/vault/task, `--no-open`, HTTP 200, 지정 작업만 표시, exit 0, 0.601초 |
| 전체 테스트 | `python3 -m unittest discover -s tests -v`: 557 tests/500.472초 OK, exit 0, driver 500.571초, source/runtime/tests 핀 불변 |
| 실제 사용자 자료 | 완료된 테스트 후 `baseline_equal=true`: DB SHA·records 113/history 709 동일, MD 242개 경로·SHA 동일, 추가/삭제/변경 0, errors 없음 |

현재 확인 source는 `ee1ee0159265e397f468d36b431443e29a5ee32ea2bbcb7344149a5ddbbcb5db`,
engine은 `dc52b77033456be39a96d9e99314e86479544ce2a7ae0b014588e1fc8f78b241`다.
`browser-completion-summary.json`에서 selection-before-refresh의 늦은 응답이 stale 상세를 되살리지 않았다.
refresh-before-selection 및 refresh 실패에서는 loading 중 선택을 차단하고 unavailable 상세를 비웠다.
실제 vault 본문과 script literal은 표시하되 script는 실행하지 않았다.
승인만으로 blocked 작업은 바뀌지 않았고 별도 execute로 goal_setting 전이를 확인했다.
목표·예산·worker budget·delegations·원문을 보존했고 실행 후 replay controls는 0이었다.
이 브라우저 결과는 isolated fixture이며 Obsidian 앱 자체를 조작한 검증은 아니다.
기본 브라우저 opener는 회귀 테스트 범위이고 위 portable 실행은 `--no-open`이었다.

### 이전 실패·중단을 유지한다

독립 검토 1~6은 모두 revise였다. 순서대로 major 2/minor 1, major 1, minor 1,
major 1, major 1, major 2이며 각 원본 summary와 source/test 핀을 보존한다.
발견·scope/history, FIFO leaf read, refresh 상태, 실제 startup exporter manifest/locks,
재선택 오류, optional 진단 nested shape 및 refresh-before-selection 경계를 고쳤다.
root의 실제 copied UI 늦은 응답 재현도 실패 기록을 남기고 epoch/loading 수리 후 다시 확인했다.
전체 테스트 세 번은 exit -2로 각각 289.745초·205.776초·188.932초에 중단됐다.
핀 불변이어도 전체 테스트 성공 근거가 아니며 이번 완료 실행과 구분한다.
관련 35→36→55→58 tests 통과는 겹치는 집합이므로 합산하지 않는다.
status lock FIFO probe의 2.005초 timeout과 export lock의 당시 0.143초 반환도 구분한다.
후자는 수정 진행 중 관찰이며 선행 실패로 주장하지 않는다.

### 근거·한계

로컬 audit: `/Users/minjoon/orca/projects/loop-work-benchmarks/obsidian-board-20261020/`.
`independent-review{,-2..-7}/summary.json`과 pins, `browser-completion-summary.json`,
`portable-completion-summary.json`, `late-response-before-failure.json`,
`detail-state-browser-final.json`, 각 full-suite summary/log 및 관련 tests 로그를 보존한다.
긴 `board-evaluation-final-draft.md`와 이전 browser/startup 증거도 그대로 유지한다.
이 로컬 산출물은 별도 전달 없이 다른 checkout에서 열리거나 재현된다고 보장하지 않는다.
이번 global discovery 설치와 commit/push는 실행하지 않았다.
기존 worker-derived knowledge promotion major 1은 별도 미해결로 유지한다.
보드 범위 구현·검증은 완료했다. 이 기능의 검증은 전체 하네스 완성·모델 품질/속도 개선·live paired benchmark·bench gate 통과의 근거가 아니다.

## 2026-10-21 — 한 작업 결속·보드 직접 제어 구현 완료: 전체 실패와 모듈 재검증의 조합

`$loop-work <prompt>` / `/loop-work <prompt>`는 대화 전체 대신 명시한 한 작업에만 결속한다.
관련 정정·상태 확인·맥락 압축은 같은 작업이며 무관한 일반 입력은 자동 처리하지 않는다.
완료·abort는 terminal transition과 결속 해제를 함께 저장하고 기록·유한 예산을 보존한다.
bare 호출은 작업 내용만 한 번 묻고 상태를 만들지 않는다. 구형 enabled는 자동 활성화 권한이 아니다.
off는 호환 해제이며 board/human은 관리 명령으로서 기존 entrypoint·KB·세션·작업을 유지한다.

보드 direct controls는 pending 질문 없이 pause/resume/correction/constraint 원문을 저장한다.
operation ID와 task/control/vault revision CAS를 사용하며 resume는 feedback pause만 해제한다.
blocked phase·QA·예산을 우회하지 않는다. runtime·관리 subprocess는 실제 취소 관찰을 수행하고
빠른 pause/resume·off/on으로 이전 호출을 되살리지 않는다. 모든 외부 프로세스의 즉시 종료나
이미 적용된 변경 rollback을 보장하지 않는다. UI는 5초 polling과 원문·focus/caret 보존을 제공한다.

### 확인된 결과와 검증 단위

| 검증 | 결과·해석 |
|---|---|
| 독립 review 4 | PASS, findings 0, TASK/INTERRUPT/BOARD/INTEGRITY 모두 true, 153.854초 |
| 검토 계측 | fresh Codex gpt-6.1-sol/high 실제 1 call, source/runtime/tests·host 핀 불변, managed receipt 1/ledger 1·accounting complete |
| 완료 전체 실행 | 596 tests/541.528초, driver 541.633초, exit 1, failures 1(595 통과), 핀 불변. **전체 PASS 아님** |
| 단일 fixture 정정 후 | strict 모듈 재실행 10 tests/18.519초 OK, driver 18.600초, exit 0, 실제 pre/post 핀 불변. 앞선 10 tests/18.591초도 별도 보존 |
| 조합 무결성 | final-routing-fixture-summary.json: product가 완료 전체·review 4와 동일, 변경 test는 tests/test_routing_cli.py 정확히 1개 |
| 사용자 자료 | 최종 targeted 후 baseline_equal=true: DB SHA·records 113/history 709, MD 242개 경로·SHA 동일, added/removed/changed 0, errors 없음 |

실제 환경은 Python 3.13.7/macOS 26.5.2 arm64다(`validation-environment.json`).
검토·전체 실행 source는 `6f5abd10e3b3430da558f118d760d43b1726307693cc9ff5e9578590be8a6083`,
engine은 `8a6d3a11ed16d00de257c3e01931dc79372596ffe74e0ba02b3b9426ebbe0c0f`다.
`final-pin-crosscheck-before.json`은 review 4 전후와 전체 시작의 source/engine/tests 일치를 확인한다.
이 기록은 전체 시작 전 대조다. 최종 조합은 final-routing-fixture-summary의 실제 pre/post 및 완료 전체·review 4 대조로 확인했다.

전체 실행의 유일 실패는 test_routing_cli의 installed nonGit capsule fixture였다.
setUp이 개발 A를 결속한 뒤 같은 세션의 별도 B도 자동 활성이라고 가정한 구형 계약이었다.
제품이 B를 inactive로 표시한 것은 새 계약에 맞다. fixture는 B 비활성·A binding 보존을
검사하고 installed CLI로 명시 A off→B --task on을 수행한 뒤 원래 delegate/assess를 실행한다.
독립 읽기에서 기존 bytecap·provider/candidate/profile·assess next·실제 accept passed·
feedback revision·nonGit·후속 blocker assertions가 유지됨을 확인했다. 기준 약화가 아니다.
전체 명령은 `python3 -m unittest discover -s tests -v`였다. fixture 정정 후 명령은
`PYTHONPATH=tests python3 -B -m unittest test_routing_cli -v`다. 두 번째 전체 596개 실행은 하지 않았다.
따라서 전체 595통과/1fixture실패 + 변경 모듈 10통과의 조합이며 새 전체 PASS를 주장하지 않는다.

### 국소 회귀와 실제 브라우저

C 통합 88 tests/47.855초 PASS, 최종 skill 6 tests/0.134초 PASS였다.
A 초기 통합 86 tests/163.310초, race 14 tests/12.190초 PASS(조정자 전달)였다.
A review2 후 15 tests/8.946초와 retained checks 3 tests/1.964초 PASS였다.
A 최종 26 tests/84.291초, team targeted 4 tests/16.898초 PASS였다.
B 보드 48 tests/12.840초, control 10 tests/1.687초, 최종 52 tests/13.316초 PASS였다.
C historical-plan 17 tests/12.187초 PASS였다. 겹치는 테스트 집합을 합산하지 않는다.

`poll-draft-before.json`의 selection 3–7→30–30 실패와 after의 원문·focus·caret 보존을 구분한다.
`control-cycle-browser.json`은 pause/resume/pause distinct 3개·원문 보존·provider calls 0이다.
`lost-ack-browser.json`은 서버 POST commit 뒤 응답만 유실시키고 poll→resume→동일 문구 pause를
확인했다. DB distinct operations 3개, 원문 보존, final paused=true, provider calls 0이었다.
`composition-poll-browser.json`은 simulated composition 동안 polls 0/종료 후 1이며 native OS IME 검증은 아니다.
`ui-overflow-result.json`은 실제 브라우저 6,000자 한글 pause→명시 resume·원문 정확 보존,
provider calls 0/delegations 0과 소유 브라우저·서버 종료를 확인했다.
worker packet 한도를 늘리거나 원문을 자르는 대신 lightweight control 상태 조회로 분리했다.

`live-fixture/worker-result-recovered.json`은 actual Codex PID와 gpt-6.1-sol/low exec argv,
실제 call 1, exit -9/cancelled=true, budget 1, goal/source/host 핀 일치와 confirmed=true를 기록한다.
collector는 finally의 directory KeyError로 원래 summary를 발행하지 못했고 persisted 기록으로 복구했다.
원래 thread response/exception은 unknown_not_preserved다. 모델 재호출은 없었다.
이 관찰은 review2 소스 시점 transport 경로이며 후속 finish/plan_review/cache 수정의 최종
모델 품질 검증을 대신하지 않는다. 원래 오류·로그와 실제 중단 관찰을 함께 보존한다.

### 이전 실패와 비교 한계

review1은 조정자의 이른 착수로 26.214초에 중단됐다. status failed, pins=false/host=true,
actual call 1·unfinished 1·accounting incomplete, verdict 없음으로 모델 품질 거절이 아니다.
review2는 248.261초 revise major 3/minor 1, review3은 219.373초 revise major 2였다.
두 완료 검토는 source/runtime/tests·host 핀 불변이었다. 원본 거절·후속 수리를 구분한다.
accepted evidence의 generation 과도 차단·plan_review writer 취소 재확인·불확실 operation cache·
첫 실행 안내를 고쳤고, review3의 long pause control 소실 및 accepted team off/on 재사용도 고쳤다.
retained evidence·source/goal/feedback 무효화·in-flight/peer generation fences·QA/예산은 유지한다.
첫 전체 실행은 driver exit130/test exit 미확인/completed=false/핀 불변의 중단 기록이다.
이후 완료된 전체 596개 실행의 fixture failure도 그대로 유지한다.

시작 baseline은 첫 plain call 1 구간 config fingerprint drift로 무효였다. 다른 11 trials는 calls 0이다.
stdout에는 config 쓰기 명령이 없고 변경 주체는 불명이다. 원본 before check/improvements와
`baseline-drift-audit.md`를 보존하며 config를 복원하지 않았다. after-dry-run은 설정 확인일 뿐이다.
비교 품질·성능은 미검증이다. task-scoped-v1은 manifest/profile/trial-plan seal로 구형과 분리한다.
실제 old planned run은 못 찾아 frozen validator가 읽는 synthetic fixture로 KeyError를 재현했다.
정확 historical read만 허용하고 신규 protocol 필수·legacy execution 거절·원본 핀 보존을 확인했다.

로컬 audit은 `/Users/minjoon/orca/projects/loop-work-benchmarks/task-scoped-20261021/`다.
[완료 전체 결과](/Users/minjoon/orca/projects/loop-work-benchmarks/task-scoped-20261021/full-suite-completion-summary.json), [최종 모듈·핀 대조](/Users/minjoon/orca/projects/loop-work-benchmarks/task-scoped-20261021/final-routing-fixture-summary.json),
[review 4](/Users/minjoon/orca/projects/loop-work-benchmarks/task-scoped-20261021/independent-review-4/summary.json), [사용자 자료 보존](/Users/minjoon/orca/projects/loop-work-benchmarks/task-scoped-20261021/user-preservation-after.json), 각 원문 log와 이전 실패를 보존한다.
이 ignored 로컬 자료는 별도 전달 없이 다른 checkout에서 열리거나 재현된다고 보장하지 않는다.
이번 구현은 source/doc/test를 변경했다. 글로벌 설치·패키지 설치·설정 조작·commit/push는 하지 않았다.
시작 config drift의 주체 불명과 이후 검증 구간 host 핀 불변은 별개 관찰이다.
기존 worker-derived knowledge promotion major 1은 별도 미해결이다.
국소 구현·검증을 전체 하네스 완성·모델 품질/속도 개선·live paired bench·bench gate 통과로 확대하지 않는다.
