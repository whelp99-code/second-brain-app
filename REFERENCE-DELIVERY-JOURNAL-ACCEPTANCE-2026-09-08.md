# 중앙 기억 후속 분석 — 영구 전달 원장과 남은 완성 조건

자비스 제품 **`6e101fc`**, 세컨드브레인 인수 도구 **`fd9df47`**.
인계 문서 `/home/jm/orca/projects/Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md`의
현재판을 다시 읽고 기존 분석·수정에 병합했다. 전체 계획은
[OSS 통합 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md),
[개선 목록](IMPROVEMENT-BACKLOG-2026-09-07.md), [진행 원장](IMPLEMENTATION-STATUS.md)에 유지한다.

**핵심 저장·검색·정정·삭제·공유는 격리 통합 경로에서 동작 검증됐다. 자비스의 실제 앱 세션과
자동 수집·문맥 공급까지 포함한 일상 운영 완성은 아직 아니다.** 서비스 active나 테스트 수만으로
전체 완료를 판정하지 않는다. 이번에 재시작 후 중복 전달 및 불확실한 재전송을 막는 제품 단위를
추가 구현·검증했다. 운영 DB migration, 배포, 재시작, push는 수행하지 않았다.

## 1. 네 OSS 제안과 기존 구현 대조

아래 OSS 항목은 인계서에 기록된 후보를 분류한 것이다. 이번에 외부 저장소 최신판을 다시
조사하거나 네 제품을 설치·벤치마크했다는 뜻은 아니다. 외부 OSS 코드를 복사하지 않았다.

| 흡수 후보 | 현재 분류 | 기존 구현·실측 근거 | 남은 조건 |
|---|---|---|---|
| LightRAG: 인용 근거와 하이브리드 검색 | 기존 구현 재사용·개선 반영 | `sb/sealed_search.py`, `sb/hybrid_search.py`, 봉인 record 벡터·정정/삭제 동기화. 합성 100질문 실제 모델 평가 | 무정답 처리·사용자 질문 평가·약 6초 검색 지연 개선. 그래프 DB 도입 보류 |
| Tencent: 에이전트 공통 기억 인터페이스 | 기존 구현 재사용, 범위 통제 미완료 | SB MCP 계약·자비스 adapter·Codex/Claude 두 클라이언트 공유 인수 | 실제 프로젝트/사용자 권한을 검증한 검색·원문 범위, 앱별 연결 |
| code-brain: 작은 문맥과 근거·예산 | 본문 준비·읽기·제출 구현 | JARVIS reference context/reader: 실제 직렬화 byte 예산, 출처/record/세대 보존 | 실제 앱 채택, 도구 결과 기반 자동 수집과 근거 충분성 |
| memory-bank: 세션 중복과 기억 수명 | 이번 영구 원장 구현, 연결부 미완료 | `submitInSession`, 기존 AuthorityDb의 key/session/attempt 3개 테이블 | native session/compaction 관측·수신 확인·삭제된 세션 후속 처리 |

세컨드브레인은 개인·업무 기억 정본, 자비스는 실행·검증, dev-wiki/Git는 개발 결정 원문으로
유지한다. 에이전트별 DB, 별도 기억 서버, 모델 Proxy, 전역 훅을 추가하지 않았다.

## 2. 이번에 수정한 실제 문제

| 문제 | 영향 | 적용한 수정 | 확인한 동작 |
|---|---|---|---|
| WeakMap만으로 제출 이력 보관 | 새 객체·다른 프로세스·재시작으로 같은 기억 재전송 가능 | 기존 AuthorityDb에 영구 시도 원장 추가 | 별도 프로세스의 재조회·재제출 callback 0회 |
| 전달 중 종료 후 성공 여부 불명 | 맹목적 재시도로 중복 외부 전달 가능 | `dispatching`/`unconfirmed`가 있으면 같은 세션의 모든 epoch 재전송 거부 | callback 진입 후 SIGKILL, 새 프로세스 재시도 0회 |
| HMAC 키 교체 시 이전 이력을 못 찾음 | 같은 원래 세션이 새 세션처럼 취급됨 | 최초 키 binding 고정, 모든 원장 API에서 키 대조 | 키 변경 거부 및 기존 행 유지 |
| durable 여부가 선택 인자로 숨음 | 연결부가 인자를 빠뜨려 조용히 보호 수준 저하 | 필수 session을 받는 `submitInSession`과 기존 `submit` 이름 분리 | session 누락 시 callback 전 거부 |
| 개인정보/삭제 이후 세션 이력 유효 | 삭제 전 문맥을 가진 세션을 계속 사용 가능 | revision/chain 변경 transaction에 모든 기존 세션 무효화 결합 | 새 epoch로도 무효화 세션 부활 불가 |
| 원장의 식별 token도 삭제 후 남음 | 새 파생 보존 표면 확대 | 무효화 시 binding/epoch/record-set/payload HMAC 제거 | fresh DB 파일에서 대상 token 8개 byte 불검출 |
| SQL 상태·시각을 임의로 변경 | 완료 상태 재시도, 이력 역행 가능 | 상태 전이·삭제/REPLACE 거부, HMAC/UTC 형식·단조 시각 검사 | 회귀 테스트에서 금지 쓰기 거부 |
| callback 실패와 삭제 경합 오류 혼동 | 불확실 전송이 다른 오류로 가려짐 | invalidated 최종 상태 보존, outward UNCONFIRMED 유지 | 실패·삭제 동시 경로 회귀 통과 |

수정 위치는 자비스의 `src/memory-reference-deliveries.ts`, `src/memory-reference-reader.ts`,
`migrations/071_memory_reference_deliveries.sql`이다. SB MCP wire 계약과 기존 migration bytes는
변경하지 않았다. 070 상태의 DB에 071을 적용해 기존 개인정보 값·migration journal 보존과
반복 적용 수렴을 확인했다. migration 적용은 격리 fixture DB에서만 실행했다.

## 3. 실제 검증 결과

상세 기계 증거: [JSON](REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.json).

- 자비스 reader/submit/context/delivery/migration/physical compaction **6파일 90 passed**.
  이후 추가한 070→071 및 잘못된 시각을 포함한 delivery 집중 검사는 **14 passed**.
  두 수치를 더해 중복 없는 테스트 수로 보고하지 않는다.
- backend TypeScript와 변경 파일 ESLint 통과. 모델 event 감사기 **14 passed**.
- 실제 Node 프로세스 **6개**: 완료, 재시작 중복 차단, callback 중 SIGKILL, 재시작 불확실 차단,
  키 변경 차단, 무효화 후 fresh-file 재개 차단. 차단된 네 호출의 callback은 모두 0회.
- fresh-file integrity `ok`, 민감 식별 token **8개 byte 불검출**. 세션 HMAC·무작위 attempt ID·
  key pin은 재개 방지용으로 보존한다. 기존 파일·백업 전체 물리 삭제를 뜻하지 않는다.
- 실제 SB MCP와 native Codex 모델 **5회**: 빈 기억 no_data, 최초 값+정확한 출처, 정정 값,
  삭제 중 모델 결과 반환 거부, 삭제 후 no_data. 최종 원장 **invalidated 4행 / callback_completed 1행**.
- 마지막 새 객체로 동일 session/epoch 재제출 시 추가 모델 callback 없이 차단했다.
- 실제 모델은 독립 ephemeral 요청이다. 원장 session ID는 **합성 adapter fixture**다.
  native Codex session ID를 사전에 관측·결합한 기능이나 실제 compaction 검증은 아니다.
- 다른 모델의 독립 코드 검토에서 키 우회·API 분리·시각 검증 등을 지적받아 수정했고,
  최종 검토에서 명시한 범위 내 blocking 결함이 없다는 결과를 받았다. reviewer는 테스트를
  실행하지 않았으며 테스트 실행 증거는 본 작업의 로그다.

처음 테스트 실행은 기본 임시 디렉터리의 quota 오류 `-122`로 수집 전 실패했다. `/var/tmp`로
명시한 재실행의 완료 결과만 위 수치에 포함했다. 전체 자비스 backend/GUI 및 SB 전체 회귀를
이번에 다시 실행했다는 의미는 아니다. SB Python 제품 변경은 없다.

원시 결과:

- `/var/tmp/sb-reference-delivery-fkYDWa/result.json`
- `/var/tmp/sb-reference-model-5vWJQ6/result.json`
- `/var/tmp/jarvis-delivery-verified-tests.log`, `/var/tmp/jarvis-delivery-upgrade-tests.log`
- 실행 빌드 `/var/tmp/sb-delivery-journal-build`, 코드 대응표 `acceptance-build.json`.
  커밋한 제품으로 재컴파일한 JS 524개와 migration 71개가 실제 실행 빌드와 byte 단위로 일치했다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-reference-delivery-acceptance.mjs /var/tmp/sb-delivery-journal-build
TMPDIR=/var/tmp node scripts/jarvis-reference-model-acceptance.mjs /var/tmp/sb-delivery-journal-build --journal
```

## 4. 수정·개선·고도화 우선 목록

P0는 공통 기억의 실제 앱 사용·잘못된 노출 방지를 위한 선행 조건이다. P1은 품질·운영 인수,
P2는 측정 후 선택할 고도화다. 과거 완료 항목은 재구현하지 않는다.

| 우선 | 구분 | 남은 문제와 영향 | 다음 변경 지점·개선 방법 | 완료 기준 |
|---|---|---|---|---|
| P0 | 연결 개선 | 실제 자비스 앱이 보호 제출 경로를 채택하지 않음 | 앱의 모델 요청 adapter에서 read→submitInSession 연결, 실제 native session ID 사용 | 앱 요청 한 건의 read/attempt/native turn/result 상관관계 증거 |
| P0 | 수명 수정 | DB claim 후 외부 송신 사이 원자성 없음 | native 수신 fence와 무효화된 세션의 후속 요청 거부 계약 | 송신 경합/삭제 직후 다음 turn에서 이전 기억 사용 차단 |
| P0 | 범위 수정 | 단일 owner fence와 검색 필터는 프로젝트 ACL이 아님 | 검증된 사용자·프로젝트 분류를 검색/원문/관계 확장 전체에 연결 | 다른 프로젝트·사용자 기억의 부정 접근 테스트 통과 |
| P0 | 수집 개선 | 실패·미확정 실행을 자동 기억하면 잘못된 경험 축적 | 도구 결과·receipt·최종 검증에 근거한 task capture, 원본 차단 계보 재사용 | 실패/미확정 결과가 성공 기억으로 승격되지 않음 |
| P1 | 세션 고도화 | 실제 compaction·재개 시점과 원장 epoch 미결합 | 클라이언트별 native event adapter, 관측된 epoch만 갱신 | compaction 전후 중복·재주입·삭제 수명 실사용 인수 |
| P1 | 검색 수정 | 의미 유사도가 높아도 질문의 답이 없을 수 있음 | 선택 근거에 답이 있는지 확인하고 no_data 반환, threshold는 후보에만 사용 | 근거 없는 세부질문에서 추측 답변 미생성 |
| P1 | 검색 개선 | 실제 검색 약 6초, 모델 메모리 비용 남음 | 기존 모델 로딩·검색 경로 프로파일 후 수명/공유 범위 최적화 | 동일 질문·장애/삭제 회귀를 유지하며 지연·자원 감소 |
| P1 | 평가 개선 | 합성 100질문만으로 개인 기억 품질 판정 불가 | 실제 사용자 질문 100–300개와 근거·무정답 평가셋 확보 | 기준선 대비 회수·정확성·오래된 기억·p95 비교 |
| P1 | 클라이언트 개선 | MCP 조회 가능과 자동 수집·주입 지원이 혼동됨 | Codex/Claude/사용 앱별 조회·쓰기·수집·주입 지원표와 adapter 인수 | 실제 사용한 각 클라이언트별 증거, 미지원 명시 |
| P1 | 운영 개선 | GUI·운영 전환·장애 가시성 미인수 | 기존 화면/API에 원문·출처·실패·준비 상태·불확실 전달 표시 | 실제 사용자 흐름과 운영 설정에서 한 주기 완료 |
| P1 | 복구 수정 | 외부 전달 이전 백업은 이후 전달 이력을 모름 | 복원 시 기존 native session 재개 금지/새 세션 요구, 외부 고수위 대조 | 오래된 백업 복원 후 중복 전달·삭제 기억 부활 방지 |
| P1 | 복구 개선 | 전체 운영 RPO/RTO 및 모델·백업 사본 삭제 미검증 | 기존 복원/보존 도구와 실제 운영 복구 훈련 | 측정된 복구 시간·손실 범위·외부 사본 한계 기록 |
| P2 | 선택 고도화 | 전역 세션 무효화는 관련 없는 세션도 중단함 | 필요한 경우 record 단위 의존 계보를 기존 projection 경계에 결합 | 선택 무효화가 전역 방식과 같은 삭제 안전성 유지 |
| P2 | 보류 고도화 | 그래프/새 Proxy/별도 기억 DB는 관리 비용과 정본 분산 증가 | 기존 검색·계약의 측정된 한계가 있을 때만 ADR로 채택 | 동일 평가셋의 이득과 삭제/범위/운영 비용까지 입증 |

## 5. 이번 단위의 명시적 한계

`callback_completed`는 callback과 사후 검사가 끝났다는 뜻이며 native 수신 영수증이나 작업
성공 증거가 아니다. `dispatching`은 시도 개시 후 종료 미확정이며, 프로세스의 현재 생존 상태가
아니다. 타이머만으로 자동 재시도하지 않는다. 복원 전 외부 송신이나 기존 모델 문맥을 원장만으로
추적·삭제할 수 없다. key 회전·실제 프로젝트 ACL·전역 자동 주입·자동 capture는 선행 조건이
준비될 때까지 보류한다. 전체 중앙 기억 완성 목표는 계속 미완료로 유지한다.
