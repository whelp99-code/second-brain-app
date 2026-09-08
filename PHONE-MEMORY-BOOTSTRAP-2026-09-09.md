# 기억 HTTP 연결 준비 중 인증 재검사

2026-09-09. JARVIS `de08adb`, SB 인수 `578bdc1`.

이전 응답 반환 직전 재검사만으로는 adapter 내부의 비동기 upstream 세션 준비 뒤에 시작하는 조회를 막지 못했다. HTTP 회귀에서 정상 조회 후 upstream CSRF를 회전시키고 다음 bootstrap 응답 때 시험 시계를 16분 이동했다. 응답은 이미 401로 차단되지만 upstream 기억 요청 수는 기대 2회에서 실제 3회로 늘어 수정 전 1개 테스트가 실패했다.

제품의 내부 AdapterProxy에 필수 요청별 isAuthenticated 콜백을 추가했다. 게이트웨이가 기존 세션 저장소와 현재 owner/동일 세션 HMAC을 확인하는 콜백을 전달하며 adapter는 bootstrap await 직후, 읽기 시작 전에 실행한다. 실패는 unauthenticated 결과로 전달하고 HTTP 계층에서 401과 만료 쿠키를 반환한다. 문자열 헤더나 사용자 supplied project/session을 신뢰하지 않는다. 외부 MCP/API 스키마는 변경하지 않았다.

같은 await 구간에서 여러 요청이 기존 동시성 검사를 함께 통과할 수 있어 전송 직전에 상한을 재검사한다. 9개 요청이 하나의 bootstrap을 공유하고 응답을 보류하는 결정적 시험에서 8개만 전송되고 나머지 1개는 unavailable로 반환됨을 확인했다. 타이머 sleep을 사용하지 않았다.

검증:

- 수정 전 HTTP 회귀 1 failed: 만료 후 불필요한 기억 요청 1회가 시작됨.
- 수정 후 관련 **60 passed / 6 files / 1.38초**.
- TypeScript 격리 emit, 후속 noEmit, 변경 파일 ESLint 및 diff 검사 통과.
- 격리 빌드 실제 HTTP bootstrap 시나리오: 정상 200, 만료 401, 재요청 401, 만료 구간 추가 기억 요청 **0회**. 정상 본문 조회는 1회이며 CSRF 회전 확인 요청은 별도의 거부 요청이다.
- 기존 응답 중 만료 시나리오 재실행: 정상 200, 만료 401, 재요청 401. 이미 시작한 기억 요청 1회는 존재하지만 본문 반환은 차단됐다.

실행 명령:

```bash
TMPDIR=/var/tmp node scripts/phone-memory-expiry-acceptance.mjs "$(cat /var/tmp/cancellation-material-build-path.txt)" bootstrap
TMPDIR=/var/tmp node scripts/phone-memory-expiry-acceptance.mjs "$(cat /var/tmp/cancellation-material-build-path.txt)"
```

실제 컴파일된 게이트웨이/루프백 HTTP를 사용하되 Tailnet 헤더·upstream 본문·시각은 fixture다. 운영 Tailnet 로그인이나 scoped MCP에 연결된 기억 인수는 아니다. 운영 서비스·설정·DB·배포를 변경하지 않았다.

남은 핵심: 실제 인증 세션과 프로젝트 정책을 backend까지 신뢰된 경계로 연결하고, scoped 조회→검증된 작업 결과 저장→영수증→새 에이전트 세션 재사용을 입증해야 한다. 현재 별도 프로세스인 gateway/backend 사이의 공통 CSRF를 인증 신원으로 승격하는 방식은 계속 보류한다. 모델 세션 삭제·정정, 정책 rollback, 다중 writer/복구와 전체 M1~M14 목표를 유지한다.
