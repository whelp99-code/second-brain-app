# 범위 검사 읽기 표면의 일관성 — `sb_search`의 빠진 단정을 채웠다

인계서 M7("모든 지원 읽기 표면의 범위 일관성 확인 — 제목/snippet/score/원문/벡터/관계 조회에서 불허 정보 노출0")과 8-C 5번("불허 프로젝트 조회 거부")이다.

## 1. 범위 검사를 받는 읽기 표면은 정확히 4개다

`sb/mcp.py`의 scoped 등록부(1114–1118행) 기준으로 `scoped_read_page`, `scoped_search`, `scoped_generation_status`, `scoped_request_status` 넷이다.

기존 단정 커버리지를 실측한 결과:

| 표면 | 불허 프로젝트 claim 단정 | 근거 |
|---|---|---|
| `sb_read_page` | 있음 + 내용 누출 0 단정 | `tests/test_mcp_scoped.py`, `scripts/scoped-mcp-acceptance.py` |
| `sb_generation_status` | 있음 | `tests/test_scoped_status_mcp.py`(`change="project"`) |
| `sb_request_status` | 있음 | `tests/test_mcp_scoped_status.py`(`projects: ["project:other"]`) |
| **`sb_search`** | **없었음** | 잘못된 `limit`(요청 결합)만 단정 |

`sb_search`는 제목·snippet·score를 돌려주는 **최고 누출 위험 표면**인데 MCP 계층에서 범위 불일치 단정이 없었다. 라이브러리 계층(`tests/test_scoped_search.py`)은 필터링을 덮지만 서명된 claim이 실린 MCP 호출은 덮지 않는다.

## 2. 추가한 단정

`tests/test_mcp_scoped.py`에 불허 프로젝트와 잘못된 agent 신원 두 변형을 추가했다. 제품 코드는 바꾸지 않았다.

**음성 단정이 공허해지지 않게 만든 것이 핵심이다.** 처음에 `read_page`가 쓰는 sentinel `"Alpha fixture"`를 그대로 썼더니 9개 파라미터가 전부 실패했다 — search 응답에는 그 문자열이 없어서 "없음" 단정이 항상 참이 될 뻔했다. 그래서 **허용 호출이 실제로 돌려준 payload**(`searched.structured_content["results"]`)를 기준값으로 잡아, 구성상 공허할 수 없게 했다.

## 3. 관측 — 결함이 아니라 두 가지 정상 형태

단정을 확정하기 전에 실제 반환값을 먼저 관측했다. 관측된 동작에 맞춰 검사를 느슨하게 고치지 않기 위해서다.

| 변형 | `is_error` | payload |
|---|---|---|
| `projects: ["project:b"]` (불허 프로젝트) | `False` | **`results: []`** — 0건 |
| `agent_id: "agent:other"` (잘못된 신원) | `True` | `None` — 명시적 거부 |

이는 [클라이언트 지원 범위 문서](AGENT-SUPPORT-AND-ACCEPTANCE-GAPS-2026-09-10.md)가 명시한 계약 "허용되지 않은 프로젝트는 **결과0 또는 명시적 거부**"와 정확히 일치한다. 프로젝트 불일치는 검색이 볼 수 있는 집합을 0으로 좁히고, 신원 불일치는 호출 자체를 거부한다. **누출은 없다.**

정확히 적어 둘 점: 0건 응답에도 `generation_id`, `vault_head`, `vault_tree`, `tombstone_sequence` 같은 read-fence 결합 metadata는 실린다. 이는 권한 있는 `sb_generation_status`가 돌려주는 것과 같은 종류이며 사용자 내용이 아니다. 내용 누출로 집계하지 않는다.

따라서 확정한 단정은 계약의 **두 형태를 모두** 받아들이되 허용 payload는 절대 나오지 않아야 한다:

```python
assert denied_search.is_error or denied_search.structured_content["results"] == []
assert allowed_results not in str(denied_search)
```

## 4. 검증

- 범위 읽기 표면 슬라이스 `tests/test_mcp_scoped.py`, `test_mcp_scoped_status.py`, `test_scoped_status_mcp.py`, `test_scoped_search.py`, `test_memory_access.py` → **44 passed / 28.61초**.
- `ruff check --no-cache tests/test_mcp_scoped.py` exit 0.
- 단정이 실제로 동작을 가른다는 근거: 같은 호출에서 허용 claim은 결과 1건, 불허 프로젝트 claim은 0건이 관측됐다.
- `tests/`가 바뀌었으므로 전체 회귀를 다시 돌렸다: **1,793 passed / 2 skipped, 503.77초, exit 0**. 각주 수정(`110b474`) 때와 개수가 같은데, 이번 변경이 기존 파라미터 테스트 안에 단정을 더한 것이라 테스트 개수가 늘지 않는 것이 맞다.

## 5. 한계

- **운영 agent MCP에서는 이 거부를 보일 수 없다.** 그 표면(`sb mcp` 기본 등록)에는 범위 claim 자체가 없다. 구조적 사실이며 빠진 검사가 아니다. 운영 경로에서 확인 가능한 것은 vault 이탈 거부까지이고, 프로젝트 범위 거부는 scoped 경로의 성질이다. 8-C 5번의 "운영 절반"은 새 authority 활성화로 scoped 경로가 운영에 올라온 뒤에야 의미가 생긴다.
- M7이 언급한 **벡터·관계 조회**는 이 4개 표면에 포함되지 않는다. hybrid는 기본 비활성이고 관계 검색은 M14 보류 상태다. 그 두 경로의 범위 일관성은 채택 시점에 함께 봐야 한다.
- 신원·정책·clock은 이 테스트에서 fixture다.
