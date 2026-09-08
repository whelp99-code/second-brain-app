# 공통 기억 본문 묶음 — 준비 경로 구현과 실제 MCP 검증

상태: **본문 묶음의 라이브러리 구현 및 실제 MCP 변환 검증. 자동 모델 전달·B5 전체 완료 아님.**

자비스 구현 커밋: `3360fe7` (`feat(memory): prepare bounded source-bound reference context`).

## 변경과 역할

[공급 공백 분석](CONTEXT-DELIVERY-GAP-ANALYSIS-2026-09-08.md)의 C1~C5를 따라 자비스에
`src/memory-reference-context.ts`와 public export를 추가했다. 구조 결정은
[자비스 ADR](../Orca-JARVIS/docs/planning/adr-memory-reference-context.md)에 먼저 기록했다.

`prepareMemoryReference`는 기존 read adapter가 검증한 최대 32개 검색 record를 받아
`memory-reference-v1` JSON을 만든다. 원문 LF/CRLF/CR/tab과 text digest, record/source/citation
identity, 세대·삭제 sequence/root와 유효 시점을 보존한다. 이전 추천용 assembler는 그대로이며
새 묶음은 live Linux 관측 없이도 참고 자료를 제공하고 항상 `untrusted`/`authority=none`이다.

- adapter 순서를 유지하고 동일 record를 중복 제거한다. 같은 ID의 상충 자료와 여러 세대 혼합,
  원문 digest 불일치는 오류다.
- 만료/미래 유효 사실, 가려진 민감 자료, binding 없는 legacy 자료는 제외한다. 미결 충돌·오프라인
  결과를 현재 사실로 바꾸지 않는다. 생략 사유별 개수를 제공한다.
- 최종 canonical JSON의 본문·출처·경고·예산 메타데이터를 모두 UTF-8 byte로 계수한다.
  과대 항목은 전체 생략하며 원문 일부를 잘라 새 digest처럼 제공하지 않는다.
- 선택적 tokenizer는 식별자와 실제 count 함수를 함께 요구한다. 미설정 시 tokens=null이다.
  이번 token 회귀는 명시적 합성 counter이며 실제 모델 encoding 성능/한도 검증은 아니다.
- 반환된 `serialized`가 계수·digest의 기준이다. 생성은 전송 완료를 의미하지 않는다.

I/O·별도 기억 DB·세션 상태·승인 엔진을 추가하지 않았다. 이 순수 모듈은 raw wire parser가 아니다.
호출자는 기존 adapter 검증과 로컬 suppression/범위 검사를 먼저 적용해야 한다. 실제 전송 직전의
generation/fence/만료 재확인, 전달 영수증과 삭제 projection 연결을 끝내기 전 전역 자동 주입을
활성화하지 않는다. 기존 frozen MCP 및 추천 snapshot 계약은 변경하지 않았다.

## 검증 증거

자비스 제품 소스 수정에 해당하는 최종 회귀는 **94 passed / 17 files (15.54초)**다.
신규 모듈의 25개 검사는 여러 줄, 32개 record/10개 예산 경계, 중복 출처 8개 불일치 사례를 포함한다.
이전 85개 실행과 신규 단독 실행은 중복이므로 합산하지 않는다. 타입 검사·변경 모듈/테스트 lint와 격리 tsc build는
통과했다. 자비스 전체 backend/GUI 인수의 통과로 확대하지 않는다.

로그: `/var/tmp/jarvis-memory-reference-regression-complete.log`,
`/var/tmp/jarvis-memory-reference-cap-regression.log`,
`/var/tmp/jarvis-memory-reference-types-final.log`,
`/var/tmp/jarvis-memory-reference-lint-complete.log`,
`/var/tmp/jarvis-memory-reference-build-complete.log`.

[실제 MCP 인수 도구](scripts/jarvis-memory-context-acceptance.mjs)는 임시 provider를 생성하고
기존 합성 기억 seed→실제 MCP search/page→자비스 adapter→새 본문 JSON을 확인한다.
`/var/tmp/sb-context-reference-2nESqV`에 native MCP 3건, adapter 결과와 reference JSON을 보존했다.
기억 1개, 최종 2,843 bytes, 원문/digest/record/source/citation/generation 일치, 빈 결과의 empty를
확인했다. 준비 JSON digest는
`sha256:5eeb66c8ac4495b9ef1535d4faea7450ac1fe202b3da99d4a981205adcc20d94`다.

재현: 자비스 소스를 별도 outDir에 tsc로 빌드하고 ESM metadata/node_modules 연결을 준비한 뒤,
SB 루트에서 `TMPDIR=/var/tmp node scripts/jarvis-memory-context-acceptance.mjs <build-root>`.
이번 build-root는 `/var/tmp/sb-context-boundary-rjw8vhqx`다. 결과는
`prepared_from_real_mcp`, `delivery_acceptance=false`로 기록한다.

초기 도구 실행은 격리 빌드에 frozen contract 자산이 없어 계약 검사에서 실패했다. 자비스의 기존
contract 파일을 명시했으며 hash 검사를 완화하지 않았다. 다음 실행에서 빈 검색을 no_data만으로
예상한 검증 도구의 오류가 드러났다. 실제 adapter의 current+빈 evidence도 검사하도록 고친 뒤
통과했다. 실패 로그는 `jarvis-memory-context-acceptance.log`, `...-final.log`, 최종 성공은
`...-verified.log`에 별도 보존한다. 독립 리뷰 수정 후 새 빌드로 다시 실행한 최종 성공 로그는 `...-complete.log`다.

## 독립 검토 상태

저장소 charter의 구현/검토 모델 분리 규칙에 따라 독립 리뷰를 요청했다. collaboration 하위 agent
생성은 `agent thread limit reached`로 실패했다. Claude Code의 파일 조회 리뷰와 직접 소스 리뷰는
각각 240초/180초 제한으로 종료됐으며 결과가 없었다. 기본 `/tmp` 쓰기 오류 122를 확인하고
정상 `/var/tmp`를 지정한 추가 실행도 180초에 종료됐다. 이 실행들을 검토 통과로 계산하지 않는다.
이후 설치된 모델 목록의 별도 모델 `gpt-5.6-sol`로 도구 없는 read-only 소스 리뷰를 실행했다.
첫 결과에서 같은 record ID의 중복 비교가 일부 출력 출처 필드를 제외한다는 medium 결함 1개를
지적했다. `canonicalize(candidate)`로 최종 출력 전체를 비교하도록 수정하고 source_ref/version,
page/sid, 관측/유효 시각, 민감도와 만료의 불일치 8개를 추가했다. 수정 후 94개 회귀와 실제 MCP
인수를 다시 통과했다. 원 검토 기록은 `/var/tmp/jarvis-memory-reference-review-sol.jsonl`이다.
최종 `/var/tmp/jarvis-memory-reference-review-final.jsonl`은 해당 결함 수정과 추가 actionable
finding 없음을 확인했다. 두 리뷰 모두 native turn.completed와 process exit 0을 확인했다.
리뷰는 read-only 소스 검토이며 테스트 실행은 이 작업의 별도 native 증거를 사용한다.

## 이어서 완성할 범위

1. 실제 client의 요청 경계에 이 JSON을 연결하고 전달 확인 수준·실패/불확실 상태를 기록한다.
2. 기존 context/projection에 session·compaction epoch·record version과 원문 없는 receipt를 결합한다.
3. 준비 후 정정·삭제·suppression/범위 변경 시 payload를 폐기하고 재조회한다.
4. 실제 모델 tokenizer와 질문 세트로 예산·근거 사용·자연어 회수를 측정한다.
5. 운영 배포·복원과 앱별 인수를 완료한다. 이 라이브러리 테스트로 해당 조건을 대체하지 않는다.

SB 원 작업공간의 제품 소스는 대규모 100회 쓰기 검증을 위해 고정했다. 검색/복구 후속 세 커밋은
기존과 같이 격리 worktree에서 병합 대기한다. 자비스의 동시 dashboard 변경과 사용자의 미추적
자료는 이번 단위에 포함하지 않는다. 전체 목표는 계속 미완료다.
