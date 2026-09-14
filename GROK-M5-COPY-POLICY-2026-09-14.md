# M5 사본 정책 — 2026-09-14

상태: `blocked_external`. 빈 HOME에서 미검출 ≠ 미지원. 운영 `~/.claude`/`~/.codex` 실험 금지.

## SB가 만든 관리 사본 (정정·삭제 대상일 수 있음)

| 종류 | 위치 규칙 | 이번 재증명 |
|---|---|---|
| generation journal | `state_root/generation-journal.db` | 코드 존재. 운영 처분 없음 |
| WAL/SHM | generation sqlite 세트 | restore exclusive는 기존 격리. 운영 세트 손대지 않음 |
| compiled wiki | vault `wiki/` `.sb/compiled/` | A 테스트 8 passed |
| inbox staging | vault `inbox/` | ack는 dir_fd unlink. 운영 inbox 삭제 없음 |
| 후보 export | `/var/tmp/sb-candidate-*` | 운영 current 아님 |

## 클라이언트 소유 (손대지 않음)

Claude 세션 JSONL, Codex 세션, Orca 로그, 브라우저 프로필, 사용자 백업. 경로가 제품/버전 입력으로 오기 전 처분 구현을 운영에 적용하지 않는다.

## 한계

native session/compaction/log 수명은 제품별 경로 입력 후. 이번 라운드 구현 없음.
