# M9 세션 compaction — 16a5a18 후속 계약

## 지원하는 다음 요청

Claude 2.1.261 공개 계약: **UserPromptSubmit**만 additionalContext 주입이 문서화되어 있다. 이것은 **다음 사용자 prompt**이지 auto-compaction 직후 같은 turn의 다음 모델 요청이 아니다. 그 잔여는 남긴다. native 미실행.

PostCompact는 stage만 (`{}`). 파일 기록만으로 전달 성공을 반환하지 않는다.

## JARVIS 소비자

`JARVIS_MODEL_TRANSPORT_CMD` (+ JSON `JARVIS_MODEL_TRANSPORT_ARGS`)가 캡처 JSON을 stdin으로 받아 **exit 0**일 때만 accepted. `FileModelTransport`는 로그이며 accepted:false (`FILE_TRANSPORT_NOT_CONSUMER`).

## 이벤트 수명

digest = session_id + 제공된 모든 occurrence 필드(prompt_id·compaction_id·event_id·uuid) + summary. 같은 prompt_id에 compaction_id c1→c2는 새 compaction. 같은 전체 키 재전달은 중복.

## 출력 실패

UserPromptSubmit는 stdout flush 성공 후에만 delivered. BrokenPipe 후 재시도는 문맥을 다시 낸다. hook ACK 없음 → exactly-once 주장 안 함.
