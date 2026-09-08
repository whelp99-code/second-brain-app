# 영속 제출 기록의 인증 범위 결합

2026-09-09. JARVIS `121d06b`, SB 인수 `57f88c1`. [실측 JSON](SCOPED-DURABLE-DELIVERY-2026-09-09.json).

기존 제출 원장은 generation/privacy에는 결합됐지만 인증된 접근 범위는 결합하지 않았다. 새로운 scoped reader를 만들면 이전과 다른 인증 세션에서도 같은 native 세션에 epoch만 바꿔 제출할 수 있었다. 수정 전 회귀에서 거부를 기대한 콜백이 실제 실행됐다.

기존 reader 옵션에 신뢰된 delivery_binding을 추가하고 scoped factory는 초기 인증 범위 식별값을 전달한다. 기존 원장의 binding HMAC에 이 값이 함께 들어가므로 같은 native 세션의 접근 범위가 바뀌면 기존 session/attempt를 무효화하고 전송을 거부한다. scope 식별값에는 provider/principal/agent/session/projects/policy/key/삭제 이력이 들어 있다. 원장에는 기존 HMAC만 저장하며 원문 범위나 쿠키를 저장하지 않는다. migration·별도 DB·새 서명 체계를 추가하지 않았다. 옵션이 없는 일반 reader의 기존 binding bytes는 유지한다.

검증:

- 수정 전 회귀 1 failed. 수정 후 scoped/reference deliveries/submit **35 passed / 3 files / 24.26초**.
- 인증 세션 변경 후 새 reader + 같은 native session + 새 epoch 제출을 콜백 전에 거부했다. 기존 중복/uncertain/무효화/개인정보/만료 회귀도 통과했다.
- TypeScript 격리 emit·변경 파일 ESLint·diff 통과.
- 실제 MCP record 2개/4,412바이트를 `submitInSession`으로 전달하고 원장 binding_key가 실제 인증 범위·세대·privacy의 HMAC과 일치하는지 대조했다.
- 새 제품 reader를 구성하여 재조회한 뒤 동일 native session/epoch로 제출하면 `MEMORY_REFERENCE_ALREADY_SUBMITTED`로 거부됐다. 원장 dump에 원문 payload나 인증 세션 문자열이 없는 것도 확인했다.

실제 결과: `/var/tmp/page-access-acceptance-8kaockvk/scoped-mcp-result.json`. 테스트 owner/key·합성 원본·fake compiler·고정 시각 및 fixture native session/epoch를 사용했다. 실제 모델/native client가 발급한 epoch 관측이나 그 로그의 삭제를 검증한 것은 아니다.

기존 일반 binding으로 기록한 native 세션을 scoped binding으로 재사용하면 불일치로 무효화된다. 지원되는 새 native 세션에서 시작해야 하며 이 검사를 완화하지 않는다. 원장 무효화는 모델 로그·compaction·백업의 본문 삭제 증거가 아니다. HTTP 인증 전달·정책 배정, 실제 native 세션 수명, scoped 쓰기/resolve/복구 및 전체 운영 인수는 계속 남는다. 운영 배포·DB 변경을 수행하지 않았다.
