# 취소 상태의 읽기 전용 조회·공개키 검증 인수

제품 커밋: `6da593e`. [설계](CANCELLATION-STATUS-DESIGN-2026-09-08.md), [실제 프로세스 결과](CANCELLATION-STATUS-ACCEPTANCE-2026-09-08.json).

## 구현과 효과

`sb/cancellation_status.py:read_cancellation_status`는 기존 journal을 `mode=ro`와 query_only로 열고 같은 transaction의 삭제 이력과 현재 status fence를 검증한다. 정확한 intent ID/digest, provider, 접수 시각, intent 본문 digest, 삭제 chain 포함 여부를 대조한다. 결과가 없으면 suppression_pending이며 내부 generation_active를 최종 완료로 바꾸지 않는다.

저장 결과는 기존 verifier와 별도의 신뢰 공개키 집합으로 검증한다. 결과 digest·접수 시각·intent binding을 확인하고 그대로 반환한다. 개인키나 issuer/executor를 받지 않고 결과를 새로 서명하지 않는다. 허용된 과거 공개키를 유지하면 키 교체 후 조회가 가능하며 철회된 공개키는 제외한다. 현재 reader 키 집합은 호출자가 현재 권한에서 공급해야 한다.

원장이 없으면 생성하지 않고 CANCELLATION_STATUS_UNAVAILABLE을 반환한다. genesis와 not_found에도 status fence를 요구한다. 변조된 저장 JSON·시각·digest와 잘못된 식별자, 만료/누락/잘못된 목적의 fence는 결과를 반환하지 않는다. 응답의 삭제 이력은 조회 스냅샷이고, 중첩된 결과의 삭제 이력은 과거 완료 시점이다.

추가 검토에서 원장의 삭제 이력만 제거하고 결과를 남긴 손상 상태가 완료로 반환되는 사례를 재현했다(신규 검사 DID NOT RAISE). 의향의 삭제 sequence/root가 검증된 현재 chain에 포함되는지 검사하여 거부하도록 수정했다. 실제 사용자의 원장을 변경한 테스트가 아니라 임시 원장의 불변 trigger를 제거한 손상 주입이다.

## 검증

- 기본 전체: `TMPDIR=/var/tmp .venv/bin/pytest -q --ignore=tests/test_embeddings.py` → **1,061 passed, 2 skipped, 185.01초**. 마지막 삭제 chain 포함 검사 추가 전 실행이다.
- 최종 관련: `tests/test_cancellation_status.py`, `tests/test_cancellation_result.py`, `tests/test_mcp_profile_compatibility.py`, `tests/integration/test_walking_skeleton.py` → **40 passed, 21.34초**. 신규 16개와 기존 24개를 포함한다. 전체 수치에 합산하지 않는다.
- `ruff check sb tests scripts/cancellation-status-acceptance.py` 통과. `basedpyright sb/cancellation_status.py` **0 errors, 0 warnings**.
- 별도 작성자가 조회 중 실제 취소 완료를 시도하는 동시성 검사에서 첫 조회는 일관된 pending, 조회 잠금 해제 이후 다음 조회는 완료 결과다. 최초 테스트가 같은 스레드에서 읽기 잠금을 잡은 채 작성 완료를 기다려 database is locked를 유발한 구성 문제는 별도 작성자와 event barrier로 교체했다. DB 모드를 WAL로 바꾸거나 잠금 검사를 완화하지 않았다.

## 실제 프로세스 인수

재현: `TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-status-acceptance.py`.

실제 임시 provider의 취소를 접수·처리·서명·저장한 뒤 작성자를 종료했다. 부모 PID 4069817이 별도 Python 프로세스 4070200/4070216/4070225/4070233에 공개키·현재 fence·정확한 ID만 전달했다. 앞의 두 조회는 동일 canonical 결과를 반환했고, 키 철회는 MEMORY_CANCELLATION_RESULT_INVALID, 권한 누락은 TOMBSTONE_FENCE_REQUIRED로 거부했다. 조회 전후 journal 전체 SQL dump가 같았다. 읽는 프로세스에 개인키는 전달하지 않았다.

최종 원본 결과: `/var/tmp/cancellation-status-acceptance-tl_6v0n0/result.json`. 실측 결과 사본은 위 JSON 링크에 보존했다. 서버 프로세스/원장/암호 검증의 실제 인수이며 MCP·Node/JARVIS 앱의 전체 인수로 확대하지 않는다.

## 다음 구현과 보류

1. 새 명시적 MCP 프로필과 sb_cancellation_status 도구, provider 공개키/철회 설정을 연결한다. 기존 schema3/4/5 bytes·해시·기본 프로필은 유지한다.
2. JARVIS의 frozen 도구/응답 계약·transport·키 정책을 함께 갱신하고 실제 stdio→Node 조회를 인수한다.
3. 실제 DB snapshot의 취소 의향 생성·전송 경합, 정확한 결과와 로컬 억제 증거의 cursor 완료, seq1 취소→정상 V2 seq2 순환을 완성한다.
4. native 사본 수명, 사용자/프로젝트 범위, 원작업 계보, 실제 앱 수집/주입, 검색 평가, GUI·운영·복구 목표는 계속 남는다.

자동 취소 route와 lane 건너뛰기는 활성화하지 않았다. 결과는 provider_local_suppression이며 모든 native 사본 삭제 증거가 아니다. 현재 조회는 원장 전체 삭제 chain을 검증하고 읽기 transaction 동안 작성 완료를 잠시 지연할 수 있다. 대규모 원장의 조회 비용은 후속 용량 인수 대상이다. 운영 변경·push는 하지 않았다.
