# 자비스 공통 기억 완성 — 인계 병합 후 상세 분석

기준: Second Brain `b8d9579`, JARVIS `30e2024a55ab16c5163024c2738313025b624ccd`. 자비스의 작업 중 변경은 제외한 커밋 소스를 격리 빌드해 대조했다. 이 문서는 기존 [24개 R/I/G 항목](IMPROVEMENT-BACKLOG-2026-09-07.md)과 [B0~B8 구현 원장](IMPLEMENTATION-STATUS.md)의 최신 읽기용 정리이며 별도 범위를 만드는 계획이 아니다.

후속 구현: [일반 여러 줄 V3 인수](REMEMBER-V3-ACCEPTANCE-2026-09-08.md). 아래 V1 제약은 구형 계약의 동작 기록이며, 명시적 새 계약으로 일반 Enter 저장·완료 소비를 연결했다. 새 버전의 실제 CLI/MCP 검증과 운영 미배포 한계는 후속 보고서를 따른다.

## 1. 현재 동작 판정

**격리된 실제 프로세스에서 자비스 저장 요청→Second Brain 처리→전체 기억 재조회→자비스 명령 완료는 검증됐다. 실제 에이전트 앱들의 중앙 기억 운영 완료는 아직 아니다.**

| 확인한 범위 | 확보한 증거 | 아직 말할 수 없는 것 |
|---|---|---|
| 원문 보존·인용·단일 writer·세대별 조회 | 기존 수집/복원·충돌/종료·MCP 계약 회귀. 최신 제품 소스 전체 검사 591 passed, 2 skipped | 모든 운영 자료·실제 설치 조합의 인수 완료 |
| 자비스 remember 순환 | 격리 실제 MCP에서 민감 record 64개, 두 클라이언트 회수, provider proved/outbox settled/control completed, 추가 dispatch 0 | 일반 Enter 본문 지원, 서로 다른 실제 앱의 자동 수집·주입 |
| 자비스 correct 순환 | 정정 후 4개 record, 이전 기억 0개. 마지막 event 실패와 lease 만료 후 원래 증거로 복구, 전송·compaction 각 1회 | 실제 사용자의 정정 화면부터 운영 provider까지 연결된 전체 인수 |
| 운영 준비 상태 | 실제 CLI/HTTP에서 검증 전 ready 503→검증 후 200→백업 손상 후 503, health 200 유지 | 운영 배포, 새 호스트의 전체 runtime 복구 및 RPO/RTO |
| 이번 본문 대조 | 실제 Python 접수 함수·JARVIS 본문/요청 검증기 12개 입력 대조. 수락 4개는 정확 재시도, 거부 8개는 요청 파일·DB 생성 없음 | MCP/HTTP/브라우저 전체 경로의 이번 신규 실사용 검증 |

기존 증거: [기억 결과 계약](REMEMBER-ARTIFACT-CONTRACT-2026-09-08.md), [정정 완료 복구](CORRECTION-CONTROL-COMPLETION-2026-09-08.md), [준비 상태·백업](READINESS-VERIFICATION-2026-09-08.md). 591/2는 직전 제품 코드 검사의 기록이며 이번 문서 작업에서 전체 pytest를 다시 실행한 수치가 아니다.

## 2. 인계 결정과 기존 구현의 대응

[인계 원문](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)의 2026-09-08 갱신 내용을 확인했다. 역할은 Second Brain=개인·업무 기억, JARVIS=실행·승인·결과 검증, dev-wiki/Git=개발 결정·운영 규칙 원문으로 유지한다.

| 인계의 흡수 후보 | 기존 구현과 대조 | 적용 판단 |
|---|---|---|
| LightRAG의 근거 연결 검색·파생 인덱스 일관성 | FTS5, cosine/RRF, sealed generation, 인용·삭제 원장이 이미 있다. `0b7f79e`에서 벡터 조회의 쓰기 부작용과 RRF 출처 손실 수정 | 기존 검색 개선. 한국어 품질·범위·삭제 일관성을 측정한 후 hybrid 활성화 판단 |
| Tencent의 공통 기억 인터페이스·공유 범위 | MCP·자비스 adapter·공통 상태기계는 있다. 일반 project/user/agent 접근 범위는 미완료 | 같은 provider에 연결하고 범위 계약을 보강. 독립 기억 서버/DB를 추가하지 않음 |
| code-brain의 작은 context pack·근거 있는 결정 기록 | 자비스 바이트 예산과 record-set 완료 reader는 있다. 작업별 선택·실제 전달 이력은 미완료 | 공통 context pack·세션 전달 확인 구현. 검색 결과 반환과 문맥 전달 성공을 구분 |
| memory-bank의 원문 기반 기억·정정·중복 주입 방지 | CAS·source/derivation·record·정정/삭제는 재사용 가능. 사실 유형·대체 관계·전달 중복은 후속 | 원문/버전/유효 시점과 수명주기 보강. Claude 파서를 다른 앱 지원의 증거로 사용하지 않음 |

이번에는 외부 OSS 소스를 복사·설치하거나 최신 upstream을 다시 조사하지 않았다. 위 표는 인계의 고정 조사 결과와 로컬 구현의 대응이다. 향후 파일을 실제 채택할 때 출처 커밋·라이선스·NOTICE를 파일별 기록한다.

## 3. 수정·개선·고도화 우선 목록

P1은 1차 운영 완성에 필요한 항목, P2는 기준선과 운영 경계 이후의 개선이다. 이미 수정한 과거 결함을 다시 미수정으로 표시하지 않는다.

| 우선 / 분류 / 기존 ID | 현재 문제·실사용 영향 | 구현할 지점·방법 | 완료 조건 |
|---|---|---|---|
| P1 수정 / I1-d·I8 | 일반 Enter 입력 불가. Python/JS 공백 판정 차이와 후보/요청의 분량 판정 차이 | 아래 4~5절의 명시적 새 본문 계약. 후보→검토→승인→요청→원문→조회에 같은 validator/벡터 적용 | LF/CRLF/CR·한국어·공백·반복·사용자 인용이 전체 원문에 대응. 양쪽 허용/거부 일치 |
| P1 수정·개선 / I1·G5 | 정정 backend와 완료 복구는 있으나 실제 사용자 정정 인수 부족 | 기존 target resolve·검토·권한·V2 saga를 화면에 연결. 대상/세대 변경 시 준비를 다시 요구 | 화면 선택→정정→완료→다른 클라이언트 최신 사실 회수. stale target 거부·중복 효과 0 |
| P1 개선 / I7·B4 | MCP 클라이언트 2개 성공이 실제 앱 2개 성공은 아님 | 사용 앱별 기존 설정/connector를 연결하고 조회·쓰기·로그 수집·문맥 공급을 따로 검사 | 실제 A 기록→B의 동일 record/출처/버전 회수. 앱별 지원·미지원·미검증 표 |
| P1 개선 / I7·B4 | project/user 범위 없는 공통 읽기를 다중 사용자 운영으로 확대할 수 없음 | 버전 있는 요청 범위와 provider의 공통 검사. 검색·직접 page·target·export에 동일 적용 | 범위 밖 자료가 어떤 조회/확장에서도 노출되지 않음. agent 출처는 권한으로 사용하지 않음 |
| P1 수정 / I1·G6 | task 기억을 수집한 후 원본을 차단해도 파생 기억까지 차단하는 계약 부족 | 원본 task ID/검증 결과/차단 상태를 파생 계보와 연결하고 철회 전파 구현 | 원본 차단 후 검색·인용·재색인·재수집·복원에서 재노출 0. 이 조건 전 자동 수집 보류 |
| P1 고도화 / G3·G6 | 검색 예산만으로 실제 문맥 전달·재사용을 입증할 수 없음 | 공통 context pack에 범위·기간·바이트/토큰 예산·제외 이유·버전 포함. 실제 전달 receipt 저장 | 전달 실패 재시도, 세션 내 중복 방지, compaction 후 재공급, 정정된 기억 재전달 |
| P1 수정 / R6·I3 | 과거 원장과 generation 디렉터리 불일치/잔여물의 운영 인수 미완료 | 현재 active·reader·pending·삭제 증거와 대조하는 복구 도구. 확인된 잔여물만 처리 | 반복 복구 수렴, 유실/중복 활성화 없음. 오래됐다는 이유만으로 삭제하지 않음 |
| P1 수정 / I1·I2 | provider의 서명된 export 수명 상태를 소비자에서 완전히 검증하지 않음 | JARVIS effect service/observer/export store에서 request·provider·manifest·서명·만료 연결 | 만료/철회/삭제된 export가 available로 표시되지 않음. 물리 정리 완료와 상태 구분 |
| P1 개선 / R8·I6 | readiness/백업 검증 소스는 수정됐으나 운영 adapter 인수와 결합 부족 | 실제 adapter 검증 결과를 준비 상태에 연결하고 stale/failure 상태 표시 | 잘못된 계약·미처리·복원 불가를 정상으로 표시하지 않음. 운영 새 백업 검증 |
| P1 개선 / I2·I4 | 복원 가능한 vault archive와 작동하는 전체 runtime 복구는 다름 | 커밋/패키지·설정·키 참조·provider identity·원장·tombstone·활성 포인터를 release/restore 절차로 묶음 | 격리 새 runtime 읽기·쓰기, 삭제 기억 부활 0, 실패 rollback, 실측 RPO/RTO |
| P1 개선 / I5·I3 | 대표 규모의 저장·조회 지연, 세대 복사량·백업 공간/잠금 비용 부족 | CAPACITY-PLAN의 실제 managed 경로로 반복 실행·동시 reader/writer 측정 | 5천 파일/10만 unit/1만 page·100회 계획의 보존/성장량/지연 보고. 단일 약 1.4초를 p95로 쓰지 않음 |
| P2 수정·개선 / I8 | 과거 설명과 후속 수정이 긴 문서에 누적되어 현재 판정이 어려움 | 구현 원장 최신 절과 이 표를 진입점으로 삼고 재현 명령·환경·commit 명시. 신규 설치와 실패 exit 전달 검사 | 현재 코드로 설치·검증 재현. 경고 일괄 억제 없이 필요한 타입/모듈 경계 정리 |
| P2 고도화 / G1·G4 | 일시 상태·결정·선호의 유효 기간과 대체 관계를 일반화해야 함 | observed/valid 시점, supersedes, 출처, 재검토 상태를 기억 유형과 연결 | 과거 시점 답변과 현재 답변 구분, 오래된 결정을 현재 사실처럼 재노출하지 않음 |
| P2 고도화 / G2·R10·B8 | hybrid가 실제 근거 회수를 개선하는지 미측정 | 한국어 100~300문항 고정 평가 후 lexical/hybrid 비교. vector 세대·필터·삭제도 검사 | Recall@k·정답 출처 포함·오래된 사실 노출·p95·비용 비교. 이득 없으면 비활성 유지 |

의존 순서: **공통 본문/저장·정정 → 실제 앱 접근과 범위 → 실제 문맥 전달 → 운영 배포·복원 인수**. 원문 차단 전파와 운영 가시성은 각각 자동 수집·운영 전환의 선행 조건이다. 검색 확장은 정합성/범위와 품질 기준선 이후다.

## 4. 이번에 재현한 본문 계약 문제

실행: `TMPDIR=/var/tmp node scripts/remember-body-compatibility.mjs <격리 빌드한 JARVIS 경로>`.

| 입력 | 후보 본문 함수 | JARVIS V1 요청 | Second Brain V1 접수 | 판정 |
|---|---|---|---|---|
| 일반 한 문장 | 허용 | 허용 | 허용 | 정상 대조군 |
| 문장 사이 LF / CRLF / CR / 탭 | 거부 | 거부 | 거부 | 일반 여러 줄 입력이 아직 지원되지 않음 |
| 문장 사이 U+2028 / NEL | 허용 | 허용 | 허용 | 기존 64-record 검증의 범위. Enter 지원의 증거가 아님 |
| 문장 앞 BOM U+FEFF | 거부 | 거부 | 허용 | JS trim/Python strip 의미 차이 |
| 문장 앞 NEL U+0085 | 허용 | 허용 | 거부 | 자비스가 만든 유효 요청도 provider가 거부할 수 있음 |
| 65개 record / 인용 이스케이프 뒤 record 크기 초과 | 허용 | 거부 | 거부 | 후보의 텍스트 검사만으로 저장 가능성을 보장하지 못함 |
| UTF-8 원문 4098바이트 | 거부 | 거부 | 거부 | 공통 원문 상한 대조군 |

후보 열은 `memory-candidate-input.ts`에서 statement에 사용하는 `memoryText(...,4096)`의 직접 실행이다. 전체 정책 분류·승인·화면에서 후보가 실제 확정됐다는 뜻은 아니다. 마지막 두 분량 사례의 영향은 **후보 단계에 저장 가능성 사전 검증이 필요하다**는 것이다.

원인: `sb/write_request_values.py:_text`는 Python strip과 제어문자 금지, 자비스 `second-brain-write-request.ts:text`와 `memory-candidate-values.ts:memoryText`는 JS trim과 제어문자 금지를 사용한다. `remember_lines`/`memoryRememberRecordTexts`의 record 검사만 고쳐서는 앞단 거부를 해결하지 못한다.

수락 4개는 동일 요청 재접수에서 replay이고 pending 파일은 각 1개다. 저장한 synthetic 본문은 원문과 같다. 거부 8개는 빈 임시 루트에 요청 DB/파일을 만들지 않았다. 12개 모두 입력 요청 불변을 검사했다. 이 재현은 현재 동작을 기록하며 불일치가 올바른 목표 동작이라고 규정하지 않는다.

## 5. 일반 여러 줄 지원의 변경 범위와 보류 기준

이 절은 후속 구현안이다. 새 wire 버전 채택·DB migration·기능 출시 기록이 아니다. V1 validator를 느슨하게 바꾸거나 승인된 본문의 줄바꿈을 Unicode 구분자로 치환하는 우회는 보류한다.

| 경계 | 필요한 변경과 검사 |
|---|---|
| 본문 값 | 새 명시적 본문 버전/프로필에서 LF·CRLF·CR·탭, Unicode scalar/NFC, 가장자리 공백/BOM/NEL의 정책을 한 번 정의. 바이트 원문을 임의 trim/정규화하지 않음. 원문 4096바이트·record 64개·각 이스케이프 결과 4096바이트 한도 유지부터 시작 |
| 후보·검토·승인 | `memory-candidate-input/values`, review spool, publication, confirmation을 대조. 본문/프로필과 원문 digest를 검토·승인 대상에 결합. 저장 불가 분량은 원문 확인 단계에서 설명. 제목·ID까지 제어문자를 허용하지 않음 |
| 요청·교섭 | V1 및 기존 V2 effect를 보존하고 새 remember 요청 종류/버전과 MCP 프로필을 양쪽에서 명시적으로 지원. 미지원 peer는 원문을 바꾸어 재전송하지 않고 거부. 기존 frozen 파일/digest는 유지 |
| 식별자·재시도 | 새 요청의 canonical digest/domain·envelope·결과 버전과 교차 버전 idempotency/lane 규칙 정의. 같은 후보를 V1/새 버전으로 바꿔 중복 기록하는 문제를 검사 |
| 요청 원장 | `request_store.py` 현재 CHECK는 `(1,2)`만 허용. 새 요청 버전을 사용할 때 기존 DB를 보존하는 migration·중단 복구·버전 불일치 거부 필요. CREATE TABLE 문자열만 바꾸면 기존 DB는 전환되지 않음 |
| 처리·복원 | `stable_requests`, envelope parser, executor의 파일 suffix/`schema_version==1 else V2` 분기, claim 재개·backup/restore/삭제 억제를 함께 대조. 새 버전을 V2로 오해하지 않도록 명시 dispatch |
| 결과 소비 | 자비스 write adapter·outbox record/control proof와 SB CAS/Vault/record rendering의 원문·인용·전체 record 기대값 연결. LF/CRLF가 다른 원문 digest임을 유지하며 렌더링 결과로 정확히 대응 |
| 인수 | 새/구 클라이언트 조합, 12개 현재 사례+빈 줄·반복·surrogate·승인 후 본문 변경·만료·동시 재전송·중단 재개·복원·정정/삭제를 검사. 실제 CLI/MCP 저장→2개 reader→outbox/control 완료까지 연결 |

새 본문 계약 하나 때문에 SB 안에 별도 승인/서명 시스템·큐·기억 DB를 추가하지 않는다. 단일 writer, 기존 JARVIS 권한 구조, 원문 CAS와 원장을 재사용한다. 일반 여러 줄 기능은 이 경계들을 연결한 후에만 완료로 바꾼다.

## 6. 이번 단위 산출물과 검증 기록

- `scripts/remember-body-provider-probe.py`: 고정 시각·synthetic 12개 입력, 실제 stable 접수·정확 재시도·원문/거부 부작용 검사. 임시 폴더는 종료 시 정리한다.
- `scripts/remember-body-compatibility.mjs`: 격리 빌드된 실제 자비스 검증기와 Python 결과를 대조한다. 운영 config·네트워크·승인 서명은 사용하지 않는다.
- 자비스 `30e2024` 격리 backend build 통과: `/var/tmp/jarvis-remember-body-build.log`.
- 12개 characterization 검사 통과: `/var/tmp/sb-remember-body-compatibility.log`. 검사는 불일치 2개와 후보/요청 상한 차이 2개를 재현했으며 이를 해결했다는 결과가 아니다.
- 기존 요청·처리기·프로필 호환·MCP runtime 계약 회귀 **40 passed, 5.26초**: `/var/tmp/sb-remember-body-contract-regression.log`.
- 전체 `sb tests`와 새 Python 스크립트 Ruff, Node 구문 검사 통과. 제품 소스·운영 서비스·실제 vault·JARVIS 작업 중 파일·frozen 계약은 변경하지 않았다.

전체 공통 기억 운영, 일반 여러 줄, 프로젝트 범위, 실제 앱별 공급, runtime 재해 복구는 미완료로 유지한다. 보류는 V1 우회·원본 차단 전파 없는 task 자동 수집·과거 generation 무근거 일괄 삭제·평가 없는 hybrid 활성화에 적용한다.
