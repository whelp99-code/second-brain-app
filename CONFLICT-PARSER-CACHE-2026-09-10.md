# 실제 모델 판정과 이전 parser 캐시 분리

기준 제품 0a198f7. 테스트에서 만든 문장 두 개(파이썬 정적 타입/동적 타입)를 현재 충돌 프롬프트로 실제 Claude CLI에 전달했다. CliLLM→check→Ledger의 정상 경로를 사용했으며 도구 사용 없이 --no-session-persistence 옵션을 지정했다. 합성 source에만 llm_policy=allow를 지정했고 운영 source 정책을 바꾸지 않았다. 최초 시도는 기존 helper의 me-wiki origin과 기본 외부 전송 거부 정책으로 모델 호출 전에 차단됐다. 이를 실제 자료로 취급하거나 정책을 풀지 않고 합성 전용 source identity와 명시적 테스트 설정으로 실행했다.

모델은 contradicts/0.95, 한국어 rationale, c1/u1 인용을 반환했다. 새 JSON parser가 이를 수락해 failure=null, conflict PageSpec 생성까지 성공했다. [결과](NATIVE-CONFLICT-2026-09-10.json). 실제 vault wiki에 기록하거나 운영 기억으로 등록하지 않았으며 Ledger와 결과는 /var/tmp/sb-native-conflict-xei2jr1j에 격리했다. 실행 명령은 `TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python /var/tmp/sb-native-conflict-check.py`였다. 이 시험은 합성 모순 한 쌍의 실제 모델 응답이며 사용자 업무·검색 품질 전체나 모든 모델의 증거는 아니다.

추가 수정: 기존 conflict-inputs-v2 키를 유지하면 이전 정규식 parser가 잘못 읽어 완료 처리한 판정도 재사용된다. parser 변경의 영향을 받는 캐시를 conflict-inputs-v3로 분리했다. 기존 원장 행을 삭제하거나 운영 기억을 수정하지 않는다. 다음 정상 실행에서 입력이 다시 평가되고 새 캐시가 만들어진다. 이전 버전으로 완료한 판정→새 버전 실제 재호출→새 결과 재사용의 회귀를 추가했다. 기존에 생성된 conflict 페이지나 supersede 효과를 자동 되돌리는 변경은 아니다. 과거 영향 내용의 운영 정정은 별도 점검이 필요하다.

관련 conflict/fake update **24 passed / 3.78초**, Ruff 전체·diff 통과, conflict 타입0오류0경고. 전체 suite는 이번 변경 후 재실행하지 않았다. 실제 모델 시험은 cache 버전 변경 전 동일 JSON parser의 새 임시 원장에서 수행했으므로 cache 재사용 시험은 별도 회귀 결과로 구분한다. 전체 운영·JARVIS 복원/사용자 업무·DR 및 M1–M14는 미완료다. push 없음.
