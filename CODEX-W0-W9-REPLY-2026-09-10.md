# Codex 회신서 — W0–W9 수행 결과

대상: [후속 검토·지시서](CODEX-FOLLOWUP-REVIEW-2026-09-10.md) (`872bda7`). 작성 시점 HEAD **`ac9c429`**. 브랜치 `codex/shared-memory-completion-20260907`. 운영 `current`는 끝까지 **`41f0751`**. 원격 push 없음.

**메인 기억 저장소 완성·운영 전환·개발 완료가 아니다.**

## 시작·끝

지시서 커밋 `872bda7` → `ac9c429`. 제품 코드 변경은 대략 `d2c5e00`(W1), `46a3de6`(W2), `b95678c`(W6), 테스트 `859691d`. 나머지는 격리 게이트·런북·보고.

전체 회귀는 HEAD `859691d`에서 **1832 passed / 3 skipped**. 그 이후 검색 변경(`b95678c`)의 전체 회귀는 다시 안 돌렸다.

## 항목

| 항목 | 판정 | 증거 |
|---|---|---|
| W0 | 완료 | [W0-BASELINE](W0-BASELINE-2026-09-10.md). memory 모듈 **prefix 124 / 197**. 운영 세대는 스냅샷마다 바뀜 |
| W1 | 구현, 운영 미검증 | `sb/vault.py` marker 없는 compiled 페이지는 dest. 손편집은 `_proposed`. [W1](W1-COMPILED-MARKER-RECOVERY-2026-09-10.md) |
| W2 | 구현, 운영 미검증 | `state_root/revoked-jarvis-signing-key-ids`. config.toml 복원으로 옛 claim 부활 안 함. [W2](W2-REVOCATION-RESTORE-2026-09-10.md) |
| W3 | 격리 게이트 완료, 전환 아님 | 후보 `14a6ed7`(게이트)와 `0eefce7`(W6 포함). 유지보수·fixture·`--work` EXIT 0. JARVIS는 페어 `195b1a7` dist, **새 artifact 아님** |
| W4 | **미실행** | `drain_authorized=false`, GJC lease 1, jarvis/dashboard/phone-gateway active. 런북 [0eefce7](CUTOVER-RUNBOOK-0EEFCE7-2026-09-10.md) |
| W5 | 명시적 제한 | 빈 격리 HOME. 인증 복사 없음. M5 수명 미지원. [W5](W5-NATIVE-ISOLATION-2026-09-10.md) |
| W6 | 붙여쓰기만 | spacing 2/2, 15문 Recall 86.7%. 자연어/의역 0. `user_curated` 없음. [W6](W6-KOREAN-SPACING-2026-09-10.md) |
| W7 | 표본만 | `14a6ed7` 17,343파일 remember 21.54s. fsync 유지. timeout 미달. [W7](W7-WRITE-DELAY-14a6ed7-2026-09-10.md) |
| W8 | DR 표본 + HTTP | 격리 restore 17349파일. GUI HTTP 23 passed, 브라우저 없음 |
| W9 | 중간 보고 | [W9-STATUS](W9-STATUS-2026-09-10.md) |

## 가져갈 것 / 말 것

가져갈 것: 전환 목표는 `0eefce7` / wheel `dc705e8a…`. 비교 `14a6ed7`, `c04dee1`. 롤백 `41f0751`. 고아 `activated` 3행은 자동 정리가 아니다.

가져가지 말 것: 운영 전환을 했다, `0eefce7`이 `25d49b4`다, 빈 격리 프로필로 M5를 닫았다, 21s remember가 timeout 목표다, 전체 회귀가 `b95678c` 이후에도 돌았다.

운영 `current`를 바꾸려면 런북 허가와 새 JARVIS artifact가 먼저다.
