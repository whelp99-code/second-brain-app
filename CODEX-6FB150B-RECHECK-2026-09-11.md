# 6fb150b 수정 재검토 및 남은 작업

대상 소스 `6fb150b9261f209202931a0d997cb1c75c6c1cd7`. 이전 검토의 구체적 사례는 개선됐지만 **관리형 compile의 사용자 편집 유실과 Unicode 검색 불일치가 남는다.** 새 wheel 생성만 남은 상태로 판정하지 않는다.

## 확인된 개선

- marker 없는 페이지를 `Vault.write_pages`에 직접 넘긴 기존 손편집 사례: 원본 보존, `proposals=1`, `pages=0`.
- 동시 철회: 기존 스레드 probe에서 `key:a`·`key:b` 모두 보존. 별도의 독립 Python 프로세스 두 개로도 exit 0/0, 두 키 보존을 확인했다. 모든 crash/복원 interleaving까지 증명한 것은 아니다.
- symlink 철회 파일: 정책 조회가 거부되고 허용 키를 반환하지 않는다. 저장소의 `REVOCATION_STORE_UNSAFE`는 scoped 정책 경계에서 `MEMORY_SCOPED_CONFIG_INVALID`로 변환된다.
- 기존 검색 세 사례(줄바꿈, ASCII 대소문자 혼합, 짧은 한글)는 SQL/record 모두 true다.
- 관련 테스트 **97 passed / 18.42s**, `ruff check --no-cache sb tests scripts/w0-w9-review-probe.py` 통과. 이전 91개 묶음에 신규/추가 테스트를 포함한 이번 실행 수치다. 전체 회귀는 재실행하지 않았다.

## P1: W1은 실제 run_compile의 staging에서 다시 실패한다

[sb/generation_runtime.py](/home/jm/orca/projects/second-brain-app/sb/generation_runtime.py)의 `staged`는 원본을 복사하고 `init_vault(root)`를 실행한 뒤 compiler를 호출한다. 기존 Git 메타데이터는 복사 대상에서 제외되므로 새 staging의 초기 커밋에는 복사된 페이지가 들어간다.

따라서 [sb/vault.py](/home/jm/orca/projects/second-brain-app/sb/vault.py)의 `_committed_bytes_match`가 비교하는 **staging HEAD는 마지막 컴파일 시점의 원본이 아니다.** 복사된 손편집까지 방금 커밋했기 때문에 손편집도 HEAD와 일치한다.

격리 재현 순서:

1. legacy vault에 SB 페이지를 생성하고 marker가 없는 상태에서 본문에 `USER_EDIT_KEEP_THIS`를 추가한다.
2. `run_compile(config, compiler=stage)`를 실행한다. compiler만 fixture이며 실제 세대 staging·`_Compiled` 조회·Vault writer를 사용한다.
3. compiler 진입 시 `marker_before=null`, `edit_before=true`, `staged_page_matches_head=true`다.
4. 결과는 `exit_code=0`, `pages=1`, `proposals=0`, **`edit_after=false`**다. active는 관리형 세대 symlink로 전환됐다.

운영 vault를 대상으로 재현한 것은 아니다. 외부 모델 호출 없이도 실제 관리형 작성 경계에서 원본 보존 결함을 확인할 수 있다.

재작업 지시:

- 이 관리형 compile 사례를 영구 회귀로 먼저 추가한다. `Vault.write_pages` 단독 테스트만으로 W1을 닫지 않는다.
- staging 초기화 전에 신뢰할 수 있는 마지막 컴파일 근거와 손편집 판정에 필요한 원본 상태를 확보하고, 해당 근거가 세대 전이 중 보존되도록 설계한다. 단순히 기존 HEAD를 전달하는 것만으로 이미 커밋된 수동 편집까지 판별할 수 있다고 가정하지 않는다.
- 마지막 컴파일 근거를 복구할 수 없으면 보존/제안 경로를 유지한다. 복구 가능한 무수정 페이지의 정상 정정과 편집된 페이지의 보호를 함께 인수한다.
- legacy → managed 최초 전이, 기존 managed 세대 후속 전이, marker 존재/부재, 재시도, 실제 CLI에서 같은 조건을 확인한다.

## P2: W6의 Unicode 규칙은 아직 다르다

[sb/search_query.py](/home/jm/orca/projects/second-brain-app/sb/search_query.py)의 SQL은 공백 5종을 제거하고 SQLite `lower()`를 사용한다. record 검색은 Python `isspace()` 전체와 `casefold()`를 사용한다.

| 질의 | 본문 | SQL | record |
|---|---|---|---|
| 은빛나침반 | 은빛 + NBSP(U+00A0) + 나침반 | false | true |
| 은빛나침반 | 은빛 + 전각 공백(U+3000) + 나침반 | false | true |
| STRASSE한글 | Straße한글 | false | true |

실제 SQL predicate와 `matches_record`로 재현했다. 이전 지시의 Unicode 공백 회귀가 아직 포함되지 않았다.

재작업 지시: 공백/Unicode casefold의 공통 계약을 정해 SQL과 record 경로에 일관되게 적용한다. 위 사례, 기존 3사례, 긴/짧은 한글, 혼합 문자열의 회귀를 추가한다. 읽기 전용 sealed 검색과 scoped 검색에 같은 규칙을 적용하고, 정규화 비용·FTS 순위 영향을 기존 평가와 함께 검증한다.

## 후보·인수 상태

`0eefce7` wheel은 여전히 `dc705e8a058565fc6f98cc8d3a6ca9a62c47119b1ad8c51f9bdc7f2c6bbbb3dd`이며 `vault.py`·`revoked_keys.py`·`search_query.py` 모두 현재 수정 소스와 다르다. **기존 후보 전환 보류는 타당하다.**

다음 순서: W1 관리형 작성 결함 해결 → W6 Unicode 일관성 → 관련 회귀 → 최종 소스 고정/전체 회귀 → 새 wheel/표준·업무·유지보수 gate. 이전 검토의 롤백 호환성, 새 키로 복원 후 정상 읽기, 철회 저장소의 초기화·유실·백업/복구 계약은 계속 남는다. W2의 이번 두 사례 통과를 M3 전체 완료로 확대하지 않는다.

## 재현 자료

[확장한 프로브](/home/jm/orca/projects/second-brain-app/scripts/w0-w9-review-probe.py), [6fb150b 재확인 JSON](/home/jm/orca/projects/second-brain-app/CODEX-6FB150B-RECHECK-2026-09-11.json). 이전 `CODEX-W0-W9-REVIEW-2026-09-11.json`은 `6c6bc17` 당시 증거로 보존했다.

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp PYTHONPATH=. uv run python scripts/w0-w9-review-probe.py
TMPDIR=/var/tmp uv run pytest -q tests/test_compiled_marker_recovery.py tests/test_vault.py tests/test_scoped_read_policy.py tests/test_mcp_scoped.py tests/test_search.py tests/test_search_query.py tests/test_revoked_keys.py
```

프로브 exit 0은 측정 완료다. 이번 JSON의 `managed_compile_human_edit.edit_after=false`와 Unicode predicate 불일치는 미해결 결함을 뜻한다. 이번에는 제품 코드·운영 데이터·릴리스 링크를 변경하지 않았다.
