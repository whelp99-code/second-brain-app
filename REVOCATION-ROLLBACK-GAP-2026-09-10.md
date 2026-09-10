# 철회는 백업 복원을 견디지 못한다 — M3의 남은 조건

인계서 M3은 "정책 revision/기발급 claim/백업 rollback의 전체 수명 검증 — 발급 뒤 철회·열린 연결·**과거 설정 복구에도 과거 권한으로 읽지 못함**"을 요구한다. 이 조건이 현재 만족되지 않으며, 원인이 구조적으로 특정된다.

## 1. 이미 만족된 부분

| M3 조항 | 상태 | 근거 |
|---|---|---|
| 기발급 claim이 policy revision 상승을 넘지 못함 | 충족 | `scripts/scoped-mcp-acceptance.py` — `policy:1`→`policy:changed`로 바꾸면 같은 claim이 거부되고 내용 누출 0 |
| 발급 뒤 철회 | 충족 | `revoked_jarvis_signing_key_ids` 추가 시 거부, 내용 누출 0 (`tests/test_mcp_scoped.py`, `tests/test_scoped_read_policy.py`, `tests/test_scoped_status_mcp.py`) |
| 응답 도중/열린 연결에서의 철회 | 충족 | 읽기 중 철회·만료 주입 시 거부([정책 경합](RESTORE-POLICY-RACE-2026-09-10.md)에서 provider가 bytes를 돌려준 직후 철회해도 `MEMORY_ACCESS_SCOPE_UNAVAILABLE`) |
| 설정 파손·부재 | 충족 | 잘못된 TOML·파일 삭제 모두 거부 |

## 2. 만족되지 않은 부분 — 과거 설정 복구

`tests/test_scoped_read_policy.py`의 마지막 두 줄이 현재 동작을 문자 그대로 말한다.

```python
path.write_text(original)
assert current_scoped_policy(config, initial) == initial
```

철회를 넣었던 설정을 **철회 이전 원본으로 되돌리면 정책이 완전히 동일하게 복귀한다.** `scripts/scoped-mcp-acceptance.py`도 같다 — `config.write_text(original)` 뒤 같은 claim의 조회가 성공하고 결과가 이전과 바이트 단위로 일치한다.

즉 **키 철회는 백업 복원으로 되돌아간다.** 과거 설정 파일을 복구하면 과거 권한이 다시 산다.

## 3. 원인 — 삭제와 철회의 비대칭

두 수명이 구조적으로 다르다.

| | 저장 방식 | 복원 후 |
|---|---|---|
| **삭제** | `tombstone_sequence` / `tombstone_set_root`가 **세대 manifest의 1급 필드**로 세대마다 승계된다 | **살아남는다.** 복원이 high-water를 이어받아 삭제 기억이 부활하지 않음을 실측했다([삭제 수명](DELETION-LIFECYCLE-2026-09-10.md): 복원 후 `seq 1` 유지, 재삭제 `seq 2`, 재복원 뒤에도 조회 0건) |
| **철회** | `revoked_jarvis_signing_key_ids`는 **설정 파일의 평범한 상태**다 | **되돌아간다.** `sb/` 전체에 철회용 sequence·high-water에 해당하는 것이 없다(`grep`으로 확인; `time.monotonic` 용례만 나온다) |

삭제는 되돌릴 수 없게 설계됐고 철회는 그렇지 않다. M3이 요구하는 것은 철회도 삭제와 같은 성질을 갖는 것이다.

## 4. 왜 이번에 고치지 않았는가

철회에 단조 high-water를 도입하는 것은 **새 권한 machinery를 추가하는 설계 변경**이고, 인계서 4절이 근거 없는 authority machinery 추가를 금지한다. 게다가 부작용이 가볍지 않다.

- 철회가 되돌릴 수 없게 되면 **잘못된 철회도 영구**가 된다. 키를 실수로 철회하면 복구 경로가 사라진다.
- 삭제 high-water는 "사용자가 지운 것은 돌아오지 않는다"는 사용자 이익과 방향이 같지만, 철회 high-water는 운영 복구 능력과 정면으로 상충한다.
- 중간 설계(철회 이력만 별도 원장에 남기고 복원 시 병합)도 가능하지만, 그 원장의 소유자·정본·복구 규칙을 새로 정해야 한다.

따라서 이것은 코드를 고쳐 닫을 항목이 아니라 **사용자가 내려야 할 설계 판단**이다. 관측만 정확히 남긴다.

## 5. 결정이 필요한 질문

백업에서 과거 설정을 복구했을 때 이전에 철회한 키가 다시 살아나는 것을 **허용할 것인가?**

- **허용한다**면 M3의 해당 조항을 현실에 맞게 수정해야 한다. 설정 파일이 정책의 정본이고 복원은 정본을 되돌리는 행위라는 일관된 입장이다.
- **허용하지 않는다**면 철회 이력을 설정 밖 단조 저장소로 옮기는 설계가 필요하다. 그 경우 잘못된 철회의 복구 경로를 함께 정의해야 한다.

## 6. 한계

- 이 문서는 **읽기와 기존 단정 대조**로 확정했다. 제품 코드와 테스트를 바꾸지 않았다.
- 격리 fixture 기준이며 운영 인증 경로가 아니다.
- M3의 나머지 조항(1절)은 충족돼 있고, 이 문서가 그것을 뒤집지 않는다.
