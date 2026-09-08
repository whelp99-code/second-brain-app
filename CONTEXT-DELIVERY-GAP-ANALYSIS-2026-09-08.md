# 자비스 인계 병합: 공통 문맥 공급의 구현 경계와 추가 과제

상태: **기존 코드 대조 및 격리 실행으로 공백 확인. B5 구현·모델 전달·운영 인수 미완료.**

인계 정본은 [자비스 인계서](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md), 통합 계획은 [OSS 흡수 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md)이다. 사용자 결정대로 Second Brain을 기억 정본으로 유지한다. 자비스는 실행·검증, dev-wiki/Git 문서는 개발 결정 원문을 맡는다. 이미 구현한 저장·정정·삭제·세대·MCP 기능을 재사용한다.

## 1. 지금 동작하는 범위와 완성되지 않은 범위

- 저장→배치→검색→원문 회수는 격리 실제 MCP 및 실제 Codex/Claude CLI에서 검증했다. 자비스의 저장 요청·완료 영수증·재조회와 정정/삭제 후 조회도 개별 인수 기록이 있다. [실제 두 클라이언트 인수](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md), [정정 명령 완료](CORRECTION-CONTROL-COMPLETION-2026-09-08.md)를 재사용한다.
- 이것이 모든 에이전트의 자동 기억 수집·문맥 주입, 프로젝트 권한 격리, 운영 배포 완료를 의미하지 않는다. 이번 실행도 운영 서비스 상태를 새로 측정한 것이 아니다.
- 검색/중단 사본 복구 후속 세 커밋 `d174276` → `47fa507` → `9323a6d`는 격리 worktree에 있다. 결합 제품 전체 764 passed/2 skipped 기록이 있으며 원 작업공간 병합은 대규모 쓰기 인수 종료 후 수행한다.
- 같은 합성 한국어 질문 세트의 Recall@5는 정답 있는 90개 중 40개에서 60개로 개선됐다. 자연어·의역 30개는 미회수다. 합성 질문을 실제 사용자 품질 인수로 계산하지 않는다.
- 현재 full 인수는 5천 source/10만 units/1만 wiki/1천 conflict 기반의 100회 쓰기와 동시 MCP 읽기다. 이 문서 작성 중 로그에서 30회 완료를 관측했으며 실행 핸들은 유지 중이다. **100회 통과 기록이 아니다.** 원 작업공간 제품 소스는 고정한다.

## 2. 네 OSS의 선별 흡수와 기존 구현 대조

아래 외부 기능은 인계서가 고정 커밋에서 확인한 내용의 재분류다. 이번에 외부 최신 버전이나 저자 성능 수치를 재검증한 것은 아니다. 외부 코드·라이브러리를 복사하거나 설치하지 않았다.

| 대상 | 흡수할 장점 | 기존 구현 재사용 | 추가 작업 / 제외 |
|---|---|---|---|
| LightRAG | 근거를 갖춘 검색과 평가, 삭제 후 파생 자료 일관성 | `sb/search.py`, `sb/sealed_search.py`, record/citation, 세대·삭제 수명주기 | 한국어 질문으로 의미 회수 개선을 평가. graph DB·추가 LLM 단계를 기본 도입하지 않음 |
| Tencent Agent Memory | 하나의 기억 인터페이스, 소유·공유·출처·버전 | SB MCP, 자비스 read/write adapter, 기존 요청·fence·영수증 | 검증된 프로젝트 분류와 접근 범위 필요. 별도 기억 서버·Proxy·DB 및 팀 관리 전체 이식 제외 |
| code-brain | 작은 작업 문맥, 예산, 결정/실패 근거 | 자비스 context assembler·context store·projection lineage | 실제 본문 전달과 세션 사용량 연결 필요. 워커·전역 훅·실행 규칙 이식 제외 |
| memory-bank | 출처 추적, 정정·대체, 세션 중복 억제 | 원문 CAS/원장, SB record, 자비스 삭제/정정 projection | 실제 전달 receipt와 compaction 후 재공급 필요. Claude 전용 파서를 모든 client 수집기로 취급하지 않음 |

## 3. 새로 확인한 연결 공백

대조 기준은 자비스 `704f238158513584ac9a763a638c738e18e27310`의 제품 소스다. 기존 변경 중인 자비스 `AGENTS.md`와 인계 문서는 보존했다. 아래 항목들은 기존 조립기의 제한된 목적을 무시하고 일반 기억 공급기로 사용할 때 생기는 결손이다. 모두 기존 기능의 오류라고 단정하지 않는다.

| ID / 분류 / 우선순위 | 코드와 재현 결과 | 공통 기억에 미치는 영향 | 구현 방향 및 완료 기준 |
|---|---|---|---|
| C1 / 연결 개선 / P1 | `src/context-assembler.ts:126`는 snapshot을 반환한다. `rg`로 확인한 직접 참조는 정의와 index export이며 production 직접 호출부가 없다. 확정 기억 1개로 `sufficient`여도 출력에 본문 없음 | snapshot 생성만으로 모델이 기억 내용을 받았다고 판단할 수 없음 | 실제 client 요청 경계에 제한된 본문 묶음을 연결. provider record→보낸 본문→응답에서 사용한 근거를 대응하고 전달 실패를 기록 |
| C2 / 계약 개선 / P1 | `second-brain-adapter-types.ts`의 trust는 `untrusted`; `context-assembler-sources.ts:61`은 `user_confirmed`만 채택. 같은 입력의 trust를 provider 값으로 바꾸면 기억 refs 0개, `UNCONFIRMED_MEMORY`, `insufficient` | adapter 출력의 필드 변환만으로 기존 조립기에 연결할 수 없음 | 검색된 참고 정보의 출처 신뢰와 사용자 확인/실행 권한을 구분. `untrusted`를 임의로 confirmed로 올리지 않으며 검증되지 않은 기억으로 실행 성공·승인을 생성하지 않음 |
| C3 / 호환성 수정 / P1 | `context-assembler-input.ts:63,103`이 LF/CRLF/CR/tab을 거부. 네 경우 모두 `CONTEXT_ASSEMBLER_INPUT_INVALID` 재현 | SB V3에서 허용한 일반 여러 줄 본문을 직접 전달할 수 없음 | 본문과 식별자 검증을 분리하고 원문 바이트·digest 의미 보존. 기존 frozen 계약 변경 없이 versioned mapping에서 검증, 허용하지 않는 제어문자는 계속 거부 |
| C4 / 예산 개선 / P1 | `context-assembler-budget.ts:79`는 직렬화 snapshot을 계수. 본문 3 byte/3,600 byte 두 경우 모두 snapshot 1,967 byte | 실제 본문을 붙일 때 총량 초과와 비용 증가 가능. 현재 수치를 모델 token 예산으로 해석할 수 없음 | 출처·충돌 경고·구분자를 포함한 최종 전달 payload를 계수. tokenizer/model 식별과 token 계산 가능 여부를 명시. 항목 전체를 생략하며 생략 이유·개수 기록 |
| C5 / 목적 분리 / P1 | `context-assembler-sources.ts:90`, budget output은 live Linux observation을 요구. 확정 기억만 있으면 refs 1개여도 `insufficient` | 운영 우선순위 추천용 조립기를 일반 기억 질의에 그대로 재사용하면 준비 상태가 맞지 않음 | 추천의 live observation 조건 유지. 기억 조회 목적의 별도 입력/출력 프로필을 기존 순수 선택/근거 도구와 결합. 가짜 관측을 만들어 sufficient로 바꾸지 않음 |
| C6 / 실제 전달 고도화 / P1 | `personal-context-store.ts:123`은 기존 projection에 context를 결합하며 저장 결과는 context ID/digest/version/count. 이것은 모델 수신 증명이 아님 | 생성됐지만 전송 실패한 기억을 이미 사용한 것으로 처리하거나 같은 기억을 반복 공급할 수 있음 | 기존 context ID·record digest·세대·정책·session/compaction epoch에 전달 결과를 연결. 전달 확인 후 중복 억제, 실패는 재시도, 새로운 session/compaction에는 필요한 재공급 허용 |
| C7 / 수명주기 개선 / P1 | 기존 `memory-projection-bindings.ts`와 `personal-context-store.ts`가 삭제 추적 경로를 제공 | 별도 plaintext context DB를 추가하면 삭제·정정 전파를 우회할 수 있음 | 기존 projection 계보 재사용. 준비/전송 직전 변경·삭제·정책 철회를 재확인하고 오래된 payload 폐기. 전달 이력은 원문 최소화 및 동일 삭제 경로에 결합 |
| C8 / 범위 개선 / P1 | [범위 ADR](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md): 현 owner fence와 record에는 검증된 project 분류가 없음 | 같은 owner 공유 검증을 프로젝트 간 보안 격리 증거로 쓸 수 없음 | 자비스가 확인한 범위와 SB 원본 분류를 함께 versioning. 검색·직접 page·conflict·export·context에서 동일 적용. 임의 project 문자열/검색 필터로 권한을 대체하지 않음 |

`SecondBrainPersonalConnectorSource`도 readiness·evidence digest·version·민감도 관측을 제공하지만 본문을 모델에 전달하는 역할은 아니다. outbox의 읽기·쓰기 완료 관측과 context 저장·notification 전달을 일반 agent의 문맥 주입 완료로 합산하지 않는다.

## 4. 구현 순서와 보류 판정

1. **C2/C5 계약 확정:** 기존 추천 프로필을 유지하면서 일반 참고 기억 공급의 목적·trust·authority 없는 결과를 정의한다. SB에 새로운 승인 엔진을 만들지 않는다.
2. **C1/C3/C4 구현:** 기존 generation-bound record를 선택하고 원문을 보존하는 작은 본문 묶음을 만든다. byte/token 예산은 최종 전달 데이터를 대상으로 검사한다. frozen MCP 필드는 바꾸지 않고 필요한 확장은 별도 버전으로 다룬다.
3. **C6/C7 연결:** 자비스의 기존 context/projection과 실제 client 전송 경계를 연결한다. 준비됨/전송 실패/전달 확인/무효화를 구분한다. 수신 확인 수준은 client별로 명시하고 CLI exit 0만으로 전달 성공을 판정하지 않는다.
4. **C8 확대:** 단일 owner 검증과 프로젝트 격리 검증을 나눈다. 범위·원본 분류가 결합되기 전 공유 범위를 자동 확대하지 않는다.
5. **실사용 인수:** Codex 기록→Claude/JARVIS 재사용, 정정 후 새 값, 삭제 후 미노출, 전달 중 오류 재시도, compaction 후 재공급, provider 장애 시 근거 부족 표시를 같은 record·receipt로 검증한다. 실제 자연어 질문 평가와 운영 복원은 별도 게이트로 유지한다.

보류: trust 강제 승격, 가짜 관측, 삭제와 무관한 별도 원문 DB, 일반 filter를 권한으로 취급, 모든 client에 전역 자동 훅 설치, 검증되지 않은 작업 요약 자동 저장. 보류 범위를 제외한 기존 저장·검색·복구 개발과 검증은 계속한다.

## 5. 이번 검증과 재현 방법

- [진단 도구](scripts/context-boundary-audit.mjs)를 추가했다. 제품 로직을 재구현하지 않고 실제 자비스 assembler와 기존 fixture를 새 빌드에서 호출한다.
- 자비스 기존 `dist`를 재사용하지 않고 `node_modules/.bin/tsc --outDir /var/tmp/sb-context-boundary-rjw8vhqx`로 격리 출력했다. build exit 0, 로그 `/var/tmp/sb-context-boundary-build.log`.
- 출력 디렉터리에 `type=module` package metadata와 기존 JARVIS node_modules 연결을 준비했다. 신규 의존성 설치와 운영 DB 접근은 하지 않았다.
- `node scripts/context-boundary-audit.mjs /var/tmp/sb-context-boundary-rjw8vhqx` exit 0. confirmed/provider/memory-only/네 구분문자/본문 크기 비교를 검사했다. 결과 `/var/tmp/sb-context-boundary-rjw8vhqx/audit.json`에 실행 모듈 hash와 한계를 기록했다. Node syntax check 통과.
- 결과 상태는 `boundary_gaps_reproduced`, `delivery_acceptance=false`이다. 진단 exit 0은 공백을 재현했다는 뜻이며 공급 기능 완성을 의미하지 않는다. provider RPC·실제 모델 요청·프로젝트 격리·삭제/compaction은 이번 진단 대상이 아니다.

이번 단위의 산출물은 인계 분석 보강·재현 가능한 연결 진단·기존 계획의 세부화다. 제품 소스 수정/배포로 보고하지 않는다. 기존 세 커밋의 병합 대기, 100회 쓰기, B4~B8의 잔여 완료 조건을 유지한다.
