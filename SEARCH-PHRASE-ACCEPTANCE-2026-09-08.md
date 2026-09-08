# 정확 문구 검색과 입력 오류 인수

최신 병합 상태: [100회 쓰기 최종 통과](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md) 후 원 작업공간 `f756872`에 반영했다. 아래 병합 대기 표시는 당시의 검증 이력이다.

## 구현

검색 확장으로 `세 번 실패`가 단어가 떨어진 다른 주제의 자료도 후보에 포함하게 됐다. 기본 AND 검색을 유지하면서 큰따옴표 그룹을 연속 문구로 지정하는 기능을 추가했다. 예: `sb search '노을 "세 번 실패"'`. 봉인·비봉인 검색과 MCP record 선택에 같은 parser를 사용한다. 같은 record에 모든 단어/문구가 있어야 하며, 기존 generation/fence/record ID·digest·선택 후 limit을 유지한다.

- 그룹 내부의 `\"`는 따옴표 문자, `\\`는 역슬래시 문자로 읽는다. 다른 역슬래시와 일반 검색어의 Windows 경로는 보존한다. `OR` 등은 검색 값이며 FTS 연산자로 실행하지 않는다.
- 입력 최대 4,096 UTF-8 bytes, 32개 그룹이다. 한도를 초과하거나 닫히지 않은/빈 따옴표 그룹, 그룹 뒤에 공백 없이 붙은 문자, NUL/지원하지 않는 ASCII 제어문자, 잘못된 UTF-8이면 명시적 오류를 반환한다. 입력을 잘라서 다른 질문으로 검색하지 않는다.
- `SearchIndex.search`와 스트리밍 진입점에서 index refresh 전에 검증한다. CLI는 실패 exit 1과 오류 이유, HTTP는 기존 400, MCP는 `ToolError`로 반환한다. MCP 프레임워크가 도메인 `ValueError`를 일반 오류로 숨기는 경로도 확인하여 명시적으로 변환했다. 실제 입력 본문을 오류 메시지에 덧붙이지 않는다.
- 새 MCP 필드/profile·index schema·외부 모델은 추가하지 않았다. 구현 전 결정은 [ADR](SEARCH-PHRASE-ADR-2026-09-08.md)다.

## 실제 CLI/MCP 전후 비교

고정 자료 `tests/fixtures/korean_phrase_v1.json`은 합성 문서 6개, 정답 문구/경로 질문 7개, 정답 없는 질문 3개다. 정답은 검색 출력으로 생성하지 않고 입력에 고정한 page ID·원문 span이다. SHA-256은 `25ee81f5870b365a0a04ca387dffd6c2c744aa6d7c63f11450092a3acc0a6bd6`이다.

| 검증 | 변경 전 `47fa507` | 변경 후 |
|---|---:|---:|
| 큰따옴표 문구·경로 정답 Recall@5 | 0/7 | 7/7 |
| 같은 자료 Hit@1 | 0/7 | 7/7 |
| 정답 없는 질의의 빈 결과 | 3/3 | 3/3 |
| 선택 record·출처·generation·정답 span 대조 | 회수 없음 | 7건 |

CLI와 MCP의 지표가 같다. 변경 전은 큰따옴표 그룹/escape 규칙을 지원하지 않아 이 입력들의 정답을 회수하지 못했다. 변경 후에는 `노을 "세 번 실패"`가 `노을 연결 실패는 세 번까지...`를 제외하며, 따옴표가 포함된 인용문과 역슬래시 경로도 그대로 찾는다. 문구만 지정한 검색을 자연어 의미 검색의 성공으로 해석하지 않는다.

기존 합성 한국어 100개도 재실행했다. 정답 있는 90개 중 **60개 회수**, 어순 변경 20/20과 정확 문구 20/20 유지, 자연어/의역 30개 미회수로 이전 지표를 유지했다. 기존 데이터 SHA-256 `8f82e7f1b431766c2a39e018055daa56dcd9430fd67a572c07065f6c1e9d3c55`는 변경하지 않았다.

잘못된 입력의 실제 subprocess/stdio 인수도 별도로 실행했다. CLI 3건(미종결 문구·byte 초과·그룹 초과)은 exit 1/빈 stdout/명시적 이유, MCP 5건(앞의 3개·빈 문구·NUL)은 `is_error=true`와 해당 `SEARCH_QUERY_*` 이유를 반환했다. CLI argv에는 NUL을 전달할 수 없으므로 NUL 사례는 MCP에서 검사했다.

## 증거와 검사

- 변경 전: `/var/tmp/sb-phrase-baseline`은 `47fa507` detached worktree다. 실제 평가 `/var/tmp/sb-korean-search-w948oic5/evidence.json`, `cli.jsonl`, `mcp.jsonl`, `rankings.jsonl`; 로그 `/var/tmp/sb-phrase-before-final.log`.
- 변경 후 문구 평가: `/var/tmp/sb-korean-search-zg00flak/evidence.json` 및 native JSONL; `/var/tmp/sb-phrase-after.log`.
- 기존 100개: `/var/tmp/sb-korean-search-5k3pc4k4/evidence.json` 및 native JSONL; `/var/tmp/sb-phrase-regression100.log`.
- 잘못된 입력: `/var/tmp/sb-phrase-invalid-native.json`, CLI 3건·MCP 5건 `state=passed`.
- 변경 후 평가 제품 hash(`sb/` 기준): `829f20d6b729b9338a20eda7b9816ede5bbdbc27d43c7b5876b475692b59c28f`. 평가 도구가 시작/종료 제품 hash와 봉인 파일 불변을 검사했다. 외부 자료·운영 저장소는 사용하지 않았다.
- 관련 회귀 **63 passed (11.11초)**. parser·byte/그룹 한도·인덱스 생성 전 거부·CLI·HTTP·봉인/비봉인·legacy/schema5 MCP를 포함한다. 로그 `/var/tmp/sb-phrase-focused-final.log`.
- 표준 전체 **764 passed / 2 skipped (222.43초)**. `/var/tmp/sb-phrase-full-tests.log`. 앞선 검색 어순/준비 사본 복구와 이번 변경을 함께 포함한 격리 제품이며 집중 검사와 중복된다.
- 새 parser/error/MCP/CLI/테스트 타입 오류·경고 0. 변경된 `sb/search.py` 전체에는 직전부터 있던 동일 6개 경고가 있다. 해당 경고를 억제하지 않았다. 로그 `/var/tmp/sb-phrase-types-final.log`, `/var/tmp/sb-phrase-types.log`. Ruff 전체 통과: `/var/tmp/sb-phrase-ruff-final.log`.
- 처음 사용한 파일 archive는 Git 메타데이터가 없어 평가 도구 초기화 단계에서 실패했다(`/var/tmp/sb-phrase-before.log`). 위의 실제 detached worktree 실행을 변경 전 기준선으로 사용한다. 초기화 실패를 검색 미회수로 계산하지 않았다.

```bash
TMPDIR=/var/tmp python scripts/korean-search-acceptance.py --dataset tests/fixtures/korean_phrase_v1.json
TMPDIR=/var/tmp python scripts/korean-search-acceptance.py
```

## 병합과 남은 범위

이 기능은 검색 어순 수정·준비 세대 복구 다음으로 `/var/tmp/sb-korean-query-work`에서 구현했다. 원 작업공간의 기존 버전 100회 쓰기 인수가 끝나기 전에는 병합/배포하지 않는다. 기본 AND 검색의 추가 후보는 그대로 존재하며, 사용자가 필요한 경우 정확 문구로 제한할 수 있다.

이번 byte/그룹 한도는 질의 자원 제한이다. 모델 context token budget이나 B5 실제 전달 receipt가 아니다. 실제 사용자 질문 100–300개, 자연어/의역, Unicode casefold·형태소·의미 검색 품질, 일반 agent fence·접근 범위, 자비스 정정 UI/원본 차단 전파, B5 문맥/전달과 운영 전환/DR의 기존 목표는 유지한다.
