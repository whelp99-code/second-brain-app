# 과거 완료와 현재 기억을 함께 검증하는 관찰

JARVIS 구현 커밋: `b1a2667`.

## 구현과 현재 판정

JARVIS `client.readRememberedCompletion(request)`를 추가했다. read v5의 현재 권한 검사를 재사용해 **완료 상태 조회 → 정확한 기억 조회 → 완료 상태 재조회**를 수행한다. 상태가 proved이고 출처·본문·분류가 원래 요청과 맞으며, 마지막 상태 조회와 기억 조회의 현재 generation/deletion high-water가 같을 때 `remembered_completion_observed`를 반환한다.

이는 scoped 최종 완료 처리에 필요한 통합 관찰이다. **outbox settled나 control completed를 기록한 것은 아니다.** 이전 단위에서 분리돼 있던 상태·artifact 조회를 그대로 조합하면 중간 변경을 놓칠 수 있어 검증 흐름을 하나로 묶었다. 원래 쓰기 응답이 없어도 read v5의 수락 회수 기능을 재사용한다.

## 구현 상세

- 원래 요청을 역사 시점에 codec으로 검증·동결한다. 읽기 권한은 그 요청에 쓰인 라벨이 아닌 기존 issuer의 현재 인증 세션/정책에서 얻는다.
- 첫 상태가 proved가 아니면 기억 조회까지 진행하지 않는다. 현재 기억은 기존 `verifyRememberedArtifactRead`로 본문·순서·원본·민감도·정확한 source classification을 확인한다.
- 마지막 상태는 첫 상태의 수락/proof/receipt와 같아야 한다. 마지막 현재 generation은 artifact를 읽은 generation과 같아야 한다. 과거 proof의 generation까지 현재와 같다고 요구하지 않는다. 별개 작업이 세대를 전진시켰어도 현재 기억이 일치하면 읽을 수 있다.
- 세 호출 모두 같은 provider/principal/agent/session/policy 문맥이어야 한다. 각 메서드의 프로젝트 grant는 원래 요청 범위를 포함해야 한다.
- 마지막 반환 전에 세 호출의 현재 key/정책/claim을 다시 확인한다. 페이지 조회 권한만 중간에 철회된 경우도 거절한다. 시계 역행과 만료를 거절한다.
- 재검사 때 만료 시각이 짧아지면 그 값도 누적해 결과의 `valid_until`을 제한한다. 현재 시간이 그 경계를 넘으면 반환하지 않는다. 이는 미래의 권한 유지 보증이나 재사용 가능한 grant가 아니다.

서버/MCP 계약, 원장 schema, SB 제품 소스는 이번에 변경하지 않았다. 관찰 결과를 저장하는 후속 트랜잭션은 원래 attempt와 독립적인 쓰기 fence, 사용 시점의 현재 권한·철회를 검증해야 한다.

## 검증

- JARVIS 최종 관련 67 passed / 6 files / 25.81초. 신규 통합 관찰 11개와 기존 상태·client·production·artifact·읽기 회귀 포함.
- 신규 허용 사례: 정상 완료, 첫 상태 뒤 현재 세대가 전진했지만 page/마지막 상태가 일치하는 경우, 페이지 정책 만료가 짧아진 경우의 유효시간 제한.
- 신규 거절 사례: pending, 기억 누락, page 뒤 세대 변경, 상태 변경, 다시 계산된 해시를 가진 proof 변경, 호출별 세션 불일치, 페이지 권한 철회, 페이지 권한 만료.
- TypeScript 격리 emit과 변경 ESLint 통과.
- 실제 production client→감독되는 stdio MCP에서도 통합 관찰·MCP 재시작 후 일치·양측 정책 철회 거절을 확인했다. 이어 기존 수락 응답 유실 복구와 기록 commit 후 exit73/새 프로세스 replay를 실행해 attempt1/event1/FK0을 유지했다.

[실제 프로세스 결과](SCOPED-COMPLETION-OBSERVATION-2026-09-09.json). 시험의 인증 세션·키·시계·내부 provider 쓰기 callback은 fixture다. 운영 서비스의 인증/쓰기/최종 완료 인수로 보고하지 않는다. SB 제품은 변경하지 않아 전체 SB 검사를 반복하지 않았으며, 이전 전체 1,260 passed/2 skipped는 [이전 단위](SCOPED-ACK-RECOVERY-2026-09-09.md)의 결과다.

## 보류 판정과 다음 변경

**기존 legacy 완료 경로에 scoped 결과를 직접 넣는 방식은 보류한다.** `memory-outbox-control-proof.ts`는 `memout:pos:v2` 식별자와 기존 settlement receipt/observation event를 재구성한다. scoped 등록은 `memout:scoped:v4`이며 provider/scope/proof·정확한 artifact 분류 결합이 추가로 필요하다. `memory-outbox-control.ts`의 일괄 복구도 legacy만 선택한다. 이 조건을 완화하거나 scoped 결과를 legacy receipt처럼 위장하지 않는다.

다음은 완료 처리의 남은 구현 조건이다.

1. 원래 scoped binding/attempt/fence 및 회수한 acceptance와 이번 관찰을 묶어 보존한다. 증명의 단순 JSON/해시 일치만으로 권한을 만들지 않는다.
2. 원래 control command/receipt 소비와 현재 철회·suppression 규칙을 대조하고, scoped reconciliation fence로 단일 트랜잭션에서 완료를 기록한다.
3. scoped 완료 증거를 원장에서 재구성하는 control 검증 경로를 구현한다. commit 전후 중단·중복 완료·동시 worker·정책/기억 변경을 실제 프로세스로 검증한다.
4. 공개 쓰기 인증 전송·최초 활성 세대 이전 상태·운영 agent 사용, 전체 M1–M14 인수는 계속 진행한다.

이번에 운영 DB/설정/서비스·vault를 바꾸거나 push/배포하지 않았다. 전체 완성 목표를 유지한다.
