# 자비스 인계 병합 — 현재 판정과 완성 작업 목록

기준: 2026-09-08. 최신 Second Brain 제품 `9e30115`, JARVIS 제품 `ea076ae`.
사용자가 전달한 [자비스 인계서](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)의 현재 내용을 기존 구현 원장·통합 계획·실제 클라이언트 인수 기록 및 취소 결과 소스와 대조했다.

**최신 인수 `42ceb35` / JARVIS 제품 `ea076ae` / SB 제품 `9e30115`: [취소 후 정상 V2 seq2의 양쪽 검증·실제 provider 실행](CANCELLATION-FOLLOWUP-PROVIDER-ACCEPTANCE-2026-09-08.md).**
취소 settlement/cursor1인 provider에 독립 기억을 저장하고 delta1개/sequence2 정정을 양쪽 validator와 실제 executor에서 proved까지 확인했다.
커밋된 wiki의 정정 반영·이전/취소 내용 부재·재실행 idle을 확인했다. 관련9통과·Ruff/syntax/diff통과.
JARVIS는 wire validator만 실행했으며 실제 seq2 authority/dispatch/완료는 미인수다. JARVIS cursor1과 전체 운영 목표를 유지한다.

**이전 JARVIS `ea076ae` / SB 제품 `9e30115`: [검증된 취소 완료·cursor 원자 저장·실제 중단 재생](CANCELLATION-SETTLEMENT-ACCEPTANCE-2026-09-08.md).**
현재 provider 신뢰·exact 로컬 영수증·미전송 억제 근거·직전 순번을 대조해 불변 settlement와 cursor를 같은 transaction에 저장한다.
실제 provider 결과→로컬 처분/완료 후 exit77→새 Node 동일 재생·cursor1을 인수했다. 최종29통과·타입/lint/격리emit통과.
정상 V2 seq2의 양쪽 검증/실행/완료는 아직 미인수이며 전체 운영 목표도 유지한다.

**이전 JARVIS `91f2f95` / SB 제품 `9e30115`: [교체 직후 중단의 사전 정보·보존 파일·실제 복구](CANCELLATION-SWAP-RECOVERY-ACCEPTANCE-2026-09-08.md).**
새 DB 안에 결과 inode/세대·검사 정보를 사전 기록하고 이전 DB의 inode 재사용을 보존 링크로 막는다. old-FD0 검증 후 보존 파일을 제거한다.
실제 provider 결과→rename 직후 exit77→새 Node 로컬20검사·동일 영수증을 인수했다. 최종22통과·타입/lint/격리emit통과.
사전 정보 없는 과거 미확정 파일·전체 settlement/cursor seq1→V2seq2 및 전체 운영 목표는 남는다.

**이전 JARVIS `112c520` / SB 제품 `9e30115`: [교체 전 중단의 검증된 재구축·실제 프로세스 인수](CANCELLATION-PRESWAP-RECOVERY-ACCEPTANCE-2026-09-08.md).**
현재 원 DB inode/세대·결과/대상/범위/layout·미완료 상태를 대조해 기존 job/input으로 재구축한다.
실제 provider 결과→사본 처분 후 swap 직전 exit77→새 Node 재구축·교체·동일 영수증을 인수했다. 최종10통과·타입/lint/격리emit통과.
rename 뒤 결과 inode 저장 전 중단·전체 settlement/cursor seq1→V2seq2 및 전체 운영 목표는 남는다.

**이전 JARVIS `0906655` / SB 제품 `9e30115`: [실제 취소 결과→로컬 DB 처분→강제 종료·동일 복구](CANCELLATION-LOCAL-COMPACTION-ACCEPTANCE-2026-09-08.md).**
provider 가상 inventory 없이 현재 검증 결과에서 로컬 compaction을 실행하고 실제20검사·DB교체 증거를 불변 저장한다.
실제 Python CLI 결과→별도 Node 처분 후 exit77→새 프로세스 동일 영수증을 인수했다. 재시작 세대1 고정 및 inode 재사용 오인도 수정했다.
최종25통과·타입/lint/격리emit통과. purge verifying/cursor0 유지. pre-swap·swap 메타데이터 전 중단 복구, 전체 settlement·seq1→V2seq2 및 운영 목표는 남는다.

**이전 JARVIS `830ca2d` / SB 제품 `9e30115`: [DB 재구성 중 쓰기 유실 경합 수정](COMPACTION-WRITER-EXCLUSION-ACCEPTANCE-2026-09-08.md).**
fresh DB 생성 후에도 runtime 쓰기가 허용되는 경합을 재현했다. drain부터 생성·교체·검사·완료까지 같은 quiesce로 보호하고 recover에도 적용했다.
최종15통과·타입/lint/격리emit통과. 실제 fresh 파일 이벤트 중 쓰기 거부, inode교체 후 새 쓰기·별도 DB 연결의 철회 상태 보존을 확인했다.
직접 DB/외부 작성자 전역 배제는 미보장이다. 취소 완료 기록/cursor·seq1→V2seq2와 전체 운영 목표를 유지한다.

**이전 JARVIS `89dbfc8` / SB 제품 `9e30115`: [취소 DB 교체 검증·실제 로컬20 관측](CANCELLATION-LOCAL-OBSERVATION-ACCEPTANCE-2026-09-08.md).**
기존 scanner를 재사용해 provider 관측 없이 JARVIS20개 관리 영역을 검사하며 금지 본문 해시 집합에 결과를 결합한다.
실제 분리 프로세스 저장/처분 exit77→새 프로세스 로컬20검사 통과. 기존 전체70 fixture로 취소 DB inode교체·결과/체크포인트 보존도 검증했다.
최종 관련6통과·타입/lint/격리emit통과. 특정 취소의 불변 로컬 완료 기록·provider 범위 조율·cursor seq1→V2seq2와 전체 운영 목표는 남는다.

**이전 JARVIS `93f1344` / SB 제품 `9e30115`: [취소 spool 수집 누락 수정·체크포인트·실제 중단 복구](CANCELLATION-MATERIAL-ACCEPTANCE-2026-09-08.md).**
원 요청과 파일 본문을 검증해 기존 compactor 재료로 연결하고 제거 전 본문 없는 증거를 원자적으로 보존한다.
실제 분리 프로세스에서 저장/처분 후 각각 exit77→복구, 파일2개 제거·본문일치0·체크포인트1을 확인했다.
관련23통과 이후 최종추가 관련15통과(중복), 타입/lint/격리emit통과. provider40 증거가 없는 취소의 전체70 검증·DB교체 완료/cursor·seq1→V2seq2는 미완료다.

**이전 JARVIS `9d8c0ed` / SB 제품 `9e30115`: [취소 결과의 자비스 불변 저장·현재 신뢰·실제 중단 복구](CANCELLATION-RESULT-STORAGE-ACCEPTANCE-2026-09-08.md).**
실제 provider 서명 결과를 원 의향/요청/삭제 이력과 등록 키에 결합하고 현재 철회를 재검사한다.
실제 CLI 결과→별도 Node DB 저장 직후 exit77→다른 프로세스 동일 재생·1행·철회 거부를 확인했다. JARVIS최종57통과·타입/lint/격리emit통과.
로컬 진단은 차단projection2개·수집본문0개·spool대체본문존재였다. 기존 전체70표면 계약도 취소 결과와 달라 그대로 적용할 수 없다.
검증된 spool 처분 재료·실제 로컬 검사/DB 교체→결과/cursor·seq1→V2seq2와 기존 전체 운영 목표를 유지한다. 자동skip보류.

## 최신 인계 재대조와 후속 발행 회귀 검사

사용자가 재전달한 인계서의 최종 방향을 다시 확인했다. 기존 OSS 대조표·14개 추적 항목·클라이언트별 조회/쓰기/수집/주입 구분을 유지한다. 인계서의 과거 931개 테스트와 초기 파일 존재 목록보다 현재 제품 및 개별 인수 증거를 우선한다. 이번에는 upstream 설치·코드 복사 없이 기존 자비스 API를 재사용했다.

JARVIS 테스트 커밋 `30cf131`은 동일 DB에서 취소 결과 저장→로컬 compaction→settlement 이후 새 후보를 검증하고, 실제 command API의 서명 확인·정정 준비·실행 승인·claim·dispatch를 수행한다. cursor를 테스트에서 직접 수정하지 않는다. 발행 요청은 실제 wire validator를 통과하며 delta 1개, sequence 2, 이전 root 일치, 발행 1회, cursor 2, 원 취소 writer 호출 0회를 확인했다.

**범위 제한:** 권한 증거·대상·provider generation status·accepted 응답은 결정적 fixture다. 최종 정정 상태는 `reconciling`이며 `settled`가 아니다. cursor 2는 접수된 발행 순번을 뜻한다. 앞서 실제 Python provider에서 seq2가 proved된 검사와 이번 자비스 API 검사는 아직 서로 분리되어 있다. 두 검사의 성공을 하나의 전체 연동 성공으로 합치지 않는다.

재검증: TypeScript `tsc --noEmit`, 변경 두 파일 ESLint `--max-warnings=0`, Vitest 직렬 실행 **1 passed / 6.34초**. 제품 소스·계약·migration 변경은 없다. 전체 테스트와 실제 운영 서비스를 이번에 재실행한 것은 아니다.

다음 구현 단위는 기존 실제 취소 인수의 자비스 DB를 보존한 채 같은 DB의 후속 command dispatch를 실제 provider 접수·실행에 연결하는 것이다. 그 다음 provider 결과와 관리 대상 사본의 관측 증거를 기존 완료 gate에 전달한다. 필수 실패 검사는 접수 응답 유실, 재시작 재조회, 키 철회, 중복 발행, 취소된 원 요청의 재발행 거부다. 공개 상태와 테스트용 accepted 응답을 혼용하지 않는다.

## 현재 판정

**핵심 기능은 격리 환경에서 동작을 검증했지만, 자비스와 여러 에이전트의 운영 공통 기억으로 전체 인수를 완료한 상태는 아니다.** 운영 서비스의 현재 실행 여부는 이번 문서 대조에서 조회하지 않았다. 테스트 성공과 운영 가동을 구분한다.

- 저장·검색·출처·세대·정정/삭제·재유입 차단의 기존 구현을 유지한다. 상세 수정 이력은 [구현 원장](IMPLEMENTATION-STATUS.md)을 따른다.
- 실제 Codex CLI와 Claude Code의 양방향 기록·회수를 확인한 기록이 있다. 이는 격리된 단일 소유자 환경의 인수이며, compile은 결정적 fixture였다. 실제 LLM의 추출 품질·프로젝트 접근 제어·자동 수집·주입까지 입증하지 않는다. [클라이언트 인수](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md)
- 취소 결과는 실제 처분 증거와 서명을 결합하고 불변 저장·재생한다. schema6의 공개키 기반 상태 조회와 JARVIS 검증은 실제 stdio에서 인수했다. DB 의향 발급도 후속 완료했으며 외부 취소 접수·응답 유실 복구까지 연결했다. 접수 후 명시적 CLI 처분·서명 결과·Node MCP 조회까지 검증했다. JARVIS 취소 전용 로컬 영수증·DB 교체·중단 복구·settlement/cursor1은 후속 인수했다. 외부 원 요청 전송과 취소의 통합 경합, 다음 정상 요청의 자비스 전체 완료는 남는다. [상태 MCP 인수](CANCELLATION-MCP-ACCEPTANCE-2026-09-08.md), [DB 발급 인수](CANCELLATION-DB-ACCEPTANCE-2026-09-08.md)
- 인계서에 인용된 931개 테스트 등의 과거 관측을 현재 수치로 사용하지 않는다. SB 전체 1,093 passed/2 skipped 이후 최종 서명 권한 관련 67통과가 있다. 이 수치는 당시 실행 기록이다. 이후 JARVIS 제품 ea076ae까지 취소 로컬 처분·복구·settlement를 보강했으며, 각 집중 검사의 범위는 개별 보고서를 따른다. 이전 EPIPE 실패 실행은 성공으로 계산하지 않는다. 전체 검사와 이후 집중 검사를 합산하지 않는다.

## 네 OSS와 기존 구현의 대조

아래 OSS 설명은 인계서의 고정 커밋 조사 결과를 재사용한 것이다. 이번 작업에서 upstream 조사·설치·코드 복사는 하지 않았다.

| 대상 | 흡수할 장점 | 기존 구현과 판단 | 다음 적용 조건 |
|---|---|---|---|
| LightRAG | 근거 연결 검색, 변경 후 파생 검색 일관성 | FTS5·cosine/RRF·봉인 세대·인용·삭제 원장을 재사용 | 실제 한국어 질문으로 근거 회수와 지연을 비교한 뒤 관계 확장 여부 결정 |
| TencentDB-Agent-Memory | 공통 인터페이스, 사용자/프로젝트 범위, 출처·상태 | 기존 MCP와 자비스 adapter를 개선. 일반 접근 범위는 남음 | 같은 provider의 검색·원문·변경·export·restore에 일관된 범위 검사 |
| code-brain | 작은 문맥 묶음, 결정/실패의 근거, 사용량 관측 | 기존 예산·참조 준비·세션 전달 구현을 재사용 | 실제 세션 전달과 compaction 이후 재사용까지 검증 |
| memory-bank | 원문 추적, 중복·정정·대체, 세션 중복 공급 방지 | CAS·파생 계보·기억 record·수명주기를 재사용 | 원작업의 실패/철회가 파생 기억과 세션 사본까지 전파되는지 검증 |

Second Brain은 개인·업무 기억 정본, JARVIS는 실행과 결과 검증, dev-wiki/Git은 개발 결정과 운영 규칙의 원문을 유지한다. 에이전트마다 별도 기억 DB를 만들지 않는다. 코드 채택이 실제로 필요해질 때 파일·커밋·라이선스·NOTICE를 기록한다.

## 수정·개선·고도화 목록

P0는 공통 기억의 정확한 사용과 완료 판정을 막는 항목, P1은 1차 운영 인수, P2는 측정 후 확장이다. 아래 14개 항목은 최초 잔여 목록에서 시작한 추적표다. 조회·키 정책은 완료했고 DB 발급은 부분 완료했으며 상태를 각 행에 표시한다.

| 우선·분류 | 문제와 영향 | 구현 방향·담당 경계 | 완료 조건 |
|---|---|---|---|
| 완료: 취소 상태 조회 | 저장된 최종 결과를 외부 소비자가 조회할 수 없어 응답 유실 이후 흐름이 끊김 | SB에 현재 읽기 권한으로 exact intent ID/digest의 저장 결과 조회. 기존 frozen 계약을 유지하는 명시적 schema6 구현·인수 완료 | 미접수/진행/완료 구분, 잘못된 fence·ID 거부, 재시작 후 동일 결과, 조회 중 재발급 없음 |
| 완료: 키 교체 후 과거 결과 읽기 | 현재 개인키에 묶인 재생 경로로는 서명키 교체 시 과거 결과 검증이 불편함 | 발급 권한과 과거 공개키 집합 분리·철회 정책 및 개인키 없는 조회 인수 완료 | 개인키 없이 조회, 허용된 과거 키 검증, 알 수 없거나 철회된 키 거부 |
| P0 부분 완료: 취소 의향 생성·전송 경합 | 내부 취소 접수는 있어도 자비스의 실제 미전송 상태와 외부 전송을 한 경계로 보장해야 함 | JARVIS DB 발급·발행 직전 권한 재검사·schema7 실제 접수·응답 유실 복구 완료. 외부 원 요청 전송과 취소의 통합 경합은 남음 | 전송 우선/취소 우선 경합에서 상반된 완료 없음, 중단 재시도 중복 효과 없음 |
| P0 수정: 후속 요청 진행 | 취소 접수나 내부 세대 활성화만으로 처리 위치를 넘기면 누락 가능 | provider 결과의 DB 저장·현재 신뢰 검증 완료. spool 본문 수집 누락 수정·체크포인트 인수 완료. 취소 전용 로컬 DB 처분·불변 영수증·실제 중단 복구 완료. 검증된 settlement/cursor1 실제 인수 완료. 정상 V2 seq2의 실제 provider proved·커밋 본문 일치까지 인수. 자비스 authority/dispatch부터 최종 완료까지 연결한 인수는 남음 | 실제 취소 seq1 완료→정상 V2 seq2 처리. 순서 건너뛰기·증거 없는 완료 없음 |
| P0 개선: 사용자·프로젝트 범위 | 공통 연결이 허용되지 않은 기억 공유로 확대될 수 있음 | 검색·직접 원문·target·쓰기·export·restore에 같은 검증된 범위 적용. agent 명칭을 권한으로 사용하지 않음 | 범위 밖 자료가 검색/원문/관계 확장/복원으로 노출되지 않음 |
| P0 수정: 원작업→기억 계보 | 실패·철회된 원작업의 파생 기억이 유효한 경험으로 남을 수 있음 | 원 task·실행 결과·후보·provider record 식별자를 연결하고 철회 전파 | 실패 결과의 성공 기억 승격 없음, 철회 후 재수집·재색인·복원 재노출 없음 |
| P0 개선: native 세션 사본 수명 | provider 삭제가 CLI 세션·SQLite WAL·백업 삭제까지 뜻하지 않음 | 관리 대상 파일/세션과 작성자 정지·보존 정책을 명시하고 실제 connector에서 확인 | 관리 대상 사본 처분 증거, compaction·재시작 후 삭제 기억 재공급 없음 |
| P0 통합: 자비스 실제 사용 순환 | 개별 함수·격리 transport 성공만으로 사용 화면부터의 전체 동작을 입증할 수 없음 | 실제 앱 조회→검증된 결과의 저장 요청→완료 확인→새 세션 재조회 연결 | 한 요청의 ID·출처·버전·결과를 전 구간 추적, 중복 전송 0 |
| P1 개선: 클라이언트 지원표 | MCP 조회 지원과 자동 수집·주입 지원이 혼동되기 쉬움 | Codex/Claude의 기존 실제 증거 유지. OpenCode/OMO/기타는 버전별 네 기능을 별도 검증 | 조회·쓰기·수집·주입을 각각 지원/미지원/미검증으로 표시 |
| P1 개선: 문맥 공급 품질 | 예산 내 검색 결과가 실제 모델에게 전달됐다는 증거는 아님 | 기존 참조/예산/전달 이력을 연결하고 정정 버전·제외 이유 기록 | 전달 실패 재시도, 세션 내 중복 방지, compaction 후 필요한 최신 기억 재공급 |
| P1 수정: 복구 증거와 미지원 사본 | 원본 제거 후 증거 누락/사본 변경이나 미지원 압축을 자동 성공 처리할 수 없음 | 기존 체크포인트를 대조하는 진단·복구 경로. ZIP/xz/bz2/Git pack 지원은 제한과 검증을 정의한 후 확대 | 변경된 사본을 놓치지 않음, 무관한 정상 백업 보존, 반복 복구 수렴 |
| P1 개선: 검색 평가 | 실제 사용자 질문의 정답 근거·오래된 결정 노출·지연을 종합 판단할 자료 부족 | 한국어 100~300문항 기준선, lexical/hybrid 동일 조건 비교. 근거 부족 시 no_data | 근거 Recall@k·오답/구버전 노출·p95·주입량 비교, 합성 데이터와 실사용 결과 구분 |
| P1 개선: 화면·운영·재해 복구 | health 성공과 검색/계약/복원 준비 상태가 다름 | 기존 GUI/API에 미처리·실패·stale 상태 반영. 새 runtime에 설정·identity·원장·최신 삭제 상태를 함께 복원 | 실제 읽기/쓰기 복구, 삭제 기억 부활 없음, 실패 rollback, RPO/RTO 실측 |
| P2 고도화: 선택적 관계 확장·유효 시점 | 그래프 및 추가 LLM 단계는 비용과 정합성 부담을 늘림 | 기준선에서 부족한 질문 유형에 한해 관계/시점/supersedes 개선 | 근거 회수 이익을 측정하고 삭제·범위 회귀 통과; 이익 없으면 비활성 유지 |

구현 순서는 **취소 조회·키 정책 → 자비스 의향/전송/완료 연결 → 범위·계보·세션 수명 → 실제 앱 전체 인수**다. 검색 측정과 운영 가시성은 독립적으로 진행할 수 있다. 다른 업무 실행자 대량 연결은 1차 인수 이후다.

## 유지하는 보류와 이유

- 취소 결과를 정상 정정의 전체70표면 완료 증거로 대체하는 방식: 보류한다. spool 수집·취소 전용 로컬20 관측·DB 교체·불변 영수증·settlement/cursor1은 구현·인수했다. 그 증거의 범위를 외부 사본이나 정상 정정 전체 완료까지 확대할 수는 없다.
- 차단 lane 건너뛰기와 자동 retirement: 실제 양쪽 validator가 `EFFECT_TOMBSTONE_DELTA_INVALID`로 거부한 기록이 있다. 유효한 취소 완료 계약 없이 재도입하지 않는다.
- 자동 collector 확대: 원작업 실패·철회와 파생 기억의 계보 검증이 선행되어야 한다.
- 네 제품 전체 설치, 별도 Proxy/기억 서버, 그래프 DB 일괄 도입: 확정 방향과 기존 구현 재사용 원칙에 맞지 않으며 현재 연동 결함을 해결하지 않는다.
- 운영 완료 선언: 실제 앱·범위·세션 수명·복구 인수가 남는다. provider 로컬 억제 영수증을 모든 외부 사본 삭제 증거로 해석하지 않는다.

최초 문서 변경은 분석이었다. 후속 schema6 상태 조회와 DB 의향 발급은 위 인수 보고서를 따른다. 명시적 취소 접수 schema7도 추가했다. 접수 후 명시적 CLI 실행·서명 결과·조회까지 연결했다. JARVIS 취소 cursor1은 인수했으며, 후속 정상 정정의 전체 완료와 운영 설정 활성화는 미완료다.

## 최초 문서 대조 당시 재검증

`TMPDIR=/var/tmp .venv/bin/pytest -q tests/test_cancellation_result.py tests/test_mcp_profile_compatibility.py tests/integration/test_walking_skeleton.py`

결과: **24 passed, 15.58초**. 취소 결과, 기존 MCP 프로필 호환, walking skeleton을 재검증했다. 전체 테스트 재실행이나 실제 운영 서비스 인수 결과는 아니다. 문서 변경은 `git diff --check`를 통과했다.
