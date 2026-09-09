[실제 gzip 서명 복원 인수](COMPRESSED-SIGNED-RESTORE-2026-09-09.md) — 위치/복사/이동3사례 및 변경 실패 시 세대·staging 보존, 관련30개 통과.

[tar 복원 입력 식별 고정](RESTORE-TAR-FILE-IDENTITY-2026-09-09.md) — 링크·처리 중 변경3회귀 재현→관련28개 및 정적검사 통과.

[복원 원본 파일 식별 고정](RESTORE-SOURCE-FILE-IDENTITY-2026-09-09.md) — 같은크기 교체·symlink·FIFO 거부, 관련24개/FIFO후15개(중복) 및 정적검사 통과.

[관리형 복원 추출 예산](RESTORE-EXTRACTION-BUDGET-2026-09-09.md) — tar/디렉터리 항목·파일·합계 한도 사전 검사, 관련22개 및 정적검사 통과.

[복원 tar 경로 모호성 거부](RESTORE-ARCHIVE-PATH-VALIDATION-2026-09-09.md) — 중복/별칭 경로 및 파일·상위경로 충돌을 추출 전 거부, 정상 tar 포함16개 통과.

[실측 기반 복원 검사 예산 조정](RESTORE-SCAN-BUDGET-TUNING-2026-09-09.md) —1MiB 실제 파일 복원/정상 기억 보존,4MiB 탐지1.38~1.87초,8MiB초과 거부 유지. 대규모 전체 인수는 미완료.

[복원 수정 후 전체 회귀](POST-RESTORE-FULL-REGRESSION-2026-09-09.md) — 1cfeafb에서1491통과/2skip(282.63초), Ruff 통과. [대규모 복원 제한 실측](RESTORE-SCAN-CAPACITY-2026-09-09.md)은 별도 보류.

[관리형 복원 staging 보호](MANAGED-RESTORE-STAGING-2026-09-09.md) — 기존 요청 자료 삭제 재현→고유0700 staging; 성공/실패 보존 포함18개 통과.

[위치 변경·복제된 삭제 대상 복원 수정](RESTORE-RELOCATED-CONTENT-FIX-2026-09-09.md) — 서명 복원3사례, bounded 내용 검사 및 최종 잔존 거부 구현; 관련19개/후속31개(중복8) 통과.

[운영 인수 보류: 위치가 바뀐 삭제 대상 잔존](RESTORE-SHIFTED-CONTENT-HOLD-2026-09-09.md) — inventory 실제 파일 재현에서 대상 잔존인데 blocked_matches=0. 기존 복원 통과 결과를 전체 삭제 보장으로 확대하지 않음.

[복원 인용 끝 개행 경계 수정](RESTORE-TOMBSTONE-SPAN-PRESERVATION-2026-09-09.md) — LF/CRLF/여러 줄 인용의 다음 정상 줄 보존, 관련15개 통과.

[복원 삭제 구간 중복에 따른 정상 기억 훼손 수정](RESTORE-TOMBSTONE-SPAN-PRESERVATION-2026-09-09.md) — 수정 전 재현, 실제 파일 네 경우 및 관련12개 통과.

[최근 복원 수정 포함 설치본 인수](CURRENT-PAIR-RESTORE-ACCEPTANCE-2026-09-09.md) — SB0ff54e2/JARVIS195b1a7 연동4경로 및 실제 설치 CLI 백업1회·복원3회 통과.

[최신 자비스 설치 후보 연동](LATEST-JARVIS-INSTALLED-PAIR-2026-09-09.md) — JARVIS195b1a7 신규 빌드, 실제 TLS/MCP 4경로 통과, 후보 전후 일치.

[반복 복원 보관 경로 충돌 수정](RESTORE-EMPTY-DESTINATION-2026-09-09.md) — 같은 초의 연속 복원과 각각의 이전 기억 보존 검증, 관련 70개 테스트 통과.

[빈 복원 대상 실패 보존 검증](RESTORE-EMPTY-DESTINATION-2026-09-09.md) — 배치 실패 시 기존 디렉터리 보존, 관련 69개 테스트 통과.

> 2026-09-09 provider 정본 manifest: [실제 Git/캐시/두 준비 receipt 연결·독립 항목 검증](PROVIDER-CANONICAL-MANIFEST-2026-09-09.md). 두 manifest 바이트일치·payload18,455항목·sidecar/digest·실제 설치연동4경로 통과. 영구봉인/JARVIS 동등검증·운영/에이전트 인수는 남음.

> 2026-09-09 독립 캐시 인수: [관측 기반 snapshot17,396항목·별도 cache 오프라인 준비](INDEPENDENT-OFFLINE-CACHE-2026-09-09.md). 공유cache/IP참조0, snapshot hash 보존·실제 설치연동4경로·관련13개 통과. 현재 입력/호스트 범위이며 정본봉인·운영/에이전트 인수는 남음.

> 2026-09-09 오프라인 준비: [--offline·실제 자식 syscall 추적·캐시 부족 거부](OFFLINE-PREPARATION-2026-09-09.md). 기존캐시 준비/설치연동4경로 통과, 빈캐시 exit1/완료manifest0, 추적 IP호출0. 중간디렉터리는 남음. 독립캐시 digest·정본 봉인/운영 인수는 미완료.

> 2026-09-09 릴리스 준비 절차 식별: [v3 ID에 준비 도구3개 hash 결합](RELEASE-RECIPE-IDENTITY-2026-09-09.md). 관련20개·새 후보 도구바이트 대조·실제 연동4경로 통과. uv/OS 전체 공급망·정본 봉인·운영 인수는 남음.

> 2026-09-09 고정 경로 재현성: [두 준비18,456항목 차이0·RECORD182검증](FIXED-PATH-REPRODUCIBILITY-2026-09-09.md). 안정된wheel경로·hash bytecode·번들pip앱설치, 관련20개/실제연동4경로 통과. 같은 로컬 환경/최종경로 범위이며 호스트간·이동·정본봉인/운영 인수는 남음.

> 2026-09-09 런타임 식별 보강: [Python 입력 hash를 release ID에 결합](PYTHON-RUNTIME-IDENTITY-2026-09-09.md). 관련20개·실제2준비 입력ID일치·설치연동4경로 통과. 전체 설치물은5,395항목 차이로 재현성 미완료를 명시, 최종 봉인/운영 인수 유지.

> 2026-09-09 provider 런타임 내부 포함: [Python3.12 복사·내부 상대 링크 후보](BUNDLED-PYTHON-CANDIDATE-2026-09-09.md). 링크1,052개 외부/절대0, 내부 Python SSL/SQLite 실행·설치 연동4경로/MCP4프로파일 통과. 관련19개 및 후속중복5개 통과. provenance/재현성·정본 봉인·운영 인수는 남음.

> 2026-09-09 정본 manifest 결함 수정: [JARVIS195b1a7 루트 파일만 자기 제외](RELEASE-MANIFEST-EXCLUSION-2026-09-09.md). nested 해시 누락 재현→관련7개·lint/별도emit·실제 Node 변경/링크거부 통과. 실제 provenance·provider 외부 실행기 및 운영 봉인은 남음.

> 2026-09-09 최신 검증 기준: [SB997e814 전체1,469통과/2skip·동일 설치본 연동/브라우저 인수](CURRENT-VERIFIED-BASELINE-2026-09-09.md). 전체273.49초, Ruff·실제TLS4경로·MCP4프로파일·설치 웹 Chromium 통과, 종료 후 inventory 일치. 운영 및 전체 목표는 미완료.

> 2026-09-09 복구 대상 잠금: [대상별 외부 inode 잠금·별도 프로세스 거부](RESTORE-DESTINATION-LOCK-2026-09-09.md). 관련68개+복구/준비/백업45개 통과, rename/예외 해제·하드링크 거부 확인. 외부 작성자/중첩 대상/강제 종료 및 운영 인수는 남음.

> 2026-09-09 복구 임시 작업 보호: [PID 기반 기존 staging 삭제 제거](RESTORE-STAGING-OWNERSHIP-2026-09-09.md). 삭제 회귀 재현→고유0700 디렉터리 생성, 관련65개·Ruff 및 별도 실제 CLI37파일/기존 증거 보존 통과. 최종 대상 동시 복구/운영 인수는 남음.

> 2026-09-09 복구 실패 처리: [게시 rename 실패 시 기존 경로 복원](RESTORE-PUBLISH-RECOVERY-2026-09-09.md). 기존 경로 유실 재현→관련64개 통과, 복귀 실패/새 대상 보존·실제 별도 CLI37파일 복원 확인. 강제 종료/동시 복구 및 운영 인수는 남음.

> 2026-09-09 최신 설치본 첫 실행 인수: [SB5fcc28c/JARVISe6984ad·바이트코드 사전 생성](CURRENT-COLD-INSTALLED-PAIR-2026-09-09.md). 새 후보 MCP4프로파일·연동4경로, 전체32,150항목 및 Node 전후 변경0. 중간548캐시 변경 거부 원인 해결, 관련16개 통과. 운영 봉인/실사용 전체 인수는 남음.

> 2026-09-09 원본 진단 경로 수정: [수집 설정과 sources의 공통 경로 해석](SOURCE-DIAGNOSTIC-PATHS-2026-09-09.md). 상대/환경변수2회귀 실패→관련23개 통과, 실제 별도 CLI doctor/sources 경로·존재 일치, Ruff/정적 통과. 운영 및 에이전트 인수는 남음.

> 2026-09-09 CLI 설정 경로 수정: [read_config의 base_dir/source_path 보존](CLI-CONFIG-PATH-PRESERVATION-2026-09-09.md). 수정 전2회귀 실패→관련55개 통과, 별도 실제 CLI 원본 폴더 진단 pass, Ruff/정적0오류0경고. 운영·개별 진단 표면 전체 인수는 남음.

> 2026-09-09 전체 회귀 및 상태 세대 수정: [a87a73d 전체1,457통과/2skip·HTTP pin 무시 재현/수정](WEB-STATUS-PIN-2026-09-09.md). 수정 후 관련22개·Ruff·web 정적0오류0경고. 전체 수치는 수정 전 기준이며 운영 배포/전체 인수는 남음.

> 2026-09-09 웹 운영 가시성: [실패 원인·브리핑 재시도 보류 표시](WEB-FAILURE-VISIBILITY-2026-09-09.md). HTTP/ops21개·Ruff 통과, 실제 Chromium23건/생략3/가림/오류 표시·통신 실패 후 초기화 확인. 과거 실패 복구·운영 배포는 미완료.

> 2026-09-09 설치본 인수 보강: [후보 전체 내용·Node 전후 검사](CONTENT-BOUND-INTEGRATION-2026-09-09.md)를 연동 도구에 연결. 관련16개·실제 TLS/MCP4경로 통과, provider8,045/JARVIS19,588항목 전후 일치. 운영 봉인/실제 업무 인수는 남음.

> 2026-09-09 설치 후보 검사: [전체 파일·권한·링크 검증](RELEASE-CONTENTS-VERIFICATION-2026-09-09.md). 관련11개 통과, 실제 JARVIS 복사본19,588항목 변조 거부·복원 통과, SB 설치본8,045항목 통과. 운영 봉인/전환은 미완료.

> 2026-09-09 인계 통합 실행 목록: [현재 판정·OSS 대조·수정 완료 8개·잔여 14개](HANDOFF-CURRENT-ACTION-LIST-2026-09-09.md). 설치본 동작과 운영 인수를 구분하고 혼합 버전 전환·새 쓰기 이후 복구 조건을 명시했다.

> 2026-09-09 복구 검사 보강: [복원 DB 무결성·외래 키 검사](ROLLBACK-DATABASE-HEALTH-2026-09-09.md). 정상/깨진 참조 회귀 포함5개 통과, 실제 복원 사본 integrity ok/FK0. 혼합 버전 hold 유지.

> 2026-09-09 리허설 보강: [최신 후보 이전 및 이전 DB 스냅샷 복원](SNAPSHOT-ROLLBACK-REHEARSAL-2026-09-09.md). 58→81/기존212테이블 보존, 복원본 구버전 수용·원래 inventory 일치. 새 DB 구버전 수용 때문에 최종hold 유지, 운영 미변경.

> 2026-09-09 후보 의존성 검증: [런타임 전체161개 설치 경로](RUNTIME-DEPENDENCY-CLOSURE-2026-09-09.md)의 버전이 lock과 일치. npm ls 전체300참조·problems없음/exit0, 네트워크·운영 변경 없음.

> 2026-09-09 배포 후보 개선: [자비스 의존성 내부 복사](CONTAINED-JARVIS-CANDIDATE-2026-09-09.md). 외부 symlink0·내부32, native SQLite 및 설치본 연동4경로 통과. 파일 해시 인벤토리 기록, 운영 봉인/전환은 미완료.

> 2026-09-09 최신 후보 통합: [SB ebe227c + JARVIS e6984ad](CURRENT-INSTALLED-PAIR-2026-09-09.md). 고정 소스 신규 설치/emit, 설치본 연동4경로·실행 파일4프로파일 통과. 후속 전환 기준 후보이며 봉인 운영 배포는 미완료.

> 2026-09-09 전환 관측 수정: [검사 중 DB/sidecar inode 변경 탐지](DATABASE-IDENTITY-RACE-2026-09-09.md). 실제 파일 교체·삭제·WAL 생성 회귀 포함5개 통과. 변경은 exit2, 운영은 읽기 전용 관측만 수행.

> 2026-09-09 전환 진단 보강: [접근 불가 PID의 프로세스명/서비스 소속](DATABASE-UNREADABLE-DIAGNOSTICS-2026-09-09.md) 추가. 이름에 의한 제외 없이 불완전 exit2 유지, 실제 검사2개·Ruff 통과.

> 2026-09-09 전환 관측 보강: [DB 메모리 매핑 검사](DATABASE-MAPPING-AUDIT-2026-09-09.md). fd 닫힌 실제 mmap 누락 재현·수정, 2개 테스트 및 운영 읽기 전용 조사 완료. 일시 관측이며 전환 허가 아님.

> 2026-09-09 자비스 운영 준비 수정: [portfolio 입력60초 제한](PORTFOLIO-INPUT-DEADLINE-2026-09-09.md). 관련9개·emit/lint 및 실제 CLI 60,211ms timeout/exit2/DB 재개 통과. 열린 운영 구버전 프로세스는 미변경.

> 2026-09-09 운영 DB 보유 원인: [SSH portfolio ingest](SSH-PORTFOLIO-DB-HOLDER-2026-09-09.md) 확인. 구 릴리스 CLI·sshd 부모·stdin pipe, 현/구 readPortfolioStdin에 대기 시간 제한 없음. 입력 대기/자원 종료 개선 대상으로 확정, 프로세스 중지 미실행.

> 2026-09-09 운영 전환 증거: [DB 열린 핸들 조사](DATABASE-HANDLE-AUDIT-2026-09-09.md). 3프로세스/9핸들, 그중 로그인 세션1개로 명명된 서비스 목록만으로 부족함 확인. 접근 불가43 PID 때문에 exit2. 읽기 전용 도구·실제 프로세스 검사1개 추가, 운영 중지 없음.

> 2026-09-09 긍정 native 인수: [Claude 실제 근거 원문 답변](NATIVE-SUPPORTED-ANSWER-2026-09-09.md). supported/첫 결정 정확 일치, 무조건 abstain·오답 거부 테스트 포함4개 및 실제 연동4경로 통과. 단일 긍정 사례에 한정.

> 2026-09-09 검증기 수정: [native 응답 전체 형식 검사](NATIVE-ANSWER-VALIDATION-2026-09-09.md). JSON 바깥 모순 문장을 버리던 검사 누락 재현·수정. 3개 테스트·실제 응답 재생 통과, 의미적 품질 평가는 별도.

> 2026-09-09 실제 모델 후속: [JARVIS f0394b9 제외 카운트 범위 안내](NATIVE-OMISSION-SCOPE-2026-09-09.md). 새 빌드 실제 Claude1회에서 IP 미추정 및 카운트가 검색 완전성을 증명하지 않음 명시. 통합15개·별도 빌드·4경로 통과, 단일 사례에 한정.

> 2026-09-09 실제 native 답변 검사: [Claude 1회 근거 부족 응답](NATIVE-ABSTENTION-2026-09-09.md). IP 값 추정 없이 insufficient_evidence/null, 4경로 통과. 설명의 omission=0 완전성 추론은 미흡으로 기록, 전체 품질 합격 아님.

> 2026-09-09 실행물 인수: [JARVIS 근거 안내 별도 빌드](GUIDANCE-INSTALLED-ACCEPTANCE-2026-09-09.md). 실제 stdio 도구 목록 전달·새 빌드 연동4경로 통과. native 답변 준수·운영 배포는 별도 미완료.

> 2026-09-09 소비자 개선: [JARVIS 61b8a42 기억 도구 근거 안내](MEMORY-CONSUMER-EVIDENCE-GUIDANCE-2026-09-09.md). 후보/순위와 답변 가능성 구분·없는 사실 추정 금지·미정/충돌 보존 명시. 통합 15개 및 ESLint 통과. 실제 native 답변 품질·운영 반영은 미검증.

> 2026-09-09 품질 기준선: [답변 불가 CLI/MCP 실제 측정](ABSTENTION-CLI-MCP-BASELINE-2026-09-09.md). 합성4문항 positive recall@5=1이나 negative_empty_rate=0, 양쪽 동일. 작은 반례 데이터셋 추가, 측정 완료와 품질 합격 구분.

> 2026-09-09 검색 품질 반례: [실제 모델 20쌍 측정](SEMANTIC-ABSTENTION-COUNTEREXAMPLE-2026-09-09.md). 정답 일정 0.613보다 무관한 주소/날짜 0.651이 높음. 기본 임계값 일괄 상향 보류, 재현 스크립트 및 동일 재실행 증거 추가.

> 2026-09-09 실제 모델 재검증: [기존 별도 캐시를 사용한 smoke·정정/삭제/복원](CURRENT-REAL-EMBEDDING-2026-09-09.md) 통과. 기본 캐시는 없지만 명시적 HF_HOME에서 offline 실행 가능. 일정 삭제 후 비용 후보 반환은 근거 부족 품질 과제로 유지, 운영 미변경.

> 2026-09-09 선택 검사 보완: [임베딩 모듈 30개 통과](OPTIONAL-EMBEDDINGS-VERIFICATION-2026-09-09.md), 실제 모델 1개 skip. 현재 기본 캐시 모델 부재·resolve_encoder unavailable 확인. 다운로드/운영 변경 없음, 실제 모델 품질 인수와 구분.

> 2026-09-09 전체 회귀 갱신: [cf2be5a 검증](CURRENT-FULL-REGRESSION-2026-09-09.md). 1,435 passed/2 skipped, 263.15초, Ruff 통과. embeddings 파일 제외. 최근 삭제·inbox·동시성 변경 포함, 운영·실제 모델 최종 인수는 미완료.

> 2026-09-09 동시성 검증: [대기 기억 세대 보존](PENDING-INBOX-CONCURRENCY-2026-09-09.md). 실제 두 작성자·독자 잠금 테스트 보강, 기존/동시 추가 기억을 다음 세대에서도 본문 비교. 관련 5개 통과. 세대 관리 경로에 한정하며 레거시/외부 직접 쓰기 혼용은 별도 인수 전 보류.

> 2026-09-09 제품 수정: [대기 inbox 복사 안전성](PENDING-INBOX-SAFETY-2026-09-09.md). 하드링크 복제 결함 재현·수정, descriptor 기반 no-follow/nonblocking 읽기. 교체 경합 포함 11개 및 자비스 실제 통합 4경로 통과. 운영·전체 인수 미완료.

> 2026-09-09 설치 후보 검증: [e6866b0 최신 후보 자비스 연동](REINGRESS-INSTALLED-INTEGRATION-2026-09-09.md). 개발/설치본 각 4경로 및 실제 MCP 실행 파일 4프로파일 통과. 설치 소스 일치, 새 로그인·독립2클라이언트 회수 확인. 운영 활성화·native 모델 인수는 미완료.

> 2026-09-09 제품 수정: [삭제 차단 정보 원자 반영](REINGRESS-ATOMIC-PUBLISH-2026-09-09.md). 부분 커밋·실패 후 3개 잔류 재현, 요청 단위 SAVEPOINT 적용. 별도 프로세스 강제 종료·재개 포함 30개 통과, 기존 차단 보존·재실행 확인. 전체 운영 인수는 미완료.

> 2026-09-09 제품 수정: [대용량 삭제 재유입 검사](REINGRESS-SQL-BUDGET-2026-09-09.md)의 SQL 변수 초과 오류 수정. 관련 17개 통과, 기본 한도에서 32,776줄 허용/삭제 차단 검증. 인계 방향 재대조, 운영 전환·전체 인수는 미완료.

> 2026-09-09 OMO native 모델 검증: [Cursor CLI OAuth 재로그인 요구](OMO-NATIVE-MODEL-HOLD-2026-09-09.md)로 보류. 새 선택적 검증 helper 추가, 실제 모델 기억 도구 호출 성공 미검증. 기본 통합 4경로 회귀 통과. 인증 상태 변경 전 재시도하지 않음.

> 2026-09-09 OMO 후속: [실제 CLI 기억 도구 등록](OMO-CLI-MEMORY-STARTUP-2026-09-09.md) 확인. jarvis_memory connected/1도구, 추가 _ast_grep 비활성화. 모델 요청 0회·사용자 설정 미변경. 자동 선택/수집/주입은 미완료.

> 2026-09-09 클라이언트 대조: [설치 OMO MCP 엔진](OMO-MCP-ENGINE-ACCEPTANCE-2026-09-09.md)으로 JARVIS 공통 기억 1회/2기록 조회 및 통합 4경로 통과. 모델 선택·자동 수집/주입은 미검증, GJC는 원격 wrapper로 별도 인수 필요.

> 2026-09-09 추가: [컴파일 재시도 이력 진단](COMPILE-RETRY-INVENTORY-2026-09-09.md). 현재 key 밖 과거 미완료 compile은 운영 관측 0건, done 이력 35건 유지. 실행/진단 key 계산 공유 및 역사적 실패 별도 표시 검증.

> 2026-09-09 제품 수정: [브리핑 수동 재큐잉 보류](BRIEF-RETRY-HOLD-2026-09-09.md). 실행 입력 없는 brief를 pending으로만 바꾸던 경로 차단, 선택 전체 상태 보존. ops/CLI 61개 및 별도 CLI 프로세스 검증 통과. 과거 실패 복구 자체는 미완료.

> 2026-09-09 진단: [브리핑 실패 5건](BRIEFING-FAILURE-DIAGNOSIS-2026-09-09.md)은 모두 9월 5일 unresolved uncited. 현재 제한 재생성·실패 시 미게시를 26개 테스트로 검증. 과거 키 일괄 requeue는 현재 날짜 실행 경로로 복구 보장 불가하여 미실행.

> 2026-09-09 읽기 전용 운영 산정: [페이지 키 재컴파일 규모](OPERATIONAL-COMPILE-KEY-ESTIMATE-2026-09-09.md). 고정 generation 18개 페이지 재컴파일 대상/호출 cap 120, 설명되지 않은 CAS 누락 0, brief 실패 5개 남음. 모델 호출·운영 변경 없음.

> 2026-09-09 추가: [페이지 키 설치본 이전 검증](COMPILE-KEY-INSTALLED-UPGRADE-2026-09-09.md). 기존 설치본의 누락 페이지 복구·출처별 권한 유지·재컴파일 불변 확인. 변경 후 전체 1,418 passed/2 skipped 및 새 후보 자비스 연동 통과.

> 2026-09-09 제품 수정: [페이지별 컴파일 키](COMPILE-PAGE-IDENTITY-2026-09-09.md). 동일 내용의 서로 다른 출처 중 두 번째 페이지가 누락되는 결함 재현·수정. 실제 CLI 포함 33개 검사 통과. 기존 페이지 1회 재컴파일 가능성은 운영 적용 전 검토 필요.

> 2026-09-09 전체 회귀·제품 수정: [원장 캐시 격리](LEDGER-CACHE-ISOLATION-2026-09-09.md). 재사용된 객체 id로 다른 원장 본문이 섞이는 결함 수정. 전체 1,418 passed/2 skipped, 설치 후보 연동 4경로 통과. 운영 전환 미완료.

> 2026-09-09 제품 수정: 모호한 복수 root 수집이 성공 코드로 숨겨지던 문제를 수정. SOURCE_ROOTS_AMBIGUOUS 실패·커서 미갱신, 재실행 시 지속 표시. 실제 CLI 포함 관련 31개 검사 통과. 상세: SESSION-MULTIROOT-HOLD-2026-09-09.md.

> 2026-09-09 정정 및 검증: [명시적 source ID별 세션 분리](SESSION-SOURCE-ISOLATION-2026-09-09.md)는 기존 파이프라인에서 지원됨. 네 형식 × 실제 CLI 3회(12프로세스)로 독립 원장/커서 및 무중복 재개 확인. 복수 root 보류는 ID별 분리가 없는 adapter instance에 한정.

> 2026-09-09 제품 수정: [복수 세션 루트 충돌](SESSION-MULTIROOT-HOLD-2026-09-09.md)을 확인해 Claude/Codex/OMO/GJC 복수 root 수집을 명시적으로 보류하고 커서를 보존. 관련 60개 검사 통과. root별 identity/migration 구현은 미완료.

> 2026-09-09 추가: [전환 서비스 경계 조사](TRANSITION-UNIT-AUDIT-2026-09-09.md): 실제 systemd 재시작/trigger 의존성 확인, 18개 단위의 읽기 전용 drain 검사와 7개 테스트 추가. 현재 활성 상태이므로 전환 gate는 보류이며 운영 중지는 실행하지 않음.

> 2026-09-09 추가: [신규 후보 DB 리허설](LOCKED-CANDIDATE-DB-REHEARSAL-2026-09-09.md)에서 58→81 및 기존 212개 테이블 보존 확인. 운영 구버전의 새 DB 수용 때문에 전환 검사 exit 1. SQL/build 일치 선검사와 회귀 테스트 3개 추가.

> 2026-09-09 추가: [설치본 간 통합 검사](INSTALLED-PAIR-INTEGRATION-2026-09-09.md)에서 provider wheel 설치본과 신규 의존성 자비스 후보의 쓰기→새 세션 읽기 및 철회/만료 4개 경로 통과. 운영 계정·systemd·봉인 릴리스 검증은 별도 미완료.

> 2026-09-09 추가: [새 잠금 의존성 후보](LOCKED-DEPENDENCY-CANDIDATE-2026-09-09.md)에서 컴파일·복원 리허설·HTTPS/MCP 쓰기→새 세션 읽기 4개 경로 통과. 운영 활성화 및 양쪽 설치본 동시 검증은 미완료.

# 중앙 기억 완성 진행 원장

**2026-09-09 운영 전환 준비 결함2개:** [Ja7a98e9 의존성 재사용 차단·SB 고정 커밋 wheel](RELEASE-PREPARATION-GAPS-2026-09-09.md). 운영 SDK 부재/lock 불일치 거부, 관련9검사·격리 publisher4경계. wheel의 미추적 bak2개 혼입을 재현해 git archive 빌드로 수정; 후보175파일 commit일치·7모듈/CLI·설치 MCP4프로필 handshake. 실제 운영 전환/DB·세션 설정 및 M1–M14는 남는다.

**2026-09-09 OMO/GJC 내용 체크포인트:** [교체·헤더 재검증·네 수집기 공통 함수](EXPORT-CONTENT-CHECKPOINT-2026-09-09.md). 회귀11실패→관련50/전체1,388통과·2skip/250.16초·정적0오류0경고, 독립11프로세스 교체/append/헤더/FIFO 인수. legacy 소급 복구·다중 root·운영 및 전체 M1–M14 유지.

**2026-09-09 세션 내용 결합 커서:** [동일크기 교체·수정 후 append 유실6재현·FIFO 회귀 수정](SESSION-CONTENT-CHECKPOINT-2026-09-09.md). Codex/Claude prefix 해시·읽는 중 변경 시 커서 보존/skip. 관련34/전체1,377통과·2skip/238.71초·Ruff/정적0오류0경고·독립8재개+2FIFO프로세스. legacy offset 소급 판별/OMO·GJC/운영 및 전체 M1–M14는 남는다.

**2026-09-09 실제 native 작성·회수:** [Claude 공개 쓰기1회→원자 완료→별도 Claude 회수1회](NATIVE-SCOPED-WRITE-READ-2026-09-09.md). 원래 검토된 JSON과 실제 tool 인수 동일, accepted replay=false, provider proved/JARVIS settled/control completed·settlement1/attempt1/FK0·새 reader2records. 전체4상태 exit0. 작성 내용·작업 근거는 fixture, 다른 모델 계열/운영/전체 M1–M14는 남는다.

**2026-09-09 공개 쓰기→완료→실제 Claude 회수:** [동일 요청·새 reader 로그인·reconcile/세대 대조](SCOPED-WRITE-TO-NATIVE-READ-2026-09-09.md). 실제 MCP/TLS/CLI proved→자비스 settled/control completed→새 agent context2records→독립2클라이언트/Claude1호출 통과. replay settlement1/attempt1/FK0, 철회·만료3상태 차단 유지. 작성자는 합성 검증 작업 fixture이며 native A쓰기/운영 및 전체 M1–M14는 남는다.

**2026-09-09 실제 인증 MCP 클라이언트:** [J70d0428·HTTPS 결함2개 수정·실제 Claude/독립2클라이언트](AUTHENTICATED-CLIENT-MCP-2026-09-09.md). 관련40통과·emit/lint. 실제 Claude1호출·각2records 회수, 범위 밖0·철회403/만료401 유지. Codex는 사용량 제한으로 호출 전 실패해 보류. 운영·scoped A쓰기→B새로그인·삭제/복원 등 M1–M14 유지.

**2026-09-09 인계 추가 분석 갱신:** [최신 수정·연결 순서·클라이언트 지원 증거](HANDOFF-MERGED-PRIORITIES-2026-09-09.md). SB HEAD5201cce와 전체1,367/2skip 기록을 대조하고 수집 회귀13개를 이번에 재실행해 통과했다. 작성 중인 JARVIS MCP 연결부는 미검증으로 구분하며 실제 scoped A→B·운영 전환·삭제/복원 등 M1–M14를 유지한다.

**2026-09-09 OMO/GJC 재개·헤더 우회 수정:** [부분 기록 보존·과거 cursor 거부·독립10프로세스](EXPORT-SESSION-RESUME-2026-09-09.md). 회귀4실패→관련35/전체1,367통과·2skip/231.54초, 정적검사 통과. GJC 첫 헤더를 재검사해 거절된 파일의 append 수집 우회를 차단한다. 운영 변경 없음·전체 M1–M14 유지.

**2026-09-09 Claude 원본 수집 누락 수정:** [native user/assistant·출처/도구 오류·실제 CLI](CLAUDE-NATIVE-COLLECTION-2026-09-09.md). 회귀4실패→관련24/전체1,362통과·2skip/246.29초·Ruff/정적검사. 실제 표본96블록 및 새 Claude 세션2블록 회수·재조회0. 과거 cursor/운영 미변경, 실제 A→B와 전체 M1–M14 유지.

**2026-09-09 세션 부분 기록 유실 수정:** [Codex/Claude cursor 보존·독립6프로세스](SESSION-PARTIAL-RECORDS-2026-09-09.md). 회귀2실패→관련20/전체1,358통과·2skip/257.79초, Ruff·정적검사 통과. 실제 Claude native user/assistant 형식 누락도 구조 표본으로 확인했으며 다음 수정 대상이다. 운영 변경 없음·전체 M1–M14 유지.

**2026-09-09 verifier DB 버전 경계:** [시작/요청마다 migration 검사·실제 TLS/MCP](PROVIDER-MIGRATION-BOUNDARY-2026-09-09.md). J867c274, async 시작·오류 연결 정리·실행 중 unknown 거절. 관련67통과·emit/lint, 실제4상태 attempt1/FK0. 운영 전환과 실제 A→B 등 M1–M14 미완료.

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

**2026-09-09 JARVIS `8ffc993` / SB 전체:** [자동 발행의 가변 Date 역행 수정](AUTO-PUBLICATION-CLOCK-2026-09-09.md). 재현1실패→관련19통과·실제 CLI/MCP/provider 저장·records4 재인수. SB `cc236a3` 기준 전체1,153통과/2skip/219.73초·전체Ruff통과. scoped 쓰기·orphan 수명·운영/모델 세션 인수는 남는다.

**2026-09-09 실제 저장 인수:** [자동 CLI 후보→실제 MCP/provider 처리→별도 클라이언트 회수](AUTO-CANDIDATE-PROVIDER-2026-09-09.md). v3 pending→proved, outbox settled/control completed, records4, 중복 replay/재처리idle/추가dispatch0/본문정리0. 관련7통과. 일반 owner 경로이며 scoped 쓰기·운영/모델 세션 인수는 남는다.

**2026-09-09 JARVIS `aa825f0`:** [자동 승인 후보 CLI 발행 구현](AUTO-CANDIDATE-PUBLICATION-2026-09-09.md). 기존 수동 경로13·최종 자동/범위7통과, v1/v3 발행/재실행/실패 복구 및 실제 컴파일 CLI→spool→scoped 준비 인수. auto-approved 발행 결손 수정. scoped 승인 소비·provider 저장·완료 영수증과 orphan 정리 전체 인수는 남는다.

**2026-09-09 v3 인수:** [한국어 다중 행 v3 spool→scoped 준비](SCOPED-DISPATCH-PREPARATION-2026-09-09.md). 관련4통과·실제 컴파일 코드/DB/spool에서 CRLF 포함 본문 일치·검증 철회 거부. 제품 추가 수정 없음. fixture 발행과 실제 CLI 자동 발행을 구분하며 auto-approved 후보의 발행 연결·scoped 저장/영수증은 남는다.

**2026-09-09 dispatch 연결:** [private spool→scoped 준비·원본 권한 재검사](SCOPED-DISPATCH-PREPARATION-2026-09-09.md). 기존 spool reader/write authority 재사용, J3통과·실제 컴파일 API에서 본문 복구/원본 verification 철회 거부/쓰기0 확인. 범위 승인만으로 원본 권한을 대체하지 않는다. 단일 소비·outbox/provider 쓰기·영수증은 미완료다.

**2026-09-09 후보 본문 결합:** [scoped 쓰기 준비 payload](SCOPED-WRITE-PAYLOAD-2026-09-09.md). 현재 signed review와 후보 제목/본문 digest 일치 검사, 호출자 본문 교체 거부. J2통과·실제 컴파일된 API와 Python의 제목/본문/준비 digest 일치. 요청 codec·승인 소비·outbox/provider 저장·완료 영수증은 미완료다.

**2026-09-09 JARVIS `0e6923b`:** [범위가 결합된 쓰기 식별자](SCOPED-WRITE-IDENTITY-2026-09-09.md). 기존 v1/v3 유지, signed review→scoped identity/key 및 Python 독립 codec. J2/SB9통과·실제 서명 검토에서 양쪽 digest/key 일치, 동일 범위 재승인 key 불변. 요청 codec·승인 소비·outbox/provider 저장·영수증은 미완료다.

**2026-09-09 JARVIS `5c8931b`:** [범위 검토의 일반 실행·소비 차단](SCOPED-WRITE-REVIEW-DESIGN-2026-09-09.md). 일반 큐 반환 회귀 재현→관련13통과·타입/lint·격리 실행기 거부 및 승인 보존 확인(독립 프로세스7개). outbox 원자적 삽입 지점을 확인했으며 범위 검토를 기존 confirmation 소비 종류로 위장하는 방식은 보류한다. scoped 쓰기 전체는 미완료다.

**2026-09-09 JARVIS `303f0d1`:** [기존 owner 서명에 범위 검토 결합](SCOPED-WRITE-REVIEW-DESIGN-2026-09-09.md). 관련15+action3통과·격리emit/lint·독립 프로세스6개 인수. 같은 제안의 서명 검토 수락, 다른 프로젝트/철회 거부, 승인 시 격리 rollback. 검토는 쓰기 권한이 아니며 영수증 단일 소비·provider 버전 계약·저장 계보·실제 UI/운영 인수는 미완료다.

**2026-09-09 JARVIS `be2c012`:** [후보 범위 제안 재검증](CANDIDATE-SCOPE-REVALIDATION-2026-09-09.md). 저장된 제안 전체 bytes·현재 후보·만료·격리 확인, 집중2통과·타입/lint·격리 build 및 독립 Node 3개에서 정상 수락/범위 변경 거부/후속 격리 거부. 제안은 not_granted이며 승인·쓰기·영수증 연결은 미완료다.

**2026-09-09 인계 추가 대조:** [수정·개선·고도화 추가 분석](HANDOFF-ADDITIONAL-ANALYSIS-2026-09-09.md). 네 OSS의 선별 흡수 방향을 재확인하고 통합 목록 M1/M9의 오래된 상태를 갱신했다. 후보 범위 제안은 기존 분류/출처에 결합하는 읽기 전용 선행 API이며 승인·scoped 저장 완료가 아니다. 승인된 범위→쓰기→영수증→다른 agent 재사용은 P0로 유지한다.

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
