# 자비스 인계 병합 — 현재 판정과 완성 작업 목록

**2026-09-09 JARVIS `29c26f1` / SB `ab0776f`:** [scoped v2 상태 조회·목적 분리·실제 전후 세대 검사](SCOPED-GENERATION-STATUS-2026-09-09.md). v1 유지, v2 status/read/search 세 도구. 관련JARVIS102·SB23통과·실제 status→조회/검색→status 및 철회 거부, 계약6개 패키징 검증. 기존 context adapter 연결·HTTP 인증 경계 및 전체 잔여 목표는 유지한다.

**2026-09-09 JARVIS `eafe913`:** [세션 시각 역행/비정상 발급 수정·실제 재인수·누적 전체 검사](PHONE-SESSION-CLOCK-2026-09-09.md). 수정 전7실패→관련57통과·격리emit/lint·실제 MCP 재인수. 수정 직전 누적 SB 전체1,141통과/2skip/214.33초. scoped 상태 조회→기존 context 연결과 HTTP 인증 경계 및 전체 잔여 목표는 유지한다.

**2026-09-09 JARVIS `7ae0684` / SB 인수 `7a675d0`:** [기존 phone 쿠키 인증→기억 세션 공급자·실제 MCP 인수](PHONE-MEMORY-SESSION-SOURCE-2026-09-09.md). 관련50통과·격리emit/lint통과. 기존 세션 buffer 노출 수정, 쿠키 누락·만료 거부 및 응답 후 철회 차단 확인. HTTP 게이트웨이→백엔드의 인증 세션 전달·정책 배정·전체 운영 인수는 남으며 공통 CSRF의 agent 인증 재해석은 보류한다.

**2026-09-09 JARVIS `62af9e2` / SB 인수 `67a2e22`:** [issuer→전송→소비 클라이언트 및 반환 직전 철회 차단](SCOPED-CLIENT-DELIVERY-2026-09-09.md). 관련19통과·격리emit/lint통과. 실제 MCP 응답 직후 정책 파일에서 세션을 철회하면 결과 반환을 거부했다. 실제 앱 인증 세션·모델 context/보존 수명 및 M2~M14 인수는 남는다.

**2026-09-09 JARVIS `ff0aecc` / SB `687ecf6`:** [고정 scoped 계약→기존 supervised transport→실제 MCP→소비자·재시작 검증](SCOPED-SUPERVISED-TRANSPORT-2026-09-09.md). 전송 관련91통과·SB6통과, 격리 패키징 계약5개 확인. M1 전송 연결은 검증했으며 실제 인증 세션/제품 context 연결·M2~M14와 전체 운영 목표는 남는다. 일반 adapter의 프로필 일괄 전환은 보류한다.

**2026-09-09 최신 통합 분석:** [수정 완료 8항목·잔여 14항목·OSS 대조·완료 조건](SHARED-MEMORY-CONSOLIDATED-REVIEW-2026-09-09.md).
**SB `ec76b14` / JARVIS `8a697d0`:** [제한 응답의 요청·claim·record 소비자 검증](SCOPED-RESPONSE-CONSUMER-2026-09-09.md). JARVIS17·SB19 집중 통과, 실제 별도 MCP 조회/검색→Node 소비자·변조 거부·재시작 반복 확인. 실제 인증 세션과 supervised transport, scoped 쓰기 및 전체 운영 인수는 남는다. 아래 과거 항목은 당시 기록이며 현재 판단은 최신 통합 분석을 우선한다.

**2026-09-09 JARVIS 파일 정책 `623ef50` / 인수 `79ede52`: [현재 정책·인증 세션 대조 공급자와 실제 MCP 연결](MEMORY-ACCESS-FILE-POLICY-2026-09-09.md).**
소유자 전용 정책 파일을 매 발급 다시 읽고 session/project/method/provider/만료를 대조한다. 누락·손상·철회·불안전 파일은 캐시 없이 거부한다. 관련21통과/13.97초·lint/타입/격리emit통과, 실제 파일 공급자→issuer→stdio 조회/검색 인수. 실제 앱 인증 세션 연결·기발급 claim의 전역 철회 및 전체 운영 목표는 남는다.


**2026-09-09 선택 누락 성공 오표시 수정 `5c8fcb2`: [없는 source ID·혼합 선택의 사전 실패](INGEST-SELECTION-VALIDATION-2026-09-09.md).**
수정 전 두 실패로 재현하고 전체 명시적 선택을 scan 전에 확인한다. 누락 ID가 있으면 SOURCE_NOT_FOUND로 실패하며 정상 원본만 부분 수집하지 않는다. 최종68통과/8.34초·Ruff/diff·정적0오류/기존경고1. 실제 CLI 원본/분류/커서 보존 확인. connector별 ID 지원과 전체 운영 목표는 남는다.


**2026-09-09 다중 원본 수집 수정 `db685e9`: [동일 adapter의 원본3 수집·커서 독립성·중복 ID 거부](MULTI-SOURCE-INGEST-FIX-2026-09-09.md).**
pipeline에서 configured source ID별 인스턴스를 선택해 첫 root만 수집되던 markdown 배치 결손을 수정했다. 실제 CLI source3/classification3, 재실행 동일, B만 갱신·A/C cursor 유지, 중복 ID 거부를 인수했다. 최종 전체1,138통과/2skip/201.63초·Ruff/diff통과·정적0오류/기존경고1. 다른 factory의 임의 ID 지원과 기존 전체 운영 목표는 남는다.


**2026-09-09 제한 검색 `d561f63`: [허용 record 선택 후 limit·실제 서명 검색·새 수집 결손](SCOPED-MCP-SEARCH-2026-09-09.md).**
제한 연결에 sb_search를 추가하고 전체 페이지 범위 검사 후 lexical record를 선택한다. query/limit 서명 결합, 불허 snippet/score 제외. 최종31통과/5.56초·Ruff/diff·정적0오류/0경고, 실제 issuer→stdio 검색2개·limit 변조 거부. 같은 adapter 여러 root가 첫 source만 수집되는 P0 결손을 새로 확인했으며 다음 수정 대상이다. 나머지 운영 목표는 유지한다.


**2026-09-09 실행 중 정책·키 철회 반영 `867d65b`: [동일 MCP 연결의 설정 변경·조회 중 만료 차단](SCOPED-MCP-POLICY-REFRESH-2026-09-09.md).**
고정된 설정 경로를 조회 전후 다시 읽고 세션/저장소 변경은 거부한다. 키 철회·손상·설정 삭제·조회 중 만료 시 본문 반환을 차단한다. 최종관련30통과/4.31초·Ruff/diff·정적0오류/0경고. 실제 stdio 동일 연결의 변경 거부·복원·재시작 반복을 인수했다. 운영 resolver·나머지 표면·정책 rollback/복구 및 전체 목표는 남는다.


**2026-09-09 범위 제한 MCP record 연결 `31d9ab1`: [실제 stdio·재시작·우회 도구 차단](SCOPED-MCP-RECORD-READ-2026-09-09.md).**
명시적 서버 문맥과 claim을 대조하는 `scoped-record-read-v1`에 `sb_read_page`만 등록한다. 실제 JARVIS issuer→별도 MCP→record2 회수와 잘못된 요청/claim 누락/변조 거부·새 프로세스 동일 응답을 확인했다. 최종 전체1,136통과/2skip/208.36초·Ruff/diff·정적0오류/0경고. 운영 resolver·정책 자동 갱신·전체 표면 및 기존 운영 목표는 남는다.


**2026-09-09 JARVIS `90bf269`: [범위 공급자의 시각 변경으로 만료 범위를 발급하는 결함 수정](ACCESS-CLAIM-CLOCK-FIX-2026-09-09.md).**
수정 전 회귀1실패/2통과로 재현하고 발급 시각 고정·공급자 Date 분리·변경 거부를 적용했다. 최종18통과/15.38초·lint/격리emit통과. 실제 issuer→Python→봉인 페이지 재인수 성공. 운영 resolver·scoped MCP 및 전체 잔여 목표는 유지한다.


**2026-09-09 JARVIS issuer `c5ad24b` / SB `3b2a08d`: [현재 키·범위 검사 발급과 실제 상호 검증](ACCESS-CLAIM-ISSUER-2026-09-09.md).**
매 요청 범위를 다시 조회하고 현재 DB 키 검사·fence·요청 digest와 만료를 결합한다. 기존 긴 provider/key ID 호환을 수정했다. JARVIS17통과/13.10초·SB31통과/6.02초·타입/lint/격리emit통과. 실제 issuer→Python→봉인 페이지를 인수했으나 scope resolver는 fixture다. 운영 resolver·scoped MCP 및 전체 운영 목표는 남는다.


**2026-09-09 범위 claim 검증 `d220902`: [계약·실제 Node 서명/Python 검증·잔여 issuer 경계](ACCESS-CLAIM-VERIFICATION-2026-09-09.md).**
별도 서명 claim을 현재 읽기 fence·provider/principal·agent/session·정책·실제 요청·유효 시간에 결합한다. 페이지 provider/삭제 high-water도 대조한다. 최종 관련43통과/7.33초·Ruff/diff·정적0오류/0경고. 실제 Node 테스트 서명과 봉인 CLI 페이지 범위 판정을 인수했다. 운영 JARVIS 발급·scoped MCP·다중 사용자·전체 표면과 기존 운영 목표는 남는다.


**2026-09-09 봉인 record 분류·내부 범위 판정 `62da782`: [구현·실제 CLI·남은 인증 경계](MEMORY-ACCESS-READER-2026-09-09.md).**
같은 세대 원장·커밋 본문·전체 원본 분류를 결합해 record를 읽고, 이미 인증된 scope의 owner/project/revision을 대조한다. 최종 관련32통과/8.42초·Ruff/diff·정적0오류/0경고. 실제 CLI 산출물의 요구 원본2/record2 및 네 범위 거부·읽기 불변을 인수했다. 내부 함수이며 caller 인증·scoped MCP·모든 표면 적용과 전체 운영 목표는 남는다.


**2026-09-09 페이지 출처 보강 `f16c142`: [원본·이전 본문 요구 분류와 커밋 해시 결합](PAGE-ACCESS-PROVENANCE-2026-09-09.md).**
원장v4에 실제 컴파일 입력과 이전 페이지의 요구 원본을 보존한다. 인용 중복 제거·미추적 캐시·미분류 본문으로 접근 범위가 조용히 넓어지지 않도록 불완전 상태를 명시한다. 실제 격리 CLI 갱신·재실행에서 요구 원본1→2 및 커밋 해시 결합을 확인했다. 최종 전체1,108통과/2skip/210.84초·Ruff/diff통과·정적0오류/기존경고1. fake LLM 인수이며 scoped MCP 권한 검사와 전체 운영 인수는 남는다.


**2026-09-09 SB 제품 `62b1609`: [설정 기반 원본 분류 저장·WAL 백업 수정·실제 CLI 인수](SOURCE-ACCESS-CLASSIFICATION-2026-09-09.md).**
source ID/URI/내용 해시에 owner/projects/policy revision을 결합하고 같은 수집 transaction에 보존한다. 재수집은 같은 분류를 재사용하고 재분류는 거부한다. 과거 무분류 원본은 자동 project 분류하지 않는다.
원장v3 마이그레이션의 main 파일 복사에서 WAL 누락을 재현·수정했다. 최종전체1,104통과/2skip/205.82초·Ruff/diff통과·정적0오류/기존경고1. 실제 봉인 CLI 최초/재수집0·재분류1 및 분류 보존을 인수했다.
원본 분류만 구현됐으며 MCP 접근 제어는 아직 적용하지 않았다. 파생 record/page·자비스 claim/요청 버전·모든 읽기/쓰기/복원 표면 연결과 기존 전체 운영 목표를 유지한다.


**2026-09-09 제품 수정 JARVIS `f7663ca`: [완료 proof의 키 유효 시점 누락 수정·실제 재인수](PROOF-KEY-WINDOW-ACCEPTANCE-2026-09-09.md).**
현재 활성 키라는 이유로 유효 기간 시작 전 completed_at의 proof를 수락하는 결함을 재현했다. 현재와 완료 시점 양쪽 유효 기간을 검사한다. 최종14통과/40.59초·타입/lint/격리emit통과.
실제 MCP→proof/40영역/10guard→로컬70검사→settled/completed·독립 재조회까지 다시 통과했다. 사용자/project ACL은 미구현이며 분류/claim/record 바인딩 및 전체 운영 잔여 목표를 유지한다.


**2026-09-09 자비스/MCP 경합 인수 `fd5e9b5`: [발행 응답 기록 전 취소·취소 제출 중 원 요청 재시도](CANCELLATION-JARVIS-MCP-RACE-2026-09-09.md).**
원 요청 선행은 실제 MCP쓰기1/취소0, 취소 선행은 원 요청쓰기0/취소 의향1 및 응답 유실 복구를 확인했다. 실제 provider 실행·커밋 본문도 각 승자와 일치했다. 관련14통과/15.13초·Ruff/syntax/diff통과.
선택한 같은 자비스 프로세스 async 경계의 실제 전송 인수다. 여러 runtime/직접 DB 작성자·root 정체성, ACL·계보·native·실제 앱·검색·운영 복구는 남는다. 단순 quarantine을 취소 근거로 사용하는 경로는 보류한다.


**2026-09-09 접수 경합 인수 `686f6e8`: [같은 원 요청과 취소의 두 순서·파일 저장 직후 중단](CANCELLATION-ORIGINAL-ADMISSION-RACE-2026-09-09.md).**
실제 별도 프로세스에서 원 요청/취소 선행 모두 단일 승자, 새 executor의 결과·커밋 본문을 검증했다. 요청 파일 저장 후 exit77에서도 취소 오승인 없이 원 요청 복구·한 번 실행을 확인했다.
관련14통과 이후 본문 검사를 추가한 최종3통과/6.75초(중복)·전체Ruff/diff통과. 제품 수정 없음. Node MCP/JARVIS 발행부터의 통합 경합 및 전체 운영 목표는 남는다.


**최신 실제 인수 `9044f27`: [취소 후 seq2의 실제 proof·관측·compaction·settled·독립 재조회](CANCELLATION-FOLLOWUP-SETTLED-ACCEPTANCE-2026-09-09.md).**
같은 자비스 DB에서 실제 MCP 발행→provider 서명/40개 영역/10개 guard 검증→로컬 정리→정정 settled·명령 completed를 연결했다. 전체70개 관측, 누락/오류/본문 일치0, 다른 Node 프로세스 동일 완료 재생을 확인했다.
JARVIS12통과/43.84초·SB11통과/9.77초·Ruff/syntax/diff통과. 합성 기억·테스트 권한의 격리 실제 실행이며, 전송 경합·범위·계보·native/실제 앱·검색·운영 복구 목표는 남는다.


**이전 실제 발행 인수 `6031d73`: [같은 자비스 DB의 후속 발행→실제 MCP→provider proved](CANCELLATION-DISPATCH-MCP-ACCEPTANCE-2026-09-08.md).**
취소 settlement/cursor1 이후 실제 record 조회·대상 resolve·확인/승인·dispatch·MCP 접수·provider 실행을 연결했다. 발행1회/delta1/seq2/cursor2, 커밋 정정 반영·이전/취소 내용 부재·재실행 idle·MCP 재시작 동일 상태를 확인했다.
관련 Python11통과/8.96초·Ruff/syntax/diff통과. 권한은 fixture이며 lifecycle observer는 not_proved다. 자비스 최종 reconciling; 실제 proof/전체 관측·compaction/settlement와 운영 전체 목표는 남는다.


기준: 2026-09-08. 최신 Second Brain 제품 `9e30115`, JARVIS 제품 `ea076ae`.
사용자가 전달한 [자비스 인계서](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md)의 현재 내용을 기존 구현 원장·통합 계획·실제 클라이언트 인수 기록 및 취소 결과 소스와 대조했다.

**이전 provider 단독 인수 `42ceb35` / JARVIS 제품 `ea076ae` / SB 제품 `9e30115`: [취소 후 정상 V2 seq2의 양쪽 검증·실제 provider 실행](CANCELLATION-FOLLOWUP-PROVIDER-ACCEPTANCE-2026-09-08.md).**
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
- 취소 결과는 실제 처분 증거와 서명을 결합하고 불변 저장·재생한다. schema6의 공개키 기반 상태 조회와 JARVIS 검증은 실제 stdio에서 인수했다. DB 의향 발급도 후속 완료했으며 외부 취소 접수·응답 유실 복구까지 연결했다. 접수 후 명시적 CLI 처분·서명 결과·Node MCP 조회까지 검증했다. JARVIS 취소 전용 로컬 영수증·DB 교체·중단 복구·settlement/cursor1은 후속 인수했다. 후속 실제 MCP 정정은 proof·전체70개 관측·로컬 정리·settled/completed 및 독립 프로세스 재조회까지 인수했다. 선택한 같은 자비스 프로세스의 전송/취소 두 순서도 인수했다. 여러 runtime·직접 DB 작성자의 전역 배제와 실제 앱 운영 인수는 남는다. [상태 MCP 인수](CANCELLATION-MCP-ACCEPTANCE-2026-09-08.md), [DB 발급 인수](CANCELLATION-DB-ACCEPTANCE-2026-09-08.md)
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
| P0 부분 완료: 취소 의향 생성·전송 경합 | 내부 취소 접수는 있어도 자비스의 실제 미전송 상태와 외부 전송을 한 경계로 보장해야 함 | JARVIS DB 발급·발행 직전 권한 재검사·schema7 실제 접수·응답 유실 복구 완료. 같은 자비스 프로세스의 실제 MCP 전송/취소 두 순서와 provider 별도 프로세스 접수 경합 인수 완료. 여러 runtime·직접 DB 작성자의 전역 배제는 남음 | 전송 우선/취소 우선 경합에서 상반된 완료 없음, 중단 재시도 중복 효과 없음 |
| 격리 인수 완료: 후속 요청 진행 | 취소 접수나 내부 세대 활성화만으로 처리 위치를 넘기면 누락 가능 | provider 결과의 DB 저장·현재 신뢰 검증 완료. spool 본문 수집 누락 수정·체크포인트 인수 완료. 취소 전용 로컬 DB 처분·불변 영수증·실제 중단 복구 완료. 검증된 settlement/cursor1 실제 인수 완료. 정상 V2 seq2의 같은 자비스 DB 승인/dispatch→실제 MCP→provider proved·커밋 본문 일치·cursor2까지 인수. 실제 서명/관측·compaction·정정 settled/명령 completed·독립 프로세스 동일 재생 인수 완료. 실제 앱/운영 범위는 별도 | 실제 취소 seq1 완료→정상 V2 seq2 처리. 순서 건너뛰기·증거 없는 완료 없음 |
| P0 개선: 사용자·프로젝트 범위 | 공통 연결이 허용되지 않은 기억 공유로 확대될 수 있음 | 원본 분류와 일반 컴파일 페이지의 커밋 해시 결합 완료. verified claim·record 및 검색·직접 원문·target·쓰기·export·restore의 공통 범위 검사는 남음. agent 명칭을 권한으로 사용하지 않음 | 범위 밖 자료가 검색/원문/관계 확장/복원으로 노출되지 않음 |
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

최초 문서 변경은 분석이었다. 후속 schema6 상태 조회와 DB 의향 발급은 위 인수 보고서를 따른다. 명시적 취소 접수 schema7도 추가했다. 접수 후 명시적 CLI 실행·서명 결과·조회까지 연결했다. JARVIS 취소 cursor1은 인수했으며, 후속 정상 정정의 격리 실제 전체 완료도 인수했다. 운영 설정 활성화와 실제 앱·다중 사용자·세션 수명 전체 인수는 미완료다.

## 최초 문서 대조 당시 재검증

`TMPDIR=/var/tmp .venv/bin/pytest -q tests/test_cancellation_result.py tests/test_mcp_profile_compatibility.py tests/integration/test_walking_skeleton.py`

결과: **24 passed, 15.58초**. 취소 결과, 기존 MCP 프로필 호환, walking skeleton을 재검증했다. 전체 테스트 재실행이나 실제 운영 서비스 인수 결과는 아니다. 문서 변경은 `git diff --check`를 통과했다.
