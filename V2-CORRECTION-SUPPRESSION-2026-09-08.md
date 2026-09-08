# V2 정정 차단 수정과 공통 기억 완성 우선 목록

2026-09-08. 인계 문서와 기존 구현 원장을 재대조한 후속 보고서.

**현재 판정: 공통 기억의 핵심 경로에는 검증된 구현이 있지만, 자비스의 메인 기억 저장소로 전체 운영 인수를 완료한 상태는 아니다.**
이번에는 V2 정정 경로의 후보 차단 누락을 수정했다. 차단된 정정 때문에 후속 정정·삭제가 멈추는
자동 복구 문제는 실제 양쪽 계약에서 재현되어 P0로 남겼다. 테스트 통과와 운영 완료를 구분한다.

- 제품 수정: JARVIS `8a55ea9`.
- 별도 프로세스 인수 도구: Second Brain `db19ec5`.
- 인계 원문: [최종 OSS 흡수 방향](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md).
- 기존 정본: [통합 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md), [전체 개선 원장](IMPROVEMENT-BACKLOG-2026-09-07.md).

## 1. 이번에 수정한 결함

| 문제 | 실제 영향 | 적용한 수정 | 검증 |
|---|---|---|---|
| V1에서 검사한 후보 차단을 V2 정정 준비가 검사하지 않음 | 화면에서 숨긴 후보를 정정 입력으로 계속 사용 가능 | spool 작성 전 및 DB immediate transaction 안에서 기존 후보 ID 차단 재검사 | 준비 전/파일 게시 직후 차단 각각 거부 |
| 같은 lane의 재준비가 동일 spool 경로를 사용 | DB 중복 삽입 실패 전에 기존 준비 파일을 덮어쓸 수 있음 | 준비 시도별 고유 파일을 쓰고 실패 시 해당 시도 파일만 정리 | 기존 파일 바이트·파일 목록·preparation 1행 유지 |
| provider 조회를 기다리는 동안 차단 상태가 바뀜 | 차단 후 tombstone과 정정 요청을 생성할 수 있음 | destructive preparation의 writer transaction 안에서 candidate 결합 검사 | tombstone·정정 요청·전송 시도 모두 0 |
| tombstone 생성 후 전송 전에 후보가 차단됨 | 전송 또는 전역 cursor 점유로 이어질 수 있음 | cursor claim과 beginDispatch를 한 immediate transaction으로 묶고 전송 전 차단 | 거부 후 cursor 미점유·fence 0·attempt 0 |
| 직접 V2 adapter 호출은 기존 V1 쓰기 검사를 거치지 않음 | saga 밖에서 차단된 후보의 정정 요청을 보낼 수 있음 | 실제 request identity에 결합된 correction row의 candidate 차단 검사 | 정상 입력 transport 진입 1회 후 차단 호출 증가 0 |
| 차단을 이유로 이미 보낸 요청의 관측까지 멈출 위험 | 불확실한 외부 효과를 추적하지 못함 | 신규 전송 검사와 기존 reconcile 경로 분리 유지 | 이미 호출한 요청의 reconciling 관측 지속 |

기존 wire schema와 migration 001–071은 유지했다. 새 기억 DB, 승인 단계, 서버, Proxy는 추가하지 않았다.
파일 게시 자체나 보상 정리의 I/O 실패까지 모두 복구된 것은 아니다. 고유 spool의 orphan 탐지·정리는 남은 과제다.

## 2. 검증 결과와 한계

- 최종 JARVIS 테스트: **6파일 22 passed**, 49.73초. 새 차단 테스트 5개와 기존 정정 완료·삭제·순서·원자적 준비 회귀를 포함한다.
- backend TypeScript, 변경 파일 ESLint, 정규 backend 격리 build: 각각 exit 0.
- 격리 build: `/var/tmp/jarvis-v2-suppression-build-ocoj8gvf`, 산출물 1,061개, migration 71개.
- 산출물 digest: `sha256:2e2de32fd70c443452bd42e2b7ee9e33f93e69983474e815128cbd68486783de`.
- 실제 OS 프로세스 3개: `/var/tmp/jarvis-v2-suppression-CLxtdH/result.json`.
- 기계 판독 결과: [검증 JSON](V2-CORRECTION-SUPPRESSION-2026-09-08.json).

| 프로세스 | 확인한 결과 |
|---|---|
| 최초 실행 | tombstone 이후 중단, correction queued, writer 0회 |
| DB 재개 | 차단 후보의 beginDispatch 거부, attempt 0, accepted sequence 0, 기존 spool 보존 |
| 실제 adapter 실행 | 유효한 V2 입력으로 transport 1회 진입, 차단 이후 추가 호출 0, reconcile 관측 유지 |

여기서 provider 응답은 결정적인 테스트 transport다. 운영 SB 처리 완료, 실제 모델 사용, native 앱
채택을 검증한 결과는 아니다. 이번에는 모델 호출 0회이며 운영 vault/DB와 서비스는 변경하지 않았다.
과거 SB 전체 931 passed/2 skipped 및 실제 Codex↔Claude 공유 결과는 이전 보고서의 증거로 유지하며
이번 최종 검사 수치에 합산하지 않는다. 독립 검토는 정정 후보 차단과 cursor rollback을 확인했고,
후속 자동 복구는 보류 상태로 남겨야 한다고 확인했다.

## 3. 추가 발견한 P0: 보류된 tombstone 이후의 자동 복구

재현 순서는 다음과 같다.

1. 정정 요청의 tombstone sequence 1이 자비스에 커밋된다.
2. provider 전송 전에 후보가 차단되거나 실행이 중단된다. provider는 여전히 sequence 0이다.
3. 차단 후보의 요청을 전송하면 안 되므로 해당 요청은 queued로 남는다.
4. 다음 정정·삭제는 local/provider checkpoint 불일치 때문에 진행되지 않는다.

미전송 요청을 자동 종료하고 다음 요청에 delta `[1, 2]`를 싣는 시제품을 검증했으나,
**실제 계약을 거친 통합 검증은 실패했다.** JARVIS `requireMemoryEffectWriteRequest`와
SB `parse_effect_request`가 모두 `EFFECT_TOMBSTONE_DELTA_INVALID`를 반환했다.
현재 V2는 각 chain entry를 현재 요청의 lane/operation/payload 또는 target/scope에 결합한다.
다른 정정·삭제의 이력을 한 요청에 넣는 것은 이 계약에 맞지 않는다.

합성 AcceptedWriter는 실제 validator를 호출하지 않아 시제품 35개 테스트 및 4프로세스 결과가
통과처럼 보였다. **해당 결과는 이 기능의 통합 성공 증거에서 제외했다.** 양쪽 실제 validator의
거부를 직접 재현한 뒤 자동 retirement, migration 072, 순서 건너뛰기, 낮은 checkpoint 조회 예외를
모두 제품에서 제거했다. 최종 22개 테스트와 3프로세스 인수는 철회 후 수정본의 결과다.

계약 검사나 해시만 약화해서 해결하지 않는다. 다음 구현은 기존 요청의 미전송 여부, 원본 target별
삭제 전파, 정정 본문 재전송 방지, provider의 처분 증거, 전역 순서 및 구버전 거부를 함께 정의해야 한다.
특히 cursor에 accepted를 기록하는 것과 실제 데이터 처분 완료는 같은 상태가 아니다.

## 4. 인계 방향과 기존 구현의 대조

| OSS에서 흡수할 장점 | 현재 적용 기반 | 추가로 필요한 것 | 이번 처리 |
|---|---|---|---|
| LightRAG의 근거 검색·파생 인덱스 일관성 | 기존 FTS/임베딩/RRF·세대·삭제/복원 | 실제 질문의 근거 회수율과 오래된 기억 노출, 지연 평가 | 기존 검색 재사용. 효과가 측정되지 않은 그래프 확장은 보류 |
| TencentDB-Agent-Memory의 공통 기억·공유 범위 | 기존 MCP·원문/버전·자비스 읽기/쓰기 adapter | 인증된 사용자·프로젝트 범위의 일관된 집행 | 후보 차단의 V2 쓰기 누락 수정. 범위 ACL 완료와는 구분 |
| code-brain의 작은 문맥·근거 있는 개발 기억 | 기존 문맥 예산·전달 원장·dev-wiki/Git 원문 | 실제 앱 세션과 compaction, 전달 확인의 결합 | 별도 리포 기억 DB·전역 훅을 추가하지 않음 |
| memory-bank의 원문 추적·대체·세션 중복 방지 | 기존 source/record 계보·정정/삭제·세션 원장 | 원task→후보→SB record 전체 차단 전파와 검증된 결과 수집 | 자동 수집보다 기존 쓰기 차단을 우선 보강 |

이번 작업은 인계 문서에 기록된 선별 흡수 방침의 적용이다. 외부 OSS 코드를 복사하거나 의존성을
추가하지 않았으므로 신규 코드 라이선스 고지 대상은 없다. 외부 저장소 최신 상태를 재조사한 보고서는 아니다.

## 5. 수정·개선·고도화 상세 우선 목록

아래는 기존 미완료 항목과 이번 발견을 병합한 실행 순서다. P0는 공통 기억 운영 인수의 선행 조건이다.

| 순서·구분 | 문제와 영향 | 구현 방향 | 완료 판정 |
|---|---|---|---|
| 1 / P0 수정 | 차단된 미전송 정정의 tombstone이 후속 작업을 막음 | 양쪽 버전 계약으로 미전송 종료·삭제 이력 전달·증거 확인 정의 | 실제 양쪽 adapter/provider를 거쳐 다음 정정·삭제 완료, 차단 본문 전송 0 |
| 2 / P0 수정 | DB 전송 검사와 외부 수신 사이에는 원자성이 없음 | 전송 claim·삭제 fence·불확실 수신 관측을 연결 | 삭제/전송 경합과 프로세스 종료에도 금지된 재전송 및 중복 완료 0 |
| 3 / P0 개선 | 실제 task 차단이 후보와 provider record까지 전파되는 계보 부족 | 검증된 원task/결과/후보/요청/record 식별자를 결합 | 원본 철회가 검색·정정·주입·재수집 모두 차단 |
| 4 / P0 개선 | sensitivity와 지식 상태만으로 프로젝트/사용자 접근을 구분할 수 없음 | 인증된 범위 계약을 검색·원문·쓰기·export·restore에 공통 집행 | 다른 사용자의 자료와 비허용 프로젝트가 모든 경로에서 거부 |
| 5 / P0 수정 | native rollout·thread_history SQLite에 삭제 기억 사본 잔류가 이전 인수에서 관측됨 | 관리형 root 소유권·writer 정지·SQLite/WAL·백업·세션 폐기 계약 | 실제 native 종료/복원 뒤 원문 재노출과 삭제 세션 재개 0 |
| 6 / P0 개선 | 모델 호출 성공과 실제 자비스 앱의 기억 순환은 다름 | 앱 조회→보호된 제출→실제 세션 전달→검증 결과→기억 재사용 연결 | 한 작업의 request/receipt/record ID를 실제 다음 요청까지 추적 |
| 7 / P1 수정 | 게시·보상 중 I/O 실패 시 고유 spool이 남을 수 있음 | 원장과 파일 대조, 유효 참조 보존, 고아 파일 정리/영수증 | 파일 게시/DB 실패/정리 실패를 각각 주입하고 재시작 수렴 |
| 8 / P1 개선 | 세션 중복 방지의 실제 compaction 처리 미완료 | 전달 이력과 native session/epoch/compaction 사건 결합 | 새 문맥 재전달·구문맥 차단·불확실 재시도 기준을 실제 클라이언트에서 검증 |
| 9 / P1 개선 | MCP 호환성을 자동 수집·주입 지원으로 오인할 수 있음 | 클라이언트별 조회/쓰기/수집/주입 지원표와 연결 검증 | Codex/Claude 실측 범위를 유지하고 각 추가 앱을 네 기능별 검증 |
| 10 / P1 고도화 | 검색 점수만으로 근거 부족을 판정하기 어려움 | 근거·최신성·정정 이력을 평가하고 no_data 기준 마련 | 고정 한글 질문에서 정답 근거 회수와 오래된 기억 노출을 비교 |
| 11 / P1 고도화 | 임베딩 배치 개선 후에도 대표 질의 지연·메모리 목표가 남음 | 실제 질의 p50/p95, cold/warm, CPU/RAM과 문맥량 측정 | 동일 데이터·질문에서 품질 유지 및 설정한 지연/자원 목표 충족 |
| 12 / P1 개선 | 기억 화면과 전역 연결 배지·실제 signer/provider 준비 상태가 일치하지 않을 수 있음 | 기존 readiness와 UI 상태를 실제 운영 경로에 연결 | 실제 backend 오류·지연·복구가 화면에 정확히 표시 |
| 13 / P1 개선 | 운영 배포·백업·복원의 최종 인수 미완료 | 릴리스/설정/세대/원장 함께 복원하고 RPO/RTO 실측 | 독립 복원 환경에서 읽기/쓰기·삭제 재유입 방지와 복구 시간 확인 |
| 14 / P2 고도화 | 전체 무효화 비용과 일반 그래프 확장의 효과 미측정 | 계보에 따른 선택 무효화, 효과가 있는 관계 검색만 도입 | 기준선 대비 비용/정확도 개선이 실측될 때 채택 |

자동 작업 기억 수집은 3번 계보와 실패/미확정 결과의 검증 계약 전까지 보류한다. native 자동 연결은
5번 보존·폐기 계약 전까지 보류한다. 운영 hybrid/그래프 확대는 10–11번 평가를 통과한 범위에서 진행한다.
전체 목표를 완료로 처리하지 않았으며 운영 배포·서비스 재시작·push는 수행하지 않았다.
