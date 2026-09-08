# 봉인 record 분류 조회·내부 범위 판정

2026-09-09 제품 `62da782`. 이전 페이지 출처 저장 `f16c142`에 이어, 같은 봉인 세대의 원장 분류와 Git 본문에서 record를 함께 읽는 경로를 구현했다. 전체 목표는 자비스와 여러 에이전트의 공통 기억 운영이며 이 단위로 완료 처리하지 않는다.

## 구현

- `sb/memory_access.py`: 세대 manifest/derived inventory를 대조하고, 정확한 커밋의 페이지 본문 해시와 `page_access`를 결합한다. 요구 원본의 분류와 checksum을 모두 검증한 뒤 같은 bytes에서 record를 파싱한다. 조회 후 세대 무결성도 다시 확인한다. caller는 응답 생성까지 세대 lease를 유지해야 한다.
- SQLite는 `mode=ro&immutable=1`로 열고 writer Ledger나 마이그레이션을 호출하지 않는다. 봉인되지 않은 vault, 다른 세대, 바뀐 원장, 빠진 분류는 거부한다.
- `require_scope`는 **이미 인증된 범위를 받아야 하는 내부 함수**다. 모든 입력 원본의 owner/policy revision 일치와 전체 project 포함을 요구한다. 표시된 record의 인용만으로 페이지 전체 권한을 축소 계산하지 않는다.
- 빈 프로젝트 집합은 wildcard가 아니다. 프로젝트 범위의 소비자에게 개인 원본을 자동 포함하지 않는다. 개인 범위는 같은 소유자·정책 및 양쪽 빈 project 집합으로 대조한다.
- 기존 source classification 해석을 `decode_source_access`로 공통화하여 수집 writer와 봉인 reader가 동일한 canonical JSON/checksum 검사를 사용한다.

## 검증

최종 집중 검사 **32 passed, 8.42초**: memory_access, page_access, source_access, record validity, task32 schema4 integration. Ruff 통과, 변경 제품 모듈 basedpyright **0 오류/0 경고**, diff 검사 통과. 앞선 전체1,108통과는 이전 커밋의 기록이며 이번 최종 전체 검사로 재표기하지 않는다.

초기 변경·누락 검사 2개는 봉인 디렉터리의 쓰기 금지 때문에 테스트 변조 단계에서 실패했다. 테스트 소유의 임시 세대에만 권한을 열어 실제 변조를 만들고 거부를 재검증했다. 운영 파일을 변경하지 않았다.

실제 CLI 인수: `/var/tmp/page-access-acceptance-egea9oz_/memory-access-result.json`.

| 항목 | 결과 |
|---|---|
| 수집→컴파일→원본 수정→컴파일 | 기존 실제 CLI 실행 성공 |
| 최종 source requirements / records | 2 / 2 |
| 같은 owner/project/revision | 내부 판정 통과 |
| 다른 owner/project/revision·빈 project 범위 | 각 `MEMORY_ACCESS_DENIED` |
| 재조회 | 같은 결과 |
| 조회 전후 원장 | SHA-256 동일, 테스트에서 WAL/마이그레이션 생성 없음 |

격리된 실제 CLI·SQLite·Git과 fake LLM 및 합성 범위를 사용했다. 실제 앱 사용자 인증·MCP 접근 제어 또는 실제 LLM 품질을 검증한 것으로 확대하지 않는다.

## 보류·잔여 조건

1. 내부 `require_scope`에 클라이언트가 보낸 owner/project 문자열을 직접 연결하는 방식은 보류한다. 인증 함수가 아니므로 이를 공개하면 권한을 위조할 수 있다. 자비스의 검증된 사용자/작업 범위와 현재 정책을 별도 claim 계약으로 연결해야 한다.
2. 기존 MCP profile·record wire는 변경하지 않았다. 이 구현으로 기존 MCP의 접근 범위가 제한되지는 않는다. 전체 검색/직접 page/resolve/status/쓰기/export/restore/context에 동일 검사를 적용해야 한다.
3. 개인 원본과 프로젝트 원본이 혼합된 페이지는 첫 범위 모델로 허용하지 않는다. 명시적인 개인 접근 능력 계약을 마련한 뒤 확장한다. 프로젝트 범위가 개인 기억을 암묵적으로 포함하는 것보다 제한을 명확히 유지한다.
4. source 분류 변경·최신 정책 철회·정정/삭제/복원 및 record 계보의 전 경로 연결은 남는다. 분류 해석과 세대 일치가 현재 사용자 권한의 증거를 대신하지 않는다.
5. 같은 OS 사용자의 직접 파일 접근·외부 작성자 전체 배제는 별도 경계다. 세대 검증만으로 해당 운영 격리를 주장하지 않는다.
6. 원작업 계보·native 세션/백업 수명·실제 자비스 앱 사용 순환·검색/GUI/DR 인수 등 기존 전체 목표를 유지한다.

운영 배포·서비스 재시작·실 vault/config 수정·push는 수행하지 않았다.
