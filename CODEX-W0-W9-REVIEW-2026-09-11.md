# W0–W9 회신 검토 및 재작업 지시

대상: `CODEX-W0-W9-REPLY-2026-09-10.md`, HEAD `6c6bc17`. 이전 지시 `872bda7` 이후 변경을 대조했다. 이번 작업은 코드 검토·격리 재현·설치물 읽기이며, 제품 코드 수정·운영 전환·운영 데이터 변경은 하지 않았다.

**판정: 진척은 인정하지만 `0eefce7`의 운영 전환은 보류해야 한다.** W1의 사용자 편집 유실과 W2의 철회 유실을 재현했다. W6에는 검색 경로 간 결과 불일치가 있다. 이는 “구현 완료, 운영 확인만 남음”으로 분류할 수 없는 코드 결함이다.

## 1. 직접 확인한 사실

| 범위 | 결과 |
|---|---|
| 설치 후보 | `/var/tmp/sb-candidate-f142a76/releases/0eefce70378a2b0051ee0d8c159a542d1fd9f554` 존재 |
| wheel 실측 | `dc705e8a058565fc6f98cc8d3a6ca9a62c47119b1ad8c51f9bdc7f2c6bbbb3dd`, 보고 JSON과 일치 |
| 후보 소스 | manifest `f142a76907cd52787103f7f51635ca8fb2ed6026` |
| 결함 관련 설치 코드 | `vault.py`, `revoked_keys.py`, `search_query.py`가 현재 검토 소스와 바이트 동일 |
| 관련 기존 회귀 | **91 passed / 16.91s** |
| Ruff | `uv run ruff check --no-cache sb tests` 통과 |
| 운영 링크 읽기 | SB `41f0751…`, authority `a3cbbbe…` 유지 |
| 전체 회귀 | 이번에는 재실행하지 않음. 회신의 1,832 통과는 W6 이전 `859691d` 결과 |

91개 대상은 `test_compiled_marker_recovery`, `test_vault`, `test_scoped_read_policy`, `test_mcp_scoped`, `test_search`, `test_search_query`다. 기존 회귀의 성공과 아래 새로운 결함 재현은 동시에 성립한다.

표준·업무·유지보수 gate의 성공은 커밋된 JSON에서 확인했으며 이번에 gate를 다시 돌리지는 않았다. 현재 링크 값 확인만으로 과거 기간 전체에 운영 변경이 없었음을 증명한 것은 아니다.

## 2. P1 — W1이 marker 없는 사용자 편집을 덮어쓴다

위치: [sb/vault.py:379](/home/jm/orca/projects/second-brain-app/sb/vault.py:379).

현재 `_divert_to_proposed`는 marker가 없고 frontmatter가 SB 형식이면 기존 페이지를 바로 갱신한다. 하지만 자동 생성된 페이지의 본문을 사람이 수정해도 `compiled_by` 등 frontmatter는 그대로 남을 수 있다. frontmatter 파싱 성공은 마지막 컴파일 이후 본문이 그대로라는 증거가 아니다.

격리 재현: SB 페이지 생성 → frontmatter를 보존한 채 본문에 `USER_EDIT_KEEP_THIS` 추가 → marker 없는 ledger로 정정 저장. 결과는 **pages=1, proposals=0, 사용자 편집 사라짐**이다. 기존 손편집 테스트는 frontmatter 없는 페이지 또는 marker가 있는 경우만 검사한다.

수정 지시:

1. marker가 없는 compiled 페이지에 실제 본문 수정이 있는 사례를 실패 회귀로 추가한다.
2. 신뢰할 수 있는 마지막 컴파일 본문 hash/기존 세대·Git 근거와 대조하는 복구를 설계한다. frontmatter만으로 무수정을 추정하지 않는다.
3. 근거를 복구할 수 없는 경우 원본을 보존하고 제안 경로를 유지한다. 정상 무수정 페이지의 marker 복구와 손편집 보호를 동시에 검증한다.
4. 실제 관리형 세대 전이·CLI·재시도에서 정정 회수와 원본 보존을 확인한 뒤 W1을 다시 인수한다.

## 3. P1 — W2의 동시 철회가 유실된다

위치: [sb/revoked_keys.py:20](/home/jm/orca/projects/second-brain-app/sb/revoked_keys.py:20).

`load → 집합 합치기 → 파일 교체` 전체를 보호하는 잠금/트랜잭션이 없다. 원자적 `os.replace`는 파일 교체만 원자적으로 수행하며 여러 writer의 집합 병합을 직렬화하지 않는다.

결정적 격리 재현: A가 빈 집합을 실제 읽은 직후 일시 정지 → B가 `key:b` 철회를 기록하고 정상 종료 → A가 `key:a` 기록을 마무리. **두 호출에 예외가 없지만 최종 파일에는 `key:a`만 남고 `key:b`가 사라진다.** 임의 반환값을 주입하지 않았고 Event로 읽기/쓰기 순서만 고정했다.

수정 지시:

1. 여러 MCP 프로세스에서 공통으로 지키는 직렬화 경계를 정하고 read/merge/publish 전체를 보호한다. 프로세스 내부 잠금만으로 끝내지 않는다.
2. 고정 `.tmp` 파일을 다른 호출이 지울 수 있는 경합도 제거한다. 잠금·임시 파일·fsync·교체·중단 회복을 함께 설계한다.
3. 두 독립 프로세스의 서로 다른 철회, 중복 철회, 중간 종료, 재시작 뒤 union 보존을 검증한다.
4. 매 조회에서 설정 철회를 관측할 때만 기록하는 현재 방식의 효력 발생 시점을 정의한다. 설정 변경 후 조회 없이 설정을 복원한 경우까지 보장하는지 별도로 다룬다.

## 4. P1 — W2는 비정상 철회 파일을 빈 집합으로 해석한다

위치: [sb/revoked_keys.py:13](/home/jm/orca/projects/second-brain-app/sb/revoked_keys.py:13).

`path.is_symlink() or not path.is_file()`이면 빈 집합을 반환한다. 격리에서 `key:test` 철회를 기록하고 설정을 철회 전으로 복원한 상태는 정상적으로 거부됐다. 이후 **철회 파일을 같은 내용의 파일을 가리키는 symlink로 바꾸자 `key:test`가 정책의 허용 키 목록에 다시 포함됐다.** 이 재현은 정책 키 선택 결과이며, 서명된 데이터 읽기까지 실행한 결과는 아니다.

수정 지시:

- 정상 최초 초기화와 기존 철회 저장소의 유실·변형을 구분한다. 불신 경로·파손·권한 오류를 빈 철회 목록으로 바꾸지 않는다.
- 기존 파일 안전성 규칙과 잠금 범위를 적용해 검사-열기 경합을 다루고, 비정상 상태에서 과거 키를 허용하지 않는지 회귀로 검증한다.
- 설정 외 별도 정본을 추가한 만큼 소유자·초기화·백업·복구·읽기/쓰기 표면의 공통 적용을 ADR/계약으로 정리한다. 이번 검색에서는 이 구현에 대응하는 철회 ADR을 dev-wiki의 decisions 아래에서 찾지 못했다.

## 5. P2 — W6에서 SQL 검색과 record 검색의 규칙이 다르다

위치: [sb/search_query.py:79](/home/jm/orca/projects/second-brain-app/sb/search_query.py:79), 같은 파일의 `matches_record`.

| 질의 | 본문 | SQL predicate | record predicate |
|---|---|---|---|
| `은빛나침반` | `은빛` + 줄바꿈 + `나침반` | false | true |
| `Alpha한글` | `alpha한글` | false | true |
| `쌀밥` | `쌀 밥` | false | true |

SQL 쪽은 긴 한글 term에 ASCII space/tab만 제거하고 대소문자를 접지 않는다. record 쪽은 모든 `isspace()` 문자를 제거하고 casefold하며 짧은 한글에도 압축 규칙을 적용한다. 실제 SQL 실행과 실제 `matches_record` 호출로 재현했다. 각각의 호출자는 `sb/search.py`/`sb/sealed_search.py`와 `sb/scoped_search.py`다.

수정 지시:

- 길이·공백·대소문자·혼합 문자열에 대한 하나의 검색 계약을 정하고 SQL/record 양쪽이 같은 결과를 내도록 한다. 줄바꿈·CRLF·tab·Unicode 공백·짧은 한글 회귀를 포함한다.
- 한글이 포함된 긴 term을 FTS에서 모두 제외하면서 순수 한글 질의의 BM25가 0.0이 되는 변화도 검토한다. 현재 코드상 순위 변화는 확인되지만 대규모 품질·지연 영향은 이번에 측정하지 않았다.
- 18문 개선만으로 전체 검색 품질을 인수하지 않는다. 정확 검색·정정/no_answer·scoped 경계·여러 페이지 순위·실제 부하의 전후 결과를 보존한다.

## 6. 롤백과 복원 검증의 미충족 조건

**`41f0751`는 복귀할 바이너리의 식별자이지 안전한 롤백 증명은 아니다.** 설치된 구버전 `sb/`에는 새 철회 파일명 참조가 없고 `sb.scoped_read_policy` 모듈도 없다. 새 state 파일을 남기는 것만으로 구버전이 같은 철회를 강제한다고 할 수 없다. 구버전 정책 함수를 호출하려던 이번 probe는 `ModuleNotFoundError`로 끝났으며, “구버전에서 옛 키 읽기가 성공했다”고 보고하지 않는다.

런북에는 새 후보가 실제로 쓴 세대·원장·철회 상태를 구버전이 어떻게 처리하는지 격리 왕복 검증을 추가한다. 호환성이나 권한 보존을 증명하지 못하면 자동 롤백을 사용하지 않는 조건과 별도 복구 절차를 명시한다. JARVIS를 그대로 두는 SB 전환만으로 누락된 production 명령 경로가 생기지도 않는다.

또한 `tests/restore_scoped_mcp.py`는 철회 후 새 stdio 서버 2회가 실패하는 검증으로 바뀌었다. 영속 철회의 부정 경로로는 타당하지만, 예전의 **복원 후 새 프로세스에서 정상 기억을 회수하는 긍정 경로**가 사라졌다. 새 유효 키로 fresh claim/fence를 발급해 회수 성공·불허 범위 거부를 검증하고, 옛 키 거부는 별도 유지해야 한다.

## 7. W0–W9 판정 갱신

| 항목 | 이번 판정 |
|---|---|
| W0 | snapshot/모듈 집계 정리는 진척. 현재 상태 문서의 c04dee1 등 오래된 표는 최신 후보/검토와 구분 필요 |
| W1 | **재작업 필요: 사용자 편집 유실 재현** |
| W2 | **재작업 필요: 동시 철회 유실, 비정상 파일에서 정책 재허용** |
| W3 | 후보 hash와 격리 gate 기록 인정. **새 JARVIS dependency artifact 미준비, 결함 수정 후보 필요** |
| W4 | 실제 신원 운영 종단 미실행. 전환 전 준비도 아직 남아 있음 |
| W5 | 빈 프로필로는 native 수명 미검증. 이 사실을 제품 자체의 삭제 지원 불가로 일반화하지 않음 |
| W6 | 붙여쓰기 개선 인정, **검색 표면 일관성 재작업**, 문맥 전달·자연어/의역 미완 |
| W7 | 약 21초 표본이며 timeout 개선/부하 인수 아님 |
| W8 | restore/HTTP 표본. 실제 브라우저 복구와 전체 DR 미완 |
| W9 | 관계 검색 가치 인수 미완, 핵심 결함보다 후순위 유지 |

후속 순서: W1 데이터 보존 → W2 직렬화·비정상 저장소·복원/롤백 계약 → W6 검색 일관성 → 복원 긍정 경로 회귀 → 최종 고정 소스 전체 회귀 → 새 후보/paired/유지보수 인수 → 새 JARVIS artifact를 포함한 전환 런북. 운영 허가가 없다는 이유로 앞의 격리 수정까지 중단하지 않는다.

## 8. 재현과 증거

[재현 스크립트](/home/jm/orca/projects/second-brain-app/scripts/w0-w9-review-probe.py), [이번 실행 JSON](/home/jm/orca/projects/second-brain-app/CODEX-W0-W9-REVIEW-2026-09-11.json).

```bash
cd /home/jm/orca/projects/second-brain-app
TMPDIR=/var/tmp PYTHONPATH=. uv run python scripts/w0-w9-review-probe.py
TMPDIR=/var/tmp uv run pytest -q tests/test_compiled_marker_recovery.py tests/test_vault.py tests/test_scoped_read_policy.py tests/test_mcp_scoped.py tests/test_search.py tests/test_search_query.py
uv run ruff check --no-cache sb tests
```

probe의 exit 0은 측정 실행이 끝났다는 뜻이며 제품 인수 성공이 아니다. JSON의 `preserved=false`, 누락된 철회, 재허용된 키, predicate 불일치가 결함 증거다. symlink 상황은 격리 디렉터리 안에서만 생성한다. 이번 보고에서 운영 데이터는 변경하지 않았다.
