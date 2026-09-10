# 실제 사용에서 발견한 각주 중복 — 쉼표 span 표기

## 무엇이 잘못됐고 사용자에게 어떤 영향이 있었나

운영 세컨드브레인이 오늘 실제로 컴파일한 wiki 페이지에 같은 출처 각주 정의가 **두 줄** 남았다.

```
[^8d98629a]: inbox:2026-09-10T031904232122-…-인수.md, span=0-480
[^8d98629a]: inbox:2026-09-10T031904232122-…-인수.md
```

사용자가 읽는 기억 원문에 같은 출처가 중복 표기되고, 이 페이지를 인용하는 에이전트도 같은 각주를 두 번 본다. 같은 입력으로 만든 daily 페이지에는 나타나지 않았다.

## 재현 근거

`sb/vault.py`의 `_render_definitions`는 모델이 붙인 span 주석을 인식해 중복을 제거하지만, 인식 패턴이 `origin span=0-12`(공백)만 허용했다. 실제 모델 출력은 `origin, span=0-480`(쉼표+공백)이었고, 이 형태는 "소유한 정의"로 분류되지 않아 중복 제거 대상에서 빠졌다.

현재 HEAD의 `_render_definitions`에 실제 페이지와 같은 본문을 넣어 재현했고, 수정 전 결과는 정의 2줄, 수정 후 1줄(`, span=0-480` 주석 보존)이다. 운영 릴리스 `41f0751a`에는 dedup 자체가 없어 같은 중복이 그대로 남는다.

## 실제 수정 지점

- `sb/vault.py`: 상수 `SPAN_SUFFIX_RE = r",? span=[0-9]+-[0-9]+"`를 두고, `_render_definitions`의 정본/native 두 비교에 함께 사용한다. 쉼표를 선택적으로 허용하는 것 외의 동작 변화는 없다.
- 유지한 기존 계약: 코드 펜스 안의 예시는 건드리지 않고, 서로 다른 span 주석은 여전히 합치지 않으며, span 주석이 있는 줄을 우선 보존한다.

## 실행한 검증

- `tests/test_vault.py`의 `test_render_keeps_code_examples_and_one_source_definition`에 span 구분자 `' '`/`', '` 파라미터를 추가했다. 수정 전에는 쉼표 변형 **8건이 실패**하고 8건 통과, 수정 후 **16건 모두 통과**한다.
- 실제 운영 페이지 본문으로 만든 재현: 정의 1줄, `, span=0-480` 유지.
- `tests/test_vault.py tests/test_vault_transactions.py tests/test_compile.py` **49 passed**.
- `ruff check --no-cache sb/vault.py tests/test_vault.py` exit 0, `basedpyright sb/vault.py` 0 errors 0 warnings.
- 전체 회귀는 이 변경 뒤 별도로 재실행했다([결과](CONTINUATION-FULL-REGRESSION-2026-09-10.md)의 후속 실행 기록 참조).

## 남은 항목

- 이미 운영 vault에 기록된 페이지의 중복 각주는 이번 수정으로 소급 정리되지 않는다. 운영 릴리스를 갱신한 뒤 해당 페이지가 다시 컴파일될 때 정리된다. 기존 페이지를 손으로 고치지 않았다.
- 모델이 만들 수 있는 다른 주석 표기(예: 괄호 표기)는 관측되지 않아 허용 목록에 넣지 않았다. 실제 사례가 나오면 같은 방식으로 추가한다.
