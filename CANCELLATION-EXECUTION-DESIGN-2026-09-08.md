# 접수된 취소의 명시적 실행

`sb apply-cancellation --intent-id ID`는 기존 원장에 접수된 정확한 의향 하나를 실행한다. 새 watcher/queue를 만들지 않고 기존 pending·generation writer 잠금과 처분 체크포인트를 재사용한다. 서명 결과까지 저장한 뒤 provider_local_suppressed를 반환하며 JARVIS cursor는 변경하지 않는다.

실행 중에는 현재 취소 목적 키·철회·provider 설정을 재검사한다. 접수 TTL은 durable accepted_at에서 검증하되 현재 목적 키 철회는 계속 적용한다. 결과 발급 전에도 현재 provider 서명키를 확인하며, 저장된 과거 결과는 별도의 신뢰 공개키 집합으로 검증한다. 서명키 교체 때문에 기존 결과를 재발급하지 않는다.

CLI에는 비밀키·본문·고정 시각을 인자로 받는 옵션을 만들지 않는다. 실제 검증은 격리된 설정/원장과 별도 프로세스에서 수행한다. 원래 요청 외부 전송 경합과 실제 로컬 억제/cursor, seq1→V2seq2는 후속 완료 조건으로 유지한다.
