# provider 취소 결과의 자비스 불변 저장·현재 신뢰 검증

2026-09-08. JARVIS 제품 `9d8c0ed`, Second Brain 제품 `9e30115`, 인수 스크립트 `bfca89e`.

## 이번 구현

기존 AuthorityDb에 migration073의 `memory_correction_cancellation_results`를 추가했다. 기존 001~072 bytes와 운영 DB는 변경하지 않았다. 결과를 원 의향/source·원 요청·삭제 chain·delegation link에 결합하며 처음 저장할 때는 준비 상태·실제 후보 억제와 미전송 증거까지 확인한다.

`MemoryCorrectionCancellationResultStore.record/get`은 provider/release별 등록 키로 실제 서명을 검증한다. 키의 유효 기간은 서명 시각에 적용하고 현재 명시적 철회는 저장/조회 모두에 적용한다. 원 의향은 발급 당시 키로 검증하며 접수 TTL을 갱신하거나 재서명하지 않는다.

저장 결과는 불변이며 재시작·중복 저장은 같은 bytes를 반환한다. 다른 유효 결과로 교체하는 재시도도 거부한다. 향후 처분 후 조회가 임시 준비 데이터에 의존하지 않도록, 원 요청의 메타데이터 검증을 준비 상태 검증과 분리했다. 최초 저장의 검증은 유지했다. 이는 실제 DB compaction 후 재생까지 검증했다는 뜻은 아니다.

## 실제 프로세스 인수

[기계 판독 증거](CANCELLATION-RESULT-STORAGE-ACCEPTANCE-2026-09-08.json).
재현은 `scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD --record-result`다.

1. 실제 JARVIS fixture DB에서 의향 발급 → Node MCP 전송 → Python provider 실제 대상 접수.
2. 명시적 Python CLI로 처분·서명 결과 생성.
3. 별도 Node 프로세스가 결과를 검증·자비스 DB에 저장한 직후 exit77.
4. 다른 프로세스에서 DB를 다시 열어 동일 결과 회수·중복 저장 확인: 결과 1행.
5. provider 키 철회 후 조회 거부. 원문 spool 보존, 원래 요청 transport0회, cursor0 유지.

최종 자료는 `/var/tmp/cancellation-submit-acceptance-spxvqhnz/result.json`이다. Node 부모 PID329364, MCP PID329436/329457/329472, Python 부모 PID329312. 대상·키·접수 시각은 격리 fixture이며 처분 결과는 실제 CLI 실행에서 받았다. 운영 앱 사용과 배포의 증거로 확대하지 않는다.

기존 `--record-result` 없는 접수 전용 인수도 다시 통과했다. 이 모드는 결과0행·세대 미변경을 유지했다(`/var/tmp/cancellation-submit-acceptance-sbftcwhc/result.json`).

## 로컬 처분·cursor 보류 근거

기존 `MemoryManagedSurfaceScanner`는 provider40 표면 및 guard10을 포함하는 전체70 표면 계약을 요구한다. 현재 `provider_local_suppressed` 취소 결과는 이 전체 manifest를 제공하지 않는다. 이 결과를 전체 검사 영수증으로 위장해 사용할 수 없다.

더구나 실제 cancellationDatabaseFixture에서 기존 `restoreBlockedProjections → collectSuppressedContent`를 실행했을 때 **차단 projection2개, 수집 본문0개**였다. **spool에는 대체 본문이 남아 있었다.** 기존 compactor를 취소 경로에 바로 연결하면 검출할 본문 자체를 놓칠 수 있다. 이 진단은 실제 격리 DB/파일 관측이며 전체 compaction을 실행한 결과는 아니다.

따라서 이번 결과 저장은 로컬 처분 또는 처리 위치 완료로 사용하지 않는다. 다음은 원 의향·원 요청에 결합된 spool 본문의 검증 및 처분 재료/재유입 금지 식별자 보존, 실제 로컬 표면 검사와 DB 교체 증거 수집이다. 그 증거와 provider 결과를 결합한 뒤에만 취소 seq1→정상 V2 seq2를 인수한다. 자동 skip/retirement는 계속 보류한다.

## 검증과 남은 범위

- JARVIS 최종 관련 **5파일57통과, 23.79초**: 결과 저장·DB 의향·migration·서명 결과·접수 계약.
- TypeScript noEmit, 변경 파일 ESLint, 격리 emit, diff 공백 검사 통과.
- 실제 결과 저장 직후 프로세스 종료·재생·현재 키 철회 검증 통과.
- Second Brain 제품 소스는 변경하지 않았다. 이번에는 실제 인수 스크립트를 검증했으며 Python 전체 테스트를 다시 실행하지 않았다.

외부 원 요청 전송과 취소의 통합 경합, JARVIS 로컬 억제·cursor, 실제 앱 전체 순환, 사용자/프로젝트 범위, 원작업 계보, native 세션/WAL/백업 수명, 검색·GUI·복구의 전체 목표를 유지한다. 운영 migration·설정 활성화·배포·서비스 재시작·push는 하지 않았다.
