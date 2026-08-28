# Second Brain 단계별 개발계획서

- 문서 상태: 실행 기준선
- 기준 프로젝트: `second-brain-app`
- 현재 기준 버전: `0.1.0`
- 목표 버전: `1.0.0`
- 작성 기준일: 2026-08-28
- 주 운영 환경: Ubuntu 서버
- 보조 지원 환경: macOS
- 문서 목적: 프로젝트 방향을 고정하고, 신뢰성 복구부터 실제 운영 가능한 1.0.0까지의 구현·검증·릴리스 순서를 정의한다.

---

## 1. 프로젝트 정의

### 1.1 고정 정의

Second Brain은 여러 로컬 자료와 AI 작업 기록을 수집하여 원본을 보존하고, 출처가 추적되는 지식 페이지로 변환하며, 상충하는 정보를 분리해 관리하고, CLI·MCP·최소 웹 화면으로 검색·열람·기록할 수 있게 하는 **로컬 우선 개인 지식 엔진**이다.

이 프로젝트의 핵심 가치는 기능 수가 아니라 다음 네 가지이다.

1. **기억이 사라지지 않는다.**
2. **생성된 지식의 근거를 확인할 수 있다.**
3. **같은 입력을 반복 처리해도 결과와 상태가 일관된다.**
4. **장애가 나더라도 원본·Vault·Git으로 복구할 수 있다.**

### 1.2 목표 사용자

1. 1차 사용자: 프로젝트·대화·문서를 여러 도구에 분산 보관하는 단일 사용자
2. 2차 사용자: MCP를 통해 과거 기록을 조회해야 하는 ChatGPT, Claude, Orca 등 AI 에이전트
3. 1.0.0 범위의 운영 모델: 단일 사용자·단일 Vault·로컬 또는 사설 서버 운영

### 1.3 1.0.0에서 제공해야 하는 핵심 사용자 흐름

- `기억 추가 → 자동 수집 → 출처 포함 지식 생성 → 검색`
- `외부 자료 연결 → 변경분 수집 → 기존 지식 갱신 또는 제안본 생성`
- `사람이 지식 페이지 편집 → AI 변경은 제안본으로 분리 → 비교·승인`
- `상충 정보 발견 → 충돌 목록 확인 → 사람이 승인·해결`
- `실행 실패 확인 → 원인 확인 → 안전한 재시도`
- `백업 생성 → 새 환경에서 복원 → 동일한 지식과 검색 결과 확인`
- `AI 에이전트가 MCP로 검색·페이지 읽기·기억 추가`

---

## 2. 범위와 비범위

### 2.1 1.0.0 포함 범위

- 로컬 파일, AI 세션 기록, Unified DB 및 inbox 자료 수집
- 원본 CAS 저장과 SHA-256 무결성 검증
- SQLite 기반 ingest·derivation·run 원장
- 출처가 포함된 Markdown 지식 페이지
- 사람 편집 보호와 `_proposed` 제안본
- 충돌 탐지, 승인, 해결, supersede 이력
- 한글을 포함한 Unicode 안전 검색
- CLI, MCP, 최소 웹 관리 화면
- Ubuntu 서비스 운영 및 macOS 보조 실행
- 자동 실행, 재시도, 상태 확인, 백업·복원
- 소스별 외부 LLM 전송 정책과 민감정보 보호
- 설치·업그레이드·롤백 문서와 검증된 마이그레이션

### 2.2 1.0.0 이전 비범위

- 다중 사용자·다중 테넌트 SaaS
- 조직용 RBAC와 복잡한 권한 위임
- 네이티브 iOS·Android 앱
- 완전 자율적인 외부 시스템 수정
- 자동 삭제·자동 supersede의 무승인 실행
- 대규모 분산 처리 클러스터
- 범용 지식 그래프 플랫폼
- 커넥터 수를 늘리는 것 자체를 목표로 하는 개발
- 벡터 검색을 필수 의존성으로 만드는 구조
- 로컬 자료를 기본값으로 외부 LLM에 전송하는 구조

비범위 기능은 1.0.0 핵심 완료를 지연시키지 않는다. 새 기능 요청은 현재 단계의 완료 게이트를 통과한 뒤 별도 버전 후보로 평가한다.

---

## 3. 목표와 성공 기준

| ID | 목표 | 1.0.0 성공 기준 |
| --- | --- | --- |
| GOAL-001 | 데이터 정합성 | 원장·CAS·Vault·Git 사이에 설명되지 않는 불일치 0건 |
| GOAL-002 | 출처 신뢰성 | AI가 생성한 사실 문장과 충돌 판정에 유효한 출처가 연결됨 |
| GOAL-003 | 멱등성 | 동일 입력과 동일 모델·프롬프트 버전의 재실행에서 불필요한 LLM 호출과 커밋이 발생하지 않음 |
| GOAL-004 | 복구 가능성 | 깨끗한 새 환경에서 백업 또는 Vault+CAS로 복원 가능 |
| GOAL-005 | 사용 편의성 | 기억 추가, 검색, 페이지 열람, 충돌 해결, 실패 재시도를 웹 화면에서 수행 가능 |
| GOAL-006 | 운영 안정성 | 100회 연속 예약 실행에서 미복구 상태·중복 커밋·데이터 손실 0건 |
| GOAL-007 | 보안 | 기본값은 로컬 전용이며, 외부 LLM 전송은 소스별 명시 허용 방식 |
| GOAL-008 | 이식성 | 지원 Ubuntu와 macOS의 깨끗한 환경에서 설치·업그레이드·검증 성공 |

---

## 4. 현재 기준선

### 4.1 현재 구현 상태

현재 `0.1.0`은 다음 기능을 갖춘 기능성 Alpha이다.

- 파일·문서·AI 세션·프로젝트 기록·Unified DB 커넥터
- PDF, HWPX, DOCX, XLSX, Markdown, TXT, JSON, YAML 파서
- CAS 원본 저장
- SQLite 원장
- LLM compile, conflict, daily briefing
- Git 기반 Vault 이력
- FTS5 검색
- CLI 11개 명령
- MCP 5개 도구
- Ruff 및 BasedPyright 통과
- wheel 및 source distribution 빌드 성공

### 4.2 확인된 출시 차단 결함

| ID | 심각도 | 결함 |
| --- | --- | --- |
| DEF-P0-001 | P0 | SQLite 원장을 외부 CLI 출력으로 복원할 때 NULL 구분자가 줄바꿈으로 해석되어 상태가 사라짐 |
| DEF-P0-002 | P0 | Vault 저장·Git 커밋 전에 derivation을 `done`으로 표시하여 결과 없는 완료 상태가 생김 |
| DEF-P0-003 | P0 | conflict 페이지가 8자리 hash를 출처로 사용해 CAS 검증을 통과하지 못함 |
| DEF-P0-004 | P0 | Git의 quote path 출력 때문에 한글 파일명이 검색 인덱스에서 누락됨 |
| DEF-P1-001 | P1 | ingest의 CAS 실패와 source 기록 성공이 분리되어 재시도 누락 가능 |
| DEF-P1-002 | P1 | failed derivation의 안전한 재시도 정책이 없음 |
| DEF-P1-003 | P1 | LLM 장애가 `unrelated` 판정으로 영구 캐시될 수 있음 |
| DEF-P1-004 | P1 | Vault에서 원장을 재구축할 때 원래 derivation key를 동일하게 복원하지 못함 |
| DEF-P1-005 | P1 | frontmatter의 `compiled_by`가 실제 prompt/model 설정과 다름 |
| DEF-P1-006 | P1 | 테스트가 저장소 외부 macOS 절대 경로 fixture에 의존함 |
| DEF-P1-007 | P1 | 엄격한 파일 권한 정책이 Ubuntu 기본 `umask 0002` 및 공유 저장소와 충돌함 |

### 4.3 현재 검증 기준선

2026-08-28 분석 시점의 결과이다.

- 기본 테스트: `229 passed, 40 failed, 2 skipped`
- 권한·외부 경로 영향을 일부 분리한 테스트: `241 passed, 26 failed, 2 skipped`
- Ruff: 통과
- BasedPyright: 오류 0, 경고 0
- 패키지 빌드: 성공

이 수치는 향후 회귀 비교의 기준선이며, 성공 수치로 간주하지 않는다.

---

## 5. 개발 원칙

### PRINCIPLE-001 — P0 해결 전 기능 추가 금지

`0.1.1`이 통과하기 전에는 UI, 신규 커넥터, 벡터 검색, 지식 그래프를 개발하지 않는다.

### PRINCIPLE-002 — 상태보다 실제 산출물이 우선

원장이 `done`이라고 표시하려면 실제 파일이 존재하고, 인용 검증을 통과하며, 필요한 경우 Git 커밋까지 확인되어야 한다.

### PRINCIPLE-003 — 한 단계의 성공은 원자적이어야 함

다음 묶음은 중간 성공 상태를 외부에 노출하지 않는다.

```text
원본 저장 → 원장 기록
LLM 생성 → 인용 검증 → Vault 기록 → Git 기록 → derivation 완료
충돌 판정 → 출처 검증 → 충돌 문서 기록
```

### PRINCIPLE-004 — 실패를 사실로 바꾸지 않음

LLM timeout, JSON 오류, 파일 쓰기 실패는 `unrelated`, `없음`, `done` 같은 정상 결과로 변환하지 않는다.

### PRINCIPLE-005 — 사람의 수정과 승인이 우선

사람이 편집한 페이지는 자동 덮어쓰지 않는다. 충돌 해결, supersede, 삭제는 기본적으로 승인 기반이다.

### PRINCIPLE-006 — 재구축 가능한 파생 데이터

검색 인덱스와 원장은 가능한 범위에서 원본 CAS, Vault frontmatter, Git 이력으로 재구축 가능해야 한다. 재구축 불가능한 필드는 명시적으로 백업 대상에 포함한다.

### PRINCIPLE-007 — 로컬 우선·외부 전송 최소화

외부 LLM 전송은 명시적으로 허용된 소스만 가능하다. 허용되지 않은 자료는 로컬 처리 또는 수집 보류로 남긴다.

### PRINCIPLE-008 — 한 PR에 한 목적

상태 저장, 검색, 충돌, UI를 하나의 PR에 섞지 않는다. 각 PR은 독립적으로 검증·되돌리기가 가능해야 한다.

### PRINCIPLE-009 — 검증 실패 시 다음 버전으로 이동 금지

문제를 다음 버전으로 넘기지 않는다. 해당 버전의 릴리스 게이트가 모두 통과할 때만 다음 단계로 이동한다.

---

## 6. 요구사항 추적 ID

| ID | 요구사항 |
| --- | --- |
| REQ-DATA-001 | 프로세스 재시작 후에도 모든 원장 상태가 정확히 복원되어야 한다. |
| REQ-DATA-002 | 파일 생성형 derivation은 유효한 산출물 기록 후에만 완료되어야 한다. |
| REQ-DATA-003 | CAS 저장 실패 시 source·cursor가 성공으로 전진하지 않아야 한다. |
| REQ-RETRY-001 | 일시적 실패는 제한된 정책에 따라 재시도할 수 있어야 한다. |
| REQ-CITE-001 | 모든 출처 hash는 실제 CAS의 64자리 digest와 연결되어야 한다. |
| REQ-CONFLICT-001 | 실제 conflict 판정 결과가 검증 가능한 문서로 저장되어야 한다. |
| REQ-SEARCH-001 | 한글·공백·탭·개행·emoji 파일명을 안전하게 인덱싱해야 한다. |
| REQ-SEARCH-002 | wiki, daily, conflicts의 커밋된 문서를 검색할 수 있어야 한다. |
| REQ-PORT-001 | 테스트와 기본 설정이 특정 Mac 절대 경로에 의존하지 않아야 한다. |
| REQ-OPS-001 | 설치 환경, 설정, Git, LLM, DB, 권한을 `doctor`가 진단해야 한다. |
| REQ-OPS-002 | 예약 실행과 재시작 복구가 지원되어야 한다. |
| REQ-BACKUP-001 | 백업·복원·무결성 검증 절차가 자동화되어야 한다. |
| REQ-KNOW-001 | 기존 지식과 새 지식의 병합·제안·충돌 상태를 지속 저장해야 한다. |
| REQ-UX-001 | 핵심 사용 흐름을 CLI 학습 없이 웹에서 수행할 수 있어야 한다. |
| REQ-SEC-001 | 소스별 외부 LLM 전송 정책과 민감정보 처리가 있어야 한다. |
| REQ-PERF-001 | 대표 운영 데이터 규모에서 수집·검색·복구 성능 기준을 충족해야 한다. |
| REQ-REL-001 | 깨끗한 설치, 순차 업그레이드, 롤백이 지원 환경에서 재현되어야 한다. |

---

## 7. 릴리스 단계 개요

| 버전 | 단계명 | 핵심 결과 | 다음 단계 진입 조건 |
| --- | --- | --- | --- |
| 0.1.1 | 신뢰성 긴급 복구 | 원장·출력·충돌·한글 검색 P0 해결 | P0 회귀 테스트와 핵심 E2E 통과 |
| 0.2.0 | 이식 가능한 엔진 | 절대 경로 제거, 독립 fixture, 설정·패키징·마이그레이션 정리 | Ubuntu/macOS 깨끗한 설치 검증 |
| 0.3.0 | 운영 가능한 로컬 MVP | 예약 실행, 재시도, 진단, 백업·복원, 운영 기록 | 무인 반복 실행과 복원 훈련 통과 |
| 0.4.0 | 지식 품질 고도화 | 지속 병합, 충돌 승인·해결, 정확한 prompt/model lineage | 인용·충돌·브리핑 품질 평가 통과 |
| 0.5.0 | 검색·회수 고도화 | Unicode 안전 증분 검색, 필터, 평가 세트, 선택적 hybrid | 한국어 golden query 기준 통과 |
| 0.6.0 | 최소 웹 콘솔 | 기억·검색·페이지·충돌·실행 관리를 웹에서 제공 | 핵심 사용자 흐름 E2E 통과 |
| 0.7.0 | 소스·보안 정책 | 소스 관리, 외부 LLM 승인, 마스킹, 보존·삭제, 인증 | 보안 검증과 데이터 정책 테스트 통과 |
| 0.8.0 | 규모·관측성 | 배치 성능, 증분 처리, 메트릭, 장애 주입, 장기 반복 | 목표 데이터 규모와 100회 반복 통과 |
| 0.9.0 | Release Candidate | 기능 동결, 마이그레이션·문서·보안·운영 인수 | RC 전체 게이트 통과 |
| 1.0.0 | 안정 운영판 | 지원 범위 고정, 설치·운영·복구가 검증된 정식 릴리스 | 모든 1.0.0 완료 정의 충족 |

---

# 8. 버전별 상세 개발계획

## 8.1 Version 0.1.1 — 신뢰성 긴급 복구

### 8.1.1 목표

데이터와 처리 상태를 신뢰할 수 없는 현재 상태를 끝낸다. 기능을 추가하지 않고 `0.1.0`의 기존 핵심 경로가 재시작·실패·Unicode 환경에서도 정확히 작동하도록 만든다.

### 8.1.2 비범위

- 웹 UI
- 신규 커넥터
- 벡터 검색
- 대규모 성능 최적화
- 지식 그래프
- 디자인 변경

### 8.1.3 구현 순서

#### WP-011-01 — 실패 재현 테스트 고정

먼저 다음 회귀 테스트를 추가해 현재 코드에서 실패하는 것을 확인한다.

1. 프로세스 종료 후 pending/running/done/failed/source/cursor/run 행이 동일하게 복원되는 테스트
2. Vault lint 실패 후 derivation이 `done`으로 남지 않는 테스트
3. Git 커밋 실패 후 derivation이 완료되지 않는 테스트
4. 실제 `conflict.check()` 결과를 `Vault.write_pages()`로 저장하는 테스트
5. 한글 파일명 페이지를 커밋한 뒤 검색되는 테스트
6. 동일 입력을 두 번 실행했을 때 두 번째 LLM 호출이 0인 테스트
7. CAS 저장 실패 후 cursor와 source version이 전진하지 않는 테스트

완료 기준: 신규 테스트가 기존 코드에서 의도대로 실패하고, 결함별 원인이 분리되어야 한다.

#### WP-011-02 — SQLite 원장 로딩 교체

- 외부 `sqlite3` CLI의 separator/nullvalue 출력을 이용한 row 복원을 제거한다.
- Python `sqlite3` connection과 typed row 변환을 단일 구현으로 사용한다.
- `PRAGMA integrity_check`도 Python API로 수행한다.
- NULL, 빈 문자열, 제어문자, Unicode를 구분해 보존한다.
- 원장 읽기와 쓰기의 스키마 버전을 기록한다.
- 기존 `0.1.0` DB를 열 수 있는 호환 테스트를 추가한다.

완료 기준:

- `REQ-DATA-001` 통과
- 저장 직후와 프로세스 재시작 후 조회 결과가 동일함
- 외부 `sqlite3` 실행 파일이 없어도 원장 기능이 작동함

#### WP-011-03 — derivation 완료 시점 재설계

- L4의 compile·conflict·briefing 생성기는 산출물 후보를 만들며, 최종 `done` 소유권은 pipeline에 둔다.
- 처리 순서를 다음으로 고정한다.

```text
ensure pending
→ mark running
→ LLM 생성
→ 구조·인용·CAS 검증
→ Vault atomic write
→ Git commit 또는 검증된 no-op
→ 실제 output hash/path 기록
→ mark done
```

- Vault·Git·검증 실패는 `done`이 될 수 없다.
- stale running은 다음 실행에서 `pending`으로 복구한다.
- retryable failure를 같은 derivation key로 다시 실행할 수 있는 명시적 reset 경로를 추가한다.
- 실제 파일 hash와 derivation output hash가 일치하는지 검증한다.

완료 기준:

- `REQ-DATA-002` 통과 및 `REQ-RETRY-001`의 수동·복구 재시도 기반 확보
- “원장 done + 파일 없음” 상태를 만드는 장애 주입 테스트 0건
- 동일 입력 no-op 재실행에서 LLM 호출·Git 커밋·attempt 증가 없음

#### WP-011-04 — ingest 원자성 복구

- CAS `put` 성공 전에 source item, cursor, unit을 성공 처리하지 않는다.
- 한 source item의 CAS·source·unit·cursor 반영 순서를 명시한다.
- 중간 실패 시 재실행으로 동일 입력을 다시 처리할 수 있어야 한다.
- DB transaction 범위를 정의해 부분 기록을 방지한다.

완료 기준:

- `REQ-DATA-003` 통과
- 디스크 쓰기 실패와 DB 실패를 각각 주입해도 다음 실행에서 복구됨

#### WP-011-05 — conflict 출처 계보 수정

- conflict 후보의 left/right ID를 실제 `Unit` 또는 `PageSpec` 출처로 해석한다.
- `SourceCite.hash`에는 실제 64자리 CAS digest를 넣는다.
- unit 출처는 origin과 span을 보존한다.
- page 출처는 기존 frontmatter의 source 목록을 재사용한다.
- LLM이 존재하지 않는 cite ID를 반환하면 새 출처를 만들지 않고, 입력 쌍으로 fallback하며 warning을 남긴다.
- 판정 오류와 실제 `unrelated`를 다른 상태로 기록한다.

완료 기준:

- `REQ-CITE-001`, `REQ-CONFLICT-001` 통과
- 실제 conflict 페이지가 `conflicts/`에 커밋되고 `sb_open_conflicts`에서 조회됨

#### WP-011-06 — Unicode 안전 Git 검색

- Git 경로 목록은 NUL 구분 출력으로 읽는다.
- `core.quotepath`와 무관하게 원래 Unicode 경로를 복원한다.
- `wiki/`, `daily/`, `conflicts/`를 모두 검색 범위에 포함한다.
- 한글, emoji, 공백, 탭, 개행이 포함된 경로 테스트를 추가한다.
- 제안본 `_proposed`는 계속 제외한다.

완료 기준:

- `REQ-SEARCH-001`, `REQ-SEARCH-002` 통과
- `remember → ingest → compile → search` 한글 E2E 성공

#### WP-011-07 — 실제 prompt/model lineage 기록

- `Vault.write_pages()`가 고정된 `v1|unknown`을 쓰지 않도록 한다.
- pipeline이 실제 package version, prompt version, model ID를 전달한다.
- frontmatter, derivation key, 재구축 로직이 같은 값을 사용한다.

완료 기준:

- fake 모델 테스트 페이지에는 `fake`가 기록됨
- CLI 모델 사용 시 설정된 model ID가 기록됨

### 8.1.4 0.1.1 검증 게이트

#### 기능 검증

- 모든 P0 재현 테스트 통과
- 기존 핵심 테스트 회귀 없음
- `sb init`, `remember`, `ingest`, `compile`, `brief`, `search`, `doctor`, MCP smoke 통과

#### 적대적 검증

다음 경계마다 강제 예외 또는 프로세스 중단을 주입한다.

- CAS 쓰기 전·후
- DB source 기록 전·후
- LLM 반환 전·후
- Vault 임시 파일 쓰기 전·후
- atomic rename 전·후
- Git add 전·후
- Git commit 전·후
- derivation done 전·후

각 장애 후 재실행했을 때 데이터 손실 없이 정상 상태로 수렴해야 한다.

#### 릴리스 게이트

- P0 미해결 0건
- P1 신규 발생 0건
- Ruff 통과
- BasedPyright 통과
- 독립 핵심 테스트 100% 통과
- clean Git 상태에서 패키지 빌드 성공
- migration/rollback 절차 기록

### 8.1.5 롤백

- DB 스키마 변경이 있다면 변경 전 DB 자동 백업
- 새 코드는 구 스키마를 읽을 수 있어야 함
- 롤백 시 새 필드를 무시해도 원본 CAS와 Vault는 유지
- 어떠한 롤백도 `raw/`, `wiki/`, `daily/`, `conflicts/`를 자동 삭제하지 않음

---

## 8.2 Version 0.2.0 — 이식 가능한 엔진

### 8.2.1 목표

Mac의 특정 폴더에서만 검증되는 저장소를 Ubuntu와 macOS의 깨끗한 환경에서 재현 가능한 패키지로 바꾼다.

### 8.2.2 주요 작업

#### WP-020-01 — 테스트 fixture 독립화

- `/Volumes/DevSpace/...` 절대 경로 제거
- 실제 형식 fixture는 비밀정보를 제거한 최소 샘플로 `tests/fixtures/`에 포함
- live 데이터 테스트는 명시적 환경 변수로만 실행
- 외부 fixture 부재는 실패가 아니라 skip 사유로 명확히 분리
- 저장소 복사본에서도 같은 결과가 나오는지 검증

#### WP-020-02 — 경로와 기본 설정 이식성

- 기본 프로젝트 경로를 코드에 고정하지 않는다.
- 설정 우선순위를 `SB_CONFIG → 사용자 설정 경로 → 명시적 기본값`으로 정리한다.
- `config.example.toml` 제공
- 상대 경로, `~`, 환경 변수, Unicode 경로 처리 규칙 정의
- README의 Mac 절대 경로 예시를 교체한다.

#### WP-020-03 — 파일 접근 정책 모드

다음 정책을 제공한다.

- `strict`: 현재와 같은 owner-only 수준
- `trusted-root`: 사용자가 명시 승인한 root에서 group writable 허용
- `audit-only`: 거부 대신 경고하되 민감 파일·symlink·path escape는 계속 차단

기본값은 `strict`이며, 정책 완화는 명시적 설정이 필요하다.

#### WP-020-04 — 설정 스키마와 진단

`sb doctor`가 다음을 점검한다.

- Python 및 package version
- Git 설치와 Vault repository 상태
- SQLite schema·integrity
- LLM CLI 존재 여부와 timeout smoke
- source root 존재·권한·민감 경로
- CAS와 frontmatter의 hash 연결
- 지원 parser 의존성
- MCP import와 stdio smoke
- scheduler 관련 항목은 0.3.0 도입 전 `N/A`, 도입 후 상태와 설정 오류를 진단

진단 결과는 `OK`, `WARN`, `FAIL`과 해결 방법으로 출력한다.

#### WP-020-05 — 버전형 DB 마이그레이션

- schema version 테이블 도입
- `sb migrate --check`, `sb migrate --apply` 또는 동등 명령 제공
- 모든 migration은 반복 실행 가능해야 한다.
- migration 전 자동 백업과 검증
- downgrade 가능 여부를 migration별로 기록

#### WP-020-06 — 패키징·지원 환경 검증

- `uv_build` 버전 범위 정리
- wheel과 source distribution 설치 테스트
- Ubuntu와 macOS CI matrix
- Python 3.12 지원 고정
- 필수 시스템 의존성과 선택 의존성 구분
- 선택적 embeddings가 없어도 기본 기능 전체 작동

### 8.2.3 비범위

- 웹 UI
- 원격 공개 서비스
- 신규 데이터 소스
- 검색 품질 고도화

### 8.2.4 완료 기준

- `REQ-PORT-001`, `REQ-OPS-001`, `REQ-REL-001` 일부 통과
- 저장소 외부 fixture 없이 기본 테스트 통과
- 깨끗한 Ubuntu와 macOS에서 설치·init·smoke 성공
- README 명령을 그대로 복사해 실행 가능
- 외부 `sqlite3` CLI 없이 핵심 기능 작동

---

## 8.3 Version 0.3.0 — 운영 가능한 로컬 MVP

### 8.3.1 목표

사용자가 매번 명령을 직접 실행하지 않아도 안전하게 수집·컴파일·브리핑이 반복되는 상태를 만든다.

### 8.3.2 주요 작업

#### WP-030-01 — 실행 상태 모델

run 상태를 최소한 다음으로 구분한다.

```text
queued → running → ok | capped | partial | failed | cancelled
```

- stage별 시작·종료·처리량·오류를 저장
- 사용자 중단과 비정상 종료를 구분
- 마지막 성공 시점과 마지막 실패 시점 제공
- `status --json` 지원

#### WP-030-02 — 재시도 정책

- retryable/final 오류 분류
- LLM timeout, 일시적 I/O, DB lock은 제한 재시도
- 잘못된 설정, unsupported format, citation violation은 자동 무한 재시도 금지
- exponential backoff와 최대 attempts
- CLI와 웹에서 강제 재시도 가능
- 같은 key의 실패 이력 보존

#### WP-030-03 — 예약 실행

- Ubuntu systemd service·timer 우선 지원
- macOS launchd 보조 지원
- 설치·제거·상태 확인 스크립트
- 중복 실행 lock 유지
- 재부팅 후 자동 복구
- 예약 실행은 기본적으로 `ingest → compile → 조건부 brief`

#### WP-030-04 — 운영 로그와 상태 파일

- 구조화된 run log
- 사용자용 간단 로그와 디버그 로그 분리
- 비밀값 redaction
- 로그 보존·rotation 정책
- 실패 요약에 source, stage, error class, retry 가능 여부 포함

#### WP-030-05 — 백업·복원 1차

백업 대상:

- Git Vault
- raw CAS
- ledger DB
- 설정 파일의 비밀값 제외 사본
- schema/version manifest
- SQLite online backup API 또는 동등한 일관 스냅샷 사용
- 백업 시점의 Git commit과 DB schema version 결합

기능:

- `sb backup create`
- `sb backup verify`
- `sb restore --target <empty-dir>`
- checksum manifest
- 복원 후 `doctor` 자동 실행

#### WP-030-06 — 운영 런북

- 최초 설치
- 예약 실행
- LLM 장애
- DB corruption
- missing CAS
- Git commit 실패
- 디스크 부족
- 백업·복원
- 안전한 종료와 재시작
- 버전 업그레이드

### 8.3.3 완료 기준

- `REQ-OPS-002`, `REQ-BACKUP-001` 1차 통과
- 20회 연속 예약 실행에서 미복구 상태 0건
- 강제 재부팅 후 다음 실행이 정상 수렴
- 백업을 새 빈 경로에 복원하고 같은 page count·CAS count·검색 결과 확인
- 사용자가 로그에서 실패 source와 해결 방법을 확인 가능

---

## 8.4 Version 0.4.0 — 지식 품질 고도화

### 8.4.1 목표

원본 문서별 요약기에 머무르지 않고, 기존 지식과 새 지식의 관계를 지속적으로 관리하는 세컨드브레인으로 발전시킨다.

### 8.4.2 주요 작업

#### WP-040-01 — 기존 본문 영속 로딩

- 프로세스 메모리 `_BodyCache`에 의존하지 않는다.
- 기존 본문은 committed Vault와 검증된 frontmatter에서 읽는다.
- 같은 page ID 갱신 시 기존 내용, 신규 unit, 사람 편집 여부를 함께 입력한다.
- 프로세스 재시작 전후 생성 결과가 동일해야 한다.

#### WP-040-02 — 페이지 역할 분리

최소 두 종류를 구분한다.

1. **Source page**: 한 원본 또는 한 세션의 출처 보존형 페이지
2. **Canonical page**: 동일 주제의 여러 source page를 사람이 승인해 합친 페이지

자동 주제 병합은 기본 금지한다. 추천만 생성하고 사용자가 승인한 경우에만 canonical mapping을 저장한다.

#### WP-040-03 — 충돌 생명주기

상태:

```text
open → confirmed → resolved
open → dismissed
confirmed → superseded
```

- 충돌 양쪽 주장과 전체 출처 표시
- 자동 supersede는 날짜·신뢰도·정책 조건을 모두 만족해도 제안 상태로만 생성
- 해결 시 선택 근거와 사용자 결정 기록
- resolved 충돌은 역사로 남기고 검색 가능

#### WP-040-04 — 주장·인용 검증

- 생성된 각 사실 문장의 footnote 존재 확인
- footnote가 page source에 존재하는지 확인
- source hash가 CAS와 일치하는지 확인
- 동일 sid prefix 충돌 처리
- 인용 없는 추천·브리핑 문장은 명확한 warning 또는 생성 실패 처리

#### WP-040-05 — prompt와 model 버전 관리

- prompt 파일 hash 또는 version 기록
- model ID, adapter, 주요 generation 옵션 기록
- 모델 또는 prompt 변경 시 derivation key가 달라짐
- 이전 결과와 신규 결과 비교 가능

#### WP-040-06 — 브리핑 품질

- 입력 facts hash가 같으면 no-op
- previous run status만 달라져도 불필요한 LLM 호출을 하지 않도록 정책 분리
- 새 자료, 열린 충돌, 오래된 페이지, 예정 항목을 검증 가능한 canonical format으로 전달
- 추천 수가 부족할 때 가짜 인용을 생성하지 않음

### 8.4.3 완료 기준

- `REQ-KNOW-001`, `REQ-CITE-001`, `REQ-CONFLICT-001` 고도화 통과
- 프로세스 재시작 전후 동일 입력 결과 일치
- 충돌 생성·확인·해결·역사 조회 E2E 통과
- 사람이 편집한 page를 AI가 직접 덮어쓰는 사례 0건
- 모델·prompt별 결과 계보 확인 가능

---

## 8.5 Version 0.5.0 — 검색·회수 고도화

### 8.5.1 목표

사용자가 저장된 기억을 실제로 찾을 수 있도록 한국어 중심의 정확하고 빠른 검색을 제공한다.

### 8.5.2 주요 작업

#### WP-050-01 — 증분 FTS 인덱스

- 매 검색마다 전체 테이블을 drop/rebuild하지 않는다.
- Git commit 또는 page content hash 기준으로 변경된 문서만 반영
- 삭제·rename 처리
- 인덱스 버전과 마지막 반영 commit 기록
- 인덱스 손상 시 전체 rebuild 가능

#### WP-050-02 — 검색 필드 확대

검색 대상:

- page title
- section title
- body
- source origin
- status
- page type
- conflict state
- updated date

#### WP-050-03 — 검색 필터와 정렬

- source 필터
- wiki/daily/conflict 필터
- 날짜 범위
- active/conflicted/resolved/proposed 상태
- relevance/newest 정렬

#### WP-050-04 — 한국어 검색 평가 세트

대표 실제 사용 질문을 익명화한 golden query 세트를 만든다.

평가 항목:

- Top-1 정확도
- Top-5 recall
- 제목·본문·부분 문자열
- 조사·띄어쓰기 차이
- 영문+한글 혼합
- 동일 단어가 많은 문서의 ranking

1.0 목표 전 단계 기준:

- 핵심 golden query Top-5 recall 90% 이상
- 저장 직후 검색 반영 성공률 100%

#### WP-050-05 — 선택적 hybrid

- lexical이 기본이며 optional embeddings가 없어도 완전 작동
- hybrid는 feature flag
- lexical 결과보다 나빠질 경우 자동 fallback
- 모델 다운로드와 로컬 데이터 전송 여부를 명시
- 검색 결과에 사용된 retrieval mode 표시

### 8.5.3 완료 기준

- `REQ-SEARCH-001`, `REQ-SEARCH-002`, `REQ-PERF-001` 일부 통과
- 한글 remember E2E 검색 성공
- wiki/daily/conflicts 모두 검색 가능
- index rebuild 후 동일 query 결과 재현
- 10,000개 page 기준 검색 응답 성능 목표를 측정하고 기준 문서화

---

## 8.6 Version 0.6.0 — 최소 웹 콘솔

### 8.6.1 목표

CLI를 몰라도 핵심 기능을 사용할 수 있는 최소 관리 화면을 제공한다. 이 단계는 새로운 지식 엔진을 만드는 것이 아니라 기존 안정화된 기능을 얇게 노출한다.

### 8.6.2 권장 기술 방향

- Python 기반 경량 웹 서버
- FastAPI 또는 동등한 최소 프레임워크
- Jinja/HTMX 계열 서버 렌더링 우선
- React 기반 대형 SPA는 비범위
- 기본 bind는 `127.0.0.1`
- 비즈니스 로직은 기존 service/pipeline 계층을 호출하고 UI에 복제하지 않음

### 8.6.3 화면

1. **Dashboard**
   - 최근 실행 상태
   - 신규 자료 수
   - 열린 충돌 수
   - 실패한 source 수
   - 마지막 백업

2. **Remember**
   - 내용과 선택적 제목 입력
   - inbox 저장 결과 표시
   - 다음 처리 예정 상태 표시

3. **Search**
   - 검색창
   - 필터
   - 결과 snippet, 출처, 상태

4. **Page Detail**
   - 본문
   - frontmatter 요약
   - 출처 목록과 원본 hash
   - Git 변경 이력
   - proposed page 비교

5. **Conflicts**
   - 양쪽 주장
   - 출처
   - 판정과 confidence
   - confirm, dismiss, resolve, supersede 제안 승인

6. **Runs**
   - stage별 상태
   - 오류 원인
   - 재시도
   - 관련 로그

7. **System**
   - doctor 결과
   - version
   - backup 상태
   - source read-only 목록

### 8.6.4 API 원칙

- 페이지 읽기와 검색은 read-only
- 기억 추가는 기존 inbox writer만 사용
- conflict 변경과 retry는 명시적 사용자 액션
- filesystem path를 클라이언트 입력 그대로 사용하지 않음
- CSRF, input size, path escape, output escaping 검증

### 8.6.5 완료 기준

- `REQ-UX-001` 통과
- 기억 추가→처리→검색 사용자 E2E
- 충돌 확인→해결 사용자 E2E
- 실패 run→원인 확인→재시도 사용자 E2E
- CLI 결과와 웹 결과가 동일한 service 계층을 사용
- 로컬 bind 기본값에서 외부 노출되지 않음

---

## 8.7 Version 0.7.0 — 소스 관리와 보안 정책

### 8.7.1 목표

자료를 어디에서 가져오고 어디까지 외부 모델에 보낼 수 있는지 사용자가 통제할 수 있게 한다.

### 8.7.2 주요 작업

#### WP-070-01 — 소스 관리

- source list/add/edit/enable/disable/test
- metadata-only discovery preview
- 예상 파일 수와 총 크기 표시
- cursor reset은 승인 필요
- source 삭제와 수집 중지는 분리
- source별 cap, schedule, parser policy

#### WP-070-02 — 데이터 분류 정책

소스별 등급:

- `local-only`
- `external-llm-allowed`
- `redact-before-external`
- `metadata-only`
- `disabled`

기본값은 `local-only`이다.

#### WP-070-03 — 민감정보 처리

- secret pattern 탐지
- 개인정보 masking 정책
- 원문 보존 여부와 LLM 전달본 분리
- redaction 전·후 hash와 audit 기록
- 숨은 reasoning 또는 민감 경로 차단 유지
- false positive를 사람이 검토할 수 있는 quarantine

#### WP-070-04 — LLM 라우팅

- source policy에 따라 local/CLI/external adapter 선택
- 외부 모델 미허용 자료는 전송 차단
- model별 timeout, budget, maximum calls
- 요청·응답 원문 로그는 기본 저장하지 않음
- token·비용 metadata만 선택 저장

#### WP-070-05 — 인증과 원격 접근

- loopback 이외 bind 시 인증 필수
- 세션 보안과 CSRF
- reverse proxy/TLS 운영 가이드
- MCP write 도구 권한 분리
- destructive action은 별도 approval token 또는 UI 확인

#### WP-070-06 — 보존·삭제 정책

- source 중지, 파생 page 제거, 원본 CAS 삭제를 별도 작업으로 분리
- dry-run과 영향 범위 제공
- Git 이력에 남는 데이터에 대한 명확한 경고
- backup에서의 삭제 정책 정의
- orphan CAS 탐지와 승인 기반 정리

#### WP-070-07 — 암호화 백업

- checksum manifest 유지
- 선택적 encrypted archive
- 복호화 key는 저장소와 분리
- restore drill 자동화

### 8.7.3 완료 기준

- `REQ-SEC-001`, `REQ-BACKUP-001` 고도화 통과
- local-only source가 외부 LLM adapter에 전달되는 테스트 0건
- 인증 없이 non-loopback bind 불가
- 삭제 dry-run이 영향을 받는 page·CAS·derivation을 정확히 표시
- 암호화 백업을 새 환경에서 복원 성공

---

## 8.8 Version 0.8.0 — 규모·성능·관측성

### 8.8.1 목표

대표 운영 데이터 규모와 반복 실행에서 성능이 급격히 저하되지 않고, 장애 원인을 수치로 확인할 수 있게 한다.

### 8.8.2 목표 부하 기준

최소 검증 데이터셋:

- source file 5,000개
- normalized unit 100,000개
- committed page 10,000개
- conflict record 1,000개
- 연속 예약 실행 100회

수치는 성능 검증 기준이며 제품의 하드 제한이 아니다.

### 8.8.3 주요 작업

#### WP-080-01 — DB transaction과 batch

- row마다 commit하는 경로 제거
- source 단위 또는 stage 단위 transaction
- WAL checkpoint 정책
- busy timeout과 lock 관측
- 장시간 transaction 방지

#### WP-080-02 — 증분 compile과 conflict 후보 축소

- 변경 unit만 compile 후보로 선정
- 이미 비교한 conflict pair 재사용
- lexical 후보 생성의 비용 측정
- 최대 LLM call cap과 partial continuation token
- capped run의 다음 실행 재개

#### WP-080-03 — 검색 성능

- 증분 index update
- query latency 측정
- index corruption 자동 감지·rebuild
- hybrid model lazy load
- 메모리 사용 상한

#### WP-080-04 — 관측 지표

- run duration
- source별 items·bytes·units
- parser skip/error 분포
- LLM calls·timeout·bad output
- pages·proposals·conflicts
- DB size·CAS size·orphan count
- search latency·index age
- backup age·verify 결과

#### WP-080-05 — 장애 주입과 복구

- 프로세스 kill
- DB lock
- DB corruption copy
- 디스크 full simulation
- permission denied
- Git failure
- malformed LLM output
- clock/timezone change
- source mutation during read
- concurrent run

#### WP-080-06 — 장기 반복 검증

- 100회 예약 실행
- 동일 자료 no-op
- 중간 신규 자료 추가
- 중간 모델 timeout
- 중간 재부팅
- 중간 backup/restore

### 8.8.4 완료 기준

- `REQ-PERF-001`, `GOAL-006` 통과
- 목표 데이터셋에서 OOM 없음
- 100회 실행 후 원장·CAS·Vault audit 오류 0건
- no-op 실행의 불필요한 LLM 호출 0
- 장애 후 수동 DB 수정 없이 정상 수렴
- 성능 기준과 측정 환경 문서화

---

## 8.9 Version 0.9.0 — Release Candidate

### 8.9.1 목표

기능 개발을 동결하고 설치·업그레이드·보안·복구·문서·사용성의 출시 증거를 완성한다.

### 8.9.2 기능 동결 원칙

허용:

- 결함 수정
- 성능 회귀 수정
- 보안 수정
- 문서·설치·마이그레이션 수정
- 접근성·사용성의 차단 문제 수정

금지:

- 신규 커넥터
- 신규 대형 화면
- 데이터 모델의 불필요한 재설계
- 새로운 자동화 기능
- 실험적 모델 라우팅

### 8.9.3 주요 작업

#### WP-090-01 — 전체 migration chain

- 0.1.0 데이터 샘플에서 0.9.0까지 순차 upgrade
- 각 schema version 중간 재시작
- 실패 migration rollback
- 백업에서 복원 후 upgrade
- migration 재실행 멱등성

#### WP-090-02 — 설치·업그레이드·삭제

- Ubuntu clean install
- macOS clean install
- wheel 설치
- source install
- service install/remove
- configuration migration
- uninstall 시 사용자 Vault 보존

#### WP-090-03 — 보안 검증

- path traversal
- symlink/hardlink
- secret file denial
- external LLM policy bypass
- web auth/session/CSRF
- MCP input validation
- backup secret handling
- dependency 취약점 검토

#### WP-090-04 — 운영 인수

필수 문서:

- README
- INSTALLATION-AND-RUN
- CONFIGURATION
- OPERATIONS-RUNBOOK
- BACKUP-RESTORE
- SECURITY-AND-DATA-POLICY
- MIGRATION
- TROUBLESHOOTING
- RELEASE-NOTES
- OSS-LICENSE-INVENTORY

#### WP-090-05 — 사용자 승인 테스트

시나리오:

1. 기억 추가와 검색
2. 폴더 source 연결과 변경분 수집
3. 사람 편집 보호와 proposed 비교
4. 충돌 발견과 해결
5. 예약 실행 실패와 재시도
6. 백업·복원
7. AI 에이전트 MCP 검색

#### WP-090-06 — 릴리스 증거

버전별로 다음을 남긴다.

- commit SHA
- package checksum
- test summary
- supported platform result
- migration result
- backup/restore result
- security checklist
- known limitations
- rollback procedure

### 8.9.4 완료 기준

- P0 0건, P1 0건
- 기능 동결 후 전체 회귀 통과
- 깨끗한 환경 설치·업그레이드·롤백 성공
- 운영 문서의 명령을 제3자가 그대로 실행해 성공
- 사용자 승인 시나리오 전체 통과
- RC에서 발견된 문제는 0.9.x에서만 수정 후 재검증

---

## 8.10 Version 1.0.0 — 안정 운영판

### 8.10.1 1.0.0 고정 제공 범위

- 단일 사용자·단일 Vault
- Ubuntu 우선, macOS 보조
- CLI, MCP, 로컬 웹 콘솔
- 검증된 기본 커넥터 집합
- CAS 원본 보존
- 출처 포함 지식 페이지
- 사람 편집 보호
- 충돌 승인·해결
- 한국어·Unicode 검색
- 예약 실행과 재시도
- 백업·복원
- 소스별 LLM 전송 정책
- 설치·업그레이드·롤백

### 8.10.2 1.0.0 완료 정의

다음 항목을 모두 만족해야 한다.

#### 제품

- 핵심 사용자 흐름 7개 모두 통과
- 일반 사용자가 CLI 없이 기억 추가·검색·충돌 해결·실패 재시도 가능
- UI가 없는 기능은 명확한 운영자 기능으로 문서화

#### 데이터

- CAS hash audit 100% 통과
- 모든 active page의 citation audit 통과
- 원장·Vault·Git 불일치 0건
- 동일 입력 no-op 재실행에서 LLM 호출 0

#### 운영

- 100회 연속 예약 실행 통과
- 재부팅·프로세스 중단·LLM 장애 후 자동 수렴
- 백업을 새 환경에 복원하고 검색 결과 재현
- doctor의 FAIL 0건

#### 이식성

- 지원 Ubuntu clean install 통과
- 지원 macOS clean install 통과
- 0.1.0 또는 정의된 최소 지원 버전에서 upgrade 통과
- uninstall이 사용자 데이터에 손상을 주지 않음

#### 보안

- local-only 기본값
- non-loopback 웹 bind 시 인증 필수
- source policy를 우회한 외부 LLM 전송 0건
- path escape, symlink, hardlink, 민감 파일 검증 통과

#### 품질

- 전체 자동 테스트 통과
- Ruff 통과
- BasedPyright 통과
- wheel/source package 빌드·설치 통과
- P0·P1 known issue 0건
- known limitation 문서화

#### 릴리스

- version, tag, checksum, release notes 일치
- migration·rollback·backup/restore 문서 완성
- 라이선스 및 OSS inventory 완성
- Git working tree clean

---

# 9. 단계별 공통 검증 체계

## 9.1 테스트 피라미드

### Unit

- 계약 객체와 상태 전이
- parser와 normalizer
- CAS와 hash
- path와 Unicode
- prompt output parser
- citation validator

### Component

- connector → CAS → ledger
- units → compile candidate
- conflict candidate → validated page
- Vault write → Git commit
- committed pages → search index

### Integration

- 실제 SQLite DB 재시작
- 실제 Git repository
- 실제 filesystem atomic rename
- CLI subprocess
- MCP stdio client
- 웹 API와 UI

### E2E

- remember → search
- source change → page update/proposal
- conflict → resolve
- failed run → retry
- backup → clean restore
- upgrade → run → rollback

## 9.2 필수 적대적 입력

- 빈 LLM 응답
- 인용 없는 응답
- 존재하지 않는 sid
- 잘못된 JSON
- 매우 큰 응답
- timeout과 command not found
- 한글·emoji·공백·탭·개행 파일명
- symlink·hardlink·FIFO·device file
- source read 중 mutation
- DB lock·corruption
- disk full·permission denied
- Git add/commit 실패
- 동시에 두 번 실행
- timezone·DST·UTC Z/offset timestamp

## 9.3 릴리스별 필수 산출물

- 변경 요구사항 ID
- architecture decision 또는 변경 이유
- migration 유무
- 테스트 추가 내역
- 적대적 검증 결과
- rollback 방법
- README/운영 문서 변경
- 알려진 제한

---

# 10. 구현 작업 관리 규칙

## 10.1 이슈 형식

각 이슈는 다음을 포함한다.

```text
ID
대상 버전
관련 요구사항
문제와 재현 절차
범위 / 비범위
구현 결정
수용 기준
테스트 계획
롤백 계획
```

권장 이슈 ID:

```text
SB-011-DATA-001
SB-011-SEARCH-001
SB-020-PORT-001
SB-030-OPS-001
```

## 10.2 PR 순서

- 한 work package는 하나 이상의 작은 PR로 분리
- 테스트 또는 재현 PR을 구현 PR보다 먼저 제출 가능
- 대규모 리팩터링과 기능 변경을 같은 PR에 넣지 않음
- 모든 PR은 관련 REQ와 수용 기준을 설명
- merge 전 가장 가까운 테스트와 전체 핵심 테스트 실행
- release gate 통과 전 버전 완료 선언 금지

## 10.3 버전 진행 규칙

```text
상태 분석
→ 버전 계획 확인
→ 재현 테스트
→ 구현
→ 단위·통합 검증
→ 적대적 검증
→ 문제 수정
→ 재검증
→ clean install 검증
→ release evidence
→ 버전 완료
→ 다음 버전 시작
```

검증에서 문제가 발견되면 같은 버전 구현 단계로 돌아간다. 문제를 남긴 채 다음 버전으로 이동하지 않는다.

---

# 11. 요구사항 추적 매트릭스

| 요구사항 | 최초 완료 / 고도화 버전 | 핵심 증거 |
| --- | --- | --- |
| REQ-DATA-001 | 0.1.1 | restart ledger integration test |
| REQ-DATA-002 | 0.1.1 | vault/git fault injection test |
| REQ-DATA-003 | 0.1.1 | CAS failure recovery E2E |
| REQ-RETRY-001 | 0.1.1 기반, 0.3.0 정책 고도화 | retry recovery test, policy component/E2E |
| REQ-CITE-001 | 0.1.1, 0.4.0 고도화 | conflict write test, citation audit |
| REQ-CONFLICT-001 | 0.1.1, 0.4.0 고도화 | create/list/resolve conflict E2E |
| REQ-SEARCH-001 | 0.1.1 | Unicode path search test |
| REQ-SEARCH-002 | 0.1.1, 0.5.0 고도화 | wiki/daily/conflicts search test |
| REQ-PORT-001 | 0.2.0 | Ubuntu/macOS CI, internal fixture test |
| REQ-OPS-001 | 0.2.0 | doctor clean-environment test |
| REQ-OPS-002 | 0.3.0 | scheduler restart/recovery test |
| REQ-BACKUP-001 | 0.3.0, 0.7.0 고도화 | clean restore and encrypted restore |
| REQ-KNOW-001 | 0.4.0 | canonical/proposal/conflict lifecycle E2E |
| REQ-UX-001 | 0.6.0 | browser core-flow E2E |
| REQ-SEC-001 | 0.7.0 | policy bypass and auth tests |
| REQ-PERF-001 | 0.8.0 | target dataset benchmark and 100-run soak |
| REQ-REL-001 | 0.9.0 | clean install/upgrade/rollback matrix |

---

# 12. 주요 위험과 대응

| 위험 | 영향 | 대응 버전 |
| --- | --- | --- |
| 원장과 실제 파일 불일치 | 기억 영구 누락 또는 중복 처리 | 0.1.1 |
| 외부 fixture 의존 | Ubuntu 검증 불가 | 0.2.0 |
| 실패의 영구 캐시 | 일시 장애가 지식 누락으로 고착 | 0.1.1~0.3.0 |
| 충돌 오판정 | 잘못된 사실을 정답으로 취급 | 0.4.0, 승인 기반 |
| 검색 누락 | 저장됐지만 찾을 수 없음 | 0.1.1, 0.5.0 |
| 외부 LLM 정보 유출 | 개인정보·업무정보 노출 | 0.7.0 |
| 전체 인덱스 재생성 | 데이터 증가 시 검색 지연 | 0.5.0, 0.8.0 |
| row별 DB commit | 대규모 처리 성능 저하 | 0.8.0 |
| UI가 엔진 로직을 복제 | CLI·웹 결과 불일치 | 0.6.0 service 계층 고정 |
| 기능 확장으로 핵심 완료 지연 | 1.0.0 미완성 | 전 단계 범위 고정 |

---

# 13. 1.0.0 이후 후보

다음은 1.0.0 완료 후 별도 평가한다.

- 다중 사용자와 팀 Vault
- 네이티브 모바일 앱
- Gmail·Google Drive·Notion 직접 커넥터
- topic clustering 자동 추천 고도화
- claim graph와 시간축 fact graph
- 여러 Vault의 연합 검색
- 원격 동기화
- 모델 품질 자동 평가와 routing
- 플러그인형 커넥터 SDK

이 후보들은 1.0.0의 고정 정의를 변경하지 않는다. 1.0.0은 단일 사용자 로컬 지식 엔진으로 완결되어야 한다.

---

# 14. 즉시 실행할 첫 작업

첫 개발 배치는 반드시 다음 순서를 따른다.

1. `0.1.1` 브랜치 또는 작업 단위 생성
2. DEF-P0-001~004 재현 테스트 추가
3. SQLite 원장 로더 교체
4. derivation 완료 시점 수정
5. conflict 전체 CAS lineage 수정
6. Unicode Git 검색 수정
7. ingest 원자성 수정
8. 전체 핵심 테스트와 fault injection
9. 깨끗한 Ubuntu 환경 설치·E2E
10. 0.1.1 릴리스 증거 작성

이 열 단계가 모두 완료되기 전에는 `0.2.0` 작업을 시작하지 않는다.
