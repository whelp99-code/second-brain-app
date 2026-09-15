# 통합 고정 후보 — held H1–H4 (2026-09-15)

운영 current는 그대로 `2ccf0267…` (제품 `8d1f8cc`). 이 후보는 보류 분기 재개 소스이며 **전환하지 않음**. push 없음.

| 역할 | 값 |
|---|---|
| 제품 소스 | `83a7aba` (H2 `0f0dd84` stage O_NOFOLLOW 포함) |
| 격리 후보 | `/var/tmp/sb-candidate-83a7aba/releases/8ea65a7d968fdcf99560f449b2a1ad656a99a2e9` |
| wheel | `6bc94e226c0158ab2ee517a344efc3d0c07faddcf75eb27868dafd46d1f965ba` |
| 운영 SB current | `2ccf0267…` 불변 |
| JARVIS authority | `a3cbbbe` 미전환 |

## 분기 커밋

| | 커밋 | 실측 |
|---|---|---|
| H1 | `e929774` | pytest 18 passed (open MCP revoke + old config + rollback allowed=false) |
| H2 | `0f0dd84` | pytest 53 passed (stage/revoke symlink·FIFO·dir·dangling) |
| H3 | `758f862` | pytest 3 passed (writer BUSY + forget-last empty) |
| H4 | `83a7aba` | pytest 2 passed (post-forget restore empty after reindex) |
