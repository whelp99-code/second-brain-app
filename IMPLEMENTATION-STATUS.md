# 중앙 기억 완성 진행 원장

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


사용자 확정 목표: 기존 수정·개선·고도화 제안을 완성하고 기능/큰 단위마다 커밋한다. 문제가 될 기능·소스는 근거와 함께 보류하며 개발 완료는 실제 사용 검증으로 판정한다. 기존 범위를 이 원장에 유지하며 테스트 통과만으로 완료로 축소하지 않는다.

정본 계획: `IMPROVEMENT-BACKLOG-2026-09-07.md`, `OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md`.

최신 인계 분석: [현재 동작 판정·OSS 대조·14개 잔여 작업과 완료 조건](HANDOFF-CURRENT-REVIEW-2026-09-08.md). 기존 제품 완료 기록을 유지하며 자비스·공통 기억의 운영 미완료 범위를 구분한다.


## 2026-09-08 인계 재대조·자비스 후속 command 회귀

인계서의 세컨드브레인 정본·네 OSS 선별 흡수·공통 기억 우선 방향을 최신 구현과 다시 병합했다. [종합 분석](HANDOFF-CURRENT-REVIEW-2026-09-08.md)의 과거 cursor/로컬 처분 미완료 설명을 수정했다.
JARVIS 테스트 `30cf131`: 취소 settlement 이후 실제 확인·준비·승인·claim·dispatch API를 거쳐 delta1/seq2, 발행1회, cursor2, 원 취소 writer0회를 확인했다. 타입·변경 파일 lint 통과, 직렬 Vitest 1통과/6.34초.
provider status/accepted 및 대상은 fixture이며 상태 reconciling이다. 실제 provider seq2 인수와 분리된 검사이고 전체 완료가 아니다. 다음은 동일 자비스 DB의 실제 dispatch→provider 실행→완료 증거 연결이다. ACL·계보·native 세션·실제 앱·검색·운영 복구의 잔여 목표는 유지한다.

**이전 실제 provider 인수 `42ceb35` / JARVIS 제품 `ea076ae` / SB 제품 `9e30115`: [취소 후 정상 V2 seq2의 양쪽 검증·실제 provider 실행](CANCELLATION-FOLLOWUP-PROVIDER-ACCEPTANCE-2026-09-08.md).**
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

**이전 SB `9e30115` / 검증 JARVIS `12d7b2a`: [취소 CLI 실행·실제 처분·서명 결과·MCP 인수](CANCELLATION-EXECUTION-ACCEPTANCE-2026-09-08.md).**
접수된 의향 하나를 기존 writer/처분 체크포인트로 실행하고 현재 취소·서명 권한을 발급 직전까지 재검사한다.
실제 DB 접수부터 CLI 처분 경계/결과 commit 뒤 exit77→복구·동일 결과→개인키 없는 Node MCP 검증을 확인했다.
전체1,093통과/2skip 이후 최종 서명 권한 관련67통과, 정적0오류/0경고·lint통과. 이전 키 신뢰/철회에 따른 결과 재생도 검증했다.
JARVIS 로컬 억제 증거/cursor·seq1→V2seq2·외부 전송 통합 경합 및 기존 전체 운영 목표는 남는다.

**이전 SB `f9daf99` / JARVIS `12d7b2a`: [DB 의향의 실제 MCP 접수·권한 재검사·응답 유실 복구](CANCELLATION-SUBMISSION-ACCEPTANCE-2026-09-08.md).**
명시적 schema7에서 취소 목적 키를 잠금 내부까지 다시 읽고, JARVIS는 발행 직전 DB 권한을 재검증한다.
실제 DB→Node→Python 대상 접수, commit 직후 exit77→uncertain/자동 재전송 없음→동일 재생·실행 중 철회 거부를 확인했다.
전체1,082통과/2skip 이후 최종 오류 정규화 관련26통과, 정적0오류/0경고·lint통과. JARVIS EPIPE 재현·수정 후 최종전송89통과·타입/lint/격리emit통과.
접수 후 실제 실행·결과/로컬 증거/cursor·seq1→V2seq2와 외부 전송의 통합 경합, 기존 전체 운영 목표는 남는다.

**이전 JARVIS `88fcd89` / SB 제품 `df9412c`: [DB 근거 취소 의향 발급·실제 중단 복구](CANCELLATION-DB-ACCEPTANCE-2026-09-08.md).**
정정 materialization에서 메타데이터를 보존하고 실제 suppression/attempt/cursor와 현재 키를 검증해 불변 의향을 발급한다.
취소 저장 직후 exit77→동일 재생·후속 claim 거부, claim 우선→발급 거부 및 Python 계약 일치를 실제 분리 프로세스에서 확인했다.
최종 관련 20통과, 타입/ESLint/격리 emit 통과. 외부 취소 전송·provider 접수·로컬 증거/cursor·seq1→V2seq2와 전체 운영 목표는 남는다.

**이전 SB `df9412c` / JARVIS `1598762`: [취소 상태 MCP·자비스 전송·의미 검증](CANCELLATION-MCP-ACCEPTANCE-2026-09-08.md).**
새 cancellation-schema6 프로필에서 읽기 전용 조회를 노출하고 구 프로필 bytes/기본 선택을 유지한다.
JARVIS는 현재 삭제 이력·정확한 의향·서명 결과·키 철회를 검증한다. 개인키 없는 실제 MCP를
Node transport에서 접수 중/완료 각각 실행·재시작하여 동일 결과, 권한 거부, 원장 불변을 확인했다.
전체1,069통과/2skip, 신규2 포함 최종프로필16통과, 제품정적0오류/0경고·lint통과.
JARVIS관련78·전송71통과(중복), tsc/ESLint/격리emit통과. DB 의향 발급·외부 취소 접수/전송 경합·
로컬 억제 증거/cursor·seq1→V2seq2와 native·범위·계보·실제앱·검색·GUI·운영 목표는 남는다.

**이전 SB `6da593e`: [취소 상태 읽기 전용 조회·공개키 검증·실제 프로세스 인수](CANCELLATION-STATUS-ACCEPTANCE-2026-09-08.md).**
현재 status fence·같은 원장 snapshot·정확한 intent·삭제 chain·저장 결과를 대조한다.
개인키 없이 공개키/철회 정책으로 조회하며 재발급·원장 변경을 하지 않는다. 삭제 이력 누락
손상 사례를 재현·수정했다. 전체1,061통과/2skip(최종 chain 검사 전), 최종관련40통과,
제품정적0오류/0경고·lint통과. 실제4개 reader 프로세스의 동일 결과·철회/권한 거부·원장불변 확인.
현재는 내부 읽기 경계이며 MCP 새 프로필·JARVIS transport/DB/cursor/seq1→seq2 연결은 남는다.
native·범위·계보·실제앱·검색·GUI·운영 전체 목표 및 자동 route/skip 보류를 유지한다.

**이전 SB `44ab911` / JARVIS `cabfba2`: [취소 결과의 실제 증거·서명·저장·교차 검증](CANCELLATION-RESULT-ACCEPTANCE-2026-09-08.md).**
별도 provider_local_suppression 결과를 exact intent/target/세대/tombstone과 실제 alias·reingress·
원본 처분·copy checkpoint·후속 세대 본문 부재에 결합한다. 원문이 있을 때 부재 검사를 저장해
재시작 시 대조하고, 검사 이후 키 철회도 전환 전에 재검증한다. 결과는 기존 journal의 불변 행으로
저장하며 응답 유실·후속 세대 이후 동일 결과를 재생한다. 전체1,045통과/2skip(최종 권한 재검사 전),
이후 관련37통과(중복·신규1포함), 제품정적0오류/0경고·lint통과. JARVIS5파일38통과·타입/lint/격리
emit통과. 실제 결과 저장 직후 exit77→새프로세스 동일결과 재생, 실제 Node↔Python13입력 판정 일치.
외부 MCP 취소/결과 조회·자비스 DB 의향 생성 경계/cursor·seq1완료→정상V2seq2는 남는다. 결과를
전체 native 삭제로 확대하지 않는다. 범위·계보·실제앱·검색·GUI·운영 전체 목표와 자동 route 보류 유지.

**이전 SB `5d9f7d4`: [남는 정상 백업 보존·무결성·실제 복원](RETAINED-BACKUP-ACCEPTANCE-2026-09-08.md).**
무관한 정상 tar.gz 때문에 정정이 UNMANIFESTED_BACKUP에 멈추는 형식 불일치를 재현·수정했다.
archive/checksum와 내부 전체 파일 집합·크기·해시를 제한된 스트림으로 검증하며 기존 디렉터리
형식과 유효한 유니코드/JSON 표현을 유지한다. 잘못된 사본은 pointer 전환 전 거부하고
오류 응답에 로컬 경로가 포함되지 않게 한다. 전체1,024통과/2skip(마지막 오류 정규화 전),
정규화 후 관련45통과(중복·신규4포함), 정적0오류/0경고·lint통과. 실제 정정/취소 강제종료77→
복구·MCP stale→healthy/기존 검색0, 무관한 백업 SHA불변·각37파일 복원을 재확인했다.
취소 최종 결과/상태/서명 영수증/MCP/JARVIS cursor, 미지원 형식·증거 재조정 및 native·범위·
계보·실제 앱·검색·GUI·운영 전체 목표는 유지한다. 운영 변경·push는 하지 않았다.

**이전 SB `461f7e3`: [압축 백업·내보내기 처분과 실제 중단 복구](MANAGED-COPY-DISPOSAL-ACCEPTANCE-2026-09-08.md).**
gzip/tar/Git loose object 안의 원문 누락을 재현하고 제한된 스트림 검사를 추가했다.
정정·삭제·취소의 사본 처분을 세대 전환 전에 실행하고 원문 없는 메타데이터 체크포인트로
재시작을 검증한다. 증거 누락/내용 변경은 보류하며 전환 전 새 백업은 재검사한다.
기본 전체1,005통과/2skip, 이후 신규2통과, 변경 제품정적0오류/0경고·lint통과.
실제 정정/취소 각 exit77→새 프로세스 복구와 MCP stale→healthy·기존 본문 검색0 확인.
자비스 인계를 재대조하고 14개 잔여 우선 목록을 병합했다. 미지원 사본 형식/남는 tar.gz의
manifest 인수·증거 재조정, 취소 최종 결과/서명 영수증/MCP/JARVIS cursor 및 native·범위·계보·
실제 앱·검색·운영 전체 목표는 남는다. 자동 취소 route와 collector 확대는 보류한다.

**이전 SB `b34b2a9`: [취소 대상의 원자 접수·백업 잠금 충돌 수정](CANCELLATION-ADMISSION-ACCEPTANCE-2026-09-08.md).**
취소 접수에 실제 generation/target 고정을 필수로 결합하고 검사 후 현재 키/만료를 재검증한다.
잘못된 세대·변조/특수 파일은 원장 위치를 바꾸지 않고 거부한다. 기존 백업 생성·검증의
반대 잠금 순서를 실제2프로세스 검사로 재현하고 pending→generation→DB로 통일했다.
기본983통과/2skip·마지막백업5통과(중복), 제품정적0오류/0경고·lint통과. 실제 Node 생산자와
Python6요청 프로세스에서 실제 대상 접수/재생·잘못된 세대의 mutation0, 실제 MCP
강제종료 복구·healthy/검색0 재확인. backup/export 처분·최종 결과/서명 영수증·MCP/JARVIS
cursor와 기존 native/ACL/계보/수집/검색/운영 전체 목표는 남는다. 자동 취소 route는 보류한다.

**이전 SB `b3c8b87`: [취소의 실제 억제 세대·중단 복구·MCP 인수](CANCELLATION-GENERATION-ACCEPTANCE-2026-09-08.md).**
접수된 취소로 기존 대상을 제거한 generation을 생성·활성화하며 정정 replacement는 적용하지
않는다. 기존 erasure/reingress/단일 writer를 재사용하고 실제 대상 검증, 활성화 직전 키 재검사,
봉인 결과 연결·중단 재개·후속 세대 이후 완료 재생을 구현했다. 기본968통과/2skip,
최종관련28통과(중복), 제품정적0오류/0경고·lint통과. 실제 worker 강제종료77→새 프로세스 복구와
stdio MCP tombstone_stale→healthy, 기존/취소 본문 검색0 확인. 내부 generation_active 결과는
전체 사본 처분·최종 서명 영수증·자비스 cursor 완료가 아니다. 접수 대상 잠금 결합,
backup/export 처분·결과 계약·MCP/JARVIS 연결과 기존 native/ACL/계보/수집/검색/운영 목표는 남는다.

**이전 SB `62d083e`: [취소 원장 접수·자비스 인계 재대조·12개 완성 우선 목록](CANCELLATION-JOURNAL-ACCEPTANCE-2026-09-08.md).**
미전송 정정 취소를 기존 pending flock과 request journal transaction에 연결했다. 원본8별칭의
영구 재접수 차단, 잠금 후 현재 서명/만료 재검사, orphan 게시 거부, tombstone/target의 원자 기록을
구현했다. 기본 전체959통과/2skip, 최종관련49통과(중복), 제품정적0오류/0경고·lint통과.
실제 Node producer→Python5프로세스에서 취소 우선/원본 우선/재시작/재생을 확인했다.
결과는 suppression_pending이며 실제 억제 세대·MCP 취소 라우트·처분 증거·자비스 cursor 연결은
아직 없다. 원장 접수를 자동복구 완료로 처리하지 않는다. 인계 방향과 native/ACL/계보/수집/
검색/운영 전체 완료 조건을 유지한다.

**이전 JARVIS `0ea62c8` / SB `e7efd62`: [본문 없는 정정 취소 의향 계약·교차 런타임 검증](CORRECTION-CANCELLATION-INTENT-2026-09-08.md).**
P0 복구의 선행 계약을 양 언어로 구현했다. 기존 서명/대상/삭제 이력과 현재 취소 서명을 결합하며
의향을 미수신·삭제 완료 증거로 사용하지 않는다. 기존 테스트 접수기도 실제 V2 validator를 거치게
수정했다. SB 기본947통과/2skip·최종집중30, JARVIS41통과, Python정적0오류/0경고·lint/build통과.
실제 Node↔Python 16입력 판정·5,775바이트 서명이 일치했다. MCP/DB/전송에는 아직 연결하지
않았으며 provider 수신경합·alias차단·실제 suppression generation·결과증거가 다음 구현이다.
자동복구와 native/ACL/계보/수집/검색/운영 전체 목표는 미완료다.

**이전 JARVIS `8a55ea9` / SB 도구 `db19ec5`: [V2 정정 차단·계약 복구 보류·14개 우선 목록](V2-CORRECTION-SUPPRESSION-2026-09-08.md).**
V2 prepare/materialization/beginDispatch/직접 adapter의 후보 차단을 수정하고 기존 spool 보존 및
cursor rollback을 검증했다. 최종6파일22통과, 타입/린트/71migration 격리build, 실제3프로세스에서
재시작 attempt0·정상 입력 후 차단 호출 증가0 확인. 자동 retirement 시제품은 실제 양쪽 validator가
혼합 delta를 거부하여 철회했다. 차단된 queued tombstone의 후속 정정·삭제 정체는 미해결 P0다.
기존 native/ACL/계보/자동capture/검색/운영 전체 완료 조건을 유지한다.

**이전 JARVIS `0c0508a` / SB 도구 `7e01e2b`: [후보 차단의 승인·remember 전송 집행](CANDIDATE-SUPPRESSION-WRITES-2026-09-08.md).**
화면에서 숨긴 후보가 classify 재생·owner 승인·outbox 전송·직접 V1 writer에서 사용되는 결함을
수정했다. 정정 confirmation도 검사/승인/settlement를 immediate transaction으로 결합했다.
관련39·최종7·유효 wire 입력 집중6 통과(중복), 타입/린트/격리 build 통과. 실제3프로세스에서
정상 transport 진입 후 차단 호출 증가0, 재시작 후 attempt0, HTTP200→404/준비승인 거부 확인.
V2 정정의 별도 preparation/dispatch 후보 차단은 다음 필수 수정이며 모든 write 완료가 아니다.
원task→provider record 계보·native/ACL/capture/검색/운영 전체 목표는 유지한다.

**이전 JARVIS `4d8bdf0` / SB 도구 `aa7e76f`: [정책 시작 오류 수정·후속 우선 목록](DASHBOARD-POLICY-STARTUP-2026-09-08.md).**
실행 cwd 정책 의존·HTTP 요청마다 서비스 조립·배포 정책 자산 누락을 수정했다. 시작 시 정책을
고정하며 잘못된 정책은 listen 전 거부하고 CLI DB를 닫는다. 관련14개/build10개·타입·린트·
독립 검토, 정규 격리 build 및 실제6프로세스 HTTP/CLI 인수 통과. 이전 화면 보고서의 다음 수정
대상은 이 단위에서 해결했다. native 원문 관리·실제 앱 연결·ACL·capture·검색·운영/DR은 미완료다.

**이전 JARVIS `53136d4` / SB 도구 `bc3313b`: [실제 기억 화면의 개인정보 수명](DASHBOARD-MEMORY-LIFETIME-2026-09-08.md).**
provider 조회 중 정책/session 변경 차단, 충돌 suppression, 상세/draft/검색어 및 만료 데이터 폐기,
같은 token 재사용의 이전 action 차단을 구현했다. Dashboard211/최종집중6, backend관련15/최종6
통과(중복 포함). 실제Chromium1440/1024와HTTP409 본문부재 확인. 상단 전역연결은 끊김으로
관측되어 전체운영준비는 미완료다. 새로 발견한 policy config 상대경로 부재의 서버 종료는 다음
수정 대상. native앱채택·scope·capture·검색품질·운영/DR 전체 목표를 유지한다.

**최신 JARVIS `0352642` / SB 도구 `33bffc0`: [JSON 사본 삭제 보강·15개 후속 과제](JSON-RETENTION-ACCEPTANCE-2026-09-08.md).**
native 보존 조사에서 이어 JARVIS의 raw-only 삭제/재유입 검사를 수정했다. 수정 전3실패,
8파일35통과·최종 동기 guard 후3파일10통과, 격리 tsc/변경lint 통과. 실제5프로세스로
4사본 제거·무관 파일 보존·재시작 후 중첩SQLite 재유입 거부·최종70surface 검사를 확인했다.
스캔은 영구지문만 사용하며 삭제에는 원문을 전달한다. native/운영 삭제 완료가 아니다.
기존 MCP/schema 유지, 제품 소스 변경은 JARVIS에 있고 SB에는 인수 도구·문서를 추가했다.
보호된 실제 앱 연결·native 소유권/백업·scope·자동capture·검색 품질·GUI/운영/DR은 미완료다.

**최신 SB 인수 `94ea45a`: [실제 native UUID·원문 보존 표면](NATIVE-SESSION-ACCEPTANCE-2026-09-08.md).**
자비스 제품 `6e101fc`를 재사용해 실제 Codex bootstrap 5회와 exact UUID resume 5회(총10회)
모델 인수를 통과했다. 원장 중복·무효화된 native 세션의 callback은 차단됐다. Node20/Python12
회귀 통과. 설치 실행체 사본 고정·umask0077·plugins/hooks 자동기능 비활성화를 추가했다.
삭제 후 rollout 3개 외에 thread_history_1.sqlite에도 원문 확인값이 남음을 실측했다.
권한 감사는 native 상태의 비공개가 아닌 객체1개 때문에 exit1을 유지하며 nativeHome 폐기
사실과 구분한다. 운영 native 연결은 이 DB/rollout/백업의 관리형 보존·삭제 계약 전까지 보류.
실제 앱 채택·compaction·범위·자동수집·운영/DR 전체 목표는 미완료이며 제품/운영 변경은 없다.

**최신 자비스 제품 `6e101fc`, SB 인수 도구 `fd9df47`: [영구 전달 원장·14개 잔여 우선 목록](REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.md).**
필수 session의 submitInSession과 기존 객체 단위 submit을 분리했다. 키 고정·영구 claim·
불확실 재전송 차단·개인정보 transaction의 전역 세션 무효화·token 제거를 구현했다.
관련 6파일 90 passed, 추가 upgrade/clock 포함 집중 14 passed, event 감사 14 passed,
tsc/lint 및 독립 검토 완료. 실제 6개 Node 프로세스 종료/재시작/fresh-copy와 native 모델
5회 원장을 검증했다. 세션 ID는 합성 adapter fixture이며 실제 앱 세션/compaction 인수는
남는다. DB→외부 callback 원자성·프로젝트 ACL·자동 수집·검색 근거 충분성·GUI/운영/DR
완료 조건을 유지한다. 운영 migration/배포/push는 수행하지 않았다.

**최신 자비스 제품 `8e233c7`, SB 도구 `4e3a8de`: [참고 문맥의 보호된 제출](REFERENCE-SUBMISSION-ACCEPTANCE-2026-09-08.md).**
기존 reader가 발급한 문맥을 객체당 한 번 제출하고 전송 직전/완료 뒤 provider·privacy·만료를
재검사한다. 실제 모델 인수에서 준비 후 정정과 이미 제출한 객체의 재전송은 추가 모델 호출 없이
차단됐고, 모델 callback 중 삭제는 결과 반환을 막았다. 최신 값/삭제 후 no_data 정상 제출 유지.
관련 70 passed, event 감사 14 passed, tsc/lint 통과 및 별도 모델 독립 검토 완료.
영구 session/epoch claim·native receipt·compaction·삭제된 세션 후속 처리·실제 앱 채택은
미완료다. 객체 단위 WeakMap을 영구 전달 원장으로 계산하지 않는다. 운영 변경은 수행하지 않았다.

**이전 실제 소비 검증 `8cb5dd5`: [모델 정정·삭제·과거 사본 재전송](REFERENCE-MODEL-LIFECYCLE-2026-09-08.md).**
자비스 `110227e`의 새 격리 빌드로 실제 CLI/MCP→모델 5개 독립 요청을 실행했다. 정정 후 새 값과
출처를 회수하고 삭제 후 새 조회/모델은 no_data였다. 그러나 보관된 최초 payload를 다시 보내면
과거 값이 그대로 회수됐다. 새 조회는 계속 record 0개이며 제품 전달 관련 세 테이블도 0행이다.
C6/C7 전체 완료가 아니며 [전달·세션·삭제 수명 계약안](REFERENCE-DELIVERY-LIFECYCLE-CONTRACT-2026-09-08.md)으로
전송 claim/확인/불확실/무효화와 client epoch 처리 조건을 구체화했다. 계약·수명 회귀 18개,
event 감사 14개·Ruff/타입/syntax 통과. SB 제품/자비스 소스/운영은 이번 단위에서 변경하지 않았다.

**현재 제품 `701e966`: [모델 배치 재사용·실제 수명주기·잔여 우선 목록](EMBEDDING-BATCH-ACCEPTANCE-2026-09-08.md).**
한 세대 생성 범위에서만 모델 자식을 재사용하고, 종료 확인 후 봉인한다. 부모 종료 후에도
자식의 writer 잠금이 유지되며 파이프/응답/초기화 timeout을 검증했다. 전체 **931 passed/2 skipped**,
집중 **58 passed/1 skipped**, Ruff/타입 통과. 실제 모델의 같은 129개 출력이 byte 단위로 같고
배치 총시간 28.75→16.81초(단일 측정), 실제 두 MCP/CLI 정정·삭제·각 백업 복원이 통과했다.
검색 요청 약 6초와 메모리 비용은 남는다. 다음 우선순위는 자비스 세션 전달·compaction·삭제
수명이며, 범위 분류·자동 수집·근거 충분성·실제 사용자 질문·GUI/운영/DR의 완료 조건을 유지한다.

아래는 각 커밋 당시의 이력이다. 과거의 진행 중/미구현 표시는 최신 보고서로 대조한다.

**이전 제품 `7deb1b9`: [실제 100질문 비교·최소 유사도 설정](SEMANTIC-RELEVANCE-2026-09-08.md).**
고정 소스의 실제 모델 100질문 평가가 exit 0으로 종료했다. CLI/MCP 모두 정답 회수는
60/90→90/90, 무정답 빈 결과는 10/10→0/10, 검색 p95 약 6.3–6.5초였다.
명시적 `min_similarity`를 모든 검색 표면의 의미 후보에 적용하고 일반 검색은 유지한다.
전체 **919 passed/2 skipped**, 집중 **85 passed/1 skipped**, Ruff/타입 통과.
최신 실제 CLI/MCP의 0.55 실험값은 작은 3사례에서 정답 유지/무정답 제거를 확인했으나,
누락된 세부정보를 묻는 추가 10질문 중 9개에는 후보가 남았다. 운영 전역값·hybrid 활성화는
보류하며 답의 존재 여부·사용자 질문·모델 지연과 자비스 C6–C8/범위·운영/DR 조건을 유지한다.

**이전 제품 `0834e86`: [실제 모델 실행 경계·평가](REAL-EMBEDDING-PROCESS-2026-09-08.md).**
실제 BGE-M3에서 부분 캐시의 온라인 로딩·무제한 대기·잘못된 출력의 fallback 누락을 확인하고
offline 인코딩·60초 자식 timeout·오류 정규화를 적용했다. 전체 **897 passed/2 skipped**,
집중 **54 passed/1 skipped**, Ruff/타입 통과. 실제 CLI/MCP 자연어·의역 각 1건의 정답 1위,
무정답 1건의 후보 5개 노출과 검색 약 6초를 측정했다. 운영 hybrid 활성화는 계속 보류한다.
일반 검색의 합성 100질문은 60/90 회수·무정답 10/10 빈 결과로 재확인했다. 실제 모델 100질문은
고정된 별도 worktree에서 진행 중이며 완료로 계산하지 않는다. 실행/재개 경로는 위 보고서를 따른다.

**이전 제품 `cbb910d`: [봉인 의미 검색 구현·인수](SEALED-VECTOR-ACCEPTANCE-2026-09-08.md).**
명시적 hybrid 설정에서 인용 레코드 벡터를 같은 세대에 봉인하고 CLI/HTTP/MCP 검색에 연결했다.
모델·레코드/벡터 digest 결합, 변경 레코드만 인코딩, 정정·삭제 시 이전 벡터 제거와 모델 장애의
lexical fallback을 구현했다. 두 실제 MCP 프로세스/CLI 정정·삭제·각 백업 복원 통과.
전체 **893 passed/2 skipped**, 집중 **50 passed/1 skipped**, Ruff/타입 오류·경고 0.
아래 과거 기록의 관리형 enabled=0 고정은 이 변경 이전 상태다. 기본 false는 유지하며 실제 모델
한국어 품질·낮은 관련성 처리·대량 인코딩/검색 지연·운영 활성화는 미완료다.
자비스 C6–C8 session 전달/compaction/삭제·범위와 B4–B8 운영/GUI/DR 조건도 유지한다.


**2026-09-08 최신:** [대규모 100회 쓰기/두 MCP reader/최종 복원](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md)이
종료·통과했고 제품 소스 고정을 해제했다. 대기 다섯 커밋을 1d3d2de → 0fecf0a → f756872 →
01f9963 → 49442bc로 병합했으며, 추가 [봉인 파일 무결성](GENERATION-INTEGRITY-2026-09-08.md)은
db94997로 반영했다. 해당 무결성 제품의 전체 회귀 815 passed/2 skipped, 병합 후 통합 26 passed,
실제 자비스 CLI 5시나리오 통과. 아래의 대기/진행 숫자는 각 기록 작성 시점의 이력이다.

최신 성능 수정 `fe21016`: [복사·경로 순회·동기화 개선](GENERATION-WRITE-PERFORMANCE-2026-09-08.md).
같은 대용량 fixture의 분리 프로파일에서 remember 33.52→12.24초, run 120.06→96.83초였다.
이 단계 전체 821 passed/2 skipped, 실제 3회 쓰기·두 MCP·복원 통과. 단일 프로파일을 운영 p95로
계산하지 않으며, 전체 처리 지연과 아래 B4~B8의 남은 조건은 유지한다.

최신 제품 `b6d9875`: [반복 보호 검사 최적화](REDACTION-PERFORMANCE-2026-09-08.md).
기존 정책/정규화 출력과 고정 2,000개 조합이 일치하며 run 단일 프로파일은 96.83→74.07초,
remember는 12.52초였다. 이 단계 전체 **860 passed/2 skipped**, Ruff/타입 검사 통과.
실제 3회 쓰기·두 MCP 검색/페이지 각 706회·복원 3개 회수·CAS 보호 검증 통과.
정책 검사 자체 생략·원문 캐시·별도 queue는 관련 수명 계약 검증 전까지 보류한다.

최신 제품 `d152819`: [벡터 경로 보호·복구/보류](VECTOR-RECOVERY-SAFETY-2026-09-08.md).
`.sb` 링크/교체 시 외부 게시를 거부하고 열린 디렉터리 기준으로 새 DB를 게시·정리한다.
현재 전체 **874 passed/2 skipped**, 집중 97 passed/1 skipped, Ruff/타입 통과.
실제 SQL 후 강제 종료→이전 검색→재시도 4 vectors, 이전 reader 3행/새 reader 4행과 hybrid
필터/정정 5건 통과. 호스트의 열린 FD 관측 제한으로 임시 DB 1개를 보존하여 자동 회수는 보류한다.

B4~B8 전체 완료는 아니다. capture/run p95 32.99/112.66초의 개선, 실제 질문/모델/GUI,
자비스 session 전달·compaction·삭제/범위, 봉인 의미 검색, 운영 전환/DR을 계속 진행한다.

B5 준비 경로 구현: 자비스 `3360fe7`의 [출처를 보존한 참고 기억 본문 묶음](MEMORY-REFERENCE-PREPARATION-2026-09-08.md). 기존 adapter 출력에서 여러 줄 원문·record/citation/세대·유효 시점을 유지하고 최종 JSON 전체 byte/선택적 tokenizer 예산을 적용한다. 관련 94 passed, 실제 MCP 3건·record 1개·본문/digest/출처/세대 일치, 독립 리뷰 결함 수정 및 재검토 완료. 기존 추천 authority·frozen MCP는 유지한다. 준비 데이터이며 실제 모델 전달, suppression/범위·세션/compaction receipt와 B5 전체는 남는다.

B5 인계 대조: [공통 문맥 공급 공백과 8개 추가 과제](CONTEXT-DELIVERY-GAP-ANALYSIS-2026-09-08.md). 자비스 새 격리 빌드로 snapshot 본문 부재, provider untrusted 제외, 여러 줄 입력 거부, live 관측 의존, 본문을 포함하지 않는 총량 계수를 재현했다. 기존 context/projection 재사용과 실제 전달·중복/compaction·삭제/범위 결합을 C1~C8로 세분화했다. 진단 성공은 B5 완성이 아니며 제품/운영 변경은 없다.

기존 병합 대기는 해소했다. 위 최신 요약과 100회 쓰기 보고서의 커밋 대응표를 따른다.

격리 검색 후속: [정확 문구·입력 오류 인수](SEARCH-PHRASE-ACCEPTANCE-2026-09-08.md). 큰따옴표 문구/경로 문자 보존과 4,096-byte/32-group 예산을 공통 검색에 연결했다. 잘못된 입력은 index refresh 전에 거부하고 CLI/HTTP/MCP에서 구체적인 오류로 반환한다. 별도 합성 문구 7/7 회수·무정답 3/3 빈 결과, 기존 100질문의 60/90 회수 유지. 실제 사용자 질문·의역·B5 문맥 예산과 전체 목표는 남으며, 대규모 쓰기 종료 후 앞선 격리 커밋들과 병합한다.

격리 복구 후속: [중단된 준비 세대 정리](STAGING-RECOVERY-2026-09-08.md). 다른 request ID의 재실행 뒤에도 남던 `.staging` raw 사본을 기존 writer/exclusive 잠금 아래에서 정리한다. 전체 트리 검증·descriptor 상대 삭제·열린 파일/진행 writer 보호·실패 재시도를 연결했다. 실제 CLI 종료→유지보수→기존/새 기억 MCP 회수·CAS byte 일치, pending inbox 보존, 전체 733 passed/2 skipped. 검색 수정과 같은 격리 worktree이며 100회 쓰기 종료 후 원 작업공간 병합이 필요하다. 운영 cleanup·전체 삭제/DR·B5 구현 완료는 아니다.

격리 개발 후속: [검색어 어순과 MCP 근거 선택 개선](KOREAN-QUERY-CONSISTENCY-2026-09-08.md). 봉인/비봉인/record가 공통 AND 질의를 사용하고 연속 문구를 우선한다. 같은 합성 자료의 Recall@5 40/90→60/90, 어순 변경 0/20→20/20, 정확 문구 20/20 유지. 실제 CLI/MCP와 분리 record·필터·frozen 계약 관련 60개를 검증했다. 100회 쓰기의 소스 고정을 위해 별도 worktree에서 개발하며 원 작업공간 병합은 해당 인수 종료 뒤 수행한다. 자연어/의역 30개·실제 사용자 질문·B4~B8 전체는 남는다.

최신 평가: [한국어 검색 기준선과 후속 개선](KOREAN-SEARCH-BASELINE-2026-09-08.md). 실제 CLI/MCP에 합성 질문 100개를 각각 실행했다. 정답 있는 90개 중 40개 회수(Recall@5 44.44%), 어순 변경·자연어·의역 50개는 미회수였다. 전체 문구 MATCH와 MCP의 연속 문자열 재검사에 대한 개선 항목을 추가했다. 선택 record/출처·세대 대조 42건, 관련 회귀 42 passed. 평가 도구 완성이며 실제 사용자 질문 100–300개·검색 개선·운영 인수는 남는다. 실행 중인 100회 쓰기의 제품 소스는 고정했다.

최신 수정: [충돌 후보 계산의 대용량 병목](CONFLICT-CANDIDATE-CAPACITY-2026-09-08.md). 첫 full 배치의 전수 빈도표 재계산을 재현하고 역색인·실행 내 캐시·상위 쌍 보관으로 개선했다. 기존 알고리즘과 400개 사례 대조, 10만 단위 후보 계산 10.56초, 중단 저장소의 실제 배치 102.67초·기억/브리핑 회수를 검증했다. 새 버전의 100회 인수, 운영 지연·후보 검토 범위와 나머지 목표는 남는다.

직전 수정: [브리핑 인용 예산과 세대별 자동 갱신](BRIEFING-RECORD-BUDGET-2026-09-08.md). 70개 충돌에서 배치 exit 0 뒤 MCP 브리핑 읽기가 실패하던 결함, 세대 전환 시 자동 생성 해시 소실, 제안만 저장된 페이지를 완료로 처리하던 결함을 수정했다. 실제 3회 capture/run·동시 MCP 조회·백업/복원 및 구버전 과대 브리핑의 갱신을 확인했다. 계획 규모의 100회 쓰기는 별도 인수이며 운영 전환은 남는다.

직전 인수: [실제 Codex·Claude 공통 기억](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md). 두 종류의 실제 CLI에서 같은 격리 provider의 양방향 capture→명시적 배치→검색/원문 회수를 확인했다. 성공 도구 6건·source 2개·CAS 원문 일치이며 CLI 종료 0/실패 도구를 구별하는 감사기를 추가했다. 이는 단일 owner/genesis 인수로 scope·자동 수집/주입·운영 전환은 남는다. [접근 범위 ADR](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md).

직전 수집 수정: [신규 unit 예산과 원본 보존 계약·인수](INGEST-BUDGET-CONTRACT-2026-09-08.md). 파일 수/실제 신규 unit 예산을 분리하고, 전체 예산 초과 원본은 명확한 실패와 함께 보존하며 잔여 예산 초과 원본은 다음 실행에서 처리한다. 실제 관리형 CLI 5 source/53 units·원문 보존·재실행 증가 0 및 5천 원본/10만 unit 구조 부하 재검증 통과. 운영 전환과 B4~B8 전체 인수는 남는다.

직전 운영 선행 수정: [대용량 인수와 보존/봉인 수정](CAPACITY-ACCEPTANCE-2026-09-08.md). 실제 5,000 원본/100,000 units와 10,000 페이지/1,000 충돌 fixture, 100회 CLI 조회 및 백업·새 경로 복원을 검증했다. 봉인 보존 조회의 쓰기 접근을 수정하고 세대 생성은 59.36→23.78초로 개선했다. unit cap의 파일 수 적용 결함을 추가 재현했으며, 100회 쓰기·운영 부하/한국어 품질과 기존 전체 범위는 남는다.

직전 기억 계약 구현: [일반 여러 줄 기억 V3 인수](REMEMBER-V3-ACCEPTANCE-2026-09-08.md), 자비스 `1f7048a`. 명시적 새 후보/본문/MCP 계약으로 LF·CRLF·CR·탭 저장과 자비스 완료 소비를 연결했다. 기존 V1/V2/frozen schema4 유지. orphan 접수 시각 복구와 실행 전 파일 전체 digest 대조도 보강했다. 실제 CLI·MCP의 혼합 4개/일반 LF 64개 record 순환을 검증했고 운영 전환은 남는다.

종합 판정: [인계 병합 후 상세 분석](SHARED-MEMORY-COMPLETION-REVIEW-2026-09-08.md). 수정·개선·고도화 14개 실행 묶음을 기존 R/I/G에 대응한다. 이 문서의 V1 제약 재현은 유지하되 새 V3 후속 구현 상태는 위 인수 보고서를 우선한다.

최신 후속: [후보 CLI 접수·원문/DB 원자성](MEMORY-CANDIDATE-INTAKE-2026-09-08.md). 파일 접수부터 owner 확인·실제 MCP 저장/재조회까지 검증했으며 실제 task 결과 자동 수집·approved/no_data 본문 인계는 남는다.

이전 구현: [후보 화면·완료 상태 인수](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md). 인계와 기존 24개 개선 항목을 유지하고 후보 검토·확인/거절·저장 명령 준비·진행 표시를 연결했다. 격리 실제 MCP에서 64개 민감 record 저장·두 클라이언트 재조회와 dashboard `stored=true`를 확인했다. 실제 입력 자동 수집, 앱별 수집/주입·범위와 운영 인수는 미완료다. 이전 코드 대조는 통합 계획 14절, 최신 변경은 15절을 따른다.

| 단위 | 범위 | 상태 | 완료 증거 |
|---|---|---|---|
| B0 | 기존 generation/provider 기반 + 운영 복구 + R1 입력 보존 | 완료 | 4da09b9; 520 passed, 2 skipped; Ruff·diff check 통과 |
| B1 | R2 public metadata / record 소비, R3 요청 기억 복원, R4 시간 계약 | 소스 구현·검증 완료, 운영 전환 미완료 | 공개 필드/ID·다중 record 소비·CAS 인용·시간 처리 수정. 실제 MCP→자비스 10개 기억 회수. 전체 업무 인수는 B4 |
| B2 | R5/R7/R9 검색 필터·결과 개수·읽기 세대 고정 | 소스 구현·검증 완료, 운영 미배포 | 필터·원장 read-only 투영, record 선택 뒤 limit, CLI pin. 동시 갱신 성능/복구는 B3에서 검증 |
| B3 | R6/I3 reader 복구·읽기 가용성 | 복구·LLM 준비 중 동시 조회 소스 검증, 운영 부하/잔여물 미완료 | 실제 reader/writer 강제 종료·PID 재사용·전환 정리, 두 writer·MCP/자비스 동시 조회 확인. 대표 p95·기존 잔여물 인수 남음 |
| B4 | I1/I7 공통 agent 접근·범위·자비스 전체 순환 | 후보 UI·명령 완료·서명 fence·일반 여러 줄 V3 소스 검증, 운영 전체 인수 미완료 | 원문 검토→승인 실행→저장 준비 브라우저 검증. V3 실제 CLI/MCP의 혼합 4개/일반 LF 64개 record·stored=true. 실제 Codex/Claude CLI 양방향 회수 추가. 자동 업무 결과 수집·정정 UI·GUI/다른 앱·범위·운영 인수 남음 |
| B5 | G1/G3/G4/G6 기억 시간·문맥 예산·전달 이력·검증된 결과 | 미완료 | 정정·compaction·중복 전달·실패 사실 취급 |
| B6 | R8/I2/I4/I6/G5 readiness·운영 UI·배포·복구 | 준비 상태·검증 백업 선행 수정, 운영 인수 미완료 | 실제 서비스·검증 백업·독립 복원·운영 상태 일치 |
| B7 | I5/G2 부하·한국어 품질·100회 반복, I8 문서/모듈 검증 | 100회 쓰기/동시 조회·복원 통과, 전체 미완료 | 5천 원본/10만 unit/1만 page/1천 conflict. 100회 쓰기와 두 MCP 각각 312,407회 검색/읽기·100개 복원 회수. 복사·보호 처리 비용 개선. 높은 쓰기 지연·실제 한국어 품질·운영 부하 인수 남음 |
| B8 | R10 선택적 hybrid/관계 확장 | standalone 필터/출처·원자 재생성·경로 보호 검증, 관리형 활성화 보류 | 봉인 vector 세대/삭제·복원 수명, MCP 의미 record 선택과 실제 품질 검증 필요. 관측 제한 호스트의 crash 잔여물 회수도 보류 |

## 위험에 따른 보류

- 네 OSS 전체 서버·Proxy·전역 hook 동시 도입: 기존 기억 정본·인증·에이전트 정책과 중복/충돌하므로 보류. 기존 코드/작은 인터페이스 재사용으로 진행한다.
- 일반 graph DB/멀티모달 전체 도입: 현재 회수 결함을 해결하지 못하며 파생 데이터 삭제·정책·성능 검증 범위를 늘리므로 검색 평가 전에는 보류.
- LLM 요약만으로 실행 성공/승인된 사실 자동 승격: 자비스의 실행 증거 계약과 충돌하므로 구현하지 않는다. 검증 결과에 연결된 기억 후보·근거만 사용한다.
- 로컬 캐시를 에이전트별 기억 정본으로 운영: 공통 기억 일관성을 깨므로 보류. 캐시/전달 receipt는 재생성 가능한 운영 자료로 한정한다.
- owner-confirmed V1 correct 확장: 기존 승인 서명에 정정 target/prior가 포함되지 않아 보류. 신규 권한 소비는 remember에 한정하고, 정정은 기존 V2 target/delegation에 연결한다. 승인 후 대상 변경 거부와 실제 정정/재조회 검증이 재개 조건이다.

보류는 핵심 R1~R9나 실제 기억 저장·해석·복구를 회피하는 근거로 사용하지 않는다. 추가 보류에는 원인, 대신 제공할 동작, 재개 기준을 기록한다.

## 커밋/검증 기록

2026-09-07 KST 기준 작업 재개 시 HEAD `0ef3866`, 기존 대규모 staged provider 구현과 후속 수정이 미커밋 상태였다. 사용자의 변경을 보존한 스냅샷은 `/var/tmp/sb-goal-development-20260907/`에 저장했다. 별도 `phone-history/`, 임시 `2n`, `.bak-*` 파일은 이 개발 단위에서 제외한다.


### B1 진행 — 공개 응답·요청 출처 보강

- `fb47313`: MCP 공개 frontmatter를 기존 계약 필드에 투영. 내부 derivation_key와 원본 인용 span 보존.
- `77f3bad`: 같은 Git 경로로 검증되는 논리 ID/`wiki/` ID만 요청 ID와 일치시킴. 다른 페이지·잘못된 ID는 정상 ID로 위장하지 않음.
- 요청 remember는 원문 CAS와 8자리 hash 인용을 만들고 Vault를 통해 기록. 동일 후보 재처리는 동일 페이지, 다른 후보의 동일 원문은 출처별 페이지·공유 CAS로 보존.
- 정정/삭제에서 의도적으로 제거한 CAS를 참조하는 생존 문장은 해당 effect의 새 스냅샷에 연결. 원래부터 누락된 CAS를 정상 출처로 위장하지 않음.
- 검증: 전체 **527 passed, 2 skipped (119.23초)**, Ruff·diff check 통과. 추가 타입 경고는 수정했고 변경된 Vault/요청 복원 테스트는 **0 errors, 0 warnings**. 기준선의 다른 파일 경고 60개는 I8에 남음.
- 실프로세스: 독립된 managed generation의 단일 한국어 기억 → 실제 MCP → 수정하지 않은 자비스 transport/read adapter: **data 1 / current / evidence 1**. 내부 derivation_key와 논리 ID가 있는 실제 Vault 산출물을 사용.
- 운영 데이터 읽기 진단(소스 MCP만 교체): `운영 복구`는 conflicts, `업무`는 RECORD_IDENTITY_INVALID. 자비스 중복 키와 R4 시간 의미가 아직 차단 요인이다.
- 증거: `/var/tmp/sb-b1-20260907/`. 이번 후속 변경은 소스 검증이며 운영 release 전환은 아직 하지 않았다. 실제 자비스 candidate→outbox→settled 및 두 에이전트 앱 교차 사용은 미완료.

기존 병합 진행 상태는 기준선 커밋 `4da09b9`에서 마무리되었다(부모 `0ef3866`, `b5811d1`). 후속 작업 브랜치는 `codex/shared-memory-completion-20260907`이다. 무관한 미추적 자료는 계속 제외한다.


### B2 진행 — CLI 읽기 세대 고정

R9의 CLI status/search/sources/retention/metrics, doctor 조회, gc/migrate 미적용 조회, compile dry-run을 공통 read_config에 연결했다. reader pin이 반환한 generation root를 그대로 사용하며 별도 active 재조회는 제거했다. doctor --rebuild-ledger는 쓰기를 마친 뒤 읽기 pin을 얻으므로 잠금 중첩을 피한다. CLI 처리 실패에서도 reader lease가 해제되는지 검증했다.

집중 검사: CLI·runtime 관련 56개 통과. 테스트는 실제 generation의 등록 reader와 배타 잠금 차단을 확인하고 CLI 출력의 root가 고정된 generation인지 검사한다. 갱신 중 응답 지연 개선은 B3에 남으며, 이 커밋만으로 동시성 전체 완료를 선언하지 않는다.


### B2 검색 필터·최종 record 개수 검증

- Sealed 검색은 상태·수정 날짜·종류를 반영하고 기존 knowledge registry를 읽기 전용 snapshot으로 조회한다. 미등록 상태는 UNKNOWN, 승인/철회/후보 상태는 registry의 실제 값을 사용한다. 조회나 compile --state-report가 immutable 인덱스를 수정하지 않는다.
- `iter_lexical_hits`는 결과를 순차 처리한다. MCP schema 4는 title/heading만 일치하는 결과를 제외한 뒤 유효 record 개수에 limit를 적용한다. 페이지와 record의 중복 처리를 줄이고 구형 저장소의 128행 구간 이후도 이어서 탐색한다. Frozen wire schema와 도구 수는 변경하지 않았다.
- 검증: 집중 108개, 전체 **534 passed, 2 skipped (123.58초)**. Ruff·diff check 통과, 타입 **0 errors, 55 warnings**(기존 60개에서 감소).
- 운영 자료 실조회: 소스 CLI status가 generation root와 wiki 18/daily 2를 반환. `업무`의 9월 5일/wiki 필터 9건, 자료 없는 날짜 범위 0건. 테스트에서도 조회 전후 generation의 모든 파일 해시가 동일함을 확인했다.
- 증거: `/var/tmp/sb-b2-full-tests.log`, `/var/tmp/sb-b2-search-retest.log`, `/var/tmp/sb-b2-real-cli.json`, `/var/tmp/sb-b2-types-final.log`.
- 지식 상태 scope는 프로젝트 접근 권한 scope와 다르다. 프로젝트 범위는 B4, hybrid의 메타데이터/범위 보존은 B8에 계속 남는다. 이번 source MCP/CLI 검증으로 운영 배포나 자비스의 전체 기억 순환 완료를 주장하지 않는다.


### B3 진행 — 종료된 reader와 중단된 disposal 복구

- Linux boot ID + process starttime을 reader lease에 연결한다. 기존 reader_leases 열/호출 계약은 보존하고 별도 identity 테이블을 추가하여 구형 journal과 프로세스의 호환성을 유지한다.
- 실제 종료, zombie 또는 확인된 PID 재사용일 때만 lease를 정리한다. 생존 확인 실패·권한 오류·식별자가 없는 구형 live PID는 유지하고 오래되었다는 이유로 삭제하지 않는다. 실제 descriptor 검사는 기존대로 계속 적용한다.
- maintenance와 다음 mutation은 이미 전환된 활성 세대의 predecessor 정리를 먼저 마친다. 포인터 전환 후 실패한 정리를 건너뛰어 추가 세대를 만드는 경로를 막았다.
- 실제 spawn 프로세스가 pin을 잡은 상태에서 SIGKILL된 뒤, lease 잔여→정리→다음 generation 활성화→이전 디렉터리 폐기까지 검증했다. PID 재사용, 불확실한 생존 상태, 유지보수/다음 mutation의 재개도 검사한다.
- 운영 읽기 전용 관측: generation 디렉터리 7개, activation 상태 proved 11/activated 2. activated 2건의 generation 디렉터리는 이미 없어졌고 현재 active도 아니다. 이 과거 불일치와 잔여물은 최신 active 재개만으로 정리됐다고 간주하지 않는다. 백업/원장 대조 후 별도 복구해야 한다.
- I3의 LLM 실행 중 장시간 배타 잠금은 여전히 남아 있다. 이번 reader 복구가 조회 지연 개선을 의미하지 않는다. 운영 코드 배포는 아직 하지 않았다.

검증 결과: 전체 **540 passed, 2 skipped (127.40초)**, Ruff·diff check 통과, 타입 **0 errors, 55 warnings**. 새 process identity/reader recovery 관련 소스·테스트는 타입 오류·경고 0. 로그는 `/var/tmp/sb-b3-full-tests.log`, `/var/tmp/sb-b3-types-final.log`에 있다.


### B1 완료 보강 — 자비스 다중 기억 소비·시간 처리

- 자비스 `5c44b1f`: parser/집계 중복 키를 bound record ID/digest로 변경. page별 모든 검색 선택을 보존하며 한 번 읽고 각각 검증한다. 같은 출처의 여러 문장, 중복 선택, 같은 페이지의 잘못된 첫 선택이 정상 마지막 선택에 가려지는 경우를 검사했다.
- 자비스 `f9513d0`: bound record는 페이지 작성일만으로 하드 만료하지 않는다. 사실 구간 밖은 stale이며 즉시 응답 만료, 구간 안은 조회 시각에 설정 TTL을 더하되 명시적 종료일로 제한한다. strict identity/digest·generation·legacy 검사를 유지했다. 날짜 형식은 Python과 동일한 연도 1~9999의 24자 canonical UTC로 검증한다.
- Second Brain: 하루 일괄 만료를 제거하고 내부 명시적 기간을 검증·보존한다. 종료 미상은 열린 종료, 시작 미상은 열린 시작으로 표현한다. 이는 사실 검증일을 새로 추론하는 것이 아니다. 읽는 시각이나 합성 Git timestamp를 record ID에 넣지 않는다. 실제 sealed 두 세대의 날짜 없는 기록도 같은 ID를 유지한다.
- 독립 검토에서 지적한 page 선택 유실, 합성 commit 시각, 확장 연도·0년 불일치를 반영했다. `trust=untrusted`/`authority=none`과 target의 5분 만료는 유지한다.
- 최종 Python 전체 **548 passed, 2 skipped (123.92초)**; Ruff 통과; 타입 **0 errors, 55 warnings**. 새 시간 소스·테스트 타입 오류·경고 0. 자비스 기억 관련 단위 **244 passed / 26 files**, 변경 파일 ESLint 및 backend build 통과. 임시 복제 디렉터리의 중복 테스트는 최종 수치에서 제외했다.
- 실제 프로세스: 소스 MCP와 빌드한 자비스 transport/read adapter로 운영 자료를 읽어 `운영 복구` current 1개, `업무` current 10개. 소비자 시계를 현재/다음 날/35일 뒤로 바꿔도 같은 record ID 10개, bounded expiry, untrusted를 확인했다. 사용자 내용을 테스트 fixture로 복제하지 않았다.
- 증거: `/var/tmp/sb-time-final-tests.log`, `/var/tmp/sb-time-final-types.log`, `/var/tmp/jarvis-memory-time-final-tests.log`, `/var/tmp/jarvis-memory-time-build.log`, `/var/tmp/jarvis-memory-time-probe.jsonl`, `/var/tmp/jarvis-memory-future-probe.jsonl`.

R4는 기존 기록의 digest를 바꾸므로 실행 파일만 바꾸는 배포는 하지 않는다. [시간 계약](MEMORY-TIME-CONTRACT-2026-09-07.md)의 유지보수 경계에서 새 provider release 세대와 실행 파일을 함께 전환하고 기존 target은 재조회해야 한다. 운영 release/서비스/active 포인터는 이번에 전환하지 않았다. 현재·미래 시계 프로브는 읽기 검증이며 35일 실운영, 자비스 candidate/outbox/settled 순환, 두 에이전트 앱 공유 완료의 증거가 아니다. B4~B8 및 I3 지연·B3 과거 잔여물은 계속 진행 대상이다.


### B4 진행 — 실제 MCP/outbox 순환과 재사용

자비스 `471cab3`에서 세션 전체 generation 고정을 public 조회 단위로 분리하고 schema4 recentChanges의 generation 유실을 수정했다. 수정 전 실제 격리 순환은 settled 이후 reader 재사용에서 실패했다. 수정 후 pending→proved→settled→같은 reader current 1개, 독립 두 번째 MCP 프로세스의 동일 record 회수, replayed=true→apply idle→outbox 추가 dispatch 0을 확인했다.

재현 가능한 `scripts/jarvis-memory-acceptance.mjs`와 격리 provider fixture를 추가했다. 자비스의 합성 검증 결과·서명 fixture를 사용하며, 하네스가 expected selector를 만들고 apply/reconcile을 호출한다. 따라서 실제 업무 검증, 운영 자동 연결, 실제 Codex/Claude 앱 공유, 여러 줄 입력 완료와 구분한다.

검증: 자비스 관련 단위 **247 passed / 26 files**, ESLint·backend build 통과, 독립 코드 검토 완료. 새 Python fixture Ruff·타입 오류/경고 0, Node 구문 검사 통과. 상세 관측 및 새로 확인한 필수 잔여 I1-a~e는 [순환 인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 있다. 핵심 잔여는 운영 outbox 생성·승인 원문 보존·selector 생성·여러 줄 판정·비동기 reconciliation이다. 운영 배포나 권한 우회는 수행하지 않았다.


### B4 진행 — 2026-09-08 승인 원문 수명과 종료 후 재확인

자비스 `64b255b`: 승인/거절 중 원문 삭제를 제거하고 committed terminal 상태에서만 digest를 검증해 정리한다. 진행 중 원문은 confirmation 기한만으로 삭제하지 않는다. 원문 정리 뒤 동일 명령의 결과 재확인이 가능하며, 정리 실패를 이미 완료된 저장의 실패로 바꾸지 않는다. 다음 cycle에서 정리를 재시도한다. 실제 분류→승인에서 드러난 후보 키/provider 키 혼용도 새 dispatch 생성에서 수정했다.

집중 검증 **91 passed / 37 files**, 변경 파일 ESLint·backend build 통과, 독립 검토 완료. 격리 실제 MCP→outbox→proved→settled→두 클라이언트 재조회 순환에서 원문 파일 0개와 terminal replay settled, 중복 dispatch 0을 확인했다. 상세 로그와 범위는 [인수 보고서 후속](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 기록했다.

I1-b는 전체 승인 쓰기까지 완료가 아니다. 승인된 inference의 authority claim/receipt 연결, 바깥 DB rollback 후 dispatch metadata 잔여물 재승인 복구가 남는다. 실제 runtime 생성·selector·여러 줄·reconciliation 및 cleanup 오류 표시도 남아 있다. B3 지연/과거 잔여물, B5~B8 전체 범위와 운영 전환은 계속 미완료다.

### B4 진행 — owner-confirmed remember 권한 연결

자비스 `d553327`: 이후 owner confirmation에서 발생한 실제 결정·서명·개인 redemption을 검사하여 remember를 허용한다. 원문·주제·정책 값과 후보를 일치시키고 실제 receipt 만료를 넘지 않는다. 기존 auto-staged 경로의 내용 불일치도 거부한다. inference 분류는 유지한다. V1 correct는 승인과 prior 결합이 부족하므로 신규 경로에서 허용하지 않고 기존 V2 연결로 진행한다.

집중 **91 passed / 36 files**, 타입 보정 후 해당 경로 **7 passed**, ESLint·backend build·독립 검토 완료. 실제 분류→합성 owner 승인→별도 MCP→provider proved→outbox settled→두 번째 클라이언트 동일 기억 회수까지 통과했다. 기존 verified fixture 순환도 통과했다. 상세 명령·증거·보류 사유는 [인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 있다.

원문/권한 경로의 소스 검증과 runtime 배포를 구분한다. 실제 서비스 자동 outbox 생성, selector, 여러 줄, reconciliation, project/user/agent 범위, rollback metadata 복구 및 B3/B5~B8의 미완료 범위는 유지한다.

### B4 진행 — 전체 record 검증·민감도·완료 관측 예산

자비스 `c7c5182`: 영속 publication/권한에서 expected_artifact 명령을 구성하며, canonical remember 결과는 원문 전체와 모든 record의 개수·순서·출처·span·세대·민감도를 대응해 판정한다. Second Brain은 요청 민감도를 Vault에 보존하고 읽을 수 없는 record 묶음을 접수/CAS 쓰기 전에 거부한다. 기본 예산은 유지하고 schema4에 명시적 record-set-v1 완료 관측 프로필을 추가했다.

전체 Python **556 passed, 2 skipped (124.09초)**, 자비스 집중 **287 passed / 32 files (36.09초)**, Ruff·변경 ESLint·backend build·Node 구문 검사 통과. 변경 Python 타입 오류/경고 0, 자비스 독립 검토 완료. 실제 격리 MCP에서 4개 반복/공백/footnote 및 64개 record의 일반·sensitive 입력이 proved→settled→두 클라이언트 회수, replay/추가 dispatch 0, terminal 원문 정리를 통과했다.

기본 64KB 예산으로 64개를 읽으면 AGGREGATE_OVERSIZE로 reconciling에 남고 원문은 유지된다. 운영 완료 reader에 새 프로필을 명시 주입해야 한다. 일반 LF는 V1에서 여전히 거부되므로 일상 여러 줄 입력 완료가 아니다. 상세 재현과 한계는 [결과 대응 계약](REMEMBER-ARTIFACT-CONTRACT-2026-09-08.md)에 기록했다. 운영 자동 구성·주기적 재확인·승인 rollback metadata 복구·V2 정정·프로젝트 범위·실제 앱 검증과 B3/B5~B8은 미완료다.

### B4 진행 — 승인 rollback metadata 복구

자비스 `316b8f2`: 승인 event/바깥 DB rollback 뒤 남은 권한 없는 dispatch 파일을 같은 원문·후보인지 검사하고 새 receipt로 재발행한다. DB writer lock 안에서 영속 receipt/decision/publication/outbox를 확인하며, 이미 확정됐거나 변경·손상된 파일은 보존한다. 동일 receipt 재시도와 원문 보존 규칙은 유지한다.

변경 전 두 경로 replay conflict 재현, 변경 후 최종 회귀 **92 passed / 35 files (40.47초)**, 변경 ESLint·backend build·독립 검토 통과. 실제 격리 MCP에서 rollback→새 승인→민감 기억 64개 proved/settled→두 클라이언트 회수·추가 dispatch 0·원문 정리까지 검증했다. 재현 명령과 한계는 [순환 인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)의 마지막 절에 있다.

I1-b의 이 소스 결함은 수정됐다. 운영 실행기 outbox 주입과 주기적 완료 확인은 여전히 없으며 I1-a/c/e를 이어간다. B3 지연/과거 잔여물, 일반 LF·V2 정정·프로젝트 범위·실제 앱, B5~B8과 운영 배포/복원 검증은 계속 미완료다.

### B4 진행 — CLI/dashboard 실행기와 주기 완료 확인 연결

자비스 `a680fd5`: 공통 production outbox factory를 CLI control.execute와 dashboard executor에 연결했다. stage-dispatch는 예상 결과를 계산해 기존 승인용 명령을 구성한다. memory outbox --once/list로 처리·상태 확인이 가능하며 dashboard 기존 interval이 bounded cycle을 실행한다. 완료 reader의 예산/read fence, 공통 spool root, transport 소유권을 보존한다. HTTP 실행과 tick을 drain한 뒤 DB를 닫고 상태 변경을 명시 통지한다.

회귀 **100 passed / 39 files**, 추가 tick/SSE 검사 **11 passed / 4 files**(일부 중복), 변경 ESLint·backend build·독립 검토 통과. 실제 격리 MCP에 CLI execute 경로로 민감 기억 64개를 보내고 다음 CLI cycle에서 settled와 독립 클라이언트 회수, 재전송 중복 0을 확인했다. Python 소스는 변경하지 않았다.

실측에서 control command는 outbox settled 뒤에도 uncertain으로 남는다. 영수증 기반 최종 상태 반영을 다음 필수 수정으로 지정했다. 기본 운영 signed-fence 구성, 후보/publication/UI 전체 흐름, 배포·실제 앱/범위 및 B3/B5~B8은 계속 미완료다. 상세 재현·변경·한계는 [기억 실행기 연결 보고서](JARVIS-MEMORY-RUNTIME-2026-09-08.md)를 따른다.

### B4 진행 — 기억 완료 증거에서 원래 명령 최종 상태 복구

자비스 `20c8936`: 앞 절의 uncertain 잔존 결함을 후속 수정했다. 기존 command/receipt/redemption/fence와 dispatch·observation·settlement 증거를 검증하고 uncertain 또는 lease 만료 claimed를 completed/failed로 반영한다. 취소/철회와 과거 uncertain 이력을 보존하며 재전송하지 않는다. 오류 작업을 지나가는 영속 순환 커서와 원자적 상태/effect/event 기록을 추가했다. cursor 저장 실패가 이미 성공한 다른 실행을 failed로 바꾸지 않는 회귀도 포함한다.

최종 회귀 **160 passed / 52 files (85.42초)**, backend build·변경 ESLint·독립 재검토 통과. 실제 격리 MCP·CLI API에서 민감 기억 64개가 proved→outbox settled→control completed로 연결됐다. 두 클라이언트 current, 추가 dispatch 0, review 원문 0개, cleanup/control 오류 없음. 소스·검증·잔여 우선순위는 [명령 완료 연결 보고서](MEMORY-CONTROL-COMPLETION-2026-09-08.md)를 따른다. 운영 배포·서명 fence 기본 구성·실제 앱/범위·B3/B5~B8의 전체 완료로 확대하지 않는다.

### B4 진행 — 삭제 이후 기본 서명 조회와 재저장

기본 CLI/dashboard가 기존 자비스 등록 키·provider identity·현재 DB 삭제 원장으로 read fence를 생성하도록 연결했다. 키 만료/철회는 매 조회 확인하고 DB별 outbox를 분리한다. 실제 삭제에서 발견한 SB 빈 `sources: []` 공개 응답도 기존 scalar로 정규화했다. frozen 계약과 승인 구조는 유지한다.

자비스 관련 회귀 **149 passed / 26 files**, Python 공개 응답·MCP 계약·삭제/복원 **18 passed**, backend build·lint·독립 검토 통과. 격리 실제 MCP에서 삭제 proved/sequence 1, 무서명·과거 fence 거부, 삭제 record 0, 이후 민감 record 64개 저장→control completed→두 클라이언트 회수 성공. 상세 설정과 증거는 [삭제 이후 조회 보고서](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md). 운영 구성·배포, 실제 후보/UI·앱별 수집/주입·접근 범위, 일반 LF/V2 정정, B3/B5~B8은 남는다.

### B3 진행 — LLM 준비 중 조회와 writer/삭제 경계

세대 writer 전용 mutex를 유지한 채 sealed 부모에서 successor를 준비하는 구간만 reader와 공유한다. 전환/폐기 전에는 EX로 복구하고 실제 부모와 삭제 원장을 다시 검사한다. MCP 조회가 유지보수의 writer 잠금에 재차 막히던 경로도 idle 조건의 정리로 바꿨다. 만료 export 상태는 cleanup이 미뤄져도 available로 서명하지 않는다.

별도 pipeline process를 준비 중 유지한 상태에서 실제 stdio MCP 검색·페이지·상태 조회, 두 writer의 순서/내용 보존, reader pin 보호, writer kill 복구, 삭제 접수 시 오래된 조회/전환 거부를 검증했다. 실제 자비스 CLI 완료 cycle과 두 MCP 클라이언트의 64개 민감 record 회수는 약 **1.394초**, control completed/outbox settled, 추가 dispatch 0, cleanup/control 오류 없음이었다. `/var/tmp/sb-jarvis-concurrent-compile-verified-acceptance.log`.

검증 중 발견한 첫 기억→export의 필수 log 누락도 Vault 초기화로 수정하고 raw/.sb의 Git 제외를 seal 경계에서 보장했다. 기존 제외 취소 규칙보다 강제 규칙을 뒤에 배치하며 CAS 원문은 보존한다. 최종 전체 **564 passed / 2 skipped, 138.84초**, 독립 검토 지적 두 건 수정 후 추가 actionable 없음, 변경 타입 오류/경고 0, 전체 Ruff·하네스 구문 검사 통과. 세부 한계는 [갱신 중 조회 보고서](GENERATION-READ-CONCURRENCY-2026-09-08.md).

운영 p95·부하 인수, 과거 `.staging`/미활성 세대의 원장 기반 복구는 남는다. 임시 디렉터리 일괄 삭제를 보류했고 자비스 signed export status 소비 미구현도 I1 후속으로 기록했다. 운영 서비스·release/active generation·push는 변경하지 않았다.


### B4 진행 — 후보 검토 화면과 실제 저장 진행 상태

자비스 `c4c5c98`: 기억 후보 상세를 영속 원문·출처·정책 digest에 결합하고 검토한 내용으로 확인/거절 명령을 준비한다. 승인된 후보의 저장 명령 준비와 control/outbox 진행 API·화면을 연결했다. remember 확인 실행기의 잘못된 correct 분기와 Overview 동시 DB 변경 오판도 재현·수정했다. 기존 owner 승인·outbox·SB 계약을 재사용한다.

최종 커밋 기준 `49446db`와 이 단위 소스를 격리하여 build 및 후보/HTTP/동시성 15개 통과. frontend 전체 143개, 관련 회귀 72개·투영 26개·최종 Overview 13개는 일부 중복으로 별도 기록한다. Playwright 1440/375px의 검토→승인 실행→저장 pending→새로고침 유지, 콘솔 오류/serious·critical 접근성 위반/가로 넘침 0. 실제 MCP/CLI 인수는 64개 민감 record·두 클라이언트 current·control completed/outbox settled에 dashboard stored=true까지 확인했다. 독립 재검토 추가 지적 없음.

상세 증거와 잔여는 [인수 보고서](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md). 실제 업무 후보 수집·private 후보 UI·일반 LF/V2 정정·앱별 공유/주입·접근 범위·운영 전환 및 B5~B8은 남는다. 서비스·운영 세대·push는 변경하지 않았다.


### B4 진행 — 제품 후보 접수와 원문/DB 시간 일치

자비스 `b89dab6`: `memory classify <input.json> <policy.json>` 제품 진입점과 기존 owner 확인/저장 흐름을 연결했다. 실제 시계에서 원문/DB 해시가 달라지던 결함, commit 전 남은 원문의 재시도 충돌, 부적격 원문 발행과 만료 감사행 제약 충돌을 수정했다. 동일 원문만 제한적으로 복구하며 새 승인 구조나 임의 자동 승인을 만들지 않는다.

CLI 접수에서 시작한 실제 MCP 인수는 민감 기억 64개·두 클라이언트 current·completed/settled/dashboard stored=true, 중복 추가 dispatch 0을 확인했다. 실제 시계의 CLI subprocess 재시도/원문 검토도 통과했다. 관련 37개 및 추가 회귀 123개, backend build·lint·독립 재검토 통과. [보고서](MEMORY-CANDIDATE-INTAKE-2026-09-08.md).

이번 중 확정된 자비스 task completion `7129b9d`와 기억 verifier authority 연결을 다음에 대조한다. 바로 approved 또는 no_data 후보의 본문 인계, 일반 LF/V2·실제 앱/범위 및 B5~B8과 운영 인수는 남는다.

### B4 보류 판정·B8 선행 수정 — 원본 차단 전파와 벡터 읽기

task completion 수집 초안은 task_id 차단 누락과 원본 차단의 파생 후보/저장 전파 부재를 확인해 제품에 반영하지 않았다. 자비스 `73d59df`에 수집 전/후·전송 중·저장/복원 후까지의 재개 조건을 기록했다. 기존 classify·검토·owner 확인·outbox는 유지한다.

SB query_cosine의 조회 중 DROP/CREATE를 readonly SQLite CTE로 바꾸고 RRF가 출처/상태 필드를 보존하도록 수정했다. 없는 DB 생성, 모델/revision 불일치 허용, 제어문자 원문 손상과 잘못된 거리의 완전 일치 오판도 수정했다. 수정 전 6건 실패로 재현했고 실제 SQLite 동시 조회 전후 DB 불변·readonly 쓰기 거부를 검증했다.

표준 전체 **566 passed, 2 skipped (138.94초)**, optional 포함 집중 **32 passed, 1 skipped (2.28초)**이며 두 실행은 일부 중복이다. Ruff·diff check 통과, 변경 소스 타입 오류/경고 0. [상세 보고서](HYBRID-READONLY-2026-09-08.md). 실제 모델 품질·cosine 전용 출처/필터·세대/삭제 수명 결합과 hybrid 활성화는 남는다. B4~B8 전체나 운영 전환 완료를 의미하지 않는다.

### B4 진행 — V2 정정의 줄바꿈·인용·완료 관측

실제 요청에서 `PROVIDER_ARTIFACT_INVALID`로 reconciling에 남던 CRLF 정정과 중간 문장 인용 누락을 수정했다. LF/CRLF·빈 줄을 보존하고 각 문장에 기존 citation을 연결한 뒤 effect snapshot으로 재결합한다. 사용자 인용 구문은 문자로 escape한다. 출력 record 수/길이를 대상 쓰기 전에 검증하며 raw content digest와 frozen V1/V2/MCP 필드는 유지한다.

격리 실제 MCP에서 새 문장 4개를 두 자비스 소비자가 current로 회수했고 내용 digest·effect 출처가 모두 일치했다. 자비스 서명 proof/관측 검증기 통과, 이전 기억 0건, replay=true/추가 적용 idle, 변경 원문과 과거 fence 거부를 확인했다. [상세 인수 및 한계](CORRECTION-RENDERING-2026-09-08.md).

전체 **571 passed, 2 skipped (157.58초)**, 관련 집중 **22 passed (20.48초)**이며 일부 중복이다. Ruff·Node 구문·diff check 통과, 변경 소스 타입 오류/경고 0.

V1 신규 remember의 일반 줄바꿈, 자비스 정정 UI/사용자 승인/production saga/control 완료의 전체 인수와 B4~B8 운영 완료는 여전히 남는다. 자비스 제품 소스·서비스·운영 세대·push는 변경하지 않았다.


### B4 진행 — 자비스 V2 정정 명령 완료와 중단 복구

자비스 `4721358`: 기존 correction saga의 settled와 control 완료 사이 commit 간격, 만료/시각 재사용, compaction 이후 명령 원형 소실, settled 주기 복구 누락을 수정했다. 원문 없는 immutable binding과 원 승인·전송 fence·서명 provider proof·동일 lane purge를 대조한 뒤 원장/완료/effect/event를 함께 commit한다. 이미 compaction이 끝났으면 provider가 중단돼도 로컬 증거로 복구한다.

새 회귀 11개를 포함한 관련 **34 passed / 9 files (50.15초)**, backend build·변경 lint·독립 재검토 통과. 격리 실제 SB MCP에서 후보 확인→승인 dispatch→정정 proved→최종 event 실패→20분 후 control completed, 전송/compaction 각 1회, 복구 중 provider 추가 관측 0회를 검증했다. 두 reader의 같은 정정 record 4개·내용/출처 digest 일치와 이전 기억 0개를 확인했다. [수정 내역·검증 한계·후속 목록](CORRECTION-CONTROL-COMPLETION-2026-09-08.md).

이 검증은 합성 owner 서명을 쓰는 실제 backend 순환이다. 정정 UI/실제 사용자 승인 화면, 실제 앱별 수집·주입, V1 일반 LF, 접근 범위, task 원본 차단 전파와 운영 인수는 남는다. 운영 DB migration·배포·서비스 재시작·push는 수행하지 않았다.


### B6 진행 — 검증 백업과 운영 준비 상태

R8/I6의 mtime 기반 백업 정상 오판, 오래된 실행·정체 요청·최근 실패·손상 journal 누락을 수정했다. CLI backup은 격리 복원 검증 후 receipt를 남기고 기존 archive는 verify-backup으로 검사한다. 원 저장소/provider·생성 시각·파일 identity·삭제 sequence/root를 확인하며, 관리형 검증은 기존 generation/request 잠금을 유지하고 오래된 삭제 이력의 archive를 복원 전에 거부한다.

표준 전체 **591 passed / 2 skipped (158.89초)**, 관련 집중 **36 passed (13.36초)**. 전체 Ruff·신규 모듈/CLI 타입 오류·경고 0, 실제 CLI/HTTP에서 health 200과 ready 503→200→503 분리, 손상 verify exit 1, 임시 복원 잔여 0, 관리형 backup origin/삭제 이력 보존을 확인했다. [상세 동작·설정·검증 및 한계](READINESS-VERIFICATION-2026-09-08.md).

실제 운영 백업 검사·배포·runtime 재기동/활성화 인수, 자비스 adapter 인수 receipt의 readiness 결합, 대용량 검증 잠금/공간 최적화는 남는다. 출처가 없는 과거 백업과 오래된 삭제 이력을 추정으로 정상 승격하지 않는다. 운영 서비스·세대·push는 변경하지 않았다.

### B6/B7 진행 — 봉인 보존 조회·대용량 인수·세대 생성 개선

실제 5,000 원본→100,000 units, 10,000 page/1,000 conflict fixture와 100회 CLI 읽기·백업 복원을 검증했다. 봉인 보존 조회는 원장을 read-only로 열고, 파생 인덱스 rows+binding은 일괄 transaction으로 commit한다. 세대 생성 59.36→23.78초, CLI 검색 p95 344.24ms. **전체 627 passed/2 skipped (161.44초)**, Ruff 통과, 변경 소스/테스트/도구 타입 오류·경고 0. [증거·제한·추가 결함](CAPACITY-ACCEPTANCE-2026-09-08.md).

`max_new_units_per_run=1`에서 20 units 저장을 재현했다. 다음 I5 필수 수정으로 파일/단위 예산과 초과 원본 보존/재개를 분리한다. 100회 managed 쓰기·동시성·한국어 품질 및 B4 접근 범위/실제 앱·B5 문맥 공급·운영 전환/DR 등 기존 범위는 남는다. 운영 cap 증대와 자동 대량 온보딩은 보류한다.

### B7/I5 진행 — 파일 수와 신규 unit 예산 분리

발견된 `max_new_units_per_run=1`→20 units 저장 결함을 수정했다. 신규 unit과 source 시도 수를 분리하고, `--limit`의 기존 원본 수 의미와 unit 제한을 함께 적용한다. 전체 예산 초과는 원본을 보존한 failed/error 응답, 잔여 예산 초과는 다음 실행에서 재개하는 capped로 처리한다. 부분 unit/source 완료는 보류하며 기존 원자적 원장 및 inbox 완료 경계를 유지한다.

실제 관리형 CLI에서 5 sources/53 units·원문 CAS 일치·재실행 증가 0, 대용량 5천 source/10만 units·100회 CLI 검색·백업 복원 재검증 통과. **전체 638 passed/2 skipped (165.25초)**, Ruff/diff 통과, 타입 오류 0/기존 경고 1. [계약·검사·증거](INGEST-BUDGET-CONTRACT-2026-09-08.md). 운영 cap/배포는 변경하지 않았으며 B4 실제 앱/범위·정정 UI, B5 문맥 공급, B6 운영 전환/DR, B7 100회 쓰기/동시성/한국어 평가 및 B8은 유지한다.

### B4 진행 — 실제 Codex CLI·Claude Code 상호 기억 회수

Codex CLI 0.153.4와 Claude Code 2.1.261의 실제 로그인/모델/MCP 도구로 A 기록→Claude 회수 및 B 기록→새 Codex 회수를 검증했다. 각각 모르는 무작위 답을 원문과 함께 회수했고 search/page 세대와 record ID/digest를 대조했다. source_item 2개, CAS 원문 일치, 성공 MCP 6건. 관련 회귀 22 passed/7.14초. [실행·권한 설정·감사·한계](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md).

검증 서버 compile은 결정적 fixture이며 실제 LLM 요약 품질을 의미하지 않는다. 일반 stdio에 없는 sb_run을 안내하던 README를 수정했다. scope를 일반 검색 필터로 대체하는 방식은 보류하고 [권한/분류 계약 경계](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md)를 기록했다. 실제 GUI·다른 client·삭제 후 일반 agent fence 연결·자동 수집/주입, B4~B8 운영 및 전체 인수는 유지한다.


### B5 진행 — 정책·세대에 결합한 실제 CLI 참고 기억 조회

자비스 `63bdd02`: `memory context`를 기존 adapter와 본문 준비 모듈에 연결했다. 웹 suppression을
공통화하고 migration 070의 revision으로 같은 개수 REPLACE를 감지한다. 전후 provider 세대와
최종 로컬 정책·key/본문 만료를 확인하고 전체 stdout까지 예산에 포함한다. 내부 오류와 cleanup
실패를 정규화했다. 관련 77 passed/7 files, 격리 build·타입·lint·독립 최종 리뷰 통과.

실제 Node CLI→SB MCP의 조회/빈 결과/불가능 예산/공개 권한 키/철회 키 5건 통과, 조회 1 record,
stdout 3,073 bytes, 조회 전후 authority 논리 행 불변. [상세 변경·증거·잔여 목록](MEMORY-REFERENCE-READ-2026-09-08.md).
모델 session 전달/compaction/후속 삭제 무효화·scope·운영 migration/배포는 미완료다.
SB 100회 쓰기 인수는 65회 관측 상태이며 제품 소스 고정과 검색/복구 세 커밋 병합 대기를 유지한다.


### B5 인수 — 실제 모델의 reference JSON 소비

[모델 소비 인수](MEMORY-REFERENCE-MODEL-ACCEPTANCE-2026-09-08.md): 무작위 합성 기억을 실제
자비스 CLI로 회수한 뒤 도구 없는 Codex 모델에 전달했다. 답·record/digest/source/세대 정확히
일치, 빈 기억은 no_data, 완료 시 만료 전·이후 provider 재조회 일치. native 이벤트 감사기 14개,
관련 Python 회귀 12개와 기존 실제 CLI 5시나리오 통과.

제품 context/projection 세 테이블은 실제 관측 0행이며 session receipt를 구현했다고 주장하지
않는다. 기존 작업 provider의 비영속 세션·승인 plan 입력 경계를 확인했고 자동 연결은 보류한다.
C6/C7/C8과 B4~B8의 남은 조건, 100회 쓰기 및 세 커밋 병합 대기는 유지한다.


### B8/R10 진행 — 벡터 검색의 필터·출처·정정 일치

격리 소스 `ef3466e`: 네 가지 실패를 재현하고 cosine 후보를 현재 검색 DB의 page/section/본문에
결합했다. lexical과 같은 종류·상태·날짜·지식 scope를 거리 정렬/limit 전에 적용하고 출처·승인
상태를 보존한다. 읽기 snapshot의 model identity와 오류 거리를 검증하며 lexical fallback을 유지한다.

집중 63 passed/1 skipped, 격리 전체 775 passed/2 skipped, 실제 CLI 5시나리오 통과. 두 DB의
동시 읽기 불변, 정정 전 vector 제외 확인. [상세 결과·제한](HYBRID-FILTERS-2026-09-08.md).
봉인 세대/삭제 수명·실제 품질·대용량 성능이 남아 운영 hybrid 활성화는 보류한다. full100 완료 후
기존 세 커밋에 ef3466e를 이어 병합한다. B4~B8 전체 목표와 자비스 자동 전달 보류는 유지한다.


### B8/R10 진행 — 벡터 재생성의 기존 DB 보존

격리 `5d25d3a`: encode 실패 시 기존 DB 삭제, 48 sections에서 SQL argv 초과, 짧은 encoder
결과의 IndexError, 봉인 root 직접 변경을 재현·수정했다. private 임시 DB·단일 writer·검증 후
원자적 교체·fsync와 ASCII hex SQL stream을 적용하고 같은 Git commit의 본문을 수집한다.

집중 83 passed/1 skipped, 전체 797 passed/2 skipped, 131 vectors 실제 CLI 재생성과 기존
필터 CLI 5건 통과. 강제 종료 후 기존 검색/다음 rebuild, 열린 reader의 이전 snapshot 보존을
확인했다. [상세 결함·검증·보류](VECTOR-REBUILD-ATOMICITY-2026-09-08.md).

강제 종료 임시 DB 자동 회수·대규모 모델 메모리·봉인 세대/삭제 수명·실제 질문 품질은 남는다.
관리형 vector는 현재 enabled=0이며 운영 hybrid 활성화는 보류한다. full100은 93회 관측,
최종 성공 전 제품 소스 고정은 유지한다. 병합 대기는 기존 네 커밋 다음 5d25d3a, 총 다섯이다.
B4~B8 전체 완료와 자비스 자동 전달/session 계약의 기존 미완료 판정을 유지한다.
