# 최초 기억 세대 이전의 원장 상태 조회

새 `scoped-request-status-v1` 프로필은 `sb_request_status` 하나만 제공한다. 기존 read v1–v5의 세대 결합 계약은 유지한다. 기존 v5는 최초 세대가 없는 시험 구성에서 서버 생성 자체가 `MEMORY_SCOPED_CONFIG_INVALID`로 거절됨을 확인했다. 새 프로필은 같은 요청의 pending/failed와 원래 acceptance를 세대 없이 회수한다.

`sb/scoped_status_mcp.py`는 서버 고정 scoped policy와 기존 서명 access claim/read fence를 사용한다. 원래 전체 V4 요청·provider·사용자·프로젝트·세션·정책·현재 tombstone high-water를 대조한다. 조회 중 정책/키 철회, 서명 만료, 삭제 이력 변경 및 시각 역행은 반환 전에 거절한다. 원장은 maintenance_only로 열어 실행 claim·수락·재발행 없이 기존 조회를 재사용한다. 이 모드는 SQLite 읽기 전용 연결은 아니며 기존 schema 점검을 수행한다.

원장 파일이 없으면 조회 불가로 처리하고 새 저장소를 생성하지 않는다. 존재하는 정상 원장에서 요청이 없을 때만 not_found를 반환한다. found 상태는 원래 acceptance(replayed=true)를 포함하며 proved는 역사적 proof/receipt를 포함한다. 응답 최상위에는 generation_id/records가 없다. **현재 기억의 가용성이나 최종 작업 완료 증거로 사용할 수 없다.** not_found/failed/error만으로 소비된 dispatch를 재전송해서도 안 된다.

새 계약: `contracts/second-brain-scoped-status-v1.json`, SHA256 `973c4ed1d26a7b258e6b35c261c074666bebd54c5de354d89fb0b085414294cf`.

검증: 관련31개 통과(11.50초), 새 모듈 basedpyright 0오류/0경고, 전체 Ruff 통과. 별도 MCP stdio 프로세스를 두 번 시작해 최초 세대 없는 pending과 동일한 원래 수락을 회수하고 실제 tools/list 스키마를 고정 계약과 대조했다. 시험 권한·시계는 fixture다. 초기 실패2개는 기존 v5가 호출 단계가 아닌 생성 단계에서 거부하는 테스트 기대를 수정했고, 추가 실패1개는 FK가 있는 fixture 원장을 삭제하지 않고 별도 빈 원장을 만들어 수정했다. 제약 완화는 없다.

최종 전체 회귀: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py` → **1,354 passed, 2 skipped, 290.17초**. embeddings 선택 테스트는 제외했다. 관련31개는 전체 결과와 중복되므로 합산하지 않는다.

이번 단위는 provider 표면이다. 자비스에는 새 프로필의 전송 선택·응답 binding 소비·현재 인증 발급과 복구 workflow 연결이 아직 필요하다. 기존 parseSecondBrainRecoveredRequestStatus는 역사적 내부 상태 검증에 재사용할 수 있지만, generation binding을 필수로 하는 기존 scoped read 소비자를 단순 완화하지 않는다. 후속 인수는 실제 JARVIS transport→새 MCP 프로필로 최초 pending/failed/응답 유실 복구이며, 실제 A→B 운영 및 M1–M14 전체 목표를 유지한다. 운영 설정/서비스/DB는 변경하지 않았다.
