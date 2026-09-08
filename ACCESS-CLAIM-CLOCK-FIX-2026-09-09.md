# 범위 claim 발급 중 시각 변경 결함 수정

2026-09-09 JARVIS 제품 `90bf269`. SB 제품은 `3b2a08d`를 유지했다.

## 재현과 수정

범위 공급자에게 호출자의 동일한 Date 객체를 전달하므로, 공급자가 시각을 과거로 변경하면 만료된 범위를 다시 유효하게 판정할 수 있었다. 범위 만료10초 후가 아니라 발급 기준+11초에 호출하고 공급자가 기준 시각으로 되돌리는 회귀 검사를 추가했다. 수정 전에는 예외 없이 claim을 발급하여 **1 failed / 2 passed**를 확인했다.

호출 시각의 밀리초 값을 먼저 고정한다. 공급자에는 복사한 Date를 전달하고, 공급자 시각 또는 호출자 시각이 변경되면 발급을 거부한다. 키/fence 발급과 claim issued_at에는 고정한 시각을 사용한다. 정상 호출자의 Date는 변경하지 않는다.

## 검증

- 새 issuer와 기존 read-fence production 직렬 검사 **18 passed, 15.38초**.
- 변경 파일 ESLint, TypeScript 격리 emit(타입 검사 포함), diff 검사 통과.
- 수정 후 실제 JARVIS issuer → Python claim 검증 → CLI 봉인 페이지 분류를 다시 실행했다. `/var/tmp/page-access-acceptance-rynyerwr/access-claim-result.json`: production issuer true, 원본 요구2/record2, 서명 검증 통과, 변조 범위 거부.
- 초기 실패는 결함 재현 결과이며 통과 수치에 합산하지 않는다. SB 전체 회귀를 이번 실행으로 주장하지 않는다.

## 범위와 잔여 목표

범위 공급자는 신뢰된 내부 포트여야 하며 이번 검사는 실제 운영 사용자 인증을 입증하지 않는다. 실제 인수의 authority DB·키·범위는 격리 fixture이고 LLM은 fake다. 운영 scope resolver, 새 scoped MCP와 모든 읽기/쓰기/복원 표면, 원작업 계보·세션 사본 수명·실제 앱·여러 writer·검색/GUI/DR 목표는 유지한다. 시각 고정만으로 이 잔여 작업을 대체하지 않는다.

운영 배포·서비스 재시작·config/vault 수정·push는 수행하지 않았다.
