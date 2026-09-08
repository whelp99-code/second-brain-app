# 미전송 정정 취소의 provider 원자 접수

2026-09-08, 구현 전 결정. 기존 취소 의향 library 다음 단계.

기존 journal.db에 취소 의향과 원본 요청 alias의 영구 거부 기록을 추가한다. 별도 기억 DB나
MCP 도구를 만들지 않는다. 실제 실행 연결은 억제 세대·처분 결과 계약까지 보류한다.

접수는 현재 서명 검증 후 기존 pending-directory flock을 잡고 BEGIN IMMEDIATE에서 진행한다.
원본 request/alias/실행 흔적 또는 원본 pending/processing 파일이 있으면 미전송 취소를
거부한다. 파일은 journal 이전 publication의 수신 증거이므로 orphan도 자동 취소하지 않는다.
원본 원장 수신이 있다면 상태와 무관하게 기존 관측/복구로 넘긴다.

미수신인 경우 원본 8 alias의 거부 marker, 취소 nonce/서명 의향, 연속 tombstone과 target
snapshot을 한 transaction에 기록한다. 결과는 suppression_pending이다. 이는 durable 접수
결과이지 generation 활성화나 물리 삭제 증거가 아니다. 기존 조회가 stale로 닫히는 것은 유지한다.
후속 worker는 여기 저장한 원문 없는 의향을 바탕으로 별도 억제 세대를 만들어야 한다.

원본 replay_status와 accept 모두 취소 alias를 검사한다. requests/request_aliases INSERT
trigger도 거부 기록을 검사하여 같은 journal을 쓰는 이전 코드의 접수를 차단한다. 파일 publication
전에 원본 요청을 거부한다. 다른 코드가 이미 파일을 게시한 경우 실패 후 파일을 임의 삭제하지 않는다.

같은 canonical intent만 idempotent replay하며 nonce/원본 alias가 같지만 의향 bytes가 다르면
충돌이다. 만료된 의향은 신규 접수/재전송에서 재검증을 우회하지 않는다. 만료 이후 복구의 조회와
갱신 의향 계약은 후속 단계다. 서명된 receipt, 실행 key purpose/revocation, 원본 실제 generation
target 검증, UI/CLI/MCP 연결도 전체 실행 인수 전 필수다.
