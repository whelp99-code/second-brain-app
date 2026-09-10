# M3 철회 후 설정 복원 — 설계 초안

기준: [인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) §4, [철회 롤백 갭](REVOCATION-ROLLBACK-GAP-2026-09-10.md), `tests/test_scoped_read_policy.py`. 코드를 바꾸지 않는다. M3을 완료·완화하지 않는다.

## 유지하는 요구

발급 뒤 철회·열린 연결·**과거 설정 복구에도 과거 권한으로 읽지 못함.** 편의로 이 조항을 허용으로 바꾸지 않는다.

현재 테스트가 고정하는 동작:

```python
path.write_text(original)
assert current_scoped_policy(config, initial) == initial
```

철회를 넣었다가 원본 설정을 되돌리면 정책이 완전히 복귀한다. 삭제 high-water(세대 manifest)와 달리 철회는 설정 파일 상태다.

## 기존 경계 안에서 먼저 볼 경로

새 정본·권한 체계를 추가하기 전에, 이미 있는 authority/정책 revision/키 수명으로 닫을 수 있는지 본다.

| 순서 | 경로 | 닫히는 조건 | 한계 |
|---|---|---|---|
| 1 | 철회 시 **새 키를 발급·회전**하고 옛 키는 `revoked_jarvis_signing_key_ids`에 남긴다. 복구는 옛 키 파일이 아니라 새 키 배포 | 실수 철회 복구 ≠ 옛 키 파일 복원. 설정 백업을 되돌려도 회전자가 거부하면 옛 claim은 죽어야 한다 | 운영 키 회전 런북·클라이언트 재발급이 선행. 지금 운영 키를 돌리지 않는다 |
| 2 | 설정 복원을 **정책 revision 단조 증가와 묶는다.** 복원본의 revision이 현재보다 낮으면 `current_scoped_policy`가 거부 | 기존 `policy_revision` 비교를 복원 경로에도 적용 | revision을 설정 파일에만 두면 파일 복원으로 같이 되돌아간다. 세대/authority 쪽에 이미 있는 revision 저장을 재사용할 수 있을 때만 유효 |
| 3 | 백업 복원 절차가 설정을 덮어쓰기 전에 **현재 철회 집합을 보존·병합**한다. `sb restore` / JARVIS backup 경로의 기존 훅 | 새 machinery가 아니라 복원 체크리스트·구현된 restore 가드 | 훅이 없으면 수작업 병합은 운영 실수에 열린다. 가드 부재를 코드 추가로 오인하지 말 것 |
| 4 | 열린 MCP 세션은 설정 복원 후 재바인딩하지 않는다. 이미 테스트가 세션 identity 변경을 거부 | 복원 창에 살아있는 연결을 끊는 운영 절차 | 절차만으로는 M3 문장(“과거 권한으로 읽지 못함”)을 닫지 못한다 |

1이 실수 철회 복구의 기본선이다. **옛 키 복원만이 유일한 복구라고 가정하지 않는다.**

## 별도 정본이 필요할 때만

1–3으로 기존 계약·validator를 깨지 않고 닫히지 않으면, 리포 규칙에 맞는 ADR을 쓴다. ADR 없이 철회 high-water를 `sb/`에 넣지 않는다. 인계서 4절의 근거 없는 authority machinery 추가 금지를 유지한다.

ADR이 필요해질 때의 최소 내용:

- 철회 이력의 소유자(SB 설정 vs JARVIS authority DB vs 세대 manifest)
- 잘못된 철회의 복구(회전, 명시적 un-revoke, 둘 다 아님)
- 백업 복원 시 병합 순서와 실패 시 활성 세대 보존
- 기존 scoped claim validator를 완화하지 않는다는 회귀 목록

## 완료 증거 (아직 없음)

격리에서: 철회 → 설정 파일 백업 복원 → 같은 claim 읽기 거부, 내용 0. 운영 인증 경로 반복은 활성화 이후 항목이며 이 초안이 그것을 대체하지 않는다.
