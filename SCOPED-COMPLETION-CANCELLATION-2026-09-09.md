# 완료 관찰의 취소 경합 수정

최종 완료 기록 경로를 대조하던 중, MCP transport가 응답을 반환한 직후 취소된 요청에도 상위 클라이언트가 remembered_completion_observed를 반환하는 경로를 재현했다. 기존 transport의 대기 중 취소 처리는 존재하지만, 이미 fulfilled된 응답을 소비하는 시점은 상위 클라이언트가 검사해야 한다.

## 변경

JARVIS memory-scoped-client의 공통 read에서 시작 전, 최초 권한 발행 후, 현재 권한 재검사 전후에 AbortSignal을 확인한다. 통합 완료 관찰도 반환 직전에 다시 확인한다. 취소는 SECOND_BRAIN_CANCELLED로 거절하며 상태→페이지→상태 후속 호출을 진행하지 않는다. 별도 취소 원장이나 서버 큐를 추가하지 않았다.

이는 확인 요청의 취소다. 이미 저장된 provider 기억을 삭제하거나 실행 중 쓰기를 취소했다는 증거가 아니다. 원래 작업의 현재 철회·suppression 및 scoped 최종 완료의 영구 증거는 별도 연결이 필요하다.

## 재현 및 검증

- 수정 전: 시작 전 취소, 각 응답 1/2/3 직후 취소, 권한 재검사 중 취소의 신규 5개가 모두 실패했다. 기존 11개는 통과했다.
- 수정 후: 완료 관찰·scoped client·재조정 관련 25개/3파일 통과(22.00초). 격리 TypeScript emit 및 변경 ESLint 통과.
- 실제 production client→stdio MCP: transport 응답이 fulfilled된 직후 wrapper에서 취소를 발생시켰다. 시작 전 호출0, 첫 응답 후 호출1, 페이지 응답 후 호출2, 마지막 상태 후 호출3에서 모두 취소 거절을 확인했다.
- 취소하지 않은 새 확인은 원래 결과와 일치했다. 기존 MCP 재시작/정책 철회 및 수락 기록 commit 직후 exit73 복구도 통과했고 attempt1/event1/재전송0, 자비스 state는 reconciling을 유지했다.
- 시계·인증 세션·provider 내부 쓰기는 fixture다. 운영 배포 및 실제 에이전트 전체 인수가 아니다.

[실제 프로세스 결과](SCOPED-COMPLETION-CANCELLATION-2026-09-09.json).

## 다음 완료 조건

현재 통합 관찰과 원래 scoped binding/attempt를 영구 증거로 결합하고, 현재 원작업/승인 철회와 재조정 fence를 동일 트랜잭션에서 검사하여 최종 완료를 기록해야 한다. 기존 legacy 식별자/receipt 검사 제거를 통한 우회는 계속 보류한다. 공개 쓰기 인증, 최초 활성 세대 이전 상태 조회, 실제 서로 다른 에이전트의 저장·새 세션 재조회 및 전체 M1–M14 인수 범위를 유지한다.

추가 회귀: production 구성·scoped 요청 상태·transport authority race 17개/3파일 통과(4.11초). 이번 단위 총42개/6파일 통과. SB 제품 소스는 변경하지 않았다.

JARVIS 구현 커밋: `2e26fd1`.
