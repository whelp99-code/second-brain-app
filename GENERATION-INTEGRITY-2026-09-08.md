# 봉인 세대와 파생 인덱스의 읽기 무결성 수정

후속: [세대 복사 성능 개선](GENERATION-WRITE-PERFORMANCE-2026-09-08.md)이 `fe21016`에 반영됐다. 아래 source hash와 검사 결과는 무결성 수정 당시의 증거다.

상태: **제품 구현·전체 회귀·실제 CLI/MCP/자비스 인수 완료, 원 작업공간 병합 완료.**
격리 커밋 `50aed3b` → 원 작업공간 `db94997`. 현재 sb/ 경로+내용 SHA-256:
`05fd287b6c94cc913f3ebc1e03f69546c565b0a03f16c34170fc30dccd5ddec1`.

## 발견과 재현

기존 `_validate_derived_stores`는 SQLite generation_meta의 세대 필드와 derived-manifest의 ID만
확인했다. 실제 파일 checksum/bytes, inventory의 전체 목록/논리 결합, generation manifest
자체 digest는 읽기에서 재검증하지 않았다. 봉인 semantic index를 연결하기 전 수정해야 할 경계다.

제품 `5d25d3a`를 별도 디렉터리에 추출하고 그 경로의 모듈을 불러온 것을 확인하여 네 실패를
재현했다. `/var/tmp/sb-generation-integrity-before-pinned.log`, 기준 소스
`/var/tmp/sb-integrity-baseline-jsn8716r`.

| 재현 | 수정 전 | 수정 후 |
|---|---|---|
| search.db 본문만 변경 후 store.active | 정상 세대로 수용 | GENERATION_SPLIT_BRAIN |
| 같은 변경 후 SearchIndex 조회 | 주입된 검색 본문 반환 | GENERATION_INDEX_INVALID, 결과 미노출 |
| canonical generation.json의 byte_count 변경 | 같은 generation ID로 수용 | 자체 digest 불일치 거부 |
| canonical derived inventory에서 파일 한 행 누락 | 정상 세대로 수용 | 고정 목록/행 수 불일치 거부 |

초기 두 manifest 테스트는 JSON을 비정규 형식으로 써서 기존 parser가 먼저 거부했다. 이를
canonical bytes로 수정하고 기준 커밋에서 다시 확인한 최종 네 실패만 결함 재현 증거로 사용했다.

## 구현

`sb/generation_integrity.py`를 GenerationStore와 봉인 검색에 공통 연결했다. 외부 MCP 필드나
세대 manifest 버전을 바꾸지 않고 이미 기록하는 정보를 검증한다.

1. 닫힌 generation 필드 집합·schema/count·generation digest와 ID를 검증한다.
2. derived inventory의 세대/HEAD/tree/tombstone/논리 digest를 대조하고 ledger/search/vector/
   briefing 네 파일이 중복·누락·추가 경로 없이 각각 한 번만 포함됐는지 검사한다.
3. nofollow descriptor에서 실제 크기와 SHA-256을 확인하고 전후 descriptor/path identity가
   달라지면 거부한다. manifest는 기존 canonical JSON 및 65,536-byte 상한을 따른다.
4. 고정된 파일 hash는 최대 128개만 메모리에 보관한다. device/inode/size/mtime_ns/ctime_ns/
   mode/uid/nlink가 바뀌면 다시 읽는다. mtime을 되돌린 같은 크기 변경도 ctime 때문에 재검사한다.
   열린 DB/원문/pipeline 상태는 캐시에 보관하지 않는다.
5. 기존 generation pin을 유지하며 SQLite URI의 특수 문자를 인코딩한다. 한글·공백·?·#·따옴표
   경로에서도 세대 검증·활성 조회·검색을 확인했다.

실제 CLI에서는 frozen exception이 context manager의 traceback 갱신을 막아 원래 오류를
TypeError로 바꾸는 문제도 재현했다. GenerationIndexError의 traceback 갱신을 허용하고 CLI가
세대/인덱스 오류를 exit 1 + 명시적 코드로 출력하도록 했다. 검색 결과나 traceback은 내보내지 않는다.

## 검증과 실제 사용 경로

- 관련 집중 **120 passed (19.47초)**, `/var/tmp/sb-generation-integrity-focused.log`.
- 전체 **815 passed / 2 skipped (190.89초)**, `/var/tmp/sb-generation-integrity-full-final.log`.
- 변경 제품·테스트 타입 **0 errors / 0 warnings**, 전체 Ruff/diff check 통과.
- 원 작업공간 병합 후 walking skeleton·memory lifecycle·generation/runtime 검사 **26 passed
  (21.77초)**, `/var/tmp/sb-generation-integrity-merged-gate.log`. 집중/전체와 중복이며 합산하지 않는다.
- 실제 CLI에서 정상 봉인 기억 회수→DB 손상→stdout 0 bytes/exit 1/GENERATION_INDEX_INVALID를 확인했다.
- 실제 3회 remember/run·두 MCP reader·무변경 replay·백업/복원 통과. 검색/페이지 읽기 각 759회,
  신규 기억 3개 복원 회수, CAS 8개 보호·orphan/invalid 0. 증거
  `/var/tmp/sb-write-cycles-qt2ex1v4/evidence.json`, `/var/tmp/sb-generation-integrity-write-smoke-final.log`.

첫 순환은 복원 경로의 .sb 디렉터리 mode=0775 때문에 실패했다. root=0700 내부의 정상 복원
형태이므로 최상위 비공개 권한과 파일 안전성은 유지하면서 내부 디렉터리의 기본 권한을 허용했다.
원 실패 `/var/tmp/sb-write-cycles-l38a45at`를 보존하고 새 전체 순환으로 통과를 확인했다. 변경 전
전체 검사 한 번은 수정 때문에 중단(exit 143)했으며 최종 통과 횟수에 포함하지 않았다.

### 대용량 최종 세대 재조회

[100회 쓰기 인수](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md)의 최종 세대를 최신 reader로 조회했다.
파생 파일/manifest 약 44,278,723 bytes의 최초 검증은 **32.46ms**, 신규 기억 100개를 각각 회수한
동일 프로세스 검색 p95는 **4.72ms**였다. 파일 hash 전후 불변.
`/var/tmp/sb-generation-integrity-capacity-read.json`. 이는 합성 고유 문구의 내부 읽기이며
새 제품으로 full100 쓰기를 다시 수행했다거나 native MCP/모델 지연을 측정한 것은 아니다.

### 자비스 실제 CLI 호환

이미 검증한 자비스 reference CLI build `/var/tmp/sb-context-boundary-rjw8vhqx`와 최신 SB 제품으로
5시나리오를 다시 실행했다. 조회 1 record/context 2,842 bytes/stdout 3,073 bytes, 빈 결과,
불가능한 예산·공개 권한 키·철회 키 거부 모두 통과했고 자비스 authority 논리 행은 불변이었다.
`/var/tmp/sb-reference-cli-b4rCqa`, `/var/tmp/sb-generation-integrity-jarvis-cli.log`.
현재 자비스 작업의 다른 소스 변경을 빌드/배포한 것이 아니라 검증된 소비자 계약과의 회귀 인수다.
모델 전달/session receipt 완료로 계산하지 않는다.

## 남은 범위

- 이 검증은 저장된 inventory와 파일 사이의 손상을 감지한다. inventory와 DB를 함께 다시 쓰는
  행위까지 독립적으로 증명하는 서명/원문 논리 행 감사는 아니다. 새 승인/서명 엔진은 도입하지 않았다.
- stat identity cache는 정상 파일시스템 변경을 감지한다. 메타데이터가 변하지 않는 매체 손상에
  대한 매 조회 전수 감사와 같지 않다. 독립 복원/운영 감사 조건은 유지한다.
- 봉인 vector는 여전히 enabled=0이다. vector 본문·모델·논리 digest·파일 inventory를 같은
  generation/pin에 결합하고 삭제·정정·복원 시험을 통과한 뒤 활성화해야 한다.
- 실제 질문/모델 품질, 큰 corpus의 capture/run 지연, 자비스 전달 receipt/compaction/삭제·범위,
  실제 GUI와 운영 전환/DR은 미완료다. 이 오류 거부 기능을 전체 공통 기억 완성으로 대체하지 않는다.

운영 vault/서비스/DB migration/push는 변경하지 않았다. 기존 원문 정본과 자비스의 승인 역할을 유지한다.
