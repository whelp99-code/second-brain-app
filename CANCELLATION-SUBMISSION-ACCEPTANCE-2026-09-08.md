# 자비스 DB → 실제 provider 취소 접수 인수

2026-09-08. Second Brain 제품 `f9daf99`, JARVIS 제품 `12d7b2a`.

## 완료한 연결

기존 DB 발급 의향을 명시적 `cancellation-submit-schema7` 프로필의 `sb_submit_cancellation`으로 접수한다. 기존 schema3/4/5/6, frozen artifacts와 기본 선택은 유지한다. 11개 도구 계약은 양쪽 `contracts/second-brain-mcp-v5.json`에서 같은 bytes이며 digest는 `d137a7a7b0e4a577abef04d6ecb2768630e9912cd24b8f270c320cb45d60165d`다.

- JARVIS `submitDatabaseCorrectionCancellation`은 실제 DB의 불변 의향을 재사용한다. 연결·queue 대기 뒤 stdin 발행 직전 동기 검사에서 현재 키·시각·미전송 근거를 다시 대조한다.
- 수신자는 별도 목적의 `cancellation_public_keys` 및 `revoked_jarvis_signing_key_ids`를 매 인증 시 다시 읽는다. 과거 원 요청의 공개키는 `jarvis_public_keys`로 분리한다. 설정 손상·목적 키 부재·provider/경로 변경은 거부한다.
- 기존 pending→generation→DB 잠금, 실제 대상/세대 확인과 원 요청 접수 증거 대조를 재사용한다. 잠금 대기와 대상 검사 후에도 현재 권한을 재확인한다.
- 응답의 intent/provider/원 요청/삭제 sequence·root/접수 시각을 대조한다. `suppression_pending`은 접수 상태이며 삭제 결과나 cursor 완료 증거가 아니다.
- 전송을 쓰기로 분류해 응답 유실 시 uncertain으로 남긴다. 자동 재시도하지 않으며 같은 저장 의향의 명시적 재접수는 동일 결과를 돌려준다. 만료·철회 이후 자동 재발급은 하지 않는다.

## 실제 프로세스 관측

[원시 메타데이터 증거](CANCELLATION-SUBMISSION-ACCEPTANCE-2026-09-08.json). 재현: `scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD`와 동반 Node 스크립트. 운영 dist 대신 `/var/tmp/jarvis-cancellation-submit-build-em91fmht`를 사용했다.

실제 provider에 합성 기억을 저장하고 봉인 세대의 대상 식별자를 JARVIS fixture의 실제 준비·억제·발급 경로에 전달했다. Node가 만든 DB 의향을 실제 Python stdio MCP가 검증·접수했다. 고정 시각과 합성 키를 사용하므로 운영 업무 인수로 확대하지 않는다.

| 검사 | 최종 관측 |
|---|---|
| 접수 commit 직후 응답 전 프로세스 종료 | exit 77; Node는 `SECOND_BRAIN_WRITE_INTERRUPTED` / uncertain |
| 자동 재전송 | 0회; 명시적 재시작 전 MCP 프로세스 1개 |
| 명시적 재시도·재시작 | 동일 접수 결과 재생 |
| 실행 중 provider 키 철회 | 같은 MCP 프로세스의 후속 접수 거부 |
| provider 저장 | 접수 1행, 원 요청 차단 alias 8행, 최종 결과 0행 |
| 원문·세대 | 원래 transport 호출 0회, 원문 spool 보존, 기존 세대 유지 |
| JARVIS cursor | active lane 없음, accepted_through_sequence=0 |
| MCP 비밀키 | 설정에 provider 개인키 없음 |

최종 Node PID 218254, MCP PID 218347/218593/218704, Python 부모 PID 217418. 임시 실행 자료는 `/var/tmp/cancellation-submit-acceptance-jkh_tx3c/result.json`이다.

## 추가 수정과 검사

실제 호출에서 취소 거부 코드가 일반 오류로 뭉개지는 문제를 수정했다. 수신 파일/DB 오류는 로컬 경로 대신 제한된 오류 코드로 반환한다. 자비스는 잘못된 최상위 인자와 의향 크기 초과를 실행기 시작 전에 거부한다.

전송 회귀 중 처리되지 않은 비동기 stdin `EPIPE`를 재현했다. 해당 실행은 테스트 단언 87개 통과에도 전체 오류 1건으로 실패했으며 성공으로 계산하지 않는다. 자식별 입력 오류를 처리하고 종료 확인까지 listener를 유지한 뒤 제거하도록 수정했다. 진행 중·종료 중 재현 2건을 추가했다.

- Second Brain 전체: **1,082 passed, 2 skipped, 231.34초**. 최종 로컬 경로 오류 정규화 전 관측이다.
- 그 수정 후 최종 MCP 관련: **26 passed, 15.76초**, 신규 오류 재현 3개 포함. 전체 결과와 합산하지 않는다.
- Second Brain 제품 정적 검사: 0 errors/0 warnings. `ruff check sb tests` 통과.
- JARVIS DB·계약·schema4 읽기·접수 관련: 5파일 60통과(최종 인자 제한·EPIPE 수정 전).
- 최종 JARVIS 전송·접수: **9파일 89통과, 8.32초, unhandled error 없음**. tsc noEmit·변경 파일 ESLint 및 격리 emit 통과.
- 최종 코드의 실제 Node→Python 접수·중단·재시작·철회 검증을 다시 통과했다.

## 남은 완료 조건과 보류

1. 접수된 의향의 실제 처분·서명 결과를 명시적 실행 경로에 연결하고 중단 복구를 인수한다. 이번 도구는 접수만 하며 자동 worker를 만들지 않았다.
2. provider 결과와 JARVIS 관리 대상 로컬 억제 증거를 모두 검증한 뒤 cursor를 완료한다. 실제 취소 seq1→정상 V2 seq2를 증명하기 전 skip/자동 retirement는 보류한다.
3. 원 요청의 외부 전송과 취소 접수의 양쪽 승패를 통합 경합으로 추가 검증한다. 기존 각 DB/접수 잠금 검증과 이번 응답 유실 검증을 그 전체 증거로 확대하지 않는다.
4. 만료/철회 의향 및 source가 없는 과거 요청의 조정 정책, 사용자·프로젝트 범위, 원작업 계보, native 세션/WAL/백업 수명, 실제 앱 전체 순환, 검색 평가·GUI·운영 복구를 유지한다.

운영 설정 활성화·서비스 재시작·운영 DB migration·배포·push는 하지 않았다. 전체 중앙 기억 운영 완료는 미검증 상태다.
