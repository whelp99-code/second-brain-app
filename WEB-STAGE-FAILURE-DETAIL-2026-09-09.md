# 배치 단계 예외 전달 및 장애 원인 정정

실행 ID별 `run_stage`를 확인했다. 최초 반환 ID `dcb54ef218284027911e12058bab0a93`와 재처리 ID `f8b1d66d6b064f7cb28bb891f10c6771`는 모두 compile의 `SecurityPolicyError: source web-inbox: LLM egress denied by source policy`였다. 최초 실행에는 별도로 brief의 모델 명령 부재 실패도 있었다.

따라서 이전 문서의 “실패는 compile이 아닌 brief” 및 “재처리가 brief 입력 보류 때문에 실패했다”는 추론을 정정한다. `/api/status`의 derivation 실패 목록은 단계 경계 예외를 모두 포함하지 않는다. `BRIEF_REPLAY_INPUTS_UNAVAILABLE`는 과거 brief를 명시적으로 재시도하는 ops 경로의 표시이며 이번 `/api/run` 실행을 차단한 원인이 아니다. 동일 키의 현재 브리핑은 pipeline에서 재개할 수 있다. 이전 증거 JSON은 당시 응답 그대로 보존한다.

제품 개선: `_run_locked`가 예외를 원장에 기록할 때 같은 상세를 `RunOutcome.failure`에도 보존한다. 웹 `/api/run`은 이를 `failure` 필드로 반환한다. 기존 normalize의 자격증명 정규식 마스킹을 재사용하고 1000자로 제한한다. 연락처 이메일·전화번호를 지우는 prompt 전용 마스킹과 구분했다. 웹 처리 결과 JSON에서 현재 실패 사유를 직접 확인할 수 있다.

검증: 실제 동일 임시 서버 재호출에서 `failure`에 원본 정책 거부가 반환됐다([증거](WEB-STAGE-FAILURE-DETAIL-2026-09-09.json)). 정책을 허용으로 바꾸거나 원장을 초기화하지 않았다. 단계 예외 반환 및 HTTP credential 마스킹 회귀를 추가했다. 상세 검사 수치는 최신 구현 원장에 기록한다.

원본 정책 거부가 정상적으로 유지됐으므로 해당 임시 입력의 검색 가능 상태를 주장하지 않는다. 정상 모델·명시적인 원본 정책으로 저장→처리→검색을 수행하는 별도 인수는 남는다. 운영 데이터와 정책은 변경하지 않았다.
