# P11 — 운영·배포·복구·종단 QA

명세 등록 / 제품 구현·시험·배포 NOT_RUN. Refs #3. P00 #4부터 병행, 릴리스 인수 시 해당 구현 전체 필요. R1/R2/R3 공통 / REQ-08 및 REQ-01–09 통합 / QA+Core+Client / 8–12인일 추정. 기준: 개발계획 11.2·14–18장.

## 목표
수집→기억→Obsidian→정정 흐름을 실제 사용자 환경에서 검증하고, 오류를 숨기지 않는 운영 상태·재개·복구를 제공한다. 개별 테스트 개수나 문서 merge로 제품 완료를 선언하지 않는다.

## 구현 체크리스트
- [ ] source last_seen/cursor/covered_window, receipt→searchable 지연, generation, briefing 생성·전달, 단말 ACK, backup 검증, disk/retry 상태를 수집한다.
- [ ] 원문·좌표·건강 수치 없이 상태·원인·필요 조치를 조회하는 health UI/API를 제공한다.
- [ ] 단일 writer 잠금, 복구 가능한 입력, 제한 재시도 조건에서만 기존 명시 run surface로 self-healing한다. 코드 자동 수정·권한 확대·운영 migration은 자동 복구에 포함하지 않는다.
- [ ] 선택 100건 backfill dry-run에서 원본 hash/record ID/발생일 미상/중복/격리/정정·삭제 상태를 비교한다.
- [ ] 추가형 migration과 schema version, 구버전 호환·비호환 시 fallback runbook을 작성한다.
- [ ] live DB 일관 백업→분리 복원→정정/삭제/tombstone→검색·View 재생성을 검증한다.
- [ ] life_events/timeline/obsidian/briefing/gap/recall/location/health/prediction flags를 독립 제어한다. OFF도 삭제·철회를 계속 처리한다.
- [ ] 기존 포트·터널·자격증명·서비스 이름을 보존하고 승인된 별도 후보 환경부터 배포한다.
- [ ] 장애 시 신규 처리·전달 중지, 백업 이후 수락 원본 격리 보존, 최신 삭제 의도 재적용, 마지막 정상 View stale 표시를 수행한다.
- [ ] requested/run/pass/fail/skip/not-run, 합성/실모델/실서비스/실기기, 기존 실패/신규 회귀를 분리 보고한다.

## 릴리스별 gate
|Gate|필수 범위|증거|
|---|---|---|
|R1|P00–P07, P10, P11-R1|실 iPhone 공유→영속 receipt→원문→사건→검색/타임라인→Obsidian→정정→5 surface, MyNotes 보존, fresh restore|
|R2|P08/P09, P06 관계 패널·P07 전달 고도화, P11-R2|질문 예산/quiet hours, 잠금300문항, scope/시간, 중복·stale 처리|
|R3|P12–P14, P11-R3|GPS/건강 실제 권한·결측·배터리·삭제, 예측 cutoff/미채점/기준선 비교|

P11 전체 완료가 R1 착수의 순환 의존성이 되지 않도록 R1/R2/R3 체크를 분리한다. R3 표본이 부족하면 코드 구현과 품질 인수 상태를 나눠 보류한다.

## 24개 인수시험 실행 책임
#3의 AC-01–24를 그대로 추적한다. P11 직접 책임은 AC-16(접수/원장/게시/ACK 경계 종료), AC-18(복원·오프라인 단말 삭제), AC-21(rollback), AC-24(전체 회귀)이며 나머지는 해당 작업의 증거를 독립 검증·통합한다. AC-06/07/08/09/17 실기기 View와 AC-22 위치/건강을 mock 성공으로 대체하지 않는다.

## 성능·사용자 평가
10만 사건/동시3 timeline p95≤1초, recall 검색 p95≤3초(모델 생성 별도), 100개/5MB View LAN 전경 p95≤10초는 계획 목표다. 하드웨어·warm/cold·모델·실측 조건을 고정하고 P00 결과로 갱신한다. 7일 실사용 관찰은 구현 뒤 실행할 인수 단계이며 이번 PR에서 실행/예약된 것이 아니다.

## 기본 실행과 증거
확인한 root에서 `uv run pytest -q`, `uv run ruff check sb tests`. 새로운 시험 파일/명령은 실제 생성·존재 확인 후 실행한다. deterministic failure injection을 사용하고 시간 sleep을 성공 동기화로 사용하지 않는다. 실제 로그, baseline/candidate revision, DB schema/count, source/hash/ID 비교, 기기 build, recovery journal, 비용/자원, 독립 리뷰를 보존한다.

## 중단·완료
원본 유실/사용자 메모 변경/범위 누출/삭제 기억 부활은 해당 릴리스 NO_GO다. 조건부 인수는 정확한 미완료 범위를 열거한다. 코드 rollback과 DB 복원을 구분하고 사용자 MyNotes를 어떤 경우도 자동 덮지 않는다. 현 PR은 문서 1개; 구현/회귀/실기기/복구/성능/7일 관찰 모두 NOT_RUN.
