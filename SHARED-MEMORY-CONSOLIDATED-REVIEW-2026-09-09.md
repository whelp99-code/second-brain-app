# 자비스 공통 기억 완성 — 수정·개선·고도화 통합 분석

**2026-09-09 미확인028 원본 복원:** [과거 배포3곳 hash 일치·운영 사본 재인수](RECOVERED-MIGRATION-028-2026-09-09.md). Ja6afd5a가502bytes 원본을 그대로 복원. 사본58→81·기존journal58 및 업무테이블212 보존·FK0/replay변경0. 고유17통과·emit/lint. unknown 출처 차단은 해소, 혼합 버전/운영 전환·실제 A→B 및 M1–M14 인수는 유지.

**2026-09-09 운영 사본 전환·미확인 이력 차단:** [58→81 사본 보존 검사와 최종 HOLD](OPERATIONAL-AUTHORITY-UPGRADE-2026-09-09.md). 수정 전212테이블/FK0/재실행변경0이나 구 실행물이 최신 사본을 ready로 수락. Ja2e59eb가 unknown 이력을 차단, 실제 운영 사본의028_budgeted_evolution_memory.sql 거절·행 불변. 관련16통과·emit/lint. 운영 전환·혼합 버전은 원본 SQL/배포 경위 확인 전 보류, 전체 M1–M14 유지.

**2026-09-09 쓰기 verifier CLI 설정 연결:** [명시적7옵션·기존 DB 연결 수명·실제 TLS/MCP](SCOPED-PROVIDER-CLI-CONFIG-2026-09-09.md). J399fb4f, 취소 fixture e6e36d7. 최종 고유82통과·emit/lint, 실제4시나리오 정상proved/철회·만료 차단·attempt1/FK0. 운영 배포·자격증명·DB 전환·실제 A→B와 M1–M14는 남는다.

**2026-09-09 운영 읽기 전용 대조:** [실행 릴리스·설정·브리핑 실패 이력](OPERATIONAL-HANDOFF-AUDIT-2026-09-09.md). SB health/ready 200·최근 배치 ok이나 새 scoped 모듈과 gateway 복구 옵션은 운영에 없음. 과거 brief 실패5건을 구버전 readiness가 판정에 반영하지 않으며 개발 로직에는 이미 검사 존재. 중복 구현 대신 배포 차이·실패 복구·실제 A→B를 우선한다. 운영 변경 없음, 전체 M1–M14 미완료.

**2026-09-09 게이트웨이 CLI 복구 설정 공급:** [13개 명시적 옵션·startup 전달·실제 HTTP/MCP 재인수](SCOPED-GATEWAY-CLI-CONFIG-2026-09-09.md). 일부 설정은 시작 거절, 기존 context 유지. 관련55통과·emit/lint, parser 조립 설정으로 실제 3상태/철회/종료복구 attempt1/FK0. 운영 경로·키·서비스 인수·쓰기 verifier CLI 설정·실제 A→B 등 M1–M14는 남는다.

**2026-09-09 실제 로그인 HTTP→scoped 복구:** [쿠키/CSRF·현재 세션·실제 3상태/종료 복구](SCOPED-RECONCILE-HTTP-2026-09-09.md). 명시적 서버 설정에서 새 POST가 실제 session store→CLI/production/MCP에 연결된다. 관련48통과·emit/lint. 실제 인증/본문/정책/만료 차단, pending/failed deferred와 proved control completed·exit73 replay·attempt1/FK0. gateway CLI 설정 공급·운영 Tailnet/서비스·실제 A→B 및 전체 M1–M14 인수는 남는다.

**2026-09-09 호스트 인증 기반 scoped 복구 CLI:** [production 구성·명령 진입점·실제 3상태/종료 복구](SCOPED-RECONCILE-CLI-2026-09-09.md). memory reconcile-scoped ID --once가 기존 세션 callback/파일 정책/키/명시적 전송으로 상태별 실행한다. 관련22통과·emit/lint, 실제 execute→MCP pending/failed deferred 및 proved control completed·exit73 replay·attempt1/FK0. 독립 CLI 로그인·실제 gateway 세션 공급/운영 설정·A→B 및 전체 M1–M14 인수는 남는다.

**2026-09-09 상태별 단건 scoped 재조정 실행:** [journal 복구→현재 기억 검증→완료·실제 3상태/종료 복구](SCOPED-RECONCILE-ONCE-2026-09-09.md). pending/failed/not_found 보류·lease 해제, proved만 기존 완료 검증 연결, 오류 lease 보존. 관련20통과·emit/lint. 실제 pending/failed 재시작 attempt1/event1, proved settled/control completed/settlement1/attempt1/FK0·exit73 독립 replay. 운영 인증/명령 진입점·서비스 설정·실제 A→B 등 M1–M14 인수는 남는다.

**2026-09-09 최초 세대 이전 수락의 영속 복구:** [현재 권한/lease·원자 기록·실제 commit 후 종료 복구](SCOPED-JOURNAL-RECOVERY-2026-09-09.md). journal 조회를 원래 outbox acceptance 기록에 연결했다. 관련41통과·emit/lint·실제 pending/failed 각각 exit73→새 프로세스 replay, attempt1/event1/FK0. 철회/취소/lease 만료는 전체 rollback. 현재 artifact/최종 완료·자동 재전송으로 승격하지 않으며 운영 worker 연결·실제 A→B 등 전체 M1–M14 인수는 남는다.

**2026-09-09 자비스 최초 세대 이전 상태 소비 연결:** [전송 계약·현재 권한 재검사·실제 pending/failed 재시작](SCOPED-JOURNAL-CLIENT-2026-09-09.md). 새 journal 전용 클라이언트가 원래 acceptance를 회수하며 현재 artifact/완료로 승격하지 않는다. 실제 MCP schema 비교 등록 누락 수정, 관련56통과·타입/lint·패키징 확인. 실제 양쪽 철회 차단과 재시작 동일 결과. 원래 outbox/lease의 영속 복구 workflow·운영 설정·A→B 및 전체 M1–M14는 남는다.

**2026-09-09 최초 세대 이전 원장 상태 표면:** [새 scoped-request-status-v1·별도 MCP 재시작·권한 경계](SCOPED-JOURNAL-STATUS-2026-09-09.md). provider의 pending/failed/원래 수락 조회를 활성 세대에서 분리했다. 기존 read v1–v5 유지, 현재 정책·서명·삭제 이력 전후 검사 및 원장 부재 거부. 전체1,354통과/2skip/290.17초(embeddings 제외)·관련31통과(중복)·정적검사/Ruff 통과. 자비스 전송/소비자·현재 인증 발급과 복구 workflow 연결은 다음 작업이며 이 원장 응답은 현재 artifact/최종 완료 증거가 아니다. 전체 M1–M14 운영 인수는 유지한다.

**2026-09-09 공개 scoped MCP 쓰기 연결:** [고정 계약·별도 MCP→HTTPS→일반 CLI 인수](SCOPED-WRITE-MCP-2026-09-09.md). JARVIS `623afa6`의 scoped-request-write-v1과 SB sb_write_request를 연결했다. 최종 SB 전체1,342통과/2skip/273.05초(embeddings 제외), J 관련49통과·정적검사·패키징 확인. 실제 프로세스 정상 proved, 수락 중 철회/실행 전 철회/로그인 만료 차단. 운영 설정·자격증명·실제 에이전트 A→B 및 전체 M1–M14 인수는 남는다. [인계 병합 최신 우선순위](HANDOFF-MERGED-PRIORITIES-2026-09-09.md)를 현재 판단으로 사용하며 아래 기록은 각 당시 상태다.

**2026-09-09 일반 CLI에 scoped 실행 연결:** [명시적 설정·CA FIFO 정지 수정·실제 TLS/CLI](SCOPED-PROVIDER-RUNTIME-2026-09-09.md). apply-requests --once가 서버 고정 credentials_path로 현재 HTTPS 권한 검증기를 구성한다. 원장/claim 전 로컬 설정 검사, FIFO/디렉터리/크기 초과 CA 차단. 최종 전체1,335통과/2skip/303.28초·Ruff/정적검사, 실제 CLI 정상proved·실행 전 철회/로그인 만료 활성 세대 없음. 공개 MCP 쓰기·운영 자격증명/설정·실제 A→B 공유와 전체 인수는 남는다.

**2026-09-09 HTTPS 현재 권한→SB 수락·실행 연결:** [실제 TLS/게이트웨이/별도 Python4시나리오](SCOPED-PROVIDER-HTTPS-2026-09-09.md). 비공개 자격증명·인증서 검사·크기/20초 제한을 갖춘 HTTPS 호출을 기존 판정 소비와 연결했다. 정상proved/수락 중 철회 원장 없음/실행 전 철회·세션 만료 활성 세대 없음, attempt1/FK0. Python76통과·정적검사, J HTTP1통과·emit/lint. 운영 자격증명/실행 설정·공개 쓰기·실제 A→B 공유 및 전체 인수는 남는다.

**2026-09-09 현재 인증 세션 기반 검증 HTTP 연결:** [실제 로그인/CSRF·원래 세션·현재 정책 검증](SCOPED-PROVIDER-LIVE-SESSION-2026-09-09.md). JARVIS ddf6ff9가 명시적 서버 설정 시 검증 전용 endpoint를 제공한다. 실제 테스트 HTTP에서 정상200/새 로그인 세션403/정책 철회403/만료401, DB 변경0·세션 연장 없음. 고유72개 통과·최종 HTTP1개 재검사·격리 emit/lint. 세션 복사 파일을 운영 인증으로 사용하는 구성은 보류한다. 운영 설정·SB 호출·공개 쓰기·실제 A→B 공유 등 전체 인수는 남는다.

**2026-09-09 실제 로컬 검증 전송 구현:** [제한된 전용 파이프·프로세스 정리·65개 검사](SCOPED-PROVIDER-PROCESS-2026-09-09.md). 서버 지정 프로그램을 매 호출 새 프로세스로 실행하고 canonical 요청/응답·32KiB/4KiB·20초 제한을 적용한다. 실제 JARVIS/Python 수락·실행에 연결해 정상/철회 차단 및 attempt1/FK0 확인, 관련65통과·Ruff/정적검사 통과. 운영 세션 공급·공개 scoped 쓰기·실제 A→B 공유 및 전체 운영 인수는 남는다.

**2026-09-09 검증 채널 소비·밀리초 경계 수정:** [정상 응답 오거절 재현·공통 연결부·45개 검사](SCOPED-PROVIDER-CHANNEL-2026-09-09.md). 신뢰 채널의 매 호출 전후 시계와 원래 요청을 검사하는 연결부를 수락/실행에 연결했다. 응답 중 판정 만료 차단, 실제 독립 Node 정상/철회 인수 통과·Ruff/정적검사 통과. 같은 밀리초의 응답 재사용은 시각만으로 검출할 수 없어 실제 인증 채널의 호출별 응답 결합이 필수다. 공개 쓰기·실제 A→B 공유 및 전체 운영 인수는 남는다.

**2026-09-09 서버 인증 세션·현재 정책 검증 조합:** [구현·실제 프로세스·공개 연동 잔여 과제](SCOPED-PROVIDER-PRODUCTION-2026-09-09.md). JARVIS 서버 소유 세션과 현재 파일 정책을 기존 dispatch 검증기에 연결하고 SB에서 요청·범위·fence·시각에 결합된 판정을 엄격히 검사한다. SB 전체1,275통과/2skip, 최종 관련25통과·Ruff·새 모듈 정적검사, J 관련11통과·emit/lint. 실제 내부 프로세스 정상 저장과 수락 중/실행 전 철회 차단을 확인했다. 인증 세션은 fixture이며 공개 scoped 쓰기 transport와 실제 A 저장→B 새 세션 회수 등 M1–M14 운영 인수는 남는다.

**2026-09-09 scoped 원장 inventory·삭제 재구성 수정:** [목록 누락/후보 단독 FK 오류 재현·실제 fresh DB](SCOPED-LEDGER-COMPACTION-2026-09-09.md). scoped3개 원장을 기존 surface에 포함하고 종속 삭제/후보 copy filter를 보완했다. 관련13통과·emit/lint, 실제 MCP 완료 원장의 새 DB 대상0/원본1·FK0·trigger/control 보존. 원문·spool·백업 전체 삭제/복원 및 운영 인수는 남는다.

**2026-09-09 scoped 저장·원작업 원자적 완료 연결:** [현재 권한/lease·영수증·실제 commit 후 종료 복구](SCOPED-ATOMIC-SETTLEMENT-2026-09-09.md). outbox/candidate settled와 control completed를 한 트랜잭션에 연결했다. 관련62통과·최종5재검사(중복)·emit/lint·패키징. 실제 MCP 완료 후 exit73/독립 replay에서 provider 호출0, settlement1/attempt1/FK0. 공개 쓰기·실제 에이전트 운영·보존/삭제/복원 및 전체 인수는 남는다.

**2026-09-09 원래 전송 권한·현재 철회 대조:** [만료와 철회 분리·uncertain 복구·실제 프로세스](SCOPED-SETTLEMENT-AUTHORITY-2026-09-09.md). 원래 승인/서명·source·범위 검토를 당시 시점에서 대조하며 현재 철회/suppression은 거절한다. 관련48통과·emit/lint, 실제 만료 후 uncertain 검증/현재 철회 거절. 새 쓰기 권한 발행이나 자동 최종 완료는 하지 않는다.

**2026-09-09 재시작 후 scoped 관찰 증거 재구성:** [원래 수락/event/proof/범위 대조·독립 reader](SCOPED-DURABLE-PROOF-READER-2026-09-09.md). 만료된 읽기 권한을 재사용하지 않고 과거 관찰의 일관성을 검사한다. 신규12+관련46=58통과·격리 emit/lint, 실제 만료 후 별도 프로세스 복원/다른 provider 거절. 최종 settlement/control 및 운영 인수는 남는다.

**2026-09-09 scoped 완료 관찰 영구 기록:** [원래 attempt 결합·권한/lease rollback·실제 MCP](SCOPED-DURABLE-OBSERVATION-2026-09-09.md). migration079와 현재 읽기 검사 callback을 연결해 수락+관찰을 원자적으로 기록한다. 총55개 통과·격리 emit/lint·migration 패키징, 실제 관찰1/attempt1/수락event1/replay. 자동 최종 완료 및 운영 인수는 미완료다.

**2026-09-09 취소 후 완료 관찰 반환 수정:** [회귀 재현·실제 MCP 응답 직후 취소](SCOPED-COMPLETION-CANCELLATION-2026-09-09.md). 신규5개 실패를 재현하고 공통 read 및 완료 반환 경계에 취소 검사를 추가했다. 관련25개 통과·타입/lint, 실제 응답0/1/2/3 경계 모두 거절·정상 재조회 및 기존 복구 통과. 원작업 철회와 영구 완료 기록의 연결은 남는다.

**2026-09-09 scoped 재조정 단일 worker·원래 요청 복원:** [구현·경합·실제 MCP 복구](SCOPED-RECONCILIATION-LEASE-2026-09-09.md). 쓰기 만료 후 원래 요청을 복원하고 재조정 fence만 증가시킨다. 관련33통과/27.52초·격리 emit/lint, 독립7프로세스 경합 승자1·stale worker 거절·attempt1, MCP 수락 기록 직후 종료에도 lease 보존. 영구 완료 증거·원자적 최종 완료·운영 쓰기·실제 에이전트 인수는 남는다.

**2026-09-09 완료 상태·현재 artifact 통합 관찰:** [중간 변경 거절·실제 MCP 재시작/철회](SCOPED-COMPLETION-OBSERVATION-2026-09-09.md). 상태→기억→상태를 묶고 현재 세대/출처/분류·세션·세 호출 권한을 최종 재검사한다. 만료 단축도 반영한다. J 관련67통과/25.81초·격리 emit/lint, 실제 통합 관찰·수락 기록 후 exit73/중복 없음. legacy 완료 경로 직접 재사용은 보류하며 scoped 원장 증거/원자 완료·공개 쓰기·전체 운영 인수는 남는다.

**2026-09-09 수락 응답 유실→MCP 복구:** [원래 수락 회수·commit 직후 종료·단일 기록](SCOPED-ACK-RECOVERY-2026-09-09.md). read v5에서 로컬 acceptance 없이 원래 요청으로 수락을 회수하고 기존 attempt에 기록한다. 실제 MCP 재시작/양측 철회·기록 후 exit73·새 프로세스 replay에서 attempt1/event1/재전송0. SB 전체1,260통과/2skip/242.39초, J 확대78/최종20통과(중복)·타입/lint·패키징. 초기 세대 이전·공개 쓰기·자동 최종 완료/운영 인수는 남는다.

**2026-09-09 scoped MCP read v4 상태 조회 연결:** [고정 계약·실제 자비스/MCP 재시작·정책 철회](SCOPED-STATUS-MCP-V4-2026-09-09.md). 새 프로필에서 원래 요청에 결합된 서명으로 완료 상태/proof/receipt를 조회한다. 기존 v1/v2/v3·기본 v2 유지. SB 전체1,255통과/2skip/223.60초, J 확대72/최종37통과(중복)·타입/lint·격리 패키징, 실제 v2/v3/v4 인수 통과. 수락 응답 자체 유실·최초 활성 세대 이전·공개 쓰기·자동 완료/운영 인수는 남는다.

**2026-09-09 scoped 과거 요청 상태 조회:** [쓰기 만료 후 완료 증명·권한 철회 인수](SCOPED-REQUEST-STATUS-2026-09-09.md). 현재 읽기 scope를 전후 검사하고 원래 요청/수락/원장 proof를 대조한다. receipt 파일 없이도 완료 영수증을 원장에서 재구성한다. 실제 별도 reader에서 쓰기 만료 후 조회·읽기 철회 거절·JARVIS proof_consistent 확인. 전체 1,252통과/2skip/212.70초·Ruff·새 모듈 정적검사 통과. 운영 인증 공개 status와 현재 artifact를 결합한 자동 완료는 후속 범위다.

**2026-09-09 전송 후 현재 권한→provider 연결:** [상세 수정·검증·남은 우선순위](SCOPED-PROVIDER-AUTHORITY-2026-09-09.md). 기존 원장/원본/소비된 범위 검토와 현재 파일 정책으로 전송 시도를 재검증한다. J 관련 52통과, SB 관련 21통과·전체 Ruff, 격리 emit/lint 통과. 실제 Python 수락·실행에서 정상 proved, 수락 도중 철회는 원장 수락 없음, 실행 전 철회는 활성 세대 없음. 인증 세션은 fixture이며 공개 v4 전송·최종 완료 소비·운영 공통 기억 인수는 남는다.

**2026-09-09 scoped read v3 정확한 접근 분류 연결:** [현재 분류 대조·실제 MCP/기존 v2 인수](SCOPED-READ-V3-ACCESS-2026-09-09.md). 같은 pinned generation에서 승인된 페이지의 전체 source 분류를 반환하고, 자비스가 원래 요청의 단일 출처·owner/projects/policy와 정확히 대조한다. 새 결과 remembered_artifact_observed, v1/v2 계약·기본 v2 유지. SB 전체1,241통과/2skip/224.67초, J 관련74통과/18.16초·타입/lint·격리 패키징. 실제 production 구성→MCP 재시작/다중 프로젝트/양측 정책 철회 검증. durable proof 소비·공개 v4 dispatch·자동 완료·운영 인수는 남는다.

**2026-09-09 자비스 기억 관찰 연결·v4 MCP 읽기 수정:** [실제 MCP 재시작/정책 철회 검증](REMEMBERED-ARTIFACT-MCP-2026-09-09.md). JARVIS readRememberedArtifact가 수락된 요청의 문장·출처를 기존 인증된 read v2로 대조한다. 실제 v4 저장 후 REQUEST_SCHEMA_UNSUPPORTED 읽기 실패를 발견해, 업그레이드/수락/claim 없이 기존 schema를 인식하는 유지보수 모드를 scoped 읽기에 연결했다. SB 전체1,237통과/2skip/215.74초, J 관련53통과/9.62초·타입/lint·격리emit. 재시작 후4레코드 일치, 다중 프로젝트 권한 포함 조회, provider/issuer 정책 철회 거절. 정확한 분류 증거/공개 v4 전송/자동 완료/운영 인수는 남는다.

**2026-09-09 후속 세대 artifact 대조·분류 계승:** [상세 분석·전체1,234통과·독립reader4](SCOPED-ARTIFACT-VERIFICATION-2026-09-09.md). 직접 GenerationStore.build 경로의 접근 분류 유실을 재현하고, 바이트가 같은 현재 페이지의 검증된 분류만 계승하도록 수정했다. 일반 runtime은 기존 ledger 복사 단계가 있어 재현 범위를 구분한다. 실제 문장/출처/민감도/분류 대조 및 후속 세대 읽기 구현, 전체1,234통과/2skip/223.33초·Ruff·새 모듈 정적검사 통과. 공개 전송·현재 정책/삭제 fence 연결·자비스 자동 완료·전체 M1–M14 운영 인수는 남는다.

**2026-09-09 접근 분류 generation identity 수정:** [분류 결합·교체 거부·전체1,222통과](SCOPED-GENERATION-IDENTITY-FIX-2026-09-09.md). 프로젝트/owner/policy 차이가 ID에 반영되고 동일 분류는 재현된다. FIFO 회귀 수정 후 전체1,222통과/2skip/204.85초·Ruff·새 모듈 정적검사 통과. 독립 scope reader4 및 JARVIS/Python8프로세스 인수. 옛 미결합 분류 세대는 거부하며 운영 재생성/reader 전환·자동 완료/전체 목표는 남는다.

**2026-09-09 JARVIS `9be13b1` proof 대조·새 P0 발견:** [26검사·독립8프로세스 proof/세대 대조](SCOPED-PROOF-VALIDATION-2026-09-09.md). 별도 [접근 분류 identity 감사](SCOPED-GENERATION-IDENTITY-AUDIT-2026-09-09.md)에서 project:a/b가 같은 generation ID/ledger digest를 생성함을 독립 읽기4건으로 재현. 접근 차단은 각각 정상이며 세대 식별자 결합 결손이다. `proof_consistent`만 반환하고 자동 settled/control completed는 보류. M2/M3/M7/M12 선행 P0 수정·전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `7c9d9b6` v4 수락 소비:** [provider 수락 해시·원자적 기록·응답 유실 복구](SCOPED-OUTBOX-RESULT-2026-09-09.md). 관련16/최종3통과(중복), 타입/lint/격리emit. Python3/Node3 실제 프로세스에서 내부 provider proved·자비스 수락 event1/reconciling·commit 후 exit73 복구. fixture authority이며 공개 전송/완료 proof 소비/운영 인수는 남는다.

**2026-09-09 JARVIS `2d7aa6b` scoped worker lease·단일 시도·복구:** [시도 commit·응답 유실·불확실 결과 복구](SCOPED-OUTBOX-WORKER-2026-09-09.md). 정책 만료 경계 회귀1실패→수정, 확대50/복구13통과(중복), 타입/lint/격리emit. 독립13프로세스에서 fence 회수·옛 worker 거부·attempt1·reconciling 후 재claim0. provider 호출0이며 전송/공개 계약/영수증/운영 인수는 남는다.

**2026-09-09 JARVIS `edd850f` 등록 요청 복원·후보 무결성 수정:** [현재 범위/원본 재검사·독립 reader 인수](SCOPED-OUTBOX-READER-2026-09-09.md). queued 상태 누락·최초 분류 해시 불일치 재현 후 수정. 확대64통과·최종18통과(중복), 타입/lint/격리emit, 독립4프로세스에서 본문51bytes 일치·파일 정책/원본 철회 거부. worker lease/전송·공개 계약/영수증·운영 연결은 남는다.

**2026-09-09 JARVIS `2c890d4` 범위 검토 단일 사용·등록:** [원자적 outbox 등록·commit 전후 종료 검증](SCOPED-OUTBOX-REGISTRATION-2026-09-09.md). 확대59통과·최종 관련25통과(중복 포함), 타입/lint/격리emit, 최종 독립6프로세스에서 0/0→1/1 또는 1/1 보존·만료 후 등록 응답 재조회. provider 호출0이며 worker/공개 계약/운영 권한 연결은 남는다. [인계 추가 분석과 우선 작업](HANDOFF-ADDITIONAL-ANALYSIS-2026-09-09.md)을 갱신했다.

**2026-09-09 JARVIS `a4ec505` outbox 프로필 분리:** [migration077·legacy worker 경계·실제76→77](OUTBOX-PROFILE-MIGRATION-2026-09-09.md). 확대71통과·타입/lint/격리emit, 실제 queued1/기존 열/FK 보존. scoped 승인 소비·등록·worker 활성화·운영 인수는 남는다.

**2026-09-09 JARVIS `53c67b1` 최종 읽기 뒤 철회 수정:** [회귀1실패→관련23통과·실제 정책 파일 철회](SCOPED-PUBLICATION-COMPOSITION-2026-09-09.md). 타입/lint/격리emit, 독립4프로세스에서 read 직후 정책 철회 시 prepared 반환 거부. 승인 소비/outbox/provider·전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `862913e` 준비→발행 조합:** [현재 권한 재검사·별도 프로세스 재시도](SCOPED-PUBLICATION-COMPOSITION-2026-09-09.md). 관련20통과·타입/lint/격리emit, 실제 CLI/서명 검토/private 정책의 독립3프로세스 인수. prepared/권한false이며 승인 소비/outbox·운영 연결은 남는다.

**2026-09-09 JARVIS `65f1e15` 발행 중단 복구:** [실제 hardlink 직후 종료·새 프로세스 재시도](SCOPED-SPOOL-CRASH-RECOVERY-2026-09-09.md). 관련19통과·타입/lint/격리emit, 전후6프로세스에서 link2 거부→동일 bytes/inode/link1 복구. live/불명 link 거부 유지. 단독 임시 파일·삭제 수명·승인 소비/outbox/운영 연결은 남는다.

**2026-09-09 JARVIS `a158052` v4 private 자료 저장:** [제한 reader·재발행·독립 프로세스 인수](SCOPED-WRITE-SPOOL-2026-09-09.md). 관련36통과·타입/lint/격리emit, 실제 publish exit73→새 reader/동일 inode 재사용·FIFO 거부. 승인 소비/outbox 연결·orphan/삭제 수명·운영 권한은 남는다.

**2026-09-09 JARVIS `9bc5976` v4 자료 검증:** [생성기 연결·Node/Python codec 대조](SCOPED-CODEC-PARITY-2026-09-09.md). J18/SB29통과·타입/lint/격리emit, 별도 프로세스13건 판정·정상 bytes 일치. 승인 단일 소비·outbox 확정·공개 계약과 실제 운영 권한 연결은 남는다.

**2026-09-09 A1 복구 수정:** [활성화 직후 중단·만료·철회 복구](SCOPED-RESUME-FIX-2026-09-09.md). 수정 전 회귀2실패→관련46통과·전체1,212통과/2skip/221.83초·Ruff/변경 실행기 정적검사 통과. 이전 실패 provider를 새 프로세스로 같은 세대 proved/새 세대0/idle 복구하고 독립 reader 범위 검증. 실제 권한·공개 계약·승인 소비 및 전체 운영 목표는 유지한다.

**2026-09-09 인계 최신 재대조:** [OSS 대조·현재 구현·우선 작업 A1~A10](HANDOFF-ADDITIONAL-ANALYSIS-2026-09-09.md). M2 내부 v4 구현 상태와 전체 검사 기록 갱신. 새 P0: 활성 포인터 저장 직후 종료→만료 후 재개 두 번 모두 reconciling/proof 없음 재현(미수정). 관련42통과/7.59초는 이 중단 결함을 포괄하지 않는다.

**2026-09-09 내부 v4 실행:** [수락→provider proved→독립 재조회](SCOPED-REQUEST-EXECUTION-2026-09-09.md). 실제 프로세스7개·records4/4·다른 프로젝트 거부·재시도/idle. 전체1,208통과/2skip/217.08초·전체Ruff. fixture authority이며 실제 검증기·자비스 승인 소비·MCP/운영 연결은 남는다.

**2026-09-09 v4 내부 수락 조합:** [발행→원장 확정·응답 유실 복구](SCOPED-REQUEST-ACCEPTANCE-2026-09-09.md). 관련45통과·실제 프로세스4개: file crash row0→1, commit crash row1→1/replay. fixture authority 검증이며 실제 권한·승인 소비·MCP·실행·영수증 연결은 남는다.

**2026-09-09 v4 파일 발행:** [기존 publisher 재사용·강제 종료 복구](SCOPED-REQUEST-PUBLICATION-2026-09-09.md). 관련33통과·최종 기존쓰기/신규30통과(중복 포함), 실제 프로세스4개에서 두 crash 지점의 bytes/시각 복구. 수락 원장·승인 소비·실행·영수증 연결은 남는다.

**2026-09-09 scoped 원장 identity:** [명시적 v4 원장·재개·중복 방지](SCOPED-REQUEST-JOURNAL-2026-09-09.md). 관련29통과·독립 프로세스2개 신규→replay/범위 변경 시 dump 불변. metadata 단계이며 provider 수락·실행·승인 소비·영수증·운영 연결은 남는다.

**2026-09-09 v4 원장 전환:** [명시적 schema 전환·독립 프로세스 인수](SCOPED-REQUEST-SCHEMA-2026-09-09.md). 관련26통과·실제 임시 원장17테이블/53의존객체/pending1 보존·FK오류0. 수락/실행 연결 전 자동 초기화 활성화는 보류한다. 전체 목표는 유지한다.

**2026-09-09 scoped v4 데이터:** [provider·원본·범위 요청 codec](SCOPED-WRITE-REQUEST-V4-2026-09-09.md). J13/SB33통과·실제 생성→독립 검증→내부 봉인/reader3 인수. 기존 v3 parser는 v4 거부. 공개 계약·수락·승인 소비·완료 영수증은 남는다.

**2026-09-09 JARVIS `fc40358`:** [기등록 후보 scoped 충돌 구분](SCOPED-DISPATCH-CONFLICT-2026-09-09.md). 기존 포괄 입력 오류를 재현하고 구체적 충돌 오류로 구분. 관련21통과·격리 API/DB 인수에서 기존 요청·승인 보존/provider0. scoped 요청 계약·단일 소비·영수증 전체 연결은 남는다.

**2026-09-09 JARVIS `9ab8293`:** [명시적 쓰기 정책→scoped 준비](SCOPED-WRITE-POLICY-2026-09-09.md). 기존 v1/v2 읽기 유지, v3 쓰기 명시·현재 정책/원본 재검사. 관련16통과·실제 격리 CLI/정책/DB 검증. 요청 수락·단일 소비·영수증·운영 활성화는 남는다.

**2026-09-09 요청 기억 분류·봉인:** [scoped remember materialization](SCOPED-REMEMBER-MATERIALIZATION-2026-09-09.md). 내부 staging의 원본/페이지 불변 분류 결합, 독립 reader 3개에서 records4/4·불허 프로젝트 거부. 전체1,169통과/2skip/220.91초·전체Ruff. 공개 쓰기 요청/승인 소비/영수증 연결은 남는다.

**2026-09-09 scoped 준비값 검증:** [provider 측 codec·SourceAccess 연결](SCOPED-WRITE-PREPARATION-CODEC-2026-09-09.md). 관련23통과·실제 JARVIS CLI 생성값의 독립 Python 검증/본문51bytes·범위 일치. 실제 쓰기 수락·단일 소비·봉인 계보·완료 영수증은 남는다.

**2026-09-09 미사용 자동 후보 정리:** [원문 만료 정리·인계 추가 대조](AUTO-EXPIRY-CLEANUP-2026-09-09.md). 관련21통과·격리 CLI v3 원문1→0/분류·원장 불변/provider 호출0. 처리 중 자료 보존. scoped 쓰기·native 세션 삭제·전체 운영 인수는 남는다.

**2026-09-09 JARVIS `8ffc993`:** [발행 시각 역행 수정·누적 전체 검사](AUTO-PUBLICATION-CLOCK-2026-09-09.md). 관련19통과·실제 일반 owner 저장 재인수, SB 전체1,153통과/2skip/219.73초(`cc236a3`) 및 전체Ruff. 전체 운영 목표 완료로 확대하지 않는다.

**2026-09-09 실제 저장 인수:** [자동 승인 후보의 일반 owner 저장 전체 연결](AUTO-CANDIDATE-PROVIDER-2026-09-09.md). 실제 CLI→MCP→provider proved→자비스 완료→별도 client records4, 중복/정리 확인. scoped 쓰기 및 M2 전체 운영 조건 완료로 확대하지 않는다.

**2026-09-09 JARVIS `aa825f0`:** [실제 CLI 자동 발행 연결](AUTO-CANDIDATE-PUBLICATION-2026-09-09.md). 이전 auto-approved 후보 발행 결손을 구현, 수동13/최종7통과·실제 v3 CLI→spool→범위 준비 검증. M2 scoped 요청/단일 소비/provider 처리/영수증은 남는다.

**2026-09-09 v3 인수:** [v3 다중 행 본문·철회 검증](SCOPED-DISPATCH-PREPARATION-2026-09-09.md). 관련4통과·실제 v3 spool 복구. fixture 발행이며 CLI auto-approved 후보의 spool 생성까지 입증한 것은 아니다. M2 자동 발행/요청/승인 소비/완료 영수증은 남는다.

**2026-09-09 dispatch 연결:** [현재 원본 권한과 private spool 기반 scoped 준비](SCOPED-DISPATCH-PREPARATION-2026-09-09.md). J3통과·실제 v1 spool/DB 인수, scope review 유효 상태에서도 원본 검증 철회 시 준비 거부. M2 실제 저장/영수증·전 버전 조합 인수는 남는다.

**2026-09-09 후보 본문 결합:** [범위 검토→persisted candidate 본문 준비](SCOPED-WRITE-PAYLOAD-2026-09-09.md). J2통과·실제 API 본문 교체 거부·Python 독립 digest 일치. 준비값은 쓰기 허가가 아니며 M2 저장 요청/소비/영수증 전체 연결은 남는다.

**2026-09-09 JARVIS `0e6923b`:** [scoped 쓰기 식별자의 양쪽 구현·실측 일치](SCOPED-WRITE-IDENTITY-2026-09-09.md). J2/SB9통과·재승인 중복 방지 키 유지·프로젝트 변경 시 분리. 아직 요청 수락이나 쓰기 권한이 아니며 M2의 단일 소비·저장·영수증 연결은 남는다.

**2026-09-09 JARVIS `5c8931b`:** [일반 실행기의 범위 검토 영수증 소비 회귀 수정](SCOPED-WRITE-REVIEW-DESIGN-2026-09-09.md). 큐 선택·직접 claim 차단, 관련13통과·독립 프로세스7개 실제 인수. 검토 승인을 보존하며 scoped outbox 단일 소비 연결은 남는다.

**2026-09-09 JARVIS `303f0d1`:** [범위 제안→기존 서명 검토](SCOPED-WRITE-REVIEW-DESIGN-2026-09-09.md). 새 비실행 action과 현재 검토 조회, 관련18통과 및 독립 프로세스6개 실제 DB/서명 인수. 후보·범위가 다른 검토 재사용과 철회 거부. M2 scoped 쓰기·단일 소비·영수증·새 agent 재조회는 남는다.

**2026-09-09 JARVIS `be2c012`:** [범위 제안 현재 상태 재검증](CANDIDATE-SCOPE-REVALIDATION-2026-09-09.md). 집중2통과·독립 프로세스3개에서 정상 제안 재사용/변경·격리 거부, DB 행 불변. 실제 승인·scoped 저장 전체 인수는 남는다.

**2026-09-09 인계 재대조:** [추가 분석과 우선 구현 목록](HANDOFF-ADDITIONAL-ANALYSIS-2026-09-09.md). 기존 HTTP/CLI·영속 제출 검증을 본문 상태표에 반영했다. scoped 쓰기의 후보 범위 제안과 실제 승인·저장 완료를 구분한다.

**2026-09-09 JARVIS `0825e0d` / SB `6831147`:** [scoped 쓰기 계약 결손·지원 기능 API](SCOPED-WRITE-CONTRACT-GAP-2026-09-09.md). 인증 capabilities에 문맥만 지원/쓰기false/준비 미검사 명시, 관련45통과·실제 HTTP 쓰기404·proxy 미전달. 승인된 프로젝트 분류→쓰기 요청→봉인 계보→영수증 확장 없이 scoped 쓰기 개방은 보류한다. 전체 쓰기 완성 목표는 유지한다.

**2026-09-09 SB `b5c192a`:** [서로 다른 agent의 실제 공유·프로젝트 제한](AGENT-POLICY-LOGIN-2026-09-09.md). 두 HTTP gateway agent가 같은 정본 records2를 동일하게 회수, peer만 프로젝트 제한 후 peer0/original2 확인. 실제 Codex/Claude 실행·쓰기/영수증/주입 및 전체 운영 인수는 남는다.

**2026-09-09 JARVIS `d020bc4` / SB `e95fa8f`:** [에이전트 정책·새 로그인 기억 사용](AGENT-POLICY-LOGIN-2026-09-09.md). 선택적 정책v2/issuer session 모드, J8·SB23통과 및 실제 서로 다른 로그인2개에서 정책 파일 수정 없이 records2 회수·agent 철회403. 기존 고정 session/v1 유지. 운영·쓰기/영수증/재사용 전체 인수는 남는다.

**2026-09-09 JARVIS `167eeca` / SB `6a03110`:** [phone CLI의 명시적 scoped 활성화](SCOPED-PHONE-HTTP-CONTEXT-2026-09-09.md). 10개 필수 옵션을 기존 시작 함수에 연결, 관련50통과·lint 수정 후9통과·타입/lint 및 CLI parser→실제 HTTP/MCP 인수. 운영 서비스 적용·세션 정책 배정·전체 목표는 남는다.

**2026-09-09 JARVIS `55bc647` / SB `cb637e7`:** [HTTP context 오류 분류·종료 중 세션 만료](SCOPED-PHONE-HTTP-CONTEXT-2026-09-09.md). 관련61통과·실제 MCP 정책403/입력400/자식 종료 중 만료401 및 쿠키 제거 확인. 운영 활성화·정책 배정·전체 인수는 남는다.

**2026-09-09 JARVIS `939a0d9` / SB 인수 `33f2a07`:** [인증 phone HTTP→scoped context 연결](SCOPED-PHONE-HTTP-CONTEXT-2026-09-09.md). 명시적 server 구성의 새 POST 경로, 관련46통과·실제 HTTP 쿠키→MCP records2/4,649bytes 및 신원 삽입/새 세션 무단 재사용/정책 철회 거부. standalone 설정·세션 정책 배정·운영 Tailnet 및 전체 인수는 남는다.

**2026-09-09 SB `c0105db`:** [scoped CLI 정리 중 인증 철회 실증](SCOPED-CLI-CONTEXT-2026-09-09.md). 실제 MCP 자식 exit에서 쿠키 철회→최종 문맥 반환 거부 확인. 기존 제품 검사가 통과해 제품 추가 수정 없이 인수 강화. 실제 호스트 로그인/HTTP 구성과 전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `e932f79` / SB 인수 `7c3fcae`:** [scoped CLI context 연결·누적 전체 검사](SCOPED-CLI-CONTEXT-2026-09-09.md). 호스트 인증 세션을 명시적으로 받는 기존 CLI execute 경로 추가, 관련27통과·실제 MCP records2/예산/쿠키 철회 거부. SB 전체1,142통과/2skip/216.57초. 독립 CLI 로그인·HTTP 세션 전달과 전체 운영 인수는 남는다.

**2026-09-09 JARVIS `de08adb` / SB 인수 `578bdc1`:** [연결 준비 후 인증·동시성 재검사](PHONE-MEMORY-BOOTSTRAP-2026-09-09.md). 만료 후 추가 조회 회귀 수정, 관련60통과·격리 HTTP 추가 기억 요청0회·동시 상한8개 확인. 실제 scoped 인증 연결과 전체 운영 인수는 남는다.

**2026-09-09 JARVIS `689114c` / SB 인수 `f32f032`:** [HTTP 기억 응답 중 세션 만료 수정](PHONE-MEMORY-HTTP-EXPIRY-2026-09-09.md). 만료 후 200 반환 회귀 재현→관련58통과, 격리 빌드 HTTP 정상200/만료401/재요청401 및 본문 차단 확인. 실제 Tailnet·scoped 인증 전달·전체 운영 인수는 남는다.

**2026-09-09 SB `a3da3b4`:** [인계 재대조·독립 프로세스 제출 검증](HANDOFF-RECONCILIATION-2026-09-09.md). 별도 Node/DB 연결/실제 MCP로 2 records 재조회 후 같은 native session/epoch 중복 제출 거부, 콜백 0회. 기존 철회·변조 검사와 lint 통과. 시험용 identity snapshot이며 실제 HTTP 인증 전달·모델 세션 재개·전체 운영 인수는 미완료다.

**2026-09-09 JARVIS `121d06b` / SB 인수 `57f88c1`:** [영속 제출 세션의 인증 범위 결합](SCOPED-DURABLE-DELIVERY-2026-09-09.md). 다른 인증 세션에서 새 reader/epoch로 native 세션을 재사용하던 회귀 수정, 관련35통과·격리emit/lint 및 실제 MCP→원장 HMAC/새 reader 중복 거부 확인. native 세션 관측·본문 삭제와 인증 진입점 등 전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `ded750c` / SB 인수 `5b07d53`:** [정책·인증 세션·기존 키·v2 전송·문맥 공급기 제품 구성](SCOPED-PRODUCTION-COMPOSITION-2026-09-09.md). 집중6통과·격리emit/lint 및 직접 소유/주입 전송기 실제 인수 통과. 키/정책 자동 생성 없이 필수 인증 문맥을 검사한다. CLI/HTTP 인증 전달·native 세션 및 전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `cec7943` / SB 인수 `158bd75`:** [빈 검색의 세대 metadata 유실 수정](SCOPED-EMPTY-GENERATION-2026-09-09.md). 다른 세대의 빈 결과가 empty 문맥으로 수락되는 회귀를 재현하고 실제 응답 세대를 후속 상태와 대조한다. 관련71통과·격리emit/lint·실제 빈 응답 대체 거부 및 기존 제출 인수 통과. 실제 인증 진입점·native 세션·전체 운영 목표는 유지한다.

**2026-09-09 JARVIS `6a9d1d8` / SB 인수 `fa0cc11`:** [scoped v2→기존 reference reader·실제 2 records/4,412 bytes 제출 검사](SCOPED-REFERENCE-DELIVERY-2026-09-09.md). 관련85통과·격리emit/lint통과. 기존 privacy/삭제/예산/중복 제출 검사를 유지하고 준비 후 범위 변경·쿠키 철회를 차단했다. 실제 CLI/HTTP 인증 진입점과 모델/native 세션 수명 및 전체 운영 조건은 남는다.

**2026-09-09 JARVIS `29c26f1` / SB `ab0776f`:** [scoped v2 상태 조회·목적 분리·실제 전후 세대 검사](SCOPED-GENERATION-STATUS-2026-09-09.md). v1 유지, v2 status/read/search 세 도구. 관련JARVIS102·SB23통과·실제 status→조회/검색→status 및 철회 거부, 계약6개 패키징 검증. 기존 context adapter 연결·HTTP 인증 경계 및 전체 잔여 목표는 유지한다.

**2026-09-09 JARVIS `eafe913`:** [세션 시각 역행/비정상 발급 수정·실제 재인수·누적 전체 검사](PHONE-SESSION-CLOCK-2026-09-09.md). 수정 전7실패→관련57통과·격리emit/lint·실제 MCP 재인수. 수정 직전 누적 SB 전체1,141통과/2skip/214.33초. scoped 상태 조회→기존 context 연결과 HTTP 인증 경계 및 전체 잔여 목표는 유지한다.

**2026-09-09 JARVIS `7ae0684` / SB 인수 `7a675d0`:** [기존 phone 쿠키 인증→기억 세션 공급자·실제 MCP 인수](PHONE-MEMORY-SESSION-SOURCE-2026-09-09.md). 관련50통과·격리emit/lint통과. 기존 세션 buffer 노출 수정, 쿠키 누락·만료 거부 및 응답 후 철회 차단 확인. HTTP 게이트웨이→백엔드의 인증 세션 전달·정책 배정·전체 운영 인수는 남으며 공통 CSRF의 agent 인증 재해석은 보류한다.

**2026-09-09 JARVIS `62af9e2` / SB 인수 `67a2e22`:** [issuer→전송→소비 클라이언트 및 반환 직전 철회 차단](SCOPED-CLIENT-DELIVERY-2026-09-09.md). 관련19통과·격리emit/lint통과. 실제 MCP 응답 직후 정책 파일에서 세션을 철회하면 결과 반환을 거부했다. 실제 앱 인증 세션·모델 context/보존 수명 및 M2~M14 인수는 남는다.

**2026-09-09 JARVIS `ff0aecc` / SB `687ecf6`:** [고정 scoped 계약→기존 supervised transport→실제 MCP→소비자·재시작 검증](SCOPED-SUPERVISED-TRANSPORT-2026-09-09.md). 전송 관련91통과·SB6통과, 격리 패키징 계약5개 확인. M1 전송 연결은 검증했으며 실제 인증 세션/제품 context 연결·M2~M14와 전체 운영 목표는 남는다. 일반 adapter의 프로필 일괄 전환은 보류한다.

기준일: 2026-09-09. [자비스 인계 원문](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md), [상세 구현 원장](IMPLEMENTATION-STATUS.md), [기존 전체 개선 목록](IMPROVEMENT-BACKLOG-2026-09-07.md)을 합친 현재 판단이다. 이전 기록의 미완료 항목은 아래 최신 완료 증거가 있는 범위에 한해 갱신한다.

**판정: 저장·검색 및 여러 연동 구간은 동작을 검증했다. 자비스와 여러 에이전트의 메인 기억 장소로 운영 인수할 조건은 아직 모두 충족하지 못했다.** 서비스 active나 MCP 목록만으로 정상 완료를 선언하지 않는다. 이번에는 운영 서비스 상태를 새로 관측하거나 배포·재시작하지 않았다.

## 1. 확정 방향과 OSS 대조

세컨드브레인은 개인·업무 기억 정본, 자비스는 작업 실행·결과 검증, dev-wiki/Git은 개발 결정·규칙의 원문이다. 네 OSS의 기능 설명은 인계서의 고정 커밋 조사에 근거하며 이번에 최신 upstream 재조사·설치·성능 측정을 수행한 것이 아니다.

| 흡수 대상 | 기존 구현 대조 | 적용 결정 | 남은 완료 증거 |
|---|---|---|---|
| LightRAG의 근거 검색·파생 인덱스 일관성 | lexical/hybrid, 봉인 세대, record 출처, 삭제 이력이 이미 존재 | 기존 검색 개선. 그래프 DB 도입은 후순위 | 실제 한글 질문 기준선, 근거 회수율·낡은 답·지연 비교; scoped hybrid에서 불허 원문 제외 |
| TencentDB-Agent-Memory의 공통 인터페이스·공유 범위 | MCP, 원본/페이지 분류, claim, 현재 정책 검사가 존재 | 단일 기억 저장소와 얇은 에이전트 연결부 유지 | 실제 인증 세션 연결과 읽기·쓰기·복구 전 표면의 동일 범위 적용 |
| code-brain의 작은 context pack·실패/결정 근거 | 자비스 context CLI, byte budget, record 검증이 존재 | 관련 기억만 예산 내 전달; 기존 작업 제어 재사용 | 실제 세션 전달·주입 영수증·중복 억제·만료/철회 후 재사용 금지 |
| memory-bank의 원문 계보·정정/대체·세션 중복 억제 | source/page/record 계보, 정정·삭제·취소 복구가 존재 | 기존 수명주기에 수집·주입 이력을 연결 | 실패 작업이 성공 기억으로 승격되지 않는 검증, 실제 클라이언트별 수집·주입 |

네 제품 전체 설치, 모델 Proxy, 별도 에이전트 기억 DB, 새 워커 오케스트레이터는 이번 구현 대상이 아니다. 이번 변경은 기존 코드와 설계의 확장이며 외부 OSS 코드 복사를 하지 않았다.

## 2. 수정 완료로 근거가 있는 주요 항목

| 문제 | 영향 | 수정·검증 근거 |
|---|---|---|
| 동일 adapter에 여러 root를 넣으면 첫 원본만 수집 | 공통 기억에 일부 프로젝트가 누락 | `db685e9`: 실제 3원본·독립 커서·재수집 불변 확인 |
| 없는 source ID를 요청해도 성공 또는 부분 성공 표시 | 사용자에게 잘못된 수집 완료 보고 | `5c8fcb2`: scan 전 전체 선택 검사, 누락 실패 및 기존 데이터 보존 |
| SQLite 파일 복사 백업의 WAL 누락 | 분류·원장이 복구에서 유실될 가능성 | `62b1609`: SQLite backup 사용, 분류 transaction 검증 |
| 페이지 인용만으로 범위를 판단하면 실제 컴파일 입력 누락 | 원래 허용 범위보다 넓은 공유 | `f16c142`, `62da782`: 입력·부모 요구 분류와 커밋 본문 해시 결합, 불완전 분류 거부 |
| 실행 중 철회·정책 변경을 오래된 연결이 반영하지 못함 | 철회 후 본문 반환 | `867d65b`: 조회 전후 정책/키/만료 검사; 실제 같은 연결에서 거부 |
| 범위 공급자가 Date를 변경하면 만료된 범위를 발급 | 만료 정책 우회 | JARVIS `90bf269`: 발급 시각 고정과 변경 거부 |
| 현재 키만 검사하고 proof 완료 시점의 유효 기간 누락 | 유효 기간 밖 완료 증거 수락 | JARVIS `f7663ca`: 현재와 완료 시각 양쪽 검사 |
| 제한 응답의 요청·세션·record 검증 연결 부족 | 다른 요청 응답 또는 변조 본문 소비 | SB `ec76b14`, JARVIS `8a697d0`: [이번 검증 보고서](SCOPED-RESPONSE-CONSUMER-2026-09-09.md) |

이 표의 수정 완료는 개별 결함의 완료다. 모든 전송 경로·모든 운영 데이터에 적용됐다는 의미가 아니다.

## 3. 우선순위별 구현 목록과 완료 조건

2026-09-10 재대조: 아래 상태 열은 현재 근거로 갱신했다. 구현 존재·격리 실측·운영 완료를 구분하며 M1–M14 범위를 축소하지 않는다. 최신 근거는 [설치 paired 인수](INSTALLED-PAIR-CURRENT-2026-09-10.md), [모델 비교](NATIVE-SECOND-MODEL-2026-09-10.md), [백업 복원 조회](RETAINED-BACKUP-READBACK-2026-09-10.md), [운영 lease](JARVIS-LEASE-OBSERVATION-2026-09-10.md), [검색 반례](STALE-HYBRID-COMPARISON-2026-09-10.md)를 따른다. 실사용 사례 입력은 사용자에게 요청했으며 운영 전환 보류와 독립적인 M11 scoped 검색 계측과 요청 단위 검증 개선을 수행했다. [최신 검색 개선](SCOPED-SEARCH-BATCH-2026-09-10.md)을 함께 참조한다.

P0는 메인 기억 장소 인수에 필요한 항목, P1은 사용 품질·운영 강화, P2는 측정 후 선택하는 고도화다.

| ID | 관점·우선순위 | 현재 부족한 점과 영향 | 구현 지점·개선 방법 | 완료 조건 |
|---|---|---|---|---|
| M1 | 연결 개선 P0 | 실제 HTTP/CLI→scoped MCP 및 설치 후보 paired 경로 검증; 운영은 이전 릴리스·키/서비스 전환 보류 | 구현된 인증 세션·정책 resolver·issuer·context 구성을 실제 운영 진입점에 적용하고 요청 취소/종료 정리를 검증 | 실제 앱 세션에서 허용 조회 성공·다른 프로젝트 거부, 구형 프로필 호환/거부 명확화 |
| M2 | 기능 완성 P0 | 공개 scoped MCP 쓰기→provider proved→자비스 settled/control completed→새 로그인 재조회 검증; 실제 사용자 업무 계보와 운영 인수는 남음 | 기존 쓰기·status·resolve·export·restore에 동일 범위 계약 적용 | 조회→검증된 작업 결과→저장→영수증→새 세션 회수까지 하나의 ID/계보로 입증 |
| M3 | 정책 개선 P0 | 조회 전후 정책 철회·만료·복원 뒤 client별 독립 철회 검증; 정책 rollback/기발급 claim 전체 수명 인수는 별도 | 최신 정책 revision·삭제 high-water의 단조성 및 소비 직전 유효성 검증 | 옛 설정/백업 복구·열린 연결·발급 후 철회 시 과거 범위로 읽지 못함 |
| M4 | 계보 개선 P0 | 합성 요청/완료/기억 연결 및 동일본문 candidate별 출처/범위 분리 검증; 실제 사용자 작업 원문의 운영 계보는 남음 | task→검증 결과→candidate→provider record 연결, 실패·철회 상태 전파 | 실패·미확정·대체된 작업은 성공 경험으로 회수되지 않음 |
| M5 | 세션 수명 개선 P0 | 복원 SIGKILL 임시 사본 회수·관리 backup 선택 삭제 검증; native session/compaction/log/WAL 전체 보존·삭제는 미완 | 기존 managed session·본문 inventory·삭제 관측에 연결 | 세션 재개·요약·원문 로그/WAL/백업에서 삭제 기억 재등장 차단 및 증거 |
| M6 | 동시성 수정 P0 | 쓰기 종료 복구·복원 SIGKILL 재시도 검증; 최근 운영 DB 관측 holder2서비스·관측불가18개·유효GJC lease1로 전환 보류 | 이미 활성화된 해당 요청의 결과 복구와 새 쓰기 권한을 분리하고, 기존 writer 배제·경로/inode 검사도 검증 | 독립 런타임·강제 종료·동일 경로 교체에서 단일 결과와 손상 없는 복구 |
| M7 | 접근 일관성 P0 | scoped 허용/거부·복원 분류 유지·독립 client 검증; 모든 프로필/벡터/운영 원문 경로 전체 지원은 미완 | 클라이언트 능력을 명시하고 scoped hybrid·원문/관계 확장도 같은 정책 사용 | 제목·snippet·score·원문·벡터 결과 어느 경로로도 불허 프로젝트 노출 없음 |
| M8 | 클라이언트 개선 P1 | native Claude Opus/Sonnet의 같은 provider 실제 MCP 조회 검증; 같은 client 제품이며 Codex/OMO 및 실제 버전별 자동 수집·주입 인수는 남음 | Codex·Claude 및 실제 사용하는 다른 클라이언트별 조회/쓰기/수집/주입 표와 형식 parser 검증 | 실제 버전별 새 세션 상호 회수, 중복·도구 실패·파서 오류 시나리오 통과 |
| M9 | 문맥 고도화 P1 | 문맥 예산·출처/freshness·중복 방지와 native 근거부족 보류 검사 존재; JARVIS 운영 세션/compaction 전체 연결은 미완 | 기존 제출 원장을 native session의 실제 전달·재개·삭제 관측과 연결하고 byte/지연/근거 기록 | 같은 세션 중복 주입 감소, 만료·철회 후 사용 금지, 빈 근거는 no_data |
| M10 | 검색 평가 P1 | 합성100질의 평가 및 최신/폐기3질의 실제 lexical/hybrid/native 비교 존재; 사용자 기반100–300 gold는 미확보 | 한글 개인/업무 질문과 정답 근거 고정, lexical 기준선부터 측정 | 근거 회수·오래된 결정·no_data 정확도 및 p50/p95 지연 비교 |
| M11 | 용량·갱신 개선 P1 | 허용 여부 후 limit 유지; 합성1,000페이지 최근각5회 전체허용p50 2.023초/허용1개0.317초·독립 writer 준비 중 pin 검색/새세대 회수 검증, 대규모 MCP/정정·운영 인수는 남음 | 요청 전후 전체 검증과 후보별 출처·권한 검사를 유지하고 더 큰 corpus/동시 갱신 비용 측정 | 대규모 corpus에서 메모리/지연·동시 조회·정정 직후 결과 확인 |
| M12 | 복구 개선 P1 | 실제 runtime tar·삭제→복원→재삭제/재복원, 관리형 사본 삭제/무관백업 복원 검증; 원장소실DR·운영RPO/RTO는 미완 | 최신 tombstone·범위 정책을 복원에 적용, 지원하지 않는 자료 형식 명시 | 백업 복원·재색인·재수집에서 삭제/철회 부활 없음; 측정 RPO/RTO |
| M13 | 운영·화면 개선 P1 | 실제 설치 CLI/paired API 및 콘솔 준비503→백업검증200→손상503 브라우저 인수; 운영 timer 새 옵션·GUI 정정/삭제 전체 수명은 남음 | 기존 화면에 원문·실패 이유·검색 준비·영수증·정정 상태 노출 | 실제 GUI에서 실패 복구와 기억 수명 확인, 배포 후 동일 인수 시나리오 |
| M14 | 관계 검색 고도화 P2 | 기준 대비 관계 확장의 효과 근거 없음; hybrid도 자연어회수 개선과 함께 무근거·폐기후보 증가 확인, 기본 활성화/그래프 도입 보류 | LightRAG식 선택 관계 확장·영향받는 파생 데이터 갱신을 제한 실험 | 고정 질문에서 효과 입증 시에만 채택; 비용·정정/삭제 일관성 유지 |

실행 순서는 M1→M2를 중심으로 M3/M4/M5/M6/M7의 필요한 선행 조건을 함께 닫고, M8~M13으로 실제 사용·운영 인수한다. M14로 핵심 연동 결손을 우회하지 않는다.

## 4. 동작 증거의 범위

- 최초 작성 시 실행: JARVIS 집중 17개, SB 집중 19개 통과. 격리된 실제 CLI→issuer→stdio→소비자에서 조회·검색 각 record 2개를 검증하고 새 프로세스 반복 및 변조 거부를 확인했다. 이후 검증은 상단 날짜·커밋별 기록을 따른다. 합성 원본·고정 시각·테스트 세션이다.
- 이전 기록: [실제 Codex·Claude 상호 회수](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md), [실제 모델 참고 기억 소비](MEMORY-REFERENCE-MODEL-ACCEPTANCE-2026-09-08.md), [정정 완료·독립 재조회](CANCELLATION-FOLLOWUP-SETTLED-ACCEPTANCE-2026-09-09.md). 이번에 이 세 인수를 다시 실행한 것은 아니다.
- 최신 전체 SB 검사는 `1f478d3`에 포함된 내부 v4 실행 변경 기준 1,208 passed/2 skipped(217.08초)라는 기존 기록이다. 이번 인계 재대조에서는 관련 42개를 재실행해 통과(7.59초)했다. optional embeddings extra와 JARVIS 전체 검사를 포함하지 않는다.
- 전송·서명·hash 검증은 기록의 식별과 허용 범위에 대한 증거다. 기억에 적힌 사실이나 작업 성공 자체를 자동 보증하지 않는다.

사용자가 요청한 최종 상태는 **실제 자비스의 검증된 작업 결과가 저장되고, 허용된 다른 에이전트의 새 세션에서 근거와 함께 재사용되며, 정정·철회·삭제·복구 후에도 같은 정책이 유지되는 것**이다. 위 M1~M7과 실제 사용·운영 검증이 남아 있으므로 전체 완성 표시는 유지하지 않는다.

2026-09-10 클라이언트 범위 재대조: [조회·쓰기·수집·자동주입·삭제 지원표와 실제 업무 인수 식별 정보](AGENT-SUPPORT-AND-ACCEPTANCE-GAPS-2026-09-10.md). 현재 소스와 과거 native/OMO 기록을 구분했고 관련 수집20통과. 실제 작업·공유 범위 사용자 입력 대기와 독립 개발을 구분한다.
