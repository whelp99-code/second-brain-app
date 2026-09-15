# SB 운영 전환 기록 — 2026-09-15 (JARVIS 미전환)

실행: Claude Fable 5.1, 사용자 승인. 2026-09-15T02:02:43.415353+00:00. 원본 `/var/tmp/claude-night-e53dd66-GBr0la/cutover-2026-09-15.json`, gates/.

- 릴리스: `~/.local/state/second-brain/app/releases/2ccf0267…` (source b9039d2, sb/ = 8d1f8cc 183파일 일치, wheel 60d66ad6…). 이전 current 41f0751 릴리스 디렉터리 보존.
- 사전 점검: pending 큐 비어 있음, active cursor 0, SB writer lock 미보유, DB 핸들은 jm-jarvis 유닛뿐, 백업 존재, 디스크 여유. 미해결 lease 1건은 실행 중인 jm-jarvis.service 소유(JARVIS 미전환이라 해당 없음).
- 백업: `second-brain-20260915T100736+0900.tar.gz` sha256 검증.
- 절차: SB 유닛만 정지 → current 원자 교체 → 유닛 재시작(web 200, apply-requests NO_PENDING_REQUEST) → 검색 `GENERATION_INDEX_INVALID` 발견(구 세대 search.db 스키마가 새 질의 계획 열 없음) → `doctor --rebuild-ledger`는 done→running 전이 오류로 실패(활성화 없음) → `jm-second-brain-refresh.service`(sb run)로 새 세대 `sbgen:v1:c58f6026…` 게시(3m40s) → 검색/web/doctor(ledger 5/5) 정상 → 타이머 재가동.
- 잔여: 구 릴리스 경로의 `sb mcp` 프로세스 18개(클라이언트 세션 재시작 시 교체), last_run `capped`(LLM 상한), doctor `scheduler-assets` warn, JARVIS는 a3cbbbe 그대로(scoped v4·postcompact consumer·N1 휴면).
- rollback: 링크를 41f0751로 되돌리고 web 재시작(구 릴리스는 전환 전 세대 febe7de2…를 읽음).
