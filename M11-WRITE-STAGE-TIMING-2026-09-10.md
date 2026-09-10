# M11 쓰기 단계 시간·영수증·재시도 — 격리 측정

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.4. 설치 후보 `c04dee1a11ff0833b634c30796924d1ea19f8a6a`의 `bin/sb`만 사용했다. 운영 `current`·DB·서비스는 건드리지 않았다. 총 wall time 두 점이 모든 규모에서 선형이라고 보지 않는다.

원본 출력: [JSON](M11-WRITE-STAGE-TIMING-2026-09-10.json), 실행 디렉터리 `/var/tmp/sb-m11-stages`. 기존 [총소요](WRITE-COST-AND-INTERRUPT-2026-09-10.md)를 단계로 나눈 것이다.

## 1. 단계 시간

프로파일은 `cProfile` 누적 시간이다. 프로세스 기동은 wall에만 들어 있다.

| 단계 (`generations.py` 등) | 운영 규모 복사 17,343파일 / 36.53MB | 새 `sb init` 31파일 / 0.03MB |
|---|---:|---:|
| `remember` wall | 21.36s | 0.70s |
| `remember` 프로파일 | 20.94s | 0.29s |
| `GenerationStore.build` | 19.44s | 0.18s |
| `_fsync_tree` | **15.35s** | 0.010s |
| `_copy_allowed` | 1.67s | (프로파일 상위 밖) |
| `activate` | 1.48s (2회) | 0.021s |
| `_complete_disposal` | 1.44s | 0.002s |
| `_build_derived_stores` | 0.063s | 0.056s |
| `copy_operational_ledger` | 0.017s | 0.000s |
| `publish_inbox` | 0.0006s | 0.0008s |

운영 규모에서 쓰기 비용의 대부분은 inbox 게시나 ledger 복사가 아니라 **세대 트리 fsync**다. 파일 수 비율은 약 560배, `_fsync_tree`는 약 1,490배, 프로파일 `remember`는 약 72배다. 항이 같지 않으므로 이 두 점만으로 모든 규모 선형을 말하지 않는다. `_build_derived_stores`는 두 규모에서 거의 같다(~0.06s).

## 2. 완료 영수증·조회

`sb remember`의 완료 출력은 inbox 상대 경로다. 운영 규모에서 `inbox/2026-09-10T113146375014-m11-stage-probe.md`, exit 0.

같은 바늘로 `sb search --json --limit 5`는 **ingest 전 0.266s `[]`**, ingest 후 0.265s `[]`. 활성 세대 CAS `raw/`와 `ledger.db`에는 바늘이 있고 inbox는 ingest 후 비어 있다. 이 실험의 `llm_policy=deny` 설정에서는 remember 직후 검색이 완료 영수증이 아니다.

`sb status` 0.258s, ingest 후 `ok pages=2 conflicts=0 errors=0`. 페이지 2는 이번 바늘의 검색 히트가 아니다.

클라이언트 MCP 타임아웃은 이번 실행에서 재측정하지 않았다. 앞선 운영 규모 쓰기 18–22s와 Codex가 약 26s에 실패를 받은 관측은 그대로 둔다. 검색/status 0.26s는 그 한도와 겹치지 않는다.

## 3. 같은 바이트 재시도

두 번째 `remember` 동일 본문: 18.11s, 다른 inbox 경로, exit 0. 이어서 `ingest` 20.20s exit 0. 원장 `source_item` 19, `unit` 17.

이전 실험의 같은 랩 기준(재시도 전 `source_item` 17 / `unit` 16)과 맞으면 출처 행 +2, unit +1이다. **같은 바이트 재시도는 지식을 한 unit으로 합친다.** 세대 복사 비용은 재시도마다 다시 낸다.

## 4. 한계

- 동시 MCP 조회/정정, p50/p95 반복, 권한 불변은 이 실행에 없다.
- 운영 `activated` 3행 원인은 여전히 열린 항목이다.
- 중간 규모 단계 프로파일은 다시 찍지 않았다. 총 wall만 [쓰기 비용](WRITE-COST-AND-INTERRUPT-2026-09-10.md)에 있다.

M11을 완료 처리하지 않는다.
