# Phone HTTP 기억 조회 중 세션 만료 수정

2026-09-09. JARVIS 제품 `689114c`, SB 실제 HTTP 인수 `f32f032`.

## 재현한 문제와 수정

`phone-gateway-owner.ts`는 요청 시작 시 쿠키를 인증했지만 POST 본문 수신과 upstream 응답을 기다린 뒤에는 인증을 다시 검사하지 않았다. 실제 HTTP 통합 회귀에서 upstream 응답 직전 시험 시계를 16분 이동하면 세션이 만료되었는데도 private_memory 본문이 HTTP 200으로 반환됐다. 수정 전 기대 401/실제 200으로 1개 테스트가 실패했다.

기존 세션 저장소로 POST 본문 수신 후 proxy 호출 직전, proxy 응답 후 반환 직전에 쿠키·현재 owner·동일 세션 HMAC을 재검사한다. 실패하면 만료 쿠키와 `PHONE_SESSION_REQUIRED`/401을 반환하고 upstream 본문을 내보내지 않는다. 인증을 재발급하거나 만료 시간을 늘리지 않는다. 이 변경은 기존 읽기 proxy의 세션 경계 보강이며 새 인증/서명 체계나 계약 버전을 추가하지 않는다.

## 검증

- 관련 5파일 **58 passed / 1.20초**: phone gateway HTTP, memory adapter, phone session, gateway unit, memory session source.
- TypeScript noEmit 및 격리 emit 통과. 변경 TypeScript ESLint, JavaScript 구문, 양쪽 git diff 검사 통과.
- 격리 빌드 제품 서버에 실제 HTTP 요청: 세션 발급→기억 조회 200→응답 중 만료 401→같은 쿠키 재요청 401.
- 정상 응답에는 시험 기억 본문이 존재했고 만료 응답에는 없었다. 만료 쿠키 제거를 확인했다. upstream 조회는 정상 요청과 진행 중이던 요청의 2회뿐이며 거부 후 재요청은 추가 조회하지 않았다.
- 코드: [제품 수정](../Orca-JARVIS/src/phone-gateway-owner.ts), [회귀](../Orca-JARVIS/tests/integration/phone-gateway-memory-adapter.test.ts), [실제 HTTP 검사](scripts/phone-memory-expiry-acceptance.mjs). 결과는 [JSON](PHONE-MEMORY-HTTP-EXPIRY-2026-09-09.json).

재현:

```bash
TMPDIR=/var/tmp node scripts/phone-memory-expiry-acceptance.mjs "$(cat /var/tmp/cancellation-material-build-path.txt)"
```

marker는 이 머신의 격리 TypeScript 빌드이며 다른 환경에서는 해당 빌드 절대 경로를 전달한다. 최초 인수 도구에서 Node fetch로 fixture Host 헤더를 보내면 로그인 단계가 403이었다. 기존 HTTP 시험과 같은 undici request로 정확한 fixture Host를 전송해 통과했다. 제품 인증 조건을 완화하지 않았다.

## 범위와 보류

실제 루프백 HTTP 서버/쿠키 인증/프록시 경로를 실행했지만 Tailnet 헤더·시계·upstream 기억 본문은 fixture다. 실제 Tailnet 로그인, 실제 scoped MCP, 모델 주입, 운영 데이터 검증으로 해석하지 않는다. 시계를 이동한 테스트로 만료 경계를 검증했으며 실시간 16분을 기다린 시험은 아니다. 운영 서비스·설정·DB를 수정하거나 재시작하지 않았다.

응답 중 만료된 읽기는 upstream에서 이미 수행됐을 수 있다. 이번 수정은 그 응답이 사용자에게 전달되는 것을 차단한다. 중간 adapter의 bootstrap/대기 중 인증 검사와 upstream의 프로젝트 범위 검사는 실제 scoped 연결 때 함께 검증해야 한다. 이미 전달된 본문이나 모델 로그를 삭제하는 기능은 아니다.

공통 upstream CSRF를 에이전트 인증으로 취급하거나 임의 session/project 헤더를 신뢰하는 연결은 보류한다. 현재 gateway는 사용자 쿠키를 upstream에 전달하지 않으며 backend는 별도 프로세스다. 기존 인증과 정책을 유지하는 신뢰된 전달 경계 및 새 로그인 세션의 정책 배정이 M1의 남은 작업이다. scoped 쓰기→검증 결과→영수증→새 에이전트 재사용, 정책 rollback/삭제 수명, 클라이언트별 실제 검증 등 전체 목표를 유지한다.
