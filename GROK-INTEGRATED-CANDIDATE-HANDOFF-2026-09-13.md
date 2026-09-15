# 통합 고정 후보 — 4차 운영 전환 (2026-09-15 20:11 KST)

| 역할 | 값 |
|---|---|
| 제품 | `7cab61b` (H7) |
| 운영 SB current | `13688d66df6f85841d02082f39f56aa060743d3b` (20:11 KST 전환) |
| 이전 current | `62ffbc9d…` 보존 |
| wheel | `2163ec219c6b816c6c6a307f0596684668cd0254657b643d8411d086c8aa6dc1` |
| LLM | Grok (`~/.config/second-brain/llm/omo-grok.sh`, OmO xai/grok-4.6). Codex에서 교체 |

## readiness

- refresh `last_run` ok
- `/ready` = ready (reasons 없음)

H7: 오늘 brief 실패는 later-done·LLM unavailable 규칙으로 superseded되지 않음. 같은 키 재요청은 pending으로 재개.
