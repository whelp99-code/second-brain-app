# SB2 명세 · 2026-09-23 계획 · master 코드 대조 (2026-09-27)

기준: master `9ad6fee`. 추적 이슈: #3.

## 이 문서가 답하는 것
- 2026-09-23 계획(`.omo/plans/second-brain-life-memory-completion-20260923.md`, 60개 작업 중 1–4번 완료)의 5–60번이 2026-09-26 SB2 명세 P00–P14 어디에 들어가는가.
- 각 명세가 master 코드에 얼마나 구현됐는가.
- 어느 명세에도 없는 작업을 새 작업 묶음 P15–P20으로 정의한다.

## 방법과 한계
- 명세 4묶음(P00·P01·P02·P10·P11 / P03·P04·P12·P13 / P05–P08 / P09·P14)을 읽기 전용 에이전트가 master 코드·테스트를 직접 열어 대조했다. 구현 주장마다 파일·함수·테스트 이름을 근거로 남겼다.
- 계획 작업 소속은 에이전트 매핑을 대조 세션이 명세 본문과 다시 맞춰 확정했다. 업무·약속·추천(31–36, 44)은 에이전트가 P01/P02에 넓게 붙였지만 명세 본문에 해당 범위가 없어 신규 P15로 옮겼다.
- 이 대조는 코드 존재와 테스트 이름까지만 본다. 인수시험·실기기·운영 검증은 하지 않았다. **"일부 있음"은 인수 완료가 아니다.**
- 2026-09-26 상태 문서(`IMPLEMENTATION-STATUS-20260926.md`) 이후 커밋(`2478af0` 등)으로 여러 패키지가 NOT IMPLEMENTED에서 부분 구현으로 바뀌었다.

## 1. 명세별 현재 상태

|작업|이름|릴리스|09-26 상태 문서|현재(master)|
|---|---|---|---|---|
|P00|기준선·복구·모바일 기술 검증|R1|PARTIAL|부분 구현|
|P01|사건·시간·상태·민감도 계약|R1|IMPLEMENTED SUBSET|부분 구현|
|P02|영속 접수·개정·근거·삭제 계보|R1|PARTIAL|부분 구현|
|P03|메모·일정·문서·메일 입력 adapter|R1|NOT IMPLEMENTED|부분 구현|
|P04|iPhone 공유→기억 반영·실기기 검증|R1|NOT IMPLEMENTED|부분 구현|
|P05|하루 타임라인·엔터티·근거 관계|R1|PARTIAL|부분 구현|
|P06|Obsidian 기억 브라우저·동기화 안전|R1 필수·R2 확장|PARTIAL|부분 구현|
|P07|아침·저녁 브리핑·전달 상태|R1·R2|PARTIAL|부분 구현|
|P08|중요한 빈칸 탐지·질문 예산·답변 반영|R2|NOT INTEGRATED|부분 구현|
|P09|상황별·시간별 회상·300문항 검색 평가|R2|NOT IMPLEMENTED|부분 구현|
|P10|모델 외부전송 정책·예산·민감정보|R1 선행|PARTIAL|부분 구현|
|P11|운영 상태·이관·롤백·24개 인수시험|R1–R3|PARTIAL|부분 구현|
|P12|위치 수집·방문/이동 집계·프라이버시|R3|NOT IMPLEMENTED|부분 구현|
|P13|건강·수면 입력·결측·권한 철회|R3|NOT IMPLEMENTED|부분 구현|
|P14|사전 예측 원장·실제 결과 연결·채점|R3|NOT IMPLEMENTED|부분 구현|

모든 패키지가 부분 구현이다. 인수 완료된 패키지는 없다.

### P00 기준선·복구·모바일 기술 검증
명세: `docs/second-brain-2/work-packages/P00-*.md` (원 명세 PR #4)

구현된 것:
- 기존 life 테스트가 ledger/CAS와 파이프라인을 실행한다: `tests/test_life_store.py::test_backup_preserves_life_rows_and_delete_intent`
- 복원 시 현재 life 행, blob, 페이지, 커서를 캡처한다: `sb/life_restore.py::capture`
- 열어 본 종단 간 프로바이더 수명주기 테스트: `tests/integration/test_memory_lifecycle.py::test_real_provider_lifecycle_remember_correct_export_forget`

남은 일:
- [ ] 현재 root/revision/dirty 해시를 기록하고 로컬, 원격, 설치된 식별자를 대조한다.
- [ ] 소유권, 복원 우선순위, 플래그, 소스 개수, 모델/리소스 기준선, 실행 표면을 문서화한다.
- [ ] 격리된 복원을 통해 일관된 백업을 검증한다. SQLite 복사 테스트만으로는 백업 인수 기준을 충족하지 않는다.
- [ ] 실제 Phone History, TLS/인증, Mac/iPhone Obsidian 설치 및 오프라인 실행 가능성을 검증한다.
- [ ] 기준선 보고서, ADR, 위험 등록부, 증거 분류를 게시한다. 패키지 `AC-24` 전체 회귀는 열어 본 코드로는 확립되지 않는다.

09-26 이후 변화: 현재 복원 코드와 테스트는 ledger의 기준선 전용 설명을 넘어 life 상태 보존을 다룬다. 전체 운영 기준선, 복원, 기기 게이트는 여전히 입증되지 않았다.

### P01 사건·시간·상태·민감도 계약
명세: `docs/second-brain-2/work-packages/P01-*.md` (원 명세 PR #5)

구현된 것:
- 고정된 이벤트, 상태, 시간, 증거, 범위, 정책 타입: `sb/life_contracts.py::LifeEventV1`
- 정책 검증에 민감/제한 데이터에 대한 로컬 전용 강제가 포함된다: `sb/life_contracts.py::SourcePolicyV1.__post_init__`
- 이벤트 수집이 기존 ledger를 통해 리비전을 파싱하고 영속화한다: `sb/store/life.py::LifeStore.accept`
- 테스트가 재시도 식별자, append-only 정정/CAS, 소스 버전 충돌, 정책 변경, tombstone을 다룬다: `tests/test_life_store.py`

남은 일:
- [ ] 계약 예시/검증기를 완성하고 모든 기존 소비자에 대한 호환성 검토를 완료한다.
- [ ] 시간대/DST/여행/지연 업로드 및 계획 대비 발생 전환 인수를 완료한다.
- [ ] 증거 링크 API/소비자 인수와 전체 패키지 검토를 완료한다.

09-26 이후 변화: 실질적인 상태 변화는 발견되지 않았다. 열어 본 코드는 ledger의 구현된 부분집합 평가를 뒷받침하지만, `P01` 인수 전체를 뒷받침하지는 않는다.

### P02 영속 접수·개정·근거·삭제 계보
명세: `docs/second-brain-2/work-packages/P02-*.md` (원 명세 PR #6)

구현된 것:
- 추가형 life 테이블, 불변 리비전 트리거, 영수증 저널, tombstone, 트랜잭션 기반 쓰기: `sb/store/life.py::LifeStore.initialize`
- 멱등 수락, 예상 리비전 검사, 불변 이력, CAS 증거, 논리적 삭제(forget): `sb/store/life.py::LifeStore.accept`
- 테스트가 재시도, 정정 CAS, 범위 필터링, 불변 리비전, 재열기, 롤백, 백업 행을 실행한다: `tests/test_life_store.py`
- Life 복원이 현재 수명주기 테이블을 캡처하고 후보로 구체화한다: `sb/life_restore.py::materialize`
- HTTP 워크플로 테스트가 정정 시 현재 회상이 제거되고 철회 시 과거 회상이 제거됨을 검증한다: `tests/test_life_workflow_http.py::test_relation_and_asof_correction`

남은 일:
- [ ] 물리적/공유 CAS 삭제와 완전한 관리 사본 계보.
- [ ] 모든 복원/장애 시나리오에서의 복원 전역 재부활 방지와 tombstone 대조.
- [ ] 완전한 크래시 매트릭스, 터미널/기기 확인(ACK) 계보, `AC-09`/`16`/`18`/`21` 전체 인수.

09-26 이후 변화: 현재 복원 코드와 HTTP 테스트는 추가적인 복원 보존, 정정, 철회 동작을 보여 준다. 물리적 삭제와 완전한 재부활 방지는 명시적으로 미완료 상태로 남아 있다.

### P03 메모·일정·문서·메일 입력 adapter
명세: `docs/second-brain-2/work-packages/P03-*.md` (원 명세 PR #7)

구현된 것:
- `LifeDocumentsAdapter.scan`을 통한 소유자 내보내기 메일/카카오/통화 파일. 크기 제한된 텍스트/EML 및 커서.
- `phone_event`를 통한 전화 이벤트 매핑/검증. 소스 기준 안정적 식별자와 첨부 파일 다이제스트 검사.
- `life_imports.prepare`가 phone-event 및 크기 제한 가져오기를 분배한다. `life_ingest.prepare_exports`는 영수증을 영속화하고 게시 후에만 커서를 전진시킨다.
- 증거: `tests/test_life_sensor_ingress.py`가 가져오기 영수증 재생과 센서 HTTP 수신을 다룬다.

남은 일:
- [ ] 각 외부 API/형식을 검증하고 어댑터 매핑/실패 코드를 고정한다.
- [ ] 캘린더 어댑터/발생 정정, 링크/노트 소스, 지원되는 AI 세션/파일 루트는 여전히 미완료다.
- [ ] 모든 어댑터에 대해 커서/오류/격리/재시도 동작과 소스 개수 대조를 완료한다.
- [ ] 종단 간 소스 픽스처, MIME/경로/인코딩/크기 경계, 기기 인수를 추가/검증한다.

09-26 이후 변화: Ledger는 `P03`를 `NOT_IMPLEMENTED`로 표시했다. 이후 master에는 소유자 내보내기 메일/카카오/통화 어댑터(`080f203`)와 life 가져오기/내보내기 코드가 포함되어 있다. 이는 의미 있는 부분 구현이지 패키지 인수는 아니다.

### P04 iPhone 공유→기억 반영·실기기 검증
명세: `docs/second-brain-2/work-packages/P04-*.md` (원 명세 PR #8)

구현된 것:
- `LifeMemoryBridge`가 기기 바인딩 HTTPS 수신을 구성하고, 리디렉션을 비활성화하며, 게시된 가져오기 영수증/다이제스트를 검사한다.
- 전화 이벤트 직렬화가 명시적 노트/링크/사진/오디오/통화 녹음 타입을 매핑한다. `life_phone.phone_event`는 식별자, 타임스탬프, 첨부 파일, MIME을 검증한다.
- `LifeHealthBridge`가 암호화된 대기 HealthKit 배치를 별도로 구현하며 영수증 이후에만 앵커를 이동한다.
- 증거: `PhoneHistoryCoreTests.testGeneratedEventUsesCanonicalFixtureFields` 및 `testSecureQueueDoesNotPersistPlaintextAndDetectsTamper`.

남은 일:
- [ ] 클라이언트에서 life로 이어지는 이벤트 ID/리비전 계보를 완성하고, 실제 UI에서 accepted/processed/searchable/projected/error를 구분한다.
- [ ] 레거시 Phone History 싱크는 여전히 `sb.uploads`를 통해 쓰고 `sb.search`를 통해 철회한다. 프로덕션 싱크가 서버 소유 HTTP 경계를 사용하도록 한다.
- [ ] 실제 서명된 빌드, 설치된 iPhone, 오프라인/재시작/응답 유실 동작과 영수증-검색-Obsidian 전체 시나리오를 검증한다.
- [ ] 만료/폐기, 표면 간 정정, 실기기 인수를 테스트한다.

09-26 이후 변화: Ledger는 `P04`를 `NOT_IMPLEMENTED`로 표시했다. 현재 master에는 기존 Phone History 흐름과 함께 `LifeMemoryBridge`와 `LifeHealthBridge`가 있지만, 열어 본 싱크는 여전히 Vault에 직접 접근하며 기기 인수는 입증되지 않았다.

### P05 하루 타임라인·엔터티·근거 관계
명세: `docs/second-brain-2/work-packages/P05-*.md` (원 명세 PR #9)

구현된 것:
- 날짜 없는 레코드, 상태 필터, 안정적 동률 정렬, 세대 고정 페이지네이션을 갖춘 KST/사용자 시간대 타임라인(`life_timeline_query.query`; `test_timeline_pages_ties_scopes_and_changed_cursor`)
- 증거 기반 관계 쓰기, 허용된 관계 종류, 유효 날짜, 추론/주장 구분(`life_relations.add`; `test_relation_and_asof_correction`)
- 순환/충돌 검사를 갖춘 명시적 엔티티 병합/분할 별칭 레코드(`life_relations.alias`)
- Obsidian 투영에 과거 Daily, 관계, 별칭 뷰가 포함된다(`life_projection.project`)

남은 일:
- [ ] 모든 원본 인용을 보존하는 소스 간 동일 이벤트 그룹화
- [ ] 소스 네임스페이스 전반에 걸친 완전한 안정적 엔티티 식별자/별칭 관리
- [ ] 정정 또는 삭제 후 모든 타임라인/관계 표면의 동일 세대 재구축과 범위 검증
- [ ] 1만 이벤트 p95 성능 인수와 `AC-03`/`04`/`05`/`09`/`15` 전체 테스트

09-26 이후 변화: 증거 기반 영속 관계, 되돌릴 수 있는 명시적 별칭, 세대 고정 페이지네이션 타임라인, 풍부해진 과거 Obsidian 투영이 추가되었다. 기기/성능 인수는 여전히 검증되지 않았다.

### P06 Obsidian 기억 브라우저·동기화 안전
명세: `docs/second-brain-2/work-packages/P06-*.md` (원 명세 PR #10)

구현된 것:
- 자동 전용 매니페스트 동기화, 콘텐츠/경로/해시 검증, 소유권 의도, CAS 쓰기, 충돌 보존, 재개, tombstone 렌더링(`sync-core.applyManifest`; 검증된 매니페스트 및 연결 끊김-재개 테스트)
- 과거 Daily, Questions, Relations 투영과 이벤트/증거 링크(`life_projection.project`)
- 하나의 세대에 고정된 매니페스트 페이징과 서버 ACK 경로(`collectManifest`; `test_persisted_brief_delivery_pagination_ack_and_health`)
- 플러그인이 일일 선택, 질문, 관계 뷰, 명시적 캡처/정정, 회상, 상태 명령을 제공한다(배포 플러그인이 모바일에서 워크플로 명령과 질문 프로토콜을 등록함)

남은 일:
- [ ] 설치/업그레이드/오프라인/재로그인 및 실제 Mac과 iPhone 인수
- [ ] 실기기에서의 기기별 자격 증명 만료와 검증된 ACK/델타 동작
- [ ] 타입별 관계 필터 패널과 완전한 Daily UX 체크리스트
- [ ] 실제 Obsidian Vault에서 100개 파일 중단, tombstone/오프라인 복원, 모든 적대적 Markdown 사례에 대한 인수

09-26 이후 변화: 과거 Daily 및 워크플로 투영, 페이지네이션과 ACK, 질문/관계 명령이 추가되었다. 실제 기기 설치/인수와 타입별 관계 패널은 여전히 미해결이다.

### P07 아침·저녁 브리핑·전달 상태
명세: `docs/second-brain-2/work-packages/P07-*.md` (원 명세 PR #11)

구현된 것:
- 결정론적 아침/저녁 사실 카드와 고정된 이벤트 기반 입력 지문(`life_views.brief`; `life_delivery.generate`)
- 영속화된 브리핑 리비전과 일/슬롯/입력 스냅숏. 입력이 변하지 않으면 재생성하지 않는다(`test_brief_delivery_claim_unknown_not_resent_and_open_requires_ack`)
- 일정 슬롯 및 방해 금지 시간 계산, 외부 tick/CLI 호출, 상주 워커 없음(`life_delivery.due_slots`; `life_cli.dispatch`)
- 불명 상태를 무작정 재시도하지 않는 영속적 최대 1회 전달 클레임, 일반 알림, 명시적 HTTPS 전송(`life_delivery.prepare`; `test_real_tls_sends_only_minimal_notification_and_preserves_query`)
- 브리핑, 전달 상태, 명시적 전송을 위한 HTTP 및 CLI 워크플로 표면

남은 일:
- [ ] 실제 승인된 스케줄러 등록과 운영 일정 인수
- [ ] 프로덕션 알림 채널 통합과 프로바이더별 영수증/대조
- [ ] 실제 알림/열람 신호 인수. 전송 2xx는 기기 수신이 아니다
- [ ] 완전한 고정 입력 증거/스냅숏 계약과 시간대, 방해 금지 시간, 따라잡기, 오래된 브리핑 인수

09-26 이후 변화: 영속화된 입력 지문, 도래 슬롯/tick 스케줄링 로직, 영속적 전달 클레임, 명시적 HTTPS 전송, 불명 결과 처리가 추가되었다. 운영 스케줄러/채널 인수는 여전히 검증되지 않았다.

### P08 중요한 빈칸 탐지·질문 예산·답변 반영
명세: `docs/second-brain-2/work-packages/P08-*.md` (원 명세 PR #12)

구현된 것:
- 규칙 기반 충돌, 계획된 발생, 누락 결과 후보. 취소된 항목과 헬스/위치 항목은 제외한다(`life_questions.candidate`)
- 영속적 일일 예산, KST 방해 금지 시간, 쿨다운, 음소거 억제(`life_questions.issue`; `test_question_budget_persists_across_runs_and_reopen`)
- 예상 리비전 검사와 `user_asserted` 이벤트 리비전을 갖춘 답변/건너뛰기/음소거(`life_questions.prepare_response`; `test_question_skip_mute_and_answer_are_new_evidence`)
- 기존 작성기를 통한 오래된 질문 보호와 정정 게시(`test_stale_question_does_not_apply_to_new_event`; `test_question_answer_republishes_and_readonly_recall`)
- Obsidian 질문 투영과 질문 응답 명령

남은 일:
- [ ] 수락된 `P07` 채널을 통한 질문 전달과 명시적 전달 영수증
- [ ] 모든 워크플로 전반의 Proposed/presented/answered/skipped/muted/stale 상태와 사용자 선택
- [ ] 소스 헬스/커버된 기간 분류가 장애를 사용자 기억 공백으로 보이지 않게 하는지 검증
- [ ] 동시 날짜 경계 예약, 여행 시간대 동작, `AC-12`/`13` 전체 주제 선택 품질 평가 검증

09-26 이후 변화: 순수 헬퍼 전용 상태를 영속화된 예산 기반 질문, 방해 금지 시간/쿨다운, 답변/건너뛰기/음소거, 리비전 고정 업데이트로 대체했다. 채널 전달과 완전한 소스 헬스 분류는 여전히 미완료다.

### P09 상황별·시간별 회상·300문항 검색 평가
명세: `docs/second-brain-2/work-packages/P09-*.md` (원 명세 PR #13)

구현된 것:
- `sb/life_recall.py:recall`: 명시적 어휘 쿼리, 선택적 `as_of`, 소스/범위 게이트, 증거 검사
- `sb/life_recall.py:temporal_versions`: 정책/범위와 유효 시간을 준수하면서 과거 리비전을 선택한다

남은 일:
- [ ] 컨텍스트/as-of/범위 인수, 의미/하이브리드 기준선, 300문항 평가
- [ ] 후보 생성 재검증, 구분된 unavailable/stale/denied 상태, 재순위화/캐시 보장

09-26 이후 변화: Ledger는 `NOT_IMPLEMENTED`라고 했다. 현재 코드에는 어휘 기반 현재/as-of 회상이 있지만, 요구되는 평가나 전체 인수에 대한 열어 본 증거는 없다.

### P10 모델 외부전송 정책·예산·민감정보
명세: `docs/second-brain-2/work-packages/P10-*.md` (원 명세 PR #14)

구현된 것:
- 소스/범위 권한 부여와 로컬 전용/외부 정책 검사: `sb/life_model_policy.py::permit`
- 일일 호출/토큰/비용 예약의 영속화와 보수적 정산: `sb/life_model_policy.py::reserve`
- 모델 입력은 40개 이벤트로 제한되고 인용은 포함된 ID로 한정된다: `sb/life_model_policy.py::generate_after_reservation`
- 경계 테스트가 누락된 레코드 41에 대한 인용을 거부한다: `tests/test_life_model_input_boundary.py::test_model_cannot_cite_omitted_records`

남은 일:
- [ ] 임베딩, 재순위화, 전사, 기타 계획된 생성기를 포함한 모든 모델 소비자에 공통 정책을 통합한다.
- [ ] 실제 프로바이더 장애 시 로컬 프로바이더 라우팅과 외부 폴백 없음을 입증한다.
- [ ] 프로바이더 장애, 캐시 무효화/폐기, 동시 예약, 외부 송신 인수를 완료한다.

09-26 이후 변화: 현재 소스에는 ledger가 남은 작업으로 명시한 일일 예약/회계를 넘어 영속화된 예산 예약/회계가 포함되어 있다. 프로바이더 라우팅과 전체 송신 테스트는 여전히 미해결이다.

### P11 운영 상태·이관·롤백·24개 인수시험
명세: `docs/second-brain-2/work-packages/P11-*.md` (원 명세 PR #15)

구현된 것:
- Life 복원이 수명주기 상태를 캡처하고 페이지/인덱스를 후보로 복원한다: `sb/life_restore.py::preserve_current`
- HTTP 헬스가 워크플로 전달 개수와 뷰 확인(ACK)을 보고한다: `tests/test_life_workflow_http.py::test_persisted_brief_delivery_pagination_ack_and_health`
- 워크플로 테스트가 페이지 단위 매니페스트 무결성, ACK, 전달 불명 상태, 헬스를 다룬다: `tests/test_life_workflow_http.py::test_persisted_brief_delivery_pagination_ack_and_health`
- Ledger 테스트가 SQLite 백업에 tombstone과 삭제 상태가 포함됨을 확인한다: `tests/test_life_store.py::test_backup_preserves_life_rows_and_delete_intent`

남은 일:
- [ ] 완전한 운영 헬스 루프, 단일 작성자 복구/롤백 대조, 기기 ACK 운영.
- [ ] 최신 삭제/정정 권한을 반영한, 검증된 일관된 라이브 백업과 격리 복원.
- [ ] 성능 게이트, 실기기 및 파일럿 인수, requested/run/pass/fail/skip/not-run 릴리스 증거.

09-26 이후 변화: 현재 코드/테스트는 영속화된 워크플로 헬스, 페이지 단위 뷰 ACK, 더 풍부한 복원 동작을 추가한다. 운영 복구, 실기기 게이트, 파일럿 인수는 여전히 미완료다.

### P12 위치 수집·방문/이동 집계·프라이버시
명세: `docs/second-brain-2/work-packages/P12-*.md` (원 명세 PR #16)

구현된 것:
- `life_sensors.parse_overland`가 크기 제한된 GeoJSON 포인트, 타임스탬프, 좌표, 정확도를 검증한다. `point_payload`는 정밀한 원시 위치를 첨부 파일로 보관한다.
- `life_sensors.segments`가 알고리즘 파라미터와 증거 참조를 사용해 방문/이동 추정치를 결정론적으로 도출한다.
- `life_imports.prepare`가 `location_capture` 및 restricted/local_only 정책을 적용한다. HTTP 수신은 `test_overland_success_shape_after_actual_publication`으로 다뤄진다.
- `test_locations_accuracy_gaps_and_replay`가 위치 재생과 정확도 공백 동작을 검사한다.

남은 일:
- [ ] 실제 Overland 앱/버전, 기기 토큰, 영속적 영수증/커서 워크플로를 통합하고 검증한다.
- [ ] 명시적 옵트인/일시 중지/폐기 UI, 위치 보존 기간, 기기 복제 제어를 완성한다.
- [ ] 실제 iPhone의 백그라운드/오프라인/재시작/권한/배터리 동작을 측정한다. 픽스처 테스트로는 이를 입증하지 못한다.
- [ ] 별칭 정정/재집계, 계보/삭제/백업 전파, 위치 프라이버시 검토를 완료한다.

09-26 이후 변화: Ledger는 일반 센서 가드만 언급하며 `P12`를 `NOT_IMPLEMENTED`로 표시했다. 이제 master에는 Overland 파싱, 결정론적 세그먼트, 수신, 테스트가 있다. 실기기 및 운영 게이트는 남아 있다.

### P13 건강·수면 입력·결측·권한 철회
명세: `docs/second-brain-2/work-packages/P13-*.md` (원 명세 PR #17)

구현된 것:
- `health_batch`가 허용 타입, 샘플 식별자, 단위, 시간/값/결측, 삭제, 앵커를 검증한다.
- `LifeHealthBridge`가 HealthKit 앵커 기반 샘플/삭제를 가져오고, 영속 대기 페이로드를 암호화하며, 게시된 영수증 이후에만 앵커를 전진시킨다.
- `life_imports.prepare`가 타입별 정책을 강제한다. `test_health_actual_http_delete_cursor_and_no_resurrection`이 HTTP 영수증, 삭제, 재부활 없음을 검증한다.
- `sleep_union`이 소스별 중첩 처리를 보존하고 평균 내지 않고 상충하는 소스 합계를 보고한다.

남은 일:
- [ ] HealthKit entitlement/서명과 실제 기기 가용성, 타입별 권한 및 OS 동작을 검증한다.
- [ ] 폐기/재부여, 빈 읽기, 오프라인/재시작, 앵커 복원, 소스 삭제 경합에 대한 실기기 테스트를 추가한다.
- [ ] 설정 가능한 보존 기간/View 범위를 완성하고 모든 뷰, 캐시, 백업 복원에 삭제/정정을 전파한다.
- [ ] 프로덕션 싱크/API 배포를 검증하고 픽스처 커버리지를 실제 샘플/기기 증명과 구분한다.

09-26 이후 변화: Ledger는 헬스 플래그 가드만 언급하며 `P13`을 `NOT_IMPLEMENTED`로 표시했다. 이제 master에는 HealthKit 클라이언트 브리지, 샘플/삭제 수신, 정책 검증, 테스트가 포함되어 있다. 실제 기기/권한 인수는 남아 있다.

### P14 사전 예측 원장·실제 결과 연결·채점
명세: `docs/second-brain-2/work-packages/P14-*.md` (원 명세 PR #18)

구현된 것:
- `sb/life_predictions.py:issue`: 컷오프 고정 소요 시간 중앙값, 증거 스냅숏, 데이터 부족 상태
- `sb/life_predictions.py:evaluate` 및 `metrics`: 안정적 대상 연결, 채점/미채점 결과, 오차 지표

남은 일:
- [ ] 완전한 리비전/재평가 이력, 시간적 홀드아웃, 동일 세트 기준선 검증
- [ ] 실제 적격 샘플 품질, 명세 인수, 증거 연결 UI 검증

09-26 이후 변화: Ledger는 `NOT_IMPLEMENTED`라고 했다. 현재 코드는 결정론적 예측/평가 배관을 추가하지만, 실제 샘플 품질과 패키지 인수는 입증되지 않았다.

## 2. 2026-09-23 계획 작업 → SB2 대응

|작업|제목|대응 명세|SB2 포함 여부|코드|
|---|---|---|---|---|
|5|날짜·빈 입력·거부 source의 브리핑 회귀를 고정한다|P07|포함|일부 있음|
|6|스케줄러·권한·readiness 복구를 격리 재현한다|P11|포함|일부 있음|
|7|원본 관측·개인회사 분류 계약을 고정한다|P01|부분(관측 계약·manifest 없음)|일부 있음|
|8|접수와 검색 반영을 구분하는 source admission을 구현한다|P02|부분(receipt 상태 생애주기 없음)|일부 있음|
|9|원문 보존과 외부 AI 전송 정책을 분리한다|P10|포함|일부 있음|
|10|무변경 scan까지 포함한 coverage 영수증을 추가한다|P02, P11|부분(무변경 scan 영수증 없음)|일부 있음|
|11|파생 데이터 lineage와 편집 보호를 관측 계약에 연결한다|P02|포함|일부 있음|
|12|additive migration과 별도 personal profile을 고정한다|P01, P02|부분(별도 personal profile 없음)|일부 있음|
|13|AI 작업 세션을 루트별로 연결하고 재개를 검증한다|P16|없음→신규|신규 영역(아래 P16 참조)|
|14|Unified DB의 늦은 수정·삭제를 읽기 전용으로 포착한다|P16|없음→신규|신규 영역(아래 P16 참조)|
|15|Phone History의 직접 Vault 접근을 HTTP 경유로 바꾼다|P04|포함|일부 있음|
|16|Hermes·Markdown·프로젝트 기록의 수집 범위를 명확히 한다|P16|없음→신규|신규 영역(아래 P16 참조)|
|17|Mac 폴더 동기화의 영수증과 오프라인 재개를 고친다|P16|없음→신규|신규 영역(아래 P16 참조)|
|18|문서 형식·추출 한도·부분 결과를 일관되게 노출한다|P16|없음→신규|신규 영역(아래 P16 참조)|
|19|메일 개인 경로와 회사 donor를 분리해 연결한다|P03|포함|일부 있음|
|20|카톡 내보내기와 기존 Mac 생산자를 정형 관측으로 연결한다|P03|포함|일부 있음|
|21|통화·녹음 원본과 로컬 전사 입력을 연결한다|P03, P17|부분(전사 연결은 신규)|일부 있음|
|22|무료 CPU 로컬 전사 worker를 추가한다|P17|없음→신규|신규 영역(아래 P17 참조)|
|23|첨부·대용량 자료의 상태와 재처리를 명시한다|P02|포함|일부 있음|
|24|모든 소스의 지속 유입과 backlog 소진을 증명한다|P11, P03|포함|일부 있음|
|25|한국어 질문 해석을 기존 literal 검색과 분리한다|P09|부분(한국어 질의 해석 모듈 보강)|없음|
|26|로컬 의미 검색을 권한 필터와 품질 gate에 연결한다|P09|포함|일부 있음|
|27|답변·기권·수집 불완전을 공개 recall 표면으로 제공한다|P09|부분(공개 CLI/MCP recall 표면 보강)|미측정|
|28|회사 기억 회상과 개인 기억을 명시적으로 분리한다|P18|없음→신규|신규 영역(아래 P18 참조)|
|29|인용 ID 충돌과 출처 변경을 끝까지 검증한다|P05|포함|일부 있음|
|30|AI별 자동 문맥 연결과 회상 품질을 측정한다|P18|없음→신규|신규 영역(아래 P18 참조)|
|31|출처 기반 업무·약속 projection을 구현한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|32|기한·상대 날짜·반복 occurrence를 정확히 모델링한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|33|완료·취소·보류·재개를 인과 순서대로 적용한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|34|수집 변화와 독립된 기한 평가를 추가한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|35|추천 선택과 표현을 분리하고 불확실성을 표시한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|36|추천 정책·품질 평가와 설명 가능성을 고정한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|37|JARVIS에 추천 전달 원장을 연결한다|P20|없음→신규|신규 영역(아래 P20 참조)|
|38|Web Push 구독·회전·폐기를 인증 경계에 넣는다|P19|없음→신규|신규 영역(아래 P19 참조)|
|39|서버 Web Push 전송과 불확실한 결과를 처리한다|P19, P07|부분(전달 상태는 P07)|일부 있음|
|40|개인 기억 API를 기존 JARVIS 인증 게이트에 연결한다|P20|없음→신규|신규 영역(아래 P20 참조)|
|41|iPhone 홈 화면 웹앱의 알림·조회 화면을 만든다|P19|없음→신규|신규 영역(아래 P19 참조)|
|42|Mac 알림을 stable delivery와 상태 화면에 연결한다|P19|없음→신규|신규 영역(아래 P19 참조)|
|43|실제 iPhone·Mac 경로를 자동화된 장치 gate로 증명한다|P11, P04|포함|일부 있음/없음|
|44|완료·보류·취소 UI 동작을 revision에 결합한다|P15|없음→신규|신규 영역(아래 P15 참조)|
|45|JARVIS 실행 결과를 검증된 완료 사건으로 전달한다|P20|없음→신규|신규 영역(아래 P20 참조)|
|46|실행과 기억 기록의 응답 유실을 독립적으로 복구한다|P20|없음→신규|신규 영역(아래 P20 참조)|
|47|수집·회상·추천 상태를 하나의 사용자 흐름으로 연결한다|P11|포함|일부 있음|
|48|회사·개인·실행 결과의 교차 흐름을 인수 검사한다|P11|포함|일부 있음|
|49|새 원본·projection·알림 사본을 삭제 inventory에 등록한다|P02|포함|일부 있음|
|50|정정·삭제·완료와 진행 중 전달의 race를 차단한다|P02|포함|일부 있음|
|51|백업에 새 상태를 포함하고 복원 후 부활을 막는다|P02, P11|포함|일부 있음|
|52|scope·키 철회·프롬프트 주입의 교차 경계를 검증한다|P10, P11|포함|일부 있음|
|53|비용·메모리·처리량과 backlog 정책을 고정한다|P11|포함|일부 있음|
|54|전 과정 crash·중복·재접속 인수 검사를 수행한다|P11|포함|일부 있음|
|55|전체 소스와 설치 패키지의 품질 gate를 실행한다|P11|포함|일부 있음|
|56|운영 전환과 롤백을 승인 가능한 단위로 준비한다|P11|포함|일부 있음/없음|
|57|배포된 Mac·iPhone·AI client의 실사용 경로를 확인한다|P11|포함|일부 있음/없음|
|58|지속 유입·기한·알림의 운영 관측을 완료한다|P11|포함|일부 있음|
|59|삭제·복원·장애 복구의 최종 운영 리허설을 수행한다|P11|포함|일부 있음|
|60|사용 설명·운영 절차·미완료 분류를 하나로 정리한다|P11|포함|일부 있음|

요약: 포함 26개, 부분 포함(명세 보강 필요) 8개, SB2에 없음 22개.

## 3. SB2에 없던 작업 — 신규 묶음 P15–P20

릴리스 배정은 제안이다. 각 묶음의 상세 범위는 09-23 계획의 해당 작업 본문(What to do·Acceptance)을 따른다.

### P15 업무·약속 projection·기한·추천 정책
- 릴리스: R2 (제안)
- 09-23 계획 작업: 31. 출처 기반 업무·약속 projection을 구현한다 / 32. 기한·상대 날짜·반복 occurrence를 정확히 모델링한다 / 33. 완료·취소·보류·재개를 인과 순서대로 적용한다 / 34. 수집 변화와 독립된 기한 평가를 추가한다 / 35. 추천 선택과 표현을 분리하고 불확실성을 표시한다 / 36. 추천 정책·품질 평가와 설명 가능성을 고정한다 / 44. 완료·보류·취소 UI 동작을 revision에 결합한다
- 왜 신규인가: SB2 명세에 할 일·약속·기한 모델과 추천 선택 정책이 없다. P07은 사실 카드 브리핑, P08은 빈칸 질문만 다룬다.
- 현재 코드: `sb/obligations.py`, `sb/obligation_time.py`, `sb/reminder_evaluation.py` 없음. 사건 타입과 `life_workflow` 상태, 기대 revision 정정만 있다.

### P16 기존 수집원 보강: AI 세션·Unified DB·Hermes/Markdown·Mac 폴더·문서 형식
- 릴리스: R1 (제안)
- 09-23 계획 작업: 13. AI 작업 세션을 루트별로 연결하고 재개를 검증한다 / 14. Unified DB의 늦은 수정·삭제를 읽기 전용으로 포착한다 / 16. Hermes·Markdown·프로젝트 기록의 수집 범위를 명확히 한다 / 17. Mac 폴더 동기화의 영수증과 오프라인 재개를 고친다 / 18. 문서 형식·추출 한도·부분 결과를 일관되게 노출한다
- 왜 신규인가: SB2 P03은 새 life 입력 adapter만 다룬다. 이미 운영 중인 기존 커넥터의 root 분리, 늦은 수정·삭제 포착, 폴더 동기화 영수증, 문서 추출 한도는 어느 명세에도 없다.
- 현재 코드: 기존 커넥터(`sessions_*`, `unified_db`, `markdown_vault`, `*_documents`)와 Mac 폴더 업로드는 있다. 계획이 요구한 보강은 이번 대조에서 코드로 확인하지 않았다(미측정).

### P17 통화·녹음 로컬 CPU 전사
- 릴리스: R2 (제안)
- 09-23 계획 작업: 21. 통화·녹음 원본과 로컬 전사 입력을 연결한다 / 22. 무료 CPU 로컬 전사 worker를 추가한다
- 왜 신규인가: P03은 '전사 상태를 별도로 둔다'고만 하고 전사 worker 자체는 범위 밖이다.
- 현재 코드: 통화 녹음 첨부 수집(`life_documents`, Phone History)은 있다. 전사 worker는 없다.

### P18 회사·개인 회상 분리와 AI 클라이언트 자동 문맥
- 릴리스: R2 (제안)
- 09-23 계획 작업: 28. 회사 기억 회상과 개인 기억을 명시적으로 분리한다 / 30. AI별 자동 문맥 연결과 회상 품질을 측정한다
- 왜 신규인가: SB2 P09는 개인 life 기억 회상만 다룬다. `sb-company` 조회 분리와 Claude/Codex/OMO/OpenCode 문맥 연결 matrix는 없다.
- 현재 코드: `sb-company` 수신·처리와 MCP 검색은 있다. 분리된 회사 조회와 클라이언트별 문맥 연결 측정은 없다.

### P19 알림 채널: Web Push·iPhone 홈 화면 웹앱·Mac 알림
- 릴리스: R2 (제안)
- 09-23 계획 작업: 38. Web Push 구독·회전·폐기를 인증 경계에 넣는다 / 39. 서버 Web Push 전송과 불확실한 결과를 처리한다 / 41. iPhone 홈 화면 웹앱의 알림·조회 화면을 만든다 / 42. Mac 알림을 stable delivery와 상태 화면에 연결한다
- 왜 신규인가: P07은 전달 상태·중복 억제까지만 다룬다. 구독 관리, 실제 채널, iPhone 웹앱 화면, Mac 알림의 stable delivery ID는 명세에 없다.
- 현재 코드: `sb/web_push.py`는 payload 생성만 한다. `life_delivery`에 HTTPS 전송과 unknown 처리 있음. 구독 저장소·PWA·Mac delivery ID 없음.

### P20 JARVIS 연동: 개인 기억 API 게이트·전달 원장·실행 결과 완료 사건
- 릴리스: R2 (제안)
- 09-23 계획 작업: 37. JARVIS에 추천 전달 원장을 연결한다 / 40. 개인 기억 API를 기존 JARVIS 인증 게이트에 연결한다 / 45. JARVIS 실행 결과를 검증된 완료 사건으로 전달한다 / 46. 실행과 기억 기록의 응답 유실을 독립적으로 복구한다
- 왜 신규인가: JARVIS 저장소 쪽 작업이라 SB2 명세 범위 밖이다. 업무 완료를 인용 가능한 영속 사건으로 남기는 요구가 여기에 속한다.
- 현재 코드: SB 쪽 영수증 재생·기대 revision은 있다. JARVIS `src/personal-memory-*.ts`, 실행 결과→완료 사건, outbox reconcile은 없다.

## 4. 권장 진행
- 남은 개발은 SB2 P00–P14와 P15–P20을 기준으로 진행한다. 09-23 계획은 작업 상세 참고 자료로만 쓰고 그대로 5번부터 실행하지 않는다.
- 부분 포함 작업(7, 8, 10, 12, 21, 25, 27, 39)은 해당 명세 이슈의 남은 일에 추가했다.
- 실기기(iPhone·Mac)·운영 전환·JARVIS 저장소 변경은 코드만으로 끝나지 않는다. 각 이슈에 별도 표시했다.
