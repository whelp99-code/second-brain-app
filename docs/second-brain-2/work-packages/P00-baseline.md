# P00 — 기준선·규칙·복구·모바일 기술 검증

상태: **개발 명세만 등록 / 구현·시험 NOT_RUN**. 통합 트래커: #3.
기준: `Second_Brain_2_Development_Plan_20260926.md` v1.0, 1·3·14·15·17장/부록 B.
원문 SHA-256: `6e2e98dec53128c6211019b6f308e451c35cf2b06c46cc6fb37cf17a2187f400`.
GitHub 시작점: `master@9437b6e24b34a25d8bc1d090a8064cbaad57a7fc`. Ubuntu 운영본과 동일하다고 가정하지 않는다.
릴리스 R1 필수 / 연계 REQ-08, REQ-09 및 전체 / 역할 Core+QA+Client / 선행 없음 / 추정 4–6인일.

## 목표
현재 코드·운영·기기·원본의 실제 상태를 고정하고 후속 P01–P14가 안전하게 작업할 기준과 차단 조건을 만든다. 계획서의 과거 테스트 수·경로·버전을 현재 성공 증거로 재사용하지 않는다.

## 구현 체크리스트
- [ ] 실제 프로젝트 root, branch, commit/tree, dirty 파일과 각 hash, staged, subproject 상태를 읽어 기록한다. 원격/로컬/설치본 차이를 별도 표로 남긴다.
- [ ] 현재 AGENTS/계층/단일 writer/커넥터 자동발견/공개 MCP·API 계약을 대조한다. Mac 경로와 Ubuntu 실행 경로, 접수 원장과 금지된 상주 queue의 차이를 ADR로 명시한다.
- [ ] CAS 원본·ledger·committed Vault·검색 인덱스·View·MyNotes의 소유와 복구 우선순위를 정한다. 기존 MemoryRecord ID/digest 보존을 회귀 기준으로 둔다.
- [ ] 비밀을 제외한 feature flag, schema version, 출처별 수량, 실패·격리·미처리 수, 모델 설치 여부, 자원 사용 기준선을 수집한다.
- [ ] 승인된 분리 환경에 일관된 백업을 복원해 원본·검색·정정·삭제 의도가 보존되는지 검증한다. 운영 SQLite 파일 단순 복사를 성공 백업으로 인증하지 않는다.
- [ ] 실제 Phone History 입력, 서버 TLS/인증, Obsidian Mac/iPhone 설치·전경 pull·토큰 보관·오프라인 읽기 가능성을 작은 spike로 검증한다.
- [ ] 기존 알림 채널과 run surface를 확인한다. payload 생성과 실제 전달 성공을 구분한다.
- [ ] 합성 fixture, 실모델, 실서비스, 실기기별 실행 증거 형식과 24개 AC 담당 범위를 정한다.
- [ ] P01 진행 가능한 항목과 운영/기기 승인 대기 항목을 분리한 baseline report/ADR/risk register를 게시한다.

## 변경 위치와 산출물
이번 PR은 이 Markdown만 추가한다. 후속 구현의 후보 산출물은 baseline report, ADR, fixture inventory, restore runbook, capability matrix다. 기존 소스 점검 대상은 `AGENTS.md`, `sb/contracts.py`, `sb/store/`, `sb/vault.py`, `sb/pipeline.py`, `phone-history/`, `clients/macos/`이며 변경 필요성은 조사 후 확정한다. `clients/obsidian/`는 신규 제안이지 현재 존재 보장이 아니다.

## 입출력·실패 계약
입력은 읽기 전용 코드·메타데이터와 명시 승인된 테스트 자료다. 결과는 확인됨/미확인/실패/해당없음이 구분된 증거 목록이다. 비밀정보나 고객 원문은 보고서에 넣지 않는다. 기존 실패는 그대로 남기고 녹색 상태로 숨기지 않는다. 실행 권한 부족·기기 부재는 BLOCKED/NOT_RUN이며 PASS가 아니다.

## 인수 및 증거
- AC-24: `uv run pytest -q`, `uv run ruff check sb tests`를 확인된 root에서 실행하고 requested/run/pass/fail/skip/not-run과 exit/log를 남긴다. 실제 모델 시험은 별도다.
- AC-21 선행: 분리 복원으로 최신 삭제/정정 상태와 복구 이후 원본·검색을 비교한다.
- AC-06/22 선행: 실제 Mac/iPhone/Obsidian/TLS 경로의 capability를 기록한다. mock 성공을 device closure로 전환하지 않는다.
- [ ] 기준선 artifact와 실제 revision 연결
- [ ] 기존 dirty 변경 전후 불변 확인
- [ ] 복구 불가 상태에서 운영 변경 차단
- [ ] ADR에 기존 계약 유지/필요 변경/미확인을 구분

## 범위 제외·안전 경계
전면 리팩터링, 운영 cutover, 자격증명 변경, 새 DB/queue/승인 서버 도입, force push, 기존 작업 자동 stash/reset은 제외한다. 이번 GitHub 등록은 이후 계정·기기·운영 변경의 포괄 승인이 아니다.

## 다음 단계와 중단
P01 계약 작업의 선행 gate다. 코드·운영본의 불일치가 해소되지 않아도 읽기 전용 명세 검토는 가능하나 운영 데이터 migration은 차단한다. spike는 분리 환경에서 제거 가능하게 하고 사용자의 원본과 기기 설정을 보존한다.

## 현재 증거
제품 구현 NOT_STARTED / 합성시험 NOT_RUN / 실제 모델 NOT_RUN / 실제 서버 NOT_RUN / 실기기 NOT_RUN / 복구 NOT_RUN. 문서 PR 생성·merge는 위 상태를 바꾸지 않는다.
