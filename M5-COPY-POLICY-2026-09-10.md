# M5 사본 정책 — 준비 초안

기준: [인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) §3·5.3, [native 사본 목록](NATIVE-COPY-INVENTORY-2026-09-10.md). 운영 기억과 사용자 클라이언트 기록을 **지우지 않는다.**

## 관측의 한계

지정 문자열·경로·SQLite 조회에서 Codex 사본 0건은 보존한다. 그 한 번의 `codex exec` 관측으로 다음을 완료 처리하지 않는다.

- 모든 `codex exec`가 전사본을 남기지 않는다
- provider 삭제만으로 처분이 끝난다
- M5 전체

버전·설정·실행 옵션(`exec` vs 대화형)·저장 위치·로그·압축/요약 형식마다 별도 확인이 필요하다. Claude 재개 결과는 provider 삭제 **전** 실험이다.

## 처분 범위 초안 (결정 전)

세컨드브레인은 vault 유일 작성자 경계를 지킨다. 클라이언트 홈 디렉터리는 다른 제품의 자료다.

| 사본 종류 | SB가 직접 지울 수 있는가 | 준비 작업 |
|---|---|---|
| provider vault / 세대 / search.db | 예, 기존 삭제·tombstone 경로 | 격리에서 삭제 후 재색인·복원 재현 |
| Claude Code `~/.claude` 세션 jsonl | 아니오. 정책·사용자 승인 없이 금지 | 제품별 “삭제 후 --resume” 시나리오를 격리 계정/임시 `HOME`에서 먼저 |
| Codex `~/.codex` | 이번 주사 0. 없다고 단정하지 않음 | 대화형 세션, 다른 모델, 로그/sqlite, archived_sessions를 재주사 |
| OMO/GJC/OpenCode/Cursor | 미측정 | [지원 갭](AGENT-SUPPORT-AND-ACCEPTANCE-GAPS-2026-09-10.md) 표에 제품·버전·경로를 채운 뒤 주사 |
| WAL/compaction/요약 | 이번 평문+컬럼 주사에서 추가 히트 없음 | 형식별 별도 확인. 없다고 쓰지 않음 |
| 운영 백업 tarball / JARVIS sqlite 백업 | 기존 retention. 삭제가 백업 재유입으로 부활하지 않는지는 P1 | 관리형 백업 처분은 운영 삭제 승인 후 |

## 격리 인수 순서 (운영 삭제보다 앞)

1. 임시 `HOME` + 임시 vault에서 실제 클라이언트 바이너리로 기억 한 건을 저장한다.
2. 그 환경에서 사본 목록을 제품별로 고정한다(경로, 파일, sqlite, 로그).
3. provider 삭제 후 새 세션 조회 0, `--resume`/요약/재색인에서 부활 여부를 기록한다.
4. 설정 복원·백업 복원이 사본을 되살리는지 본다. M3와 교차하면 교차점만 인용하고 요구를 약화하지 않는다.
5. 통과한 절차만 운영 삭제 체크리스트에 올린다.

운영 vault나 `~/.claude`를 이 순서의 실험장으로 쓰지 않는다.

## 격리 고정 (관리 대상이 아닌 클라이언트 사본)

`tests/test_managed_copy_disposal.py::test_forget_does_not_dispose_unmanaged_client_session_copy`: forget이 관리형 backup/export는 처분해도 `client-home/.claude/.../session.jsonl` 바이트는 그대로다. 실제 Claude 바이너리 `--resume`이 아니다. 운영 `~/.claude`를 쓰지 않았다.

## 완료 증거 (아직 없음)

사본 종류마다: 삭제 전 목록, 처분 행위, 삭제 후 재개/복원/재색인에서 내용 0. Codex 0건 한 줄은 이 표를 채우지 않는다.
