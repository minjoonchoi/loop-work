# Tauri GUI 작업에서 본 loop-work 회고 — 2026-10-24

대상은 완료된 `tauri-harness-gui` 개발 작업이다. 이 문서는 하네스 사용 경험의 회고이며,
아래 개선 후보를 구현했거나 효과를 검증했다는 보고가 아니다.

## 판단 범위와 근거

- **사실**은 실제 기록에서 확인한 실행·판정이다. **해석**은 그 기록의 의미에 대한 판단이다.
- **개선 후보**는 다음 변경의 가설이며, 적용 권한이나 효과 검증을 대신하지 않는다.
- 이번 조사에서는 final 평가, M1 1~8/final 디렉터리와 존재하는 gate/review JSON,
  중단·캐시 복구·벤치마크 평가, native 최종 증거 평가 및 관련 규칙/실행 경로를 읽었다.
- 원본 사용자 대화 전체, 모든 프로세스 로그와 전체 코드에 대한 새 감사는 하지 않았다.
  추가 테스트·모델 호출·설치·설정 변경·목표 상태 변경도 수행하지 않았다.

경로 표기의 기준은 다음과 같다.
`G` = `.loop/state/tauri-harness-gui/gates` (저장소 루트 기준).
`T` = `/Users/minjoon/orca/projects/loop-work-benchmarks/tauri-gui-20261024-ctux2q7d`.
`G`와 `T`의 감사 자료는 로컬 실행 산출물이다. 별도 전달 없이는 다른 checkout에서 열리거나
재현되지 않는다. 저장소 설명 문서와 이식 가능한 실행 증거를 혼동하면 안 된다.

## 결과와 실패 이력

`T/final-root-assessment.json`은 목표 완료와 A1~A5 수용을 기록한다.
최종 source 표기는 `638194d26d235a1ca93ac2a7bb55de4fcb7a8d2cf4515f06911476860cb8e5d5`이다.
이는 2026-10-24 12:36:34 UTC 당시 완료의 과거 증거다. 이번 별도 회고 정책 변경 이후의
현재 소스를 새로 검증했다는 뜻이 아니다. 해당 평가의 소스 범위이며, native verifier의
engine digest와 같은 함수의 해시가 아니다.

| 실행 | 남은 기록과 판정 |
|---|---|
| M1-1 | 기본 native fixture 경로 실패 뒤 중단. gate.json 없음. |
| M1-2 | 검사 8개 통과, 독립 검토 revise: major 4건. |
| M1-3 | 이동한 Cargo 캐시의 과거 절대경로 참조로 중단. gate.json 없음. |
| M1-4 | 검사 8개 통과, 독립 검토 revise: major 3건. |
| M1-5 | 검사 8개 통과, 독립 검토 revise: major 2건. |
| M1-6 | renderer 실패 뒤 중단. gate.json 없음. |
| M1-7 | 검사 8개 통과, 독립 검토 revise: major 1건. |
| M1-8 | 검사와 독립 검토 pass. |
| final-1 | fresh 검사와 독립 검토 pass, 미해결 finding 0. |

이 표는 M1 예산 8회를 새로 시작하거나, 중단된 실행을 통과로 바꾸지 않는다.
중단 근거는 `T/checkpoint-M1-r1-interruption.json`, `checkpoint-M1-r3-interruption.json`,
`checkpoint-M1-r6-interruption.json`이다. 완료 근거는 `G/milestone-M1-8-3e392373/gate.json`과
`G/final-1-67e427b0/gate.json`이다. 이전 실패는 최종 성공 뒤에도 남아 있다.

최종 검증 단위는 frontend 13건, Rust 12건, renderer 51건, 원본 shipping native 4건,
별도 test-only `native-qa` 17건, Python 737건 표기 중 skip 1건이다. 서로 겹치는 검사 묶음이므로
합산한 숫자를 독립적인 품질 점수로 쓰지 않는다. `T/native-final-r1-evidence-assessment.json`은
실제 WebView/Rust IPC·합성 fixture·native 취소 callback과 보존 조건을 대조한 평가다.
물리 키보드·실제 OS IME·수동 dialog 클릭은 미검증이며, 실제 Linux native 실행도 미검증이다.
실제 HOME 설치와 commit/push는 이 작업의 완료 기록에서 미실행이다.

## 좋았던 점

자동검사 성공과 수용을 분리했다. M1-2/4/5/7에서는 검사 8개가 모두 통과했지만 독립 검토가
초안 소실, 재시도 식별자 유실, 이력 범위 혼입, 종료 경쟁, 빈 입력 IME 공백을 거절했다.
최종 검토는 원래 발견과 새 회귀 증거를 확인했다. 이는 실제 결함을 발견한 관찰이며,
다른 개발 방식보다 우월하다는 비교 실험 결과는 아니다.

CLI 가용성도 정직하게 기록했다. Claude 부재로 Codex의 fresh same-provider 검토를 사용했다.
최종 모델/effort는 `gpt-6.1-sol/high`이며, 이를 교차 제공자 검증이라고 부르지 않는다.
근거: 각 gate의 `routing.review_selection` 및 final의 `review`.

소스 핀, 후보 경계, 실패 산출물을 보존해 결과의 범위를 정정할 수 있었다.
원본 release lifecycle과 test-only populated native 검사를 구분했고, 단순 renderer_ready나
Chromium 검사를 실제 native 편집 검증으로 승격하지 않았다. 실제 사용자 데이터 보존과
합성 fixture 보존 또한 다른 관찰로 취급해야 한다.

## 불필요하거나 방해가 된 부분

검증 준비의 결함이 제품 수리와 섞였다. 기본 fixture 경로, fixture 설치 전후 source 관찰 변화와
완료 증거 생성 순서, 반복 생성한 Cargo 캐시의 디스크 소진, 이동 뒤 절대경로 잔존을 구분해야 했다.
설치의 관찰 변경은 확인했지만, 과거 완료표시 실패의 원인을 그 사실 하나로 확정하지는 않았다.
캐시 복구 근거는 `T/native-cache-recovery.json`, `T/root-cache-rebuild-audit.json`이다.
이런 문제를 모델 품질 실패로 분류하거나 더 강한 모델 재시도로 해결하려 해서는 안 된다.

종료 보호를 wiki 저장, 실행 접수, 저장 대기 중 새 실행, response/control IME 순으로 보완했다.
각 수정은 필요했지만 같은 사용자 여정의 상태 조합을 초기에 충분히 고정하지 못했다는 해석이 가능하다.
후속 native 150초 timeout은 정확한 정지 원인이 확정되지 않았다. 진행 표식 뒤 성공했다고 해서
그 표식이 원인을 고쳤다고 단정하지 않는다. 근거: `T/root-close-race-native-r1-stage-audit.json`과
`T/root-close-race-native-r3-evidence-assessment.json`.

끝까지 실행된 gate 6개(수정 요구 판정 포함)의 Python 검사 시간 합계는 **4,474.255초**다. 대상은 M1-2/4/5/7/8 및 final-1의
`python-regression.process.duration_seconds`이며, 중단된 1/3/6과 별도 targeted 검사는 제외했다.
`T/final-root-assessment.json`의 기록된 실행 시간은 **14,323.351초**(예산 14,400초)다.
두 수치는 다른 단위다. 작업·빌드·검토·대기를 원인별로 집계한 자료가 없으므로 약 4시간 전체를
하네스의 낭비로 돌리거나, 전체 재검증이 무조건 불필요했다고 말할 수 없다.
합계는 다음 읽기 전용 집계로 확인할 수 있다.

```python
import json
from pathlib import Path
root = Path('.loop/state/tauri-harness-gui/gates')
paths = list(root.glob('milestone-M1-*/gate.json'))
paths += [root / 'final-1-67e427b0/gate.json']
seconds = sum(c['process']['duration_seconds'] for p in paths
              for c in json.loads(p.read_text())['checks'] if c['id'] == 'python-regression')
print(f'{seconds:.3f}')  # 4474.255: 6 fully executed gate records, including revise
```

## 스킬·규칙·런타임 개선 후보 — 아직 적용·효과 검증하지 않음

| 후보와 정확한 변경 위치 | 관찰된 문제 | 한정 수정 가설 | 관측 가능한 수용 검사 |
|---|---|---|---|
| 1. `rules/workflow.md`, `skills/loop-work/SKILL.md` | 자동검사 통과 뒤 같은 종료 여정의 새 누락이 반복 발견됨 | GUI 계획에 상태 전이·전송 전/후·응답 유실·조합·종료의 교차표를 만들고 skill은 해당 규칙만 참조 | 각 수용 기준에 실제 renderer/native/합성/물리 입력 구분과 실패 순서 fixture가 연결됨. 누락 발견을 0으로 미리 가정하지 않음 |
| 2. `loop_work/engine.py`, `rules/workflow.md` | 실패가 알려진 뒤에도 남은 비싼 검사가 시작됐고 외부 중단이 필요했음 | 새 계약에서만 fail-fast/진단 계속 정책을 명시적으로 고정. 실패 후 미실행은 미실행으로 기록 | 실패 fixture 뒤 후속 비싼 명령이 호출되지 않고 gate는 실패함. 최종 수용에는 여전히 전체 fresh 검사와 독립 검토가 필요함 |
| 3. `rules/delegation.md`, `scripts/verify_tauri_native.py`, `loop_work/desktop_install.py` | 실제 기본 명령·설치 순서·캐시 위치·공간이 검증 시작 뒤 문제를 드러냄 | GUI handoff 전에 기본 argv와 source 밖 fixture, 설치 후 증거 생성, 고정 feature 캐시·공간을 확인 | 기본 명령이 독립 temp에서 동작하고 설치 전후 관찰 차이가 기록됨. 캐시 재사용/공간 실패가 명확하며 사용자 파일·다른 캐시는 보존됨 |
| 4. `rules/writing.md`, `scripts/verify_tauri_native.py`, `desktop/src-tauri/src/native_qa.rs` | timeout에 마지막 단계가 없거나, 이미 saving인 검사를 실제 flush-await로 읽을 위험이 있었음 | 검사 시작/종료의 bounded 진행 표식과 증거 종류·범위 필드를 유지. 기존 성공 표현은 실제 경로에 한정 | 고의 실패/정지에서 마지막 실제 단계와 종료 상태를 남김. 원본 shipping·test-only native·실제 API·합성 IME·물리 입력을 각각 표시하고 부분 성공을 final pass로 쓰지 않음 |
| 5. `rules/benchmark.md`, `loop_work/bench_check.py`, `loop_work/benchmark.py`, `loop_work/desktop_sources.py` | 고정 old exporter가 새 필수 source를 누락했고, 별도 새 runner 측정은 비교 불가능했음 | 모델 호출 전 exporter/필수 파일/로컬 설치 호환성 점검. runner·protocol 변경은 별도 측정으로 명시 | 필수 파일 누락이 모델 호출 전에 검출됨. 새 runner 설치 진단 성공을 원래 before/after 승격으로 쓰지 않고, host fingerprint 검사와 고정 rubric을 유지함 |

이 표는 자동 승인된 정책 변경이나 검증 강도 완화안이 아니다. 최종 fresh 검사·유한 예산·독립 검토,
사용자 원문·명시 실행·설치 소유권을 유지하는 조건으로 다음 변경의 별도 검증을 설계해야 한다.
시간·호출·재발 감소 효과는 각 후보를 적용한 뒤 같은 기준으로 측정하기 전까지 가설이다.

## 아직 말할 수 없는 것

벤치마크 품질 비교는 **inconclusive**다. before는 host profile drift로 유효한 비교 baseline이 없었고,
고정 old runner의 after는 새 필수 `scripts/verify_tauri_native.py` 누락으로 설치에 실패했다.
이는 서로 다른 실패다. 새 runner 보조 실행의 candidate 설치 6건은 성공했지만 실제 호출 1건 뒤
다시 host drift가 발생했으며, 설정 변경 주체는 확정되지 않았다.
근거: `T/after-final-root-assessment.json`, `T/after-m1-r8-root-assessment.json`,
`T/current-runner-benchmark-validation.json`, `T/before/check.json`.
따라서 bench gate 승격, plain 대비 품질·속도·비용 개선, 모델 가격 순위에 따른 절감을 주장하지 않는다.
다음 작업은 위 개선 후보 하나를 골라 원래 수용 기준을 유지한 채 별도 변경·검증하는 것이다.


## 2026-10-25 후속 적용 기록 — 전체 검증 진행 전

앞의 기준일·미구현 후보·원래 실패와 비교 한계는 당시 기록으로 보존한다. 아래는 별도 후속
변경의 범위와 확인된 targeted 근거이며, 앞선 성공/실패를 덮어쓰지 않는다.
`W`는 `/Users/minjoon/orca/projects/loop-work-benchmarks/retrospective-improvements-20261025-bf6u513c`다.
W의 감사 로그는 로컬 산출물이므로 별도 전달 없이는 이식 가능한 실행 증거가 아니다.

| 후보 | 후속 반영 범위 | 현재 근거와 한계 |
|---|---|---|
| 1 | 관련 GUI 변경만 기존 계획에 상태 조합·기준·보존 원문·부작용·fixture·renderer/native/synthetic/physical 범위를 연결. 단순 작업에 새 PRD/reviewer/gate 없음 | 정책·배치·링크 검사. 실제 누락/재발 감소 효과는 미측정 |
| 2 | 신규 계약 check_failure_policy=fail_fast, diagnostic_continue 선택, 기존 누락은 continue. not_run_checks로 후속 미실행과 원인을 기록 | W/engine-policy-related-r2.log: 계약+engine 43개 PASS(100.929초). 실패 뒤 side effect 차단·legacy/continue·timeout/취소/예산·동결·fresh final 회귀 |
| 3 | 실제 기본 argv·source 밖 fixture·설치 후 증거와 feature/cache 고정. write probe·capacity 관측, ENOSPC setup 분류, 다른 cache 보존 | W/native-install-targeted-final-r2.log: 11개 PASS(0.660초). 실제 전체 native 실행 완료를 뜻하지 않음 |
| 4 | preflight.json/progress.json/run-failure.json의 bounded 64events·현재/마지막 완료/native 단계·timeout/interrupted/storage_enospc 구분 | W/native-targeted-final-r2.log: 13개 중 12 PASS·명시 native 검사 1 skip(0.145초). shipping_native_lifecycle와 test_only_native_webview_actual_api, 합성 composition/physical input 미검증 구분 |
| 5 | 새 profile만 setup_protocol=isolated-copy-install-v1. exported 동일성·고립 install/import 사전검사 실패는 inconclusive/model_calls=0·judge/history 승격 없음 | W/benchmark-reviewfix-final-targeted.log: 관련 79개 PASS(52.624초). live 결과물 품질·속도 개선 근거가 아님. legacy profile hash·host/rubric 보존 |

benchmark 초기 후보의 legacy/timeout 분류 오류는 적용 전에 거절·수리했으며, 이전 76개 검사 기록을 현재 수용 후보의 근거로 대체하지 않는다. 원래 후보와 실패 기록은 보존한다.

후속 before의 result.errors 원문은 `Host profile changed before trial; evidence retained` 11건과
`Host profile changed during turn; evidence retained` 1건이다. 실제 Codex call record 1건은
completed/exit0이지만 유효 비교 baseline은 성립하지 않았다. config.toml 단일 보호파일의 내용
해시와 size/inode/mtime/ctime이 달라졌고, 변경 내용·주체는 확인하지 않았다. HOME 원문을
열람·복사하거나 원인을 추측한 평가가 아니다. turns 배열이 비었다고 모델 호출 0으로 세지 않는다.

### 이후 검증 결과 — 추가 기록 영역

- 전체 Python·fresh review·실제 native 검증: 현재 pending. 부모가 실제 명령·source pin·결과·미해결 사항을 추가한다.
- live before/after 품질 비교: inconclusive. bench gate 승격이나 품질·비용·속도 향상은 미입증이다.
- 추후 결과는 날짜·근거와 함께 여기에 추가하며, 기존 실패·미실행·skip·이전 제한을 삭제하지 않는다.


### 2026-10-25 동일 runner 전후 비교와 새 setup 진단

이 추가 기록은 사용자 요청에 따른 후속 회고다. 새 task/session/goal이나 강제 완료 gate를
만들지 않는다. 앞선 미구현 후보·거절·수리·실패 기록은 당시 사실로 그대로 보존한다.

동일 frozen runner의 before/after는 output 경로만 바꾼 같은 명령으로 실행했지만, 양쪽 모두
유효한 paired run을 끝내지 못했다. 각 실행의 원문 오류와 실제 호출은 다음과 같다.

| 실행 | 시작 전 오류 | 진행 중 오류 | 실제 Codex call record | 판정 |
|---|---|---|---|---|
| before | Host profile changed before trial; evidence retained — 11건 | Host profile changed during turn; evidence retained — 1건 | 1건, exit0·timeout 없음 | inconclusive |
| after | Host profile changed before trial; evidence retained — 11건 | Host profile changed during turn; evidence retained — 1건 | 1건, exit0·timeout 없음 | inconclusive |

두 실행 모두 judge의 `Complete the paired run before judging`로 중단되어 품질 개선은
unverified다. turns 배열이나 완료되지 않은 trial 수로 실제 호출을 0으로 세지 않는다.
보호파일 config.toml의 내용 해시·파일 metadata 변화는 관측했지만 그 원문·변경 주체는
확인하지 않았다. 조정자는 host 설정을 편집하거나 fingerprint를 완화하지 않았다.
근거: `W/quality-comparison-assessment.json`, `W/before/check.json`, `W/after/check.json`.

새 runner의 `isolated-copy-install-v1` 진단은 고립 설치 관리 파일 112개, 복사 모듈 import
42개와 entrypoint help를 확인했고 사용자 파일을 보존했다. dry-run 설정 검사는 PASS이며
model_calls=0이다. 이는 설치/import/setup 구성의 진단이지 기존 runner before/after 성공,
live 품질 비교나 bench gate 승격이 아니다. 새 protocol 표식은 별도 profile에만 적용하며
legacy hash·고정 rubric·host 검사는 그대로다. 근거: `W/new-runner-validation/summary.json`.

다섯 개선 후보의 재발·대기·검사 비용 감소 효과는 아직 가설이다. targeted PASS는 해당
동작 경계의 근거로 한정하고 전체 수용이나 모델 품질·속도·비용 향상으로 확대하지 않는다.
물리 GUI 입력·실제 OS IME는 검증하지 않았으며 합성 composition 근거와 구분한다.

### 2026-10-25 통합 검증 결과

앞선 pending은 검증 전 작성 당시의 상태다. 해당 기록을 보존하고 이후 완료된 실행을 추가한다.

| 검증 | 실제 결과 | 범위와 제한 |
|---|---|---|
| 전체 Python | 772개 중 771 PASS·명시 opt-in native 검사 1 SKIP, exit0. suite 779.797초·wrapper 779.881초 | W/full-python-result.json과 assessment 근거. skip을 실행·통과로 세지 않음 |
| shipping native | 실제 배포 binary lifecycle 4경우 모두 PASS | 소유·재사용·교체 등 해당 시작/종료 경계의 근거 |
| 감사용 native | 별도 test-only 실제 Tauri WebView 17경우 모두 PASS, real_tauri_ipc=true·api_proxy_shim=false | W/native-final/populated-native-qa/result.json. actual flush-await 3849ms 등 개별 근거를 보존. physical GUI·OS IME 검증은 아님 |

native는 실제 기본 argv `python3 scripts/verify_tauri_native.py`로 실행했다. output/cache만
`W/native-final-command.json`의 고정 환경으로 분리했으며 181.473초가 걸렸다. progress는
completed·마지막 native 17 done이고 event는 64개로 bounded다. source before/after는 모두
`67b0694b4fb46d1b4b63c17095c2c3f9b049f1a51898f9c4758da3b50e54d83c`로 같았다.
근거: `W/native-final/summary.json` 및 위 원본 결과. shipping/test-only·합성 composition과
`physical_gui_input_verified=false`·OS IME 미검증을 분리한다.

fresh 독립 검토는 이 기록 작성 뒤 수행한다. 최종 판정과 미해결 사항은
`W/final-review/review.json`, `W/final-root-assessment.json`의 원문을 함께 확인한다.
이 단락 자체가 독립 검토 통과의 증거는 아니다.

동일 runner의 live 품질 비교는 계속 inconclusive다. 단위·native PASS는 다섯 후보의
품질·속도·비용 개선 효과를 입증하지 않는다. 이 작업의 조정자가 설정을 편집하지 않았다는
기록과, 관측된 host drift의 실제 변경 주체가 불명이라는 판단은 별개의 사실로 유지한다.


### 2026-10-25 후속 진단과 선택·poll 경합 수리 기록

첫 fresh 검토는 shipping ENOSPC 진단에서 원문 stderr/경로가 사라지는 minor 1건으로
revise였다. 두 파일에서 head+tail 최대4000자와 stage/kind를 보존하도록 수리했고,
관련 portable12 PASS 뒤 두 번째 검토는 A1~A5/findings0으로 판정했다. 당시 판정은
당시 코드의 전체/native 검증을 조건으로 한 것이며 이후 UI 수정 코드의 검토가 아니다.
근거: `W/final-review/review.json`, `W/native-enospc-repair.patch`, `W/final-review-r2/review.json`.

ENOSPC 수리 후 전체 Python은 773개 중 772 PASS·opt-in native1 SKIP였지만, 같은 후보의
native 실행은 앞선15검사 뒤 control IME 대상 선택에 실패해 whole run이 실패했다.
부분 PASS를 native 전체 통과로 바꾸지 않는다. progress에는 동적 marker4종이 빠졌다는
별도 진단 결함도 확인했다. 근거: `W/native-r2-failure-root-assessment.json`.

동적 marker 이름을 명시적으로 허용하는 수리와 QA-only bounded trace32를 추가했고,
관련 portable14개 실행은 13 PASS·1 SKIP(0.138초)였다. 기존 클릭·timeout·assert는 유지했다. 근거: `W/native-dynamic-stage-targeted-r2.log`.
`W/diagnostic-selection-r3`의 실제 test-only17검사는 통과했지만 shipping 검증은 없었고,
실패 원인 자체도 그 실행에서 재현되지 않았다. 진단 추가 뒤 통과했다는 사실만으로
진단이 원인을 고쳤다고 주장하지 않는다.

별도 source 함수와 실제 이전 renderer에서 단일 GET 지연·5초 poll이 대상 선택을 지우는
경합을 재현했다. 최소 App 수정은 현재 project와 epoch가 맞는 선택 GET이 진행 중일 때
scheduled poll만 미뤄 한 번의 클릭을 보존했다. manual refresh와 프로젝트 전환의 stale 거절은 유지했으며,
이를 놓친 초기 후보도 거절 기록으로 보존했다. 최종 frontend 단위13 PASS·build PASS,
실제 renderer52검사 모두 PASS·errors0으로 one-click 대상 보존과 poll 재개를 확인했다.
근거: `W/selection-poll-renderer-red`, `W/verification-r3/frontend-results.json`,
`W/verification-r3/renderer-final/actual-browser-*/result.json`.

위 기록은 각 후보·검증 범위의 사실이다. 수리 전 full772/shipping4/test-only17,
중간 full773와 review2, shipping 없는 diagnostic17을 최신 코드의 전체 수용 근거로
합치지 않는다. 최종 코드는 `W/verification-r3/frozen-source-manifest.json`에 고정돼 있다.
후속 전체/native의 실제 결과는 해당 코드·명령·원문과 함께 별도 추가한다.
최신 fresh 검토 `W/final-review-r3/review.json`은 A1~A5 satisfied·findings0으로 판정했으며,
해당 시점의 전체/native 결과가 아직 끝나지 않아 부모의 최종 수용은 보류됐다.

동일 frozen runner의 live 비교는 여전히 host drift로 inconclusive이며 변경 주체는 불명이다.
조정자가 설정을 편집하지 않았다는 기록은 주체를 확정하는 증거가 아니다. 최신 고립 setup
112파일·42모듈·모델0 진단도 기존 paired 품질 비교를 대신하지 않는다. 근거는
`W/quality-comparison-final-assessment.json`,
`W/verification-r3/new-runner-validation/summary.json`이며, 이전 r2 자료를 최신 코드의
근거로 대신하지 않는다. 다섯 후보의 일반적인
품질·속도·비용 개선 효과는 가설이며, 합성 composition은 물리 GUI·OS IME 검증이 아니다.


### 2026-10-25 최종 코드의 후속 검증 결과

앞선 pending·수리 전772개 중771PASS·1SKIP·중간773/native15후 실패·shipping 없는 진단17 통과와
검토 revise는 해당 시점의 역사적 기록으로 유지한다. 최종 고정 코드에서는 다음 실행이 끝났다.

| 검증 | 최종 실제 결과 | 근거와 범위 |
|---|---|---|
| 전체 Python | 774개 중 773 PASS·명시 opt-in native1 SKIP, exit0. suite780.907초·wrapper781.0초 | W/verification-r3/full-python-result.json. skip을 실행·통과로 세지 않음 |
| shipping native | 배포 앱 lifecycle4경우 모두 PASS | W/verification-r3/native-final/summary.json. 재사용·소유권·종료와 보존 경계 |
| test-only native | 실제 Tauri WebView17검사 모두 PASS, real_tauri_ipc=true·api_proxy_shim=false | W/verification-r3/native-final/populated-native-qa/result.json. physical GUI·OS IME 검증과 구분 |
| fresh 독립 검토 | Claude CLI가 없어 Codex same_provider_fresh로 최종27파일 후보 A1~A5 satisfied·findings0 | W/final-review-r3/review.json. 이전 review2를 최신 코드 근거로 대신하지 않음 |

실제 기본 native argv의 최종 실행은 exit0·179.367초였고, 보존 guard는 모두 true,
backend는 stopped였다. progress는 completed·event64·native17 done이며 동적 marker4종도
관측했다. source before/after는 모두
`3293b4756889031566205f11106b61050c1e91e3b5f073f3953197b0dea6b300`로 같았다.
근거: `W/verification-r3/native-final-cli-result.json`, summary와 progress 원문.
최종 통합 판정은 `W/final-root-assessment.json`에 연결한다.

이 결과는 관측된 동작과 원문 보존·검증 경계의 근거다. 처음 native 선택 실패의 정확한
actual ordering은 여전히 확정하지 못했다. 별도로 재현한 old-renderer poll 경합의 수리를
그 원실패의 확정 원인으로 바꾸지 않는다. 합성 composition이며 physical GUI·실제 OS IME는
미검증이다. fixed-runner 품질 비교는 최종 코드에서도 inconclusive였고, 변경 주체는 불명이다.
다섯 개선 후보의 일반적인 품질·속도·비용 효과는 여전히 가설이다.
