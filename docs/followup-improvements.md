# 실사용 후속 평가에 따른 두 가지 보완

기준일: 2026-10-18. **runtime 격리와 위임 전 setup 확인을 보완했으며 실제 결과 품질의
비퇴행은 아직 입증하지 못했다.** 새 전체 테스트와 독립 검토의 최종 결과는 아래 추가
영역에 남긴다. 시간·토큰·호출수는 운영 기록이며 품질 판정은 정확성·요구 충족·근거·누락만
사용한다. 원본 실사용 평가와 동결한 before 자료는 변경하지 않았다.

## 1. 실사용에서 목표를 방해한 원인과 이번 범위

직접 읽은 [orion-authz 후속 평가](/Users/minjoon/orca/projects/orion-authz/docs/loop-work-followup-evaluation.md)는
Spring A5 미해결·전체 미완료를 명시한다. 제품의 raw 감사·컴파일 로그 전체를 이번 문서
작성에서 재실행하거나 독립 검증한 것은 아니다. 다음 관찰은 원문에 기록된 사례다.

| 목표 방해 원인 | 이번 보완 | 해결했다고 주장하지 않는 범위 |
| --- | --- | --- |
| 연결된 live runtime 변경으로 반환물이 stale 처리됨 | 명시적인 fixed runtime snapshot | 이미 바뀐 과거 runtime 복원, 기존 동결 목표의 중간 교체·재봉인 |
| 공개 API·Settings·정확한 compiler 진단의 입력 누락, draft note 실패 뒤 종속 호출, 실행 중 parent 변경 | provider를 부르지 않는 dispatch preflight와 조정자 입력·명령 순서 규칙 | compiler 후보의 자동 수리, semantically 필요한 미선언 API의 자동 발견 |

원문이 구분한 Fastify native 변경·setup 실패·제품 정확성 결함도 유지한다. stronger
profile의 성공적인 호출이나 더 많은 검사는 Spring 후보 컴파일 성공을 보장하지 않는다.
raw SHA와 executable mode를 포함한 pin의 구분은 이미 있던 계약이다. 이번에는 그
알고리즘을 바꾼 개선이라고 중복 주장하지 않는다.

## 2. 명시적 runtime 사본: 새 실행의 입력을 고정

[구현](../loop_work/runtime.py)과 [운영 설명](operations.md)에 따라 현재 실행 소스를
새 절대 경로에 복사한다. 신규 장기 실행이나 live-linked runtime의 변경 가능성이 있으면
preflight 전에 snapshot의 명시적 선택을 검토한다. 도구 추가만으로 자동 선택되거나
기존 바인딩이 바뀌지는 않는다. 상위 디렉터리는 이미 존재하는 실제 경로여야 한다.

```sh
python3 scripts/runtime.py snapshot --destination /absolute/new-runtime --expect-digest ENGINE_DIGEST
```

`--expect-digest`는 선택 항목이지만 기존 engine pin을 요구하는 경우에는 정확히 그 값을
사용한다. 원본과 사본의 content·exec pin, 복사 전후 소스 안정성, 별도 Python 프로세스의
engine digest를 확인한다. package·규칙·canonical skill·메타데이터는 기존 canonical
engine seal로, templates와 진입 스크립트는 별도 파일 pin으로 보존한다. 새 manifest와
절대 entrypoint·rules_home을 반환하며 기존 destination·symlink·잘못된 기대값을 거절한다.

선택한 절대 entrypoint·rules_home·engine digest는 동일 session_id·knowledge_home과
함께 보존한다. 이는 선택한 실행 근거의 보존이며 진행 중 목표의 자동 전환이 아니다.

설치·설정·인증·프로젝트 state·지식 DB를 복사하거나 기존 세션을 자동 재바인딩하지
않는다. **진행 중 동결 목표의 runtime을 임의 교체하지 않는다.** 현재 소스가 기존
pin과 다르면 복사는 실패한다. 맞는 기존 runtime을 사용하거나 정당하게 새 실행을
준비해야 하며, 이 명령으로 바뀐 소스를 과거 seal에 맞춘 것처럼 만들 수 없다.

[관련 테스트](../tests/test_runtime.py)는 8개, 0.937초, OK였다. 실제 copied CLI 실행,
copied runtime에서 다시 복사, 원본 후속 변경의 격리, 기존 destination 보존·생성 경합,
content·exec 변조와 source drift 거절을 확인했다. 단위 리뷰 범위는 로컬
`/tmp/loop-runtime-snapshot-review-20261018.md`에 보존했다. 이는 모델 품질 비교가 아니다.

## 3. 위임 전 확인: 경고와 오류를 분리

[dispatch preflight](../loop_work/delegation.py)와 [위임 규칙](../rules/delegation.md)은
실제 dispatch와 같은 setup 검사를 provider 호출 없이 수행한다.

```sh
python3 scripts/loop.py --root /absolute/project delegate GOAL --input /absolute/assignment.json --check
python3 scripts/loop.py work delegate TASK --input /absolute/assignment.json --path /absolute/project --check
```

실패하면 `diagnostics`의 code·stage·message·remediation을 확인하고 종속 delegate를
실행하지 않는다. 정상 결과의 `passed=true`는 현재 dispatch 또는 reuse가 가능하다는
의미다. 작업·시도·예산·derived view를 바꾸지 않으며, 실제 호출 시 freshness와 내부
assessment·완료 검증은 다시 필요하다.

없는 declared read는 `missing_read` warning을 반환한다. 의도적으로 파일 부재를
확인할 수도 있으므로 일괄 차단하지 않는다. 조정자는 경고마다 필요한 입력인지 판단해
필요한 경우 정확한 공개 entrypoint·Settings 정의를 보충한다. 실제 존재하지만 ignored인
compiler log를 선언한 경우는 scope 오류다. ignored 경로 인용만으로 읽기 권한을 넓히지
않고, 허용된 경로나 supplied notes로 진단을 제공한다.

[개발 규칙](../rules/workflow.md)은 `note`·validation·seal 검사 등 선행 명령의 exit를
확인하고 오류면 종속 dispatch를 중단하도록 한다. draft에서는 허용된 discovery·contract를
사용하고 실행 중 parent 입력은 변경하지 않는다. compiler 수리에는 실제 classpath·
의존성·공개 API와 최신 정확한 진단을 전달한다. 예를 들어 `BiConsumer`가 `String,Object`
두 인자를 요구하는데 `AnnotationData` 하나를 받은 진단을 요약하면서 인자 정보를 잃지 않는다.
이 안내는 후보의 없는 API·접근 제어·arity 오류를 자동 해결한다는 주장이 아니다.

## 4. 고정 before와 호환성 진단의 실제 결과

자료는 저장소 밖
[quality-start-20261018-a3dbd496](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/manifest.json)에
보존했다. before source hash는
`83bfee4396bc2b733e50208640a2cfc75f5372d3a9cac01e55648d943410655b`다.
이는 당시 소스 식별자이며 live 품질 baseline 통과 증거가 아니다.

| 고정 진단 | before | after snapshot의 관찰 |
| --- | --- | --- |
| R1 snapshot 격리·덮어쓰기 거절 | 기능 없음 | 통과 |
| R2 없는 read의 무조건 `passed=false` 기대 | `--check` 없음 | 원래 기준 미충족: 부재 경고를 동반한 `passed=true` |
| R3 유효한 check 뒤 정상 dispatch | check 기능 없음; 일반 fake dispatch는 candidate | 통과: check 호출·state 변경 0, 후속 fake provider 1회 candidate |
| R4 stale source의 acceptance 차단 | 통과 | 통과; 제안 미적용과 감사 보존 |

근거는 [원래 before](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/diagnostics/before/report.json),
[adapter 정정](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/probe-adapter-correction.json),
[정정 adapter의 before](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/diagnostics/before-adapter-v2/report.json),
[after](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/diagnostics/after/report.json)다.
원래 R2를 지우거나 통과로 바꾸지 않았다. 기존 schema에는 required-input 표시가 없고
합법적인 부재 조사가 가능하므로, 없는 파일을 모두 거절하면 지원되던 작업 계약을 깨뜨린다.
따라서 [별도 호환 기준](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/compatibility-criteria.json)을
추가해 [before](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/compatibility/before/report.json)와
[after](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/compatibility/after/report.json)를
분리 기록했다. after는 부재 warning과 실제 ignored 입력 차단 두 조건을 모두 충족했고
provider·state 변경은 없었다. 이는 기준 정정 이유와 호환성 확인이며 원래 실패 은폐가 아니다.

진단에는 실제 javac의 arity 오류와 mode-aware pin control도 있다. 이들은 검사 방식의
positive control이며 제품 Spring 수리나 live worker 결과가 아니다. before에 없던
명령도 실패한 live 모델 답변으로 점수화하지 않는다. frozen 자료·AGENTS 정책을 고쳐
새 기준을 소급 적용하지 않았다.

## 5. 아직 남은 품질 검증

단위 테스트와 결정적 fixture는 snapshot·scope·freshness 동작을 확인하지만 실제
작업 결과가 더 나빠지지 않았다는 전체 live benchmark를 대신하지 않는다. 이 문서에서
성능은 결과의 정확성·요구 충족·근거·누락만으로 판단하며 시간·토큰·호출수로 개선을
판정하지 않는다. Spring A5의 제품 후보 불량이 이번 하네스 보완으로 해결됐다고
주장하지 않는다. 링크된 외부 프로젝트·로컬 감사 자료는 이 문서만으로 다른 checkout에
전달되지 않으므로 별도 보존이 필요하다.

새 전체 테스트와 fresh 독립 검토는 진행 중이며 최종 결과는 아직 미확정이다.
확정 후 실행 명령·개수·판정·증거 범위와 남은 live 품질 검증을 이곳에 추가한다.

### 최종 검증 추가 영역

전체 테스트: 미확정. 독립 검토: 미확정. 전체 live 품질 비퇴행: 미검증.

## 2026-10-18 추가 확인 — after-final-v2

앞의 after 결과와 미확정 기록을 보존하고 최종 수정본을 별도로 확인했다.
[after-final-v2 manifest](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/after-final-v2-manifest.json)의
source hash는 `efa2489f14eb796b1d2aee22fbaf54ff58d1bc6f7ce498dc80b811a62b18eb0a`이며
대상은 `sources/after-final-v2`다. 앞선 snapshot과 결과를 이 값으로 소급 대체하지 않는다.

1. **거절과 수정 보존:**
   [첫 독립 검토](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/independent-review/summary.json)는
   새 `scripts/runtime.py`가 benchmark source seal에서 빠진 major finding을 냈다.
   수정 후 [다음 검토](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/independent-review-final/summary.json)는
   candidate·done reuse가 read visibility 검사보다 먼저 반환해 새 ignored 파일을 놓치는
   major finding을 냈다. 둘 다 수정했으며 실패 기록을 유지한다. 최초 검토의 호출 귀속은
   `calls_complete=false`였으므로 최종 검토의 완전한 집계와 혼동하지 않는다.
2. **최종 독립 검토:**
   [fresh final-v2 검토](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/independent-review-final-v2/summary.json)는
   Codex `gpt-6.1-sol` / `low`에서 PASS였다. host·source·추가 entrypoint 보존과
   `calls_complete=true`를 확인했다. read visibility는 reuse 전에 검사하며, 정상 reuse는
   worker-call 예산이 소진돼도 새 호출 없이 가능하도록 유지했다. 이는 정적 독립 검토이지
   제품 수리나 live 결과 품질의 개선 판정이 아니다.
3. **수정본의 결정적 진단:**
   [after-final-v2 probe](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/diagnostics/after-final-v2/report.json)는
   R1·R3·R4 통과, 원래 R2 미충족을 확인했다.
   [호환 조건 2개](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/compatibility/after-final-v2/report.json)는
   통과했다. 선언 당시 없던 파일이 ignored 파일로 생긴
   [candidate 이후](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/ignored-reuse/after-candidate/report.json)와
   [done 이후](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/ignored-reuse/after-done/report.json)에도
   check와 실제 dispatch가 차단돼 추가 provider 호출이 없었다. 원래 R2를 통과로 바꾸거나
   합법적인 부재 조사를 무조건 막는 방식으로 기준을 맞추지 않았다.
4. **구현 테스트와 중단:** 관련 실행은 runtime 8개, dispatch 11개와 기존 관련 21개,
   새 benchmark seal 3개, 관련 bench 75개가 통과했다. 이 수치는 각각의 실행 범위이며
   중복 없는 총수로 합산하지 않는다. 앞선 전체 테스트 두 실행은 benchmark seal 보완과
   major finding 수정 때문에 SIGINT·exit 130으로 중단했으며 통과가 아니다. 새 전체
   실행은 `/tmp/loop-followup-final-v2-tests-20261018.log`에서 진행 중이고 이 영역 작성
   시 최종 개수·결과는 미확정이다.
5. **실제 결과 품질:** 3회 반복의 새 live 품질 측정은 준비·진행 예정이며 아직 결과가
   없다. 시간·토큰·호출수를 품질 평가에 넣지 않는다. 이번 결정적 진단과 독립 검토의
   통과만으로 실제 결과 품질 향상이나 전체 live 비퇴행을 확인했다고 주장하지 않는다.

### final-v2 최종 확정 — 2026-10-18

앞의 진행 중·미확정 기록은 당시 상태로 보존하고 다음 결과를 최종 확인했다.

| 검증 | 확정 결과 | 근거와 범위 |
| --- | --- | --- |
| 전체 테스트 | `python3 -m unittest discover -s tests -v`: **347 tests, 355.491초, OK, exit 0** | `/tmp/loop-followup-final-v2-tests-20261018.log` |
| fresh 독립 검토 | **PASS** | 위 final-v2 검토 기록과 동일하며 기존 두 major finding의 수정 이후 결과 |
| 고정 target의 실제 결과 품질 | **3/3 PASS** | [최종 live 요약](../../loop-work-benchmarks/quality-start-20261018-a3dbd496/live-quality-after-final-v2-frozen-target/summary.json). source `efa2489f14eb796b1d2aee22fbaf54ff58d1bc6f7ce498dc80b811a62b18eb0a` |

최종 live 실행은 같은 요청·rubric·plan seal, target 전체의 안정성, 기존과 같은 host,
after snapshot과 원래 before snapshot의 보존을 확인했다. 세 호출 모두 accounting이
완전했다. 이전 before·after·plain 각각 3/3과 최종 after 3/3은 **품질 동률**이다.
이 단일 README 설명 과제에서는 관측된 품질 퇴행이 없었지만, 결과 품질 향상이나 전체
하네스 품질의 비퇴행을 입증하지는 않는다. 시간·토큰은 품질 점수에 넣지 않았다.

앞선 `live-quality-after-final-v2` 묶음은 실제 호출 3회 중 2회만 완료됐다. 첫 후보는
동시에 수정된 `docs/followup-improvements.md` 한 파일 때문에 정상 stale guard에서
차단됐다. 이 오염된 측정과 1개 파일 차이는 보존하며 고정 target 결과로 합치거나
실패를 삭제하지 않았다. 고정 target 재실행의 3/3은 별도 후속 결과다.

scripted coordinator의 공통 work 부분집합·같은 문서 과제의 세 반복이라는 한계가
남는다. 개발 전체 흐름·제품 compiler 수리·과거 실패 과제의 회복이나 전체 live
benchmark gate는 검증하지 않았다. trust 준비 승인 없이 전체 live bench/gate를
통과했다고 표시하거나 승격을 주장하지 않는다. 원래 R2 미충족과 별도 호환 조건,
모든 기존 실패·중단·원본 평가를 계속 보존한다.

## 2026-10-18 추가 확정 — 두 P2 setup 결함 수정

이전 결과를 보존하고 두 setup 결함의 수정·검증 결과를 추가한다. 새 품질 비교나
성능 향상 측정이 아니라 아래 동작에 대한 구현 검증이다.

1. **새 dispatch 전 실행 가능성 확인:** 선택된 CLI·관리 wrapper의 존재와 실행 가능성,
   frozen catalog 일치를 새 호출 전에 확인한다. setup 오류는 구조화된 `provider_setup`
   진단으로 반환하며 provider 호출·시도·예산 소비는 0이다. stale pending candidate의
   recovery 상태를 바꾸기 전에도 이 검사를 수행해 실행 불가가 기존 증거를 훼손하지
   않는다. 현재 candidate·done의 정상 reuse는 새 CLI가 필요 없으므로 CLI 부재나
   worker-call 예산 소진 상태에서도 새 호출 없이 유지된다.
2. **managed provider 선택 보존:** 관리 환경에서는 재구성된 PATH 대신 고정 wrapper를
   확인한다. catalog에 구성된 반대 provider의 wrapper가 없거나 실행 불가하면 오류이며
   같은 provider로 조용히 fallback하지 않는다. 반대로 단일 provider catalog 자체는
   정상 지원한다. catalog 밖의 추가 CLI·wrapper는 무시하고, 선택한 worker/provider가
   catalog 밖이면 fail-closed로 처리한다. 이미 선택된 provider의 인증·권한·호출 실패를
   다른 provider 선택으로 대체하지 않는다.
3. **회귀 테스트:** 관련 dispatch 36개와 provider 17개가 통과했다. 이는 범위가 겹칠 수
   있는 별도 실행이므로 중복 없는 총수로 합산하지 않는다. 새 missing-wrapper fixture는
   처음에 실제 worker와 다른 provider catalog를 사용했고, 다음에는 일반 fake CLI가 있는
   경로를 빈 관리 transport로 오인했다. 두 fixture 가정을 바로잡았으며 해당 보정은 제품
   코드 변경이 아니다. 최종 fixture는 양 provider catalog와 전용 빈 transport 경로를
   사용하고, wrapper 부재와 별도 일반 CLI 존재를 각각 assertion으로 확인한다.
4. **독립 검토와 경합의 보존:** 최초 검토는 “단일 catalog 밖에 설치된 반대 CLI도 반드시
   오류”라는 잘못된 검토 기준 때문에 revise였다. 원본
   `/private/tmp/loop-followup-p2-review-20261018-57sdk6o0`은 보존하고 그 finding을 유효한
   제품 결함으로 채택하지 않았다. 호환 계약을 정정한 새 독립 Codex 검토는 PASS였다.
   근거는 `/private/tmp/loop-followup-p2-review-corrected-20261018-32hg_ppm/summary.json`이다.
   runtime·host는 전후 같았지만 테스트 fixture 변경과 겹쳐 `tests_unchanged=false`였다.
   최종 fixture 전체가 reviewer stderr의 실제 읽기 출력과 정확히 일치함을 별도로
   확인했고 `fixture-final-observation.json`에 최종 두 test pin과 함께 보존했다. 이를
   테스트까지 무경합이었다고 바꾸어 설명하지 않는다.
5. **전체 최종 검증:** `python3 -m unittest discover -s tests -v`는 **356 tests,
   356.889초, OK, exit 0**으로 완료했다. 근거는
   `/tmp/loop-p2-fixes-final-tests-20261018.log`다. 앞의 347개 통과는 당시 snapshot의
   기록으로 유지한다. 이번 결과는 두 결함 수정과 기존 동작의 회귀 검증이며 새 실제
   결과 품질 향상이나 전체 live benchmark 비퇴행을 입증하지 않는다. 품질 평가는 계속
   정확성·요구 충족·근거·누락만 사용한다.
