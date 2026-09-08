# 중앙 기억 인계 병합: JSON 사본 삭제 보강과 잔여 실행 목록

제품 커밋 JARVIS `0352642`, SB 인수 도구 `33bffc0`.

2026-09-08. JARVIS 인계 문서와 기존 분석·구현·인수를 이어서 대조했다. 세컨드브레인을 개인·업무
기억 정본으로 유지하고 네 OSS의 설계 장점만 선택적으로 적용한다. 네 제품 설치나 소스 복사는 없다.
개발 결정 정본은 dev-wiki이며 이번에 수정하지 않았다.

현재 판정은 **저장·검색·정정·삭제와 두 실제 CLI의 기억 공유는 검증됨, 자비스 및 모든 앱의
운영 중앙 기억 완성은 미완료**다. 현재 실행 중인 운영 서비스 전체를 새로 진단한 결과는 아니다.
이전 인수와 이번 검사 결과를 구분한다.

## 기존 구현·OSS 대조

| 후보 | 판단 | 기존 근거 | 남은 조건 |
|---|---|---|---|
| LightRAG 근거·하이브리드 검색 | 재사용·개선 반영 | 봉인 검색·record 벡터·정정/삭제/복원 인수, 실제 모델 평가 | 근거 충분성·무정답·약 6초 검색 지연·사용자 질문 평가 |
| Tencent 공통 기억·범위 | 공통 인터페이스 재사용, 권한 연결 필요 | 기존 MCP/JARVIS adapter, 실제 Codex↔Claude 회수 | 검증된 프로젝트/사용자 ACL 및 실제 앱 채택 |
| code-brain 작은 문맥·출처·예산 | 구현 재사용·연결 개선 필요 | reference reader, 전체 직렬화 byte 예산·출처/세대 결합 | 앱 요청 경로·실패/미확정 도구 결과의 capture 경계 |
| memory-bank 세션 중복·수명 | 영구 원장·native 검증, 보존 보강 필요 | submitInSession, 실제 UUID 5개 bootstrap/resume, 무효화 재개 차단 | native 사본 소유권·폐기·compaction·수신 fence |

위 이전 증거는 `REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.md`와
`NATIVE-SESSION-ACCEPTANCE-2026-09-08.md`에 있다. 이전 native 실행은 삭제 후 rollout 3개와
thread_history SQLite에 원문 잔류를 확인했다. 아래는 그 조사에서 이어진 신규 수정이다.

## 재현한 결함과 실제 수정

JARVIS `memory-compaction-external.ts`는 원문 바이트만 비교했다. 줄바꿈·따옴표·역슬래시가
있는 기억을 JSONL 또는 중첩 JSON SQLite TEXT로 저장하면 원문 비교가 실패했다.
`memory-forbidden-content.ts`도 원문에서만 영구 지문을 생성해 재시작 후 같은 사본을 놓쳤다.

수정 전 3개 테스트 모두 실패했다: 사본 4개 중 1개만 발견, 영구 표현 지문 3개 대신 1개,
dist의 JSON 사본을 거부하지 못함. 새 `memory-content-representations.ts`가 원문 및 JSON
문자열 내부의 1중·2중 표현을 생성하고 삭제·지문 양쪽에서 공통 사용한다.

- 유효 UTF-8만 추가 표현을 만들며 잘못된 바이트를 U+FFFD로 바꾸지 않는다.
- 바이트 단위 JSON escaping으로 평문 JS 문자열 추가 생성을 피하고, 생성 Buffer는 동기
  callback 이후 성공/예외 모두 0을 채운다. caller 소유 원문은 보존한다. thenable 반환은 거부한다.
- 최대 100,000개, 원문과 생성 Buffer 누적 64 MiB를 할당 전에 검사한다. 초과 purge는 완료가
  아닌 reconciling/오류로 남는다. 이 값은 RSS/스캐너 파일 읽기 상한이 아니다.
- 기존 raw 지문·DB schema·MCP wire는 유지한다. 과거 raw-only 지문에서 원문을 복원하거나
  과거 purge를 자동 보강하지 않는다.

## 검증 결과

[기계 증거](JSON-RETENTION-ACCEPTANCE-2026-09-08.json). 격리 빌드
`/var/tmp/sb-json-retention-build-jvgb0_pd`, 결과 `/var/tmp/sb-json-retention-pCgilZ/result.json`.

| 검증 | 결과 |
|---|---|
| 수정 전 재현 | 3 failed |
| 관련 회귀 | 8파일 35 passed, 32.59초 |
| 최종 동기 callback 제한 추가 후 관련 재검사 | 3파일 10 passed, 11.56초; 앞 결과와 중복이며 합산하지 않음 |
| backend TypeScript·격리 emit·변경 ESLint | 통과 |
| 실제 별도 Node 프로세스 | 5개 PID, 원문 없는 scanner 재시작 포함 |
| 원문/JSONL/중첩 SQLite/복원 JSON | 4개 검출, 4개 제거, 무관 파일 보존 |
| 저장된 SQLite 사본 복원 | 재시작 scanner 거부, 제거 후 70개 surface 검사 통과 |
| 기존 compactor 통합 | 열린 old FD 차단→회수→새 inode 복구, JSONL/SQLite 사본 부재 |

인수의 provider/guard 관측은 결정적 fixture다. 실제 SB 삭제 영수증이나 실제 Codex 사본 삭제를
이번 검사로 증명한 것은 아니다. native 모델 호출 0회, 운영 데이터 사용 없음. 전체 SB 931개와
JARVIS 전체 verify를 이번 단위에서 재실행하지 않았다. 합성 원문은 fixture 외부 증거 파일에
남으며 모든 fixture 평문 또는 원격 모델 데이터의 삭제 완료로 주장하지 않는다.
재시작 scanner만 원문 없이 영구지문으로 검출한다. 사본 제거에는 부모 프로세스가 원문을
다시 전달한다. 지문만으로 삭제하는 경로나 완전한 fixture 소거를 검증한 것이 아니다.

독립 검토에서 생성 버퍼 정리·할당 상한·동기 callback 강제 지적을 반영했다. 전체 테스트 실행은
구현 담당의 위 결과이며 검토자가 테스트를 수행했다는 의미가 아니다.

재현: `TMPDIR=/var/tmp node scripts/jarvis-json-retention-acceptance.mjs /absolute/isolated-jarvis-build`.
격리 build에는 backend/test JS, migrations, contracts, package.json, node_modules 링크 및
source SHA manifest인 acceptance-build.json이 필요하다.

## 수정·개선·고도화 상세 우선 목록

아래 항목은 기존 14개 과제를 유지하며 native 보존 조사 결과를 구체화한 후속 목록이다.

| 우선 | 구분 | 문제·영향 | 구현 방향 | 완료 증거 |
|---|---|---|---|---|
| P0 | 수정 | native rollout/SQLite는 provider 삭제 후 남음 | native root·DB sidecar·백업을 기존 managed surface와 출처 계보에 결합; writer 종료·FD 처리 | 실제 앱 삭제 뒤 사본 부재·이전 세션 재개 차단·무관 세션 보존 |
| P0 | 개선 | 실제 JARVIS 앱이 보호 제출 경로를 채택하지 않음 | 요청 adapter에서 reader→submitInSession 연결 | 앱 요청/attempt/native turn/result 상관관계 |
| P0 | 수정 | claim 직후 외부 송신과 삭제 사이 경합 | 수신 fence·삭제된 세션 후속 turn 거부 | 경합 재현 및 삭제 이후 이전 기억 사용 차단 |
| P0 | 수정 | 검색 필터·단일 owner는 프로젝트 ACL이 아님 | 신뢰 가능한 사용자/프로젝트 분류를 검색·원문·관계에 일관 적용 | 다른 프로젝트/사용자의 부정 접근 거부 |
| P0 | 개선 | 실패·미확정 실행이 성공 기억으로 축적될 가능성 | 검증된 도구 결과·receipt 기반 capture 및 원본 차단 전파 | 실패·불확실 시나리오에서 성공 기억 생성 0 |
| P1 | 고도화 | native compaction과 epoch 미결합 | 실제 client event만 epoch에 연결 | compaction/재개 전후 중복·정정·삭제 인수 |
| P1 | 수정 | 유사한 문서에 답이 없어도 후보 반환 | 답의 근거 충분성·no_data 경계 보강 | 근거 없는 세부 질문에서 추측 답변 억제 |
| P1 | 개선 | 검색 약 6초·모델 자원 비용 | 실제 프로파일 후 모델 수명/공유 최적화 | 동일 평가·삭제 회귀 유지, p95/RSS 비교 |
| P1 | 개선 | 합성 평가만으로 개인 기억 품질 보장 불가 | 사용자 질문·정답 근거·무정답 100–300개 평가셋 | 회수율·오래된 결정·지연·주입량 비교 |
| P1 | 개선 | MCP 가능과 자동 수집/주입 지원 혼동 | Codex/Claude/사용 앱별 지원표·adapter 인수 | 조회/쓰기/수집/주입 각 실제 경로 증거 |
| P1 | 개선 | GUI·운영 준비/실패 가시성 미인수 | 기존 화면/API의 출처·실패·불확실 전달 표시 | 운영 설정에서 사용자 기억 한 주기 완료 |
| P1 | 수정 | 이전 백업은 이후 전달·삭제를 모름 | 복원 고수위 대조·기존 native session 재개 금지 | 과거 백업 복원 후 중복·삭제 기억 부활 없음 |
| P1 | 개선 | 전체 DR/RPO/RTO·외부 사본 삭제 미검증 | 실제 운영 복원 훈련·소유 범위별 보존 검사 | 복구 시간·손실·외부 보존 한계 실측 |
| P2 | 고도화 | 무관한 세션까지 전역 무효화 | 필요시 record별 의존 계보 | 전역 방식과 동등한 삭제 안전성 |
| P2 | 보류 | 그래프·새 Proxy·별도 DB의 복잡성 | 기존 검색의 실측 부족이 있을 때만 ADR | 동일 평가의 이익과 삭제/범위/운영 비용 입증 |

현재 수정의 제외 범위: 다른 Unicode escape 직렬화, 3중 이상 JSON, 압축·암호화, SQLite overflow
page의 바이트 분절, 파일 traversal 경합, 외부 열린 FD와 원격 모델 보존. byte fingerprint의
window 일치는 보수적 차단이며 전체 원문 동일성 증명이 아니다. native 자동 주입을 이 수정만으로
활성화하지 않는다. SB 운영 vault/JARVIS 운영 DB·migration 배포·서비스 재시작·push는 수행하지 않았다.
