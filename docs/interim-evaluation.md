# loop-work 실제 사용 중간 평가와 보완 가설

기준일: 2026-10-18. 사용자 제공 실사용 평가를 바탕으로 정리한 기록이다.
당시 제품 작업은 미완료였고 진행 표시는 **4/5**였다. 이는 당시 조정자의
보고이며 테스트 통과율·수용 기준 충족률이나 이번 하네스 보완 작업의 진행률이 아니다.
제품의 이후 완료 여부는 이 문서에서 확인하지 않았다.

## 근거와 접근 범위

제품 작업의 사실은 사용자가 제공한 중간 평가에서 인용·요약했다. 원본 대화 전체,
감사 로그, 제품 코드나 실행 결과를 이 저장소에서 직접 확인한 평가는 아니다.
원문의 `verification.md`, `compatibility.md`와 `.loop/` 감사 기록은 이 저장소에
없으므로 실재하는 저장소 근거처럼 링크하지 않는다. 원문에 언급된 `.artifacts/`,
가상환경·빌드·소비 fixture도 별도 전달 없이는 재현 근거가 되지 않는다.

이번 보완의 직접 근거는 [개발 규칙](../rules/workflow.md),
[공통 작업 규칙](../rules/work.md), [품질 규칙](../rules/quality.md),
[작성 규칙](../rules/writing.md), [벤치마크 규칙](../rules/benchmark.md)와
[구조 설명](architecture.md)이다. 규칙의 기존 요구와 이번 명시적 보완을 구분한다.
이 파일은 이식 가능한 평가 기록이며 제품 감사 원본이나 생성된 실행 상태를 대체하지 않는다.

## 당시 관찰: 완료 대신 예산 소진으로 중단

제공된 기록에 따르면 `endpoint-libraries-resumed`는 M1 통과 후 M2 검토 다섯 번을
소진했다. 마지막 Codex 검토도 수정 요구였고, Node 테스트 180개 통과와 별개로
다음 세 정확성 문제가 남았다.

1. Express escaped path를 실제 등록 의미와 다르게 OpenAPI 경로로 투영했다.
2. 중첩 JSON Schema resource의 참조 기준 재배치에서 resource 경계를 놓쳤다.
3. Express 설정 조회를 route 등록으로 관찰해 존재하지 않는 경로를 만들었다.

중단 원인은 남은 결함과 동결된 M2 시도 예산 소진이었다. 테스트 통과는 독립 검토
통과를 대신하지 않았다. 당시 다섯 번의 상한은 사용자 선택이 아닌 조정자 선택이었다.
사용자의 추가 수리 의사와 기존 예산을 소급 변경할 수 없다는 제약 사이에서 재개 요청과
상태 확인이 반복됐다. 후속 예산인 단계별 8회·worker 호출 24회·활성 시간 10,800초도
조정자의 선택이었다. 이 기록은 해당 예산을 승인하거나 이전 실패를 초기화하지 않는다.

## 과거 검증: 서로 다른 단위는 합산하지 않음

아래는 제공된 평가에 기록된 과거 결과이며 이번 저장소에서 재실행한 결과가 아니다.
고정 버전 전체 목록과 OS 지원 범위는 원본 호환 문서가 없으므로 확인하지 않았다.

| 구분 | 제공된 과거 결과 | 단위와 범위 |
| --- | --- | --- |
| Python | 3.11.12 / 3.12.11 / 3.13.5 각각 109 | 각 환경 pytest 공통 61 + FastAPI 48 tests |
| Node | 180 tests | Nest 11/12 각각 90: runtime 77 + native-nullability 7 + versioning-metadata 2 + final-registration 4; 실패·skip·cancelled·todo 각각 0 |
| Spring | 310 검증 항목 | Boot 3/4 MVC·WebFlux Java assertion 292 + inventory·표준 OpenAPI 검증 18 |
| 배포물 소비 | wheel 3 / npm 4 / Maven 7 | wheel 소비 검증 3항목, tarball 설치 앱 4개, Maven JAR/POM 소비 검증 7항목 |

환경별 반복 실행·test·assertion·소비 앱·검증 항목을 하나의 총 테스트 수로 합치지 않는다.
이 결과를 남은 세 결함 수리 이후의 새 gate나 다른 버전의 인증으로 확대하지 않는다.

## 정정과 해석의 경계

제공된 이전 제안 평가에 따르면 Fastify 자체가 schema에 symbol을 추가했고 fixture는
ready 이후 live schema를 직렬화했다. 이를 SDK의 schema 변조로 단정한 설명은 잘못이었다.
중복 route fixture의 `FST_ERR_DUPLICATED_ROUTE` 코드 기대도 잘못된 가정이었다.
원래 Error 객체의 동일성을 확인한 검증은 유효하며, 잘못된 코드 기대와 구분해야 한다.
native already-declared 메시지와 원래 객체 보존은 각각 실제 관찰로 검증해야 한다.

발견은 여러 검토에 나뉘어 추가됐으며 전체 파일 교체 제안과 fixture 수정이 반복됐다고
보고됐다. 전체 파일 형식이 실패나 추가 시간을 일으켰다는 인과관계는 측정되지 않았다.
whole-file 제안은 현재 하네스의 전달 형식이므로, 설명을 관련 변경과 근거에 한정하는
것과 전달 프로토콜 자체를 바꾸는 것을 혼동하지 않는다.

긴 대기·반복 상태 안내·문서 후순위화가 보고됐지만 시간·반복 횟수·원인별 비용의
집계는 없다. 문서는 완료 뒤 작성하는 순서로 미뤄졌으며, 중간 문서 우선 지시 이후에도
이를 위반해 계속 지연했다는 근거는 없다. 이번 우선순위 보완은 예방 가설이다.

## 유지할 점

1. 고정 프레임워크 조합과 suite별 단위를 기록하고 실제 설치 위치를 확인한 배포물 소비 검증.
2. 거절된 제안을 채택 결과와 분리 보존하고 실패 이력을 성공으로 덮지 않는 절차.
3. 통과한 Node 테스트가 놓친 정확성 결함을 찾아낸 독립 검토의 실효성.
4. 예산 소진을 완료로 처리하지 않고 남은 결함과 과거 검증을 구분한 보고.
5. 사용자의 Claude 검토 제외 요청을 task-local Codex-only 진입점으로 반영한 결정.

마지막 항목은 당시 제품 작업의 사용자 지정 예외다. 설치된 하네스가 변경됐다는 뜻도,
이번 저장소의 반대 제공자 검토 요구를 자동 해제하는 권한도 아니다.

## 이번 규칙 보완과 관찰 가능한 검증

규칙은 원래 실제 테스트·독립 검토·유한 예산·실패 보존·중복 기록 억제를 요구했다.
다음은 해당 요구를 대체하는 새 실행 엔진이 아니라 조정자의 판단 지침을 명확히 한 것이다.
효과는 아직 측정되지 않았다.

| 대상 | 한정된 보완 | 후속 검증 기준 |
| --- | --- | --- |
| 예산과 후속 실행 | freeze 전 조정자 예산·근거·소진 조건을 공개하고, 추가 수리 요청 시 이전 목표·실패 gate·미해결 acceptance를 후속 preflight에 연결 | 이전 시도는 보존되고 새 예산의 선택 주체가 명확함; 상태 질문만으로 새 실행하지 않음 |
| 의미 경계 | correctness finding을 재현하는 회귀와 native 동작 근거를 연결하고 finding별 해소 여부를 보고 | 문자열·오류 코드·변조 주체의 추정 대신 실제 등록·참조·객체 근거를 확인; 테스트 개수만으로 해소 판정하지 않음 |
| 중간 산출물과 상태 안내 | 요청된 중간 산출물을 다음 안전한 경계에서 추가 구현보다 먼저 전달하고, 새 결과·장애·확인 조건을 담아 안내 | 중간 문서는 제품 gate를 완료시키지 않음; 무변화 대기를 새 진척으로 표현하지 않음; 과거 중단 기록 유지 |

당시 제품의 남은 세 결함에는 각각 실제 등록 또는 schema resource 회귀를 고정하고
Node 전체 검증과 독립 검토를 수행하는 후속 행동이 적절하다. 해당 제품 코드는 이 저장소에
없으며 이번 변경에서 수리하거나 검증했다고 주장하지 않는다.

## 평가의 한계와 벤치마크 상태

단일 실사용 사례이며 동일 조건의 plain-control이 없다. 모델·effort·문제 난이도·재시도
예산을 통제한 비교나 일관된 토큰·금액·활성 시간·대기 시간 집계도 없다. 비용 절감,
속도 향상, 다른 방식 대비 우월성을 주장할 수 없다. 구성된 비용 순위도 실제 비용은 아니다.

이번 확인은 `python3 scripts/benchmark.py --help`와 CLI 가용성 확인까지다.
`command -v claude`에서 Claude CLI가 발견되지 않았고 명시적 모델·effort도 미확정이다.
따라서 live starting baseline, 변경 후 `bench check`, 전후 비교와 `bench gate`는 미실행이다.
임의 모델로 setup 실패 실행을 만들지 않았다. 유닛 테스트나 모의 CLI 성공은 이 누락을
대신하지 않으며, 이번 보완은 benchmark-validated 개선으로 표시할 수 없다.

## 이번 저장소 검증 — 결과 추가 영역

조정자가 실제 실행한 명령·환경·결과와 날짜를 이 영역에 추가한다. 아직 기입되지 않은
결과를 통과로 읽지 않는다. 라이브 벤치 미실행 범위와 실제 구현 검증을 구분한다.

## 제품 재개 작업 — 아직 평가하지 않음

이후 제품 수리·새 gate·독립 검토·배포물 소비 결과는 아직 평가하지 않았다.
추가 기록에는 날짜·실행 식별자·변경 범위·검증 명령과 환경·단위별 결과·미해결 사항·
개선 가설 관찰을 남긴다. 미실행은 미실행으로 표시한다. 당시 4/5·M2 다섯 번 소진·
마지막 세 결함의 이력은 보존하며 정정은 날짜·대상 진술·근거를 명시한다.

## 2026-10-18 추가 결정 — CLI 가용성에 따른 독립 검토

사용자가 반대 CLI가 실제 있을 때만 교차 검토하고, Codex만 있는 로컬 환경에서도 검증과
벤치를 지원하도록 요청했다. 앞의 Claude 부재 기록은 당시 상태로 보존한다. 이번 변경은
plan-review에서 반대 CLI 가용성을 확인해 검토 제공자를 기록하고, 없으면 동일 제공자의
새 읽기 전용 호출을 선택한다. 이후 선택한 CLI의 인증·권한·실행 실패를 다른 제공자로
조용히 재시도하지 않는다. 모델·effort는 여전히 명시적으로 고정한다.

벤치는 단일 제공자 모델·effort catalog를 지원하고 catalog 밖의 중첩 제공자 호출을
거절한다. 검토 정책과 제공자 집합은 실험 프로필에 기록하며 교차 제공자 baseline과
합치지 않는다. 동일 제공자 검토의 효과나 기존 교차 검토와의 동등성은 아직 입증되지
않았다. 새 프로필의 첫 라이브 실행은 별도 baseline이며 개선 증거가 아니다.
실제 테스트와 라이브 실행 결과는 조정자가 위 검증 영역에 추가한다.

## 2026-10-18 추가 검증 — 이번 하네스 변경

앞의 미실행 기록 이후 사용 가능한 로컬 설정을 확인해 `gpt-6.1-sol`, effort `low`를
명시적으로 사용했다. 아래는 이번 저장소 변경의 검증이며 당시 제품 작업의 결과가 아니다.

| 검증 | 확인 결과와 한계 |
| --- | --- |
| 전체 테스트 | 최종 `python3 -m unittest discover -s tests -v`: 302 tests, 328.683초, OK. 로그: `/tmp/loop-work-final-verification-v5-20261018.log`. `git diff --check`도 통과했다. |
| 실제 독립 CLI 검토 | Codex `gpt-6.1-sol` / `low`의 새 호출로 검토했다. Claude CLI가 없어 같은 제공자 검토였다. v1은 재검토 시 오래된 approval이 남는 결함, v2는 단일 제공자 보고서의 `KeyError: claude`를 지적했고 각각 수정했다. v3는 PASS였다. 최종 검토: `/tmp/loop-work-independent-review-20261018-v3.txt`. |
| 실패 보존 | 초기 295개 실행의 error 1건은 실행 도중 규칙 수정으로 integrity guard가 거절한 결과다. 중간 300개 실행은 통과했다. 이후 302개 실행 중 한 번은 새 단일 제공자 테스트가 `phase=judge`에서 실패했다. 원래 오류 세부사항이 없어 원인은 미확정이며 단독·선행 순서·전체 모듈 import 조건의 재현 3회는 모두 통과했다. assertion에 반환값 진단을 추가한 후 위 최종 302개 실행이 통과했다. |

`/tmp/` 로그와 아래 실측 디렉터리는 로컬 증거이며 이 문서만으로 다른 checkout에
전달되지 않는다. 실패 실행을 최종 통과로 대체하거나, 재현 실패를 원인 해소 증거로
읽지 않는다. 유닛 테스트·모의 CLI·독립 코드 검토는 실사용 품질 개선 측정을 대신하지 않는다.

## 2026-10-18 추가 관찰 — 진행 중인 Codex-only 실측

다음은 `../loop-work-benchmarks/codex-only-20261018-02` 실행의 일부 완료 trial을 직접
확인한 관찰이다. 경로 기준은 저장소 루트이며 이 디렉터리는 저장소 밖에 있다.
이 영역 작성 시 run02는 **11/12 trial 완료, 마지막 candidate 진행 중, 채점 미완료**였다.
최종 결과는 후속 영역에 추가한다. trial의 `status=completed`는 CLI 대화 종료이며 제품
수용 기준 통과를 뜻하지 않는다.

1. **실험 경계:** run01은 소스 수정이 필요하다는 판정으로 중단하고 보존했다. run02는
   Codex-only `gpt-6.1-sol` / `low`, `repeats=1`의 구성·전송 확인 실행이다. 해당
   source/profile의 선행 live baseline은 없으며 전후 개선·품질 검증·승격 근거가 아니다.
   최종 judge·gate가 끝나기 전에 통과를 주장하지 않는다.
2. **notes-basic:** `trials/e42cb09e84f14e0db4a629bd77f22281/result.json`의 persistence와
   empty_unicode 검사가 실패했다. `workspace/app/.loop/state/notes-json/delegations/`
   아래 `notes-plan-scoped-7abdc8ee0b40/{result,assessment}.json`에서 필수 `add` 반환값을
   제외한 계획과 실제 거절을 확인했다. 조정자가 전달한 instruction에도 반환값 요구가
   빠져 있어 모델 품질만의 원인으로 단정하지 않는다. `turns/0/stdout.log`에는 재시도의
   `No higher allowed worker profile remains` 오류가 있다. 초기에는 별도로 app-server
   초기화 권한 오류도 있었다. 후속 가설은 필수 동작의 handoff 누락을 먼저 검사하고,
   fixed 단일 프로필에서 품질 거절 후 더 강한 프로필이 없다는 제한을 명시하는 것이다.
3. **notes-errors:** `trials/ec37eb5540324b2b918722c6084aa0cb/result.json`의
   invalid_unchanged와 ids_text 검사가 실패했다. `workspace/app/.loop/state/notes-validation/`
   의 `delegations/inspect-notes-55cf3ff8b794`는 app-server 초기화 권한 오류,
   `inspect-notes-4429f09c3891`은 실행 중 source 변경으로 무효화,
   `inspect-notes-bf9193de0eea`는 모델이 보고한 해시 불일치였다. 마지막 worker의 raw
   SHA-256은 supplied pin과 다른 알고리즘이었다. 세 파일을 실제 `storage.file_hash`의
   내용·실행 비트 digest로 재계산하면 모두 prompt pin과 일치했다. 마지막 주장을 실제
   stale-source 장애로 볼 근거는 없다. 후속 가설은 pin 알고리즘을 명시하고 모델의
   blocker를 실제 파일 근거와 대조하는 것이다.
4. **호출 집계 누락:** 두 trial의 `result.json`과 `accounting/worker-outcomes.json`은
   conversation 1회·worker 0회로 집계하지만 각 delegation의 `process.json`에는 실제
   Codex 호출이 3개씩 있다. argv는 trial wrapper 대신 실제 Codex 실행 경로를 가리킨다.
   따라서 기록된 `provider_calls=1`을 전체 호출수로 사용할 수 없다. wrapper를 벗어난
   정확한 메커니즘은 미확정이다. 후속 확인은 nested process와 ledger의 일치이며,
   현재 자료로 전체 예산 준수·비용 절감·모델 품질 개선을 주장하지 않는다.
5. **off 유도:** 두 trial의 `responses.json`은 미완료를 보고하면서 사용자가 요청하지
   않은 `loop-work off`를 다음 행동으로 제안했다. 이는 사용자가 해제를 선택했다는
   근거가 아니다. 후속 가설은 해제를 해결책으로 유도하기보다 실제 실패·남은 범위·
   복구 조건을 보고하도록 안내하는 것이다. 아직 그 효과를 측정하지 않았다.

## Codex-only run02 최종 결과 — 후속 추가 영역

진행 중인 마지막 trial, 전체 외부 검사, judge·gate 및 최종 실패·미실행 범위를 조정자가
확인한 뒤 추가한다. 위 11/12 시점과 두 candidate 실패 관찰은 이후 결과로 덮어쓰지 않는다.

## 2026-10-18 최종 추가 — Codex-only run02 종료 결과

run02의 `check.json`, `report.md`, `improvements.md`, `index.json`과 각 trial 결과를
확인했다. 위 11/12 시점 이후 **12/12 대화는 모두 종료**했지만 `index.complete=false`였고,
전체 check는 **exit 3, phase `judge`, verdict `inconclusive`, passed=false**로 끝났다.
오류는 `Complete the paired run before judging`이다. 실제 judge 호출은 0회이며 품질은
미측정이다. 아래 결과는 이전 미실행·진행 중 기록 이후의 관찰이다.

1. **환경 변경으로 완결성 조건 미충족:** 조정자가 종료 시 대조한 결과
   `~/.codex/config.toml`의 profile hash가 manifest의
   `98834600818167a2d1c9c4c832b4821176cebf2d2e095526d53b11c0362123be`에서
   `cec11f4c451725a72a548fc0b070202654f4828dfe77a86c150097401c383dd0`으로 달랐다.
   source snapshot은 manifest와 일치했고 다른 host profile hash는 같았다. 누가 왜
   설정을 변경했는지는 미확정이다. 이번 작업 도구로 전역 설정을 쓰지 않았으며,
   hash 차이만으로 변경 주체를 추정하지 않는다. profile guard가 채점을 막은 결과다.
2. **외부 검사 관찰:** 각 trial의 모든 외부 check가 통과한 사례는 plain 6/6,
   candidate 3/6이었다. candidate에서는 source-explanation·session-refresh·small-change가
   통과했고 notes-basic·notes-errors·readme-contract가 실패했다. 이는 1회 실행의 외부
   검사 결과이며, rubric을 포함한 종합 품질 점수나 통계적 개선 판정이 아니다.
3. **시간·호출 해석 제한:** `improvements.md`의 관측 평균 시간은 plain 21.321초,
   candidate 116.630초다. 실행 중 환경 변경과 단일 반복 때문에 차이의 원인이나 일반적인
   속도 효과를 단정하지 않는다. 앞서 확인한 nested CLI 누락 때문에 보고서의 호출
   합계·평균을 실제 전체 호출량이나 비용으로 사용할 수 없다.
4. **gate와 baseline:** 별도로 실행한 `bench gate`도 exit 3, `inconclusive`,
   passed=false였다. 근거는 `/tmp/loop-work-bench-gate-20261018.log`다. baseline은
   전진하지 않았다. 고정 정책의 최소 반복은 3회인데 이번 진단 실행은 `repeats=1`이므로
   환경이 안정적이었어도 품질 검증·승격은 허용되지 않는다. 보고서의 개별 mandatory
   check 실패와 시간 초과 관찰은 보존하되, 전체 판정을 통과나 개선으로 바꾸지 않는다.
5. **다음 한정 행동:** 보존된 delegation `process.json`과 trial `calls/`를 대조해
   nested 호출 누락 경로를 확인하고, 재실험 전 host profile의 안정성을 확인한다.
   이 문서는 전역 설정 변경·설치·추가 실행을 승인하거나 자동 수행하지 않는다.

이번 구현 검증의 최종 결과는 앞서 기록한 **302 tests, 328.683초, OK**다. 구현 검증
통과와 실측 gate 미통과는 별개의 결과이며, 이번 보완의 비용·전체 호출량·품질 개선은
입증되지 않았다. run01의 중단과 run02의 실패·미측정 근거는 보존한다.

## 2026-10-18 추가 완료 조건 — 실제 결과의 비퇴행 검증

사용자가 완료 조건을 추가했다. **전달한 개선점을 수정하면서 실제 하네스가 더 나쁜
결과를 만들지 않는다는 검증이 필요하다.** 코드·규칙 수정과 유닛 테스트만으로 이 조건을
충족하지 않는다. 현재 유효한 live baseline과 동일 조건의 전후 비교는 없으므로 품질
개선과 비퇴행은 미검증이며, 요청 전체가 최종 완료됐다고 보고할 수 없다.

1. **계측·환경 관찰 보완:** 관리 wrapper의 절대 경로 사용, 정확히 일치하는 managed
   receipt의 reconciliation과 common-work 경로, 직접 호출의 별도 취급을 보완했다.
   host 설정은 내용과 target·symlink metadata, 변경 후 원복, 없는 파일의 조상 경로까지
   관찰하며 관찰 race는 실패로 처리한다. 관련 테스트 63개가 통과했고 실제 독립 Codex
   CLI 검토 `/tmp/loop-work-accounting-review-v3-20261018.txt`는 PASS였다. 이는 계측
   구현 검증이며 모든 실제 호출이 집계됐거나 환경이 고정됐다는 실측 증거는 아니다.
2. **작업 흐름 보완:** 필수 요구사항의 handoff 보존, raw SHA-256과 metadata 포함 pin의
   구분, 불필요한 반복 조사·계획 억제, preflight와 off 유도 제한,
   `PYTHONDONTWRITEBYTECODE`의 환경 우선순위를 보완했다. 관련 테스트 55개와 실제
   독립 Codex 검토 `/tmp/loop-work-workflow-review-20261018.txt`가 통과했다. 새 전체
   테스트는 `/tmp/loop-work-nonregression-implementation-tests-20261018.log`에서 진행
   중인 상태를 확인했으며 이 영역 작성 시 최종 결과는 아직 확인하지 않았다.
3. **3회 반복 baseline 시도도 차단:** 저장소 밖
   `../loop-work-benchmarks/frozen-before-20261018-r1`은 변경 금지된 before 원본이다.
   `../loop-work-benchmarks/nonregression-before-20261018-r1`은 반복 3회·36시도를
   계획했지만 첫 plain source-explanation 실행 중 전역 Codex 설정의 실제 파일 hash가
   바뀌고 175 bytes 증가해 strict profile guard가 차단했다. 나머지 35개 CLI는 실행되지
   않았다. index의 36개 기록은 36개 실제 실행을 뜻하지 않는다. check는 judge 단계
   `inconclusive`이며 유효한 baseline이나 전후 비교를 만들지 못했다. 이는 단순히
   profile 변경으로 잘못 판정한 사례가 아니라 실제 파일 변동이다. 해당 trial의 trusted
   stanza 길이도 175 bytes지만, 동일한 길이만으로 작성 주체·PID나 원인을 확정하지 않는다.
4. **환경 준비와 권한 경계:**
   `../loop-work-benchmarks/nonregression-preflight-20261018`에 before·after 각
   36 trial, 각각 42 Git root에 해당하는 총 84개 root의 준비 자료가 있다.
   `workspace-roots.txt`, `before-trialplans.json`, `after-trialplans.json`,
   `plan-checks.json`은 준비 증거이며 설정 반영·실측 통과 증거가 아니다.
   전역 Codex 설정 변경은 아직 승인되지 않았으므로 쓰지 않는다. 승인 필요의 출처는
   실제 저장소 AGENTS 파일의 별도 Autonomy 문단이 아니라, 사용자가 이 대화에 제공한
   working policy의 “Codex or MCP configuration changes”에 대한 명시적 승인 요구다.
5. **남은 검증:** 선택적 `--trial-plan` 경로는 아직 준비 단계이며 구현·사용 완료로
   표시하지 않는다. 전체 테스트와 계획 검증의 결과를 확인하고 환경 권한을 해결한 뒤,
   기존 실패와 before 원본을 보존한 채 동일 기준의 유효한 baseline·후속 실행·gate가
   필요하다. 허용되지 않은 전역 설정 변경이나 설치를 자동 수행하지 않는다. 이번
   테스트와 검토만으로 실제 품질·비용·비퇴행을 입증했다고 주장하지 않는다.

### 후속 확인 — 아직 결과 미기입

새 전체 테스트의 최종 명령·개수·결과, `--trial-plan` 구현 여부와 검증, 승인된 환경
준비 범위 및 재실험의 baseline·gate 결과를 확인한 뒤 이 영역에 추가한다. 앞의 중단과
설정 변경 관찰은 성공 결과로 덮어쓰지 않는다.

## 2026-10-18 추가 준비 검증 — trial-plan과 설정 절차

선택적 `--trial-plan` 경로의 구현과 준비 검증이 진행됐다. 관련 bench 테스트는
**72개, 34.770초, PASS**였다. trial-plan과 설정 helper의 새 독립 CLI 검토도
`/tmp/loop-work-preflight-final-review-20261018.txt`에서 PASS를 확인했다. 검토는
고정된 실험·judge 조건, trial 식별자와 root, 기존 동작 보존 및 정확한 84개 key만
다루는 helper의 경계를 확인했으며, 설정 변경 승인이나 실제 실행을 대신하지 않는다.

준비된 before·after 명령의 `--dry-run`은 각각 exit 0이었다. 이는 계획 검증이며
실측 모델 호출은 없었다. **84개의 정확한 벤치 전용 경로에 대한 trust 추가와 추가분
정리는 사용자 승인 대기**이고 실제 설정 helper는 실행하지 않았다.

전체 unittest의 새 최종 실행은
`/tmp/loop-work-nonregression-final-tests-20261018.log`에서 진행 중이며 이 영역 작성
시 결과는 미확정이다. 관련 테스트·독립 검토·dry-run 통과를 유효한 live baseline이나
실제 품질 비퇴행으로 바꾸어 해석하지 않는다. 비퇴행 실측은 여전히 미검증이며,
최종 전체 테스트 결과와 승인 이후 실제 환경 준비·실측 결과는 확인 후 추가한다.

## 2026-10-18 추가 확정 — 전체 최종 테스트

바로 앞 준비 검증 영역에서 미확정으로 남긴 전체 unittest 결과를 확인했다.
`python3 -m unittest discover -s tests -v`는 **325 tests, 340.871초, OK, exit 0**으로
완료했다. 근거는 `/tmp/loop-work-nonregression-final-tests-20261018.log`다. 앞의
진행 중 기록은 당시 상태로 보존하며 이 추가 기록으로 최종 결과를 구분한다.

관련 bench 테스트 72개와 독립 CLI 검토 PASS는 유지된다. 실제 품질 비퇴행은 여전히
미검증이고, 84개 벤치 전용 경로의 trust 추가·추가분 정리는 사용자 승인 대기다.
전체 테스트 통과가 설정 변경 권한이나 실측 완료를 의미하지 않는다.

## 2026-10-18 추가 실행 — 공통 work 단일 smoke

저장소 밖 `../loop-work-benchmarks/smoke-commonwork-20261018-fc6e8ca8`의
`summary.json`과 `post-run-verification.json`을 직접 확인했다. README 내용을 세 문장으로
설명하는 문서 과제에서 실제 Codex `gpt-6.1-sol` / `low` 관리 호출 1회 이후
`assess accept`와 `finish`를 거쳐 공통 work가 completed 상태가 됐다. worker CLI는
9.558초, 위임·평가·완료 구간은 10.184초였고 managed receipt와 ledger가 각각 1개로
일치했다. 외부 확인 8개가 통과했으며 host 설정과 source 보존도 확인했다.

최초 content check의 `source_readme_unchanged`는 자기 비교라 독립적인 보존 근거가
아니었다. 원래 봉인된 평가 증거는 유지하고, 이후 외부 확인의
`README_matches_dispatch_pin`으로 실제 README와 dispatch pin의 일치를 확인했다.

처음 시도한 ignored 파일 수정은 scope 보호에서 거절돼 문서 과제로 전환했다.
따라서 이 결과는 코드 수정이나 개발 gate를 검증한 것이 아니다. plain 비교군이 없는
단일 smoke이며 개선·비퇴행을 입증하지 않는다. CLI reported tokens는 50,110이지만
실제 비용과 비교 조건이 없어 효율성도 판정하지 않는다. 앞서 승인 대기로 기록한 전역
설정 절차와 실측 비퇴행 조건은 이 smoke의 성공으로 충족되지 않는다.

## 2026-10-18 추가 비교 — README 공통 work 각 3회

저장소 밖 `../loop-work-benchmarks/local-comparison-20261018-389bd1d0`의 `plan.json`과
`results.json`을 직접 확인했다. 동일한 README의 정책 사실·자료형·행 근거를 답하는
한 과제를 before·after·plain 각 3회, Codex `gpt-6.1-sol` / `low`로 비교했다.
세 조건 모두 정확성 **3/3 통과**였다. 결과를 재계산한 수치는 아래와 같으며,
조정자가 전달한 별도 `workflow_audit` 계산 결과와도 일치한다.

| 조건 | 정확성 | 전체 workflow 평균 초 | CLI 평균 input tokens |
| --- | --- | --- | --- |
| before | 3/3 | 9.619 | 49,264.7 |
| after | 3/3 | 9.166 | 49,764.3 |
| plain | 3/3 | 8.109 | 44,351 |

after−before의 반복별 시간 차이는 **−1.957, +0.223, +0.377초**였다. 평균은 약 4.7%
감소했지만 3회 중 2회는 after가 느렸으므로 안정적인 속도 개선을 입증하지 않는다.
after는 plain보다 평균 약 13% 느렸다. 입력량과 캐시 상태가 달랐고 캐시 변동은
통제하지 않았으므로 비용·효율 개선으로 해석하지 않는다.

9회 모두 host 설정·선택한 source·작업 저장소 source·README의 전후 보존을 확인했다.
전체 관리 호출은 9회로 집계됐고 재시도는 없었다. 이는 해당 관리 호출 범위의 계측
확인이며 임의의 외부 호출까지 자동 포착한다는 뜻은 아니다.

판정은 **이 단일 README 과제의 정확성 동률, 안정적인 속도 개선 미입증**이다.
고정된 scripted coordinator가 공통 work를 실행한 비교이므로 전체 메인 대화의
조사·계획·개발 흐름, 과거 실패 사례의 회복, 전체 benchmark gate를 검증하지 않았다.
같은 과제의 세 반복은 서로 다른 세 과제 표본이 아니다. 이 결과로 요청 전체의 실제
비퇴행 검증이나 최종 완료를 선언하지 않으며 앞의 실패 기록도 보존한다.

## 2026-10-18 평가 기준 추가 — 결과 품질만으로 판정

사용자가 “결과 품질 평가로만 해”라고 기준을 정했다. 이후 개선·비퇴행 판정에는
**결과의 정확성, 요구사항 충족, 근거의 타당성, 누락 여부만** 사용한다. 시간·토큰·
호출수는 과거 운영 기록으로 보존하지만 품질 판정에서 제외한다. 앞의 시간 비교와
운영 관찰은 삭제하지 않으며 이후 품질 개선·퇴보의 판단 근거로 사용하지 않는다.

기존 9회 비교의 고정 품질 조건은 네 정책 사실의 정확성·자료형·요구된 출력 형태와
각 사실을 뒷받침하는 README 행 근거다. before·after·plain은 각각 **3/3 통과로
품질 동률**이다. 시간 차이로 어느 조건의 품질이 개선되거나 퇴보했다고 판정하지
않는다. 같은 문서 과제의 반복이므로 전체 조사·계획·개발 결과 품질을 입증하지 않는다.

별도 `workflow_audit`의 quality-only assessment artifact는 작성 예정이며 아직 이
기록에서 완료된 근거로 취급하지 않는다. 이후 해당 평가의 결과와 확인 범위를 추가한다.
