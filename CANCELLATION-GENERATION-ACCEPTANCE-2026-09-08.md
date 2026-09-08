# 취소된 정정의 실제 억제 세대·중단 복구 인수

2026-09-08. 제품 `b3c8b87`. 이전 [원자 접수 구현](CANCELLATION-JOURNAL-ACCEPTANCE-2026-09-08.md)의 후속이다.

## 완료한 기능

접수된 취소를 실제 generation에 적용하는 내부 실행 경로를 구현했다. 기존 대상을 제거하고
취소된 정정의 replacement 본문은 적용하지 않는다. 기존 ErasureEngine/ReingressGate와
GenerationMutationService를 재사용하며 새 일반 V2 요청이나 별도 기억 DB를 만들지 않았다.

- 접수 당시 서명·만료를 재검증하고 현재 허용 키 목록을 요구한다. 세대 writer를 기다리거나
  세대를 생성하는 동안 키가 제거되면 활성화 직전 재검사에서 거부한다.
- 실제 활성 generation의 provider/id/manifest/head/tree와 커밋된 페이지 blob, 본문 digest,
  인용 span을 대조한다. 대상 불일치는 successor 생성 전에 거부한다.
- 기존 원장의 intent→sealed generation 연결을 남긴다. 기존 단일 writer가 수정된 내용과
  파생 저장소를 봉인하고 포인터를 전환하며 이전 세대 정리를 수행한다.
- 영구 source/content/citation/subject 재수집 차단을 적용한다. 정정 본문 없이 작업을 재개한다.
- 실제 활성화 기록이 proved에 도달했는지 확인해 완료를 기록한다. 활성 세대의 포인터 전환
  직후 중단은 재개하며, 이후 정상 세대가 해당 결과 세대를 정리했어도 기존 완료 결과를 반환한다.

반환 상태 `generation_active`는 해당 억제 세대가 활성화·이전 세대 정리를 마쳤다는
**과거 처리 사실**이다. 항상 현재 포인터를 가리킨다는 뜻이 아니며, provider 전체 물리 삭제나
자비스에 제출할 서명된 최종 영수증도 아니다. 기존 MCP 계약을 변경하거나 취소 도구를 노출하지 않았다.

## 실제 검증

| 범위 | 결과 | 한계 |
|---|---|---|
| 기본 전체 회귀 | 968 passed, 2 skipped / 132.25초 | 최종 권한·과거 결과 재생 보강 및 회귀 3개 추가 전 실행 |
| 최종 관련 4개 모듈 | 28 passed / 14.42초 | 위 전체 검사와 중복. 합산하지 않음 |
| 제품 정적 검사 | 변경 제품 4개 파일 basedpyright 0 오류/0 경고, `ruff check sb tests` 통과 | 실제 운영 구성 검증은 별도 |
| 중단 회귀 | 봉인·포인터 rename·활성화 확인·이전 세대 정리에서 KeyboardInterrupt 후 재개 통과 | 결정적인 장애 주입, sleep 없음 |
| 실제 강제 종료 | 포인터 rename 직후 별도 worker 프로세스 `os._exit(77)` → 새 worker에서 복구 | 격리된 합성 기억, 운영 프로세스 중단 없음 |
| 실제 stdio MCP | 처리 전 pointer_health=tombstone_stale/조회 거부 → 복구 후 healthy | 자비스 앱의 최종 소비 cursor 연결은 미실행 |
| 원문·검색 | 활성 generation에서 기존 원문·취소 replacement 모두 0건, 두 MCP 검색 결과도 0건 | backup/export/native 보관처 전체 처분 증거는 아님 |
| 재생·보호 | 재시작 재생, 후속 세대가 결과 파일을 제거한 뒤 재생, 키 제거, 실제 페이지 변조 거부 통과 | 배포된 key-purpose/revocation 정책 구성은 후속 |

실제 실행은 제품 RequestExecutor로 기억을 저장하고 커밋된 실제 대상을 해석한 뒤, 서명된
취소를 접수한 격리 fixture를 사용했다. 두 worker(강제 종료/복구)와 두 MCP 프로세스(처리 전/후)를
실행했다. 현재 시각의 서명된 read fence로 MCP를 호출했다. 해당 fixture의 서명 키·원 요청
시각은 테스트용이며 운영 권한을 사용하지 않았다.

최종 [실행 원본](/var/tmp/cancellation-generation-spdaeck7/result.json),
[보존한 기계 판독 보고서](CANCELLATION-GENERATION-ACCEPTANCE-2026-09-08.json),
[재실행 스크립트](scripts/cancellation-generation-acceptance.py).
복구 generation은 `sbgen:v1:95bbf7fdb36d6c2e21cdbe7ea2ed8fa03ebed1c66ce35391673ba21fb20b8af7`,
tombstone sequence는 1이며 이전 원문 세대 디렉터리가 제거됐다.

## 다음 구현과 보류 조건

이번 변경으로 이전 우선 목록의 **실제 억제 세대 생성·재시작 복구**를 구현했다. 다만 queued
lane의 자동 해제와 후속 V2 sequence2의 자비스 전체 전송 순환은 여전히 미완료다.

| 우선 | 이어갈 작업 | 완료 조건 |
|---|---|---|
| P0 | 취소 대상의 실제 세대 검증을 접수와 결합 | 잘못되거나 이미 바뀐 대상의 취소가 원장 high-water를 막기 전에 거부. pending→generation→DB 잠금 순서 유지 |
| P0 | backup/export 및 잔여 managed surface 처분 | 기존 억제 대상과 연결되는 사본을 처분하고 재시작·복원 후 재유입 0 및 검증 가능한 inventory 확보 |
| P0 | 버전 있는 취소 결과·상태 조회 계약 | 실제 활성화·처분 결과를 양쪽 validator로 검증. 만료 후 조회, 중복·유실·재생 처리 |
| P0 | 자비스 producer/MCP route/cursor 완료 연결 | 취소 seq1 완료 증거 후 정상 V2 seq2만 전송. 혼합 delta 예외나 낮은 checkpoint 허용 없이 실제 통합 성공 |
| P0 | 실행 권한 구성과 접수 지연 정책 | 현재 key purpose/revocation을 실제 구성에 연결. 긴 writer 대기 후 만료를 일관되게 처리 |
| P0 | 원task 계보·사용자/프로젝트 범위·native 원문 수명 | 이전 재현 결함과 검증 공백 유지. 실제 앱 공급→실행→검증 결과 저장→재사용·정정·삭제 순환 인수 |
| P1 | 에이전트별 실제 수집/주입·검색 평가·운영/복구 | 지원표와 실제 질문 평가, 화면 준비 상태, 백업 복원·RPO/RTO 검증 |
| P2 | 선택적 무효화·관계 검색 | 출처 계보와 검색 품질 실측을 먼저 갖춘 뒤 도입 효과로 판정 |

**자동 취소 라우트·자비스 lane 건너뛰기는 보류**한다. 현재 내부 결과에는 모든 사본 처분과
최종 서명 영수증이 없다. **자동 collector 확대는 원task 계보 전까지 보류**한다.
네 OSS 선별 흡수, SB 기억 정본/JARVIS 실행/dev-wiki 개발 원문이라는 인계 방향과 전체 완성
조건을 유지한다. 운영 DB·vault 변경, 배포·서비스 재시작·push는 수행하지 않았다.
