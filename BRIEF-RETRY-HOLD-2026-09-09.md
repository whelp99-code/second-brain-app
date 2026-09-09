# 실행할 수 없는 브리핑 재큐잉 차단 — 2026-09-09

운영 retry helper는 실패 행을 pending으로 바꾸지만, 실제 brief stage는 오늘 날짜·현재 입력에서 key를 계산한다. 과거 key를 순회하거나 당시 입력을 복원하지 않는다. `requeued=N`이 출력되어도 해당 과거 작업이 실행되는 것을 보장하지 못했다.

`sb.ops.retry_failed`는 실제 선택 대상(limit 적용 후)에 brief가 있으면 BRIEF_REPLAY_INPUTS_UNAVAILABLE로 전체 선택을 거부한다. 어떤 작업의 상태나 시도 횟수도 바꾸기 전에 검사한다. stage를 생략한 mixed retry에도 적용된다. 실패 brief가 선택되지 않은 compile/conflict retry는 유지한다. 날짜를 복원할 입력이 없으므로 현재·과거 여부를 추측하지 않고 수동 brief 재큐잉 전체에 적용한다. 정상 brief 실행과 현재 키의 자체 재시도는 변경하지 않았다.

수정 전 회귀 검사 2개에서 잘못된 재큐잉을 재현했다. 수정 후 ops·CLI 전체 61 passed / 4.88s, Ruff 통과. 임시 vault를 사용한 별도 실제 CLI 프로세스에서도 exit 1, 명시적 보류 코드, requeued 성공 문구 없음, 기존 derivation 상태·시도 횟수 보존을 확인했다.

이는 과거 브리핑 복구 기능 완성이 아니라 부정확한 성공 표시와 실행되지 않는 pending 작업을 막는 보류다. 날짜/입력/권한을 고정한 재처리와 감사 가능한 역사적 실패 처리 정책이 필요하다. 운영 5건은 그대로 보존했고 운영 재시도·배포는 하지 않았다.
