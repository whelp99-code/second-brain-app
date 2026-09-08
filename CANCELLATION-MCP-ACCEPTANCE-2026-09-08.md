# 취소 상태 MCP·자비스 전송·결과 검증 인수

제품: Second Brain `df9412c`, JARVIS `1598762`.
[프로필 설계](MCP-CANCELLATION-PROFILE-2026-09-08.md), [실제 프로세스 결과](CANCELLATION-MCP-ACCEPTANCE-2026-09-08.json).

## 구현

- 명시적 `SB_MCP_CONTRACT_PROFILE=cancellation-schema6`에서 `sb_cancellation_status(intent_id, intent_digest, read_fence)`를 노출한다. 새 프로필은 도구 10개와 remember V3를 포함한다. 기존 schema3/4/5의 도구·파일 bytes·기본 선택은 유지했다.
- 새 도구는 기존 읽기 전용 cancellation_status 경계로 직접 위임한다. 세대 유지보수·pin·취소 실행·결과 발급을 호출하지 않는다. 현재 status fence, 정확한 요청 식별자와 삭제 이력, 저장된 결과를 검증한다. not_found에도 fence가 필요하다.
- `provider_result_public_keys`와 `revoked_provider_result_key_ids`를 Config에 추가했다. 개인키에서 공개키를 자동 추출하지 않는다. 키 설정은 서버 인스턴스 생성 시 고정되는 기존 운영 방식이며 hot reload를 구현한 것은 아니다.
- JARVIS는 `contractProfile: "cancellation-schema6"` 또는 `JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=cancellation-schema6`를 명시해야 새 메서드를 호출한다. 구 프로필에서 호출하면 프로세스 생성 전에 거부한다. 기존 기본은 task32-schema4다.
- JARVIS `requireCorrectionCancellationStatus`는 응답 형태·provider·intent ID/digest·기대하는 현재 삭제 이력·접수 시각을 검사한다. 완료 상태는 기존 결과 verifier로 서명과 원본 요청/대상 결합을 검증하고, 철회된 결과 키를 제외한다. pending/not_found에 완료 영수증을 붙이거나 generation_active를 완료로 내보내는 응답을 거부한다.

새 계약 `contracts/second-brain-mcp-v4.json`의 schema_version은 6이며 SHA-256은 `8be1ca195f60cb73f05c989d3d5f3e62053020988ccd8bb028cd4d8b442063b4`다. 두 저장소의 artifact와 sidecar bytes가 일치한다. artifact의 implementation_commit은 고정된 진입 기준 `6da593e8306fc3de23a3342fe6d1480753d2ed4d`이며 현재 기능 커밋을 자기 참조하지 않는다.

## 자동 검증

- Python 전체: **1,069 passed, 2 skipped, 188.63초**. 제품 최종 코드 기준이며 이후 추가한 테스트 2개는 이 수치에 포함하지 않는다.
- 추가 테스트 포함 마지막 프로필/호환 검사: **16 passed, 5.32초**. schema6 generation status의 기능·계약 해시 광고, 실제 V3 접수·재생을 확인했다.
- 앞선 Python 관련 검사: 30 passed, 13.14초. 새 조회와 기존 상태·프로필 회귀를 포함한다. 전체와 합산하지 않는다.
- Python `ruff check sb tests scripts/cancellation-mcp-acceptance.py` 통과, 변경 제품 3개 파일 basedpyright **0 errors, 0 warnings**.
- JARVIS 관련 7개 파일 **78 tests passed, 4.12초**. 추가 전송 계층/adapter 9개 파일 **71 tests passed, 5.81초**. 중복이 있어 합산하지 않는다.
- JARVIS backend tsc, 변경 파일 ESLint, 별도 경로 TypeScript emit 통과. 운영 dist를 덮어쓰지 않았다.

첫 artifact 재현 검사에서 새 파일과 기존 파일의 마지막 줄바꿈 방식 차이를 확인했다. 기존 exporter의 canonical bytes 방식을 재사용하고 새 artifact·양쪽 pin을 함께 갱신했다. 기존 파일 해시나 schema 검사를 완화하지 않았다.

## 실제 연결 인수

재현 명령: `TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-mcp-acceptance.py <격리 JARVIS tsc 출력 경로>`.

실측 build: `/var/tmp/jarvis-cancellation-mcp-build-t21m966d`. 결과: `/var/tmp/cancellation-mcp-acceptance-or7pw1il/result.json`.

실제 임시 provider에 취소를 접수한 뒤 자비스 Node transport가 Python MCP를 직접 실행했다. 접수 중 조회는 Node PID 4122221과 MCP PID 4122245/4122362, 실제 취소 처리 이후 완료 조회는 Node PID 4122542와 MCP PID 4122574/4122681이다. 각 단계에서 MCP를 재시작하여 같은 결과가 나오는지 비교했다.

- pending은 suppression_pending, 완료는 provider_local_suppressed로 구분됐다.
- 완료 응답을 자비스 의미 검증기에 넣었고, 실제 provider가 저장한 결과와 정확히 일치했다.
- 각 단계의 잘못된 권한은 TOMBSTONE_FENCE_REQUIRED, 존재하지 않는 정확한 형식의 ID는 not_found였다.
- MCP 설정에는 provider 개인키가 없었다. 각 조회 구간 전후 journal 전체 SQL dump가 같았다.
- 실제 transport의 tools/list 계약 검사를 통과한 연결이다. 두 개의 가짜 클라이언트를 실제 앱으로 계산한 결과가 아니다.

## 남은 P0와 보류

조회는 연결됐다. 다음은 **자비스 DB snapshot에서 미전송 의향 생성 → provider 접수/전송 경합 → 실제 로컬 억제 증거와 exact 결과의 cursor 완료 → 취소 seq1 이후 정상 V2 seq2**다. 외부 취소 실행 요청 경로는 아직 연결하지 않았다. 라이브러리 함수를 호출자가 성공했다고 주장하는 것으로 실제 DB 검증을 대체하지 않는다.

이번 결과는 provider_local_suppression 범위다. native 세션·SQLite WAL·백업 등 모든 외부 사본 삭제 증거로 확대하지 않는다. 자동 route·lane 건너뛰기·collector 확대는 관련 증거 전까지 보류한다. 사용자/프로젝트 범위, 원작업 계보, 실제 앱 수집·주입, 한국어 검색 평가, GUI·운영·복구의 전체 목표는 계속 남는다. 운영 설정 변경·서비스 재시작·배포·push는 하지 않았다.
