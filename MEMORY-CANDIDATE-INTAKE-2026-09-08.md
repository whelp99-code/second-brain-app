# 기억 후보 접수 경로 — 구현·검증 후속

2026-09-08. 자비스 구현 커밋 `b89dab6` (부모 `7129b9d`). [후보 화면 연결](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md) 이후 실제 입력 진입점이 없는 공백을 진행했다. 자비스 `MemoryCandidateStore.classify`는 제품 호출자가 없었고 테스트만 사용했다. 기존 분류기를 호출하는 `memory classify <input.json> <policy.json>`을 추가했다. 중앙 기억 저장 완료가 아닌 후보 분류/검토 접수이며 기존 owner 확인과 저장 명령 흐름을 이어 쓴다.

## 변경과 발견된 문제

- 크기가 제한된 일반 JSON 파일·정책을 접수한다. 검증한 fd에서 읽고 JSON 중복 키·손상 UTF-8·symlink·디렉터리·과대 입력·읽기 도중 변경을 거부한다. 원문과 입력 경로를 결과/오류에 넣지 않는다. 입력 파일은 보존한다.
- required_confirmation만으로 review를 생성하던 조건을 awaiting_confirmation으로 수정했다. 거부·만료·no_data는 원문을 review spool에 발행하지 않고 분류 결과를 기록한다.
- 원문 발행과 DB 입력에 서로 다른 시각을 사용하던 P1 결함을 수정했다. writer transaction에서 같은 computation을 사용하고 fsync 후 실제 시각으로 권한·출처·만료를 재검증한다.
- DB commit 전 종료/외부 rollback으로 남은 원문은 durable candidate가 없고 현재 입력·정책·권한으로 원래 시각의 digest를 완전히 재현할 때만 채택한다. 유효한 동일 bytes만 재사용하고 기한을 연장하지 않는다. 다른 내용·손상·만료 orphan은 보존하여 거부한다. 실패 정리도 writer lock과 채택 여부를 재확인한다.
- 만료 후보 감사행의 확인 시각이 이미 과거여서 SQL 제약을 위반하던 경로를 수정했다. terminal rejected/expired에만 제약을 만족하는 now+1ms 최소값을 사용하며 승인 가능 상태로 전환하지 않는다. 유효 후보 TTL과 shipped migration은 변경하지 않았다.

파일·사용법·검증 세부는 [자비스 구현 보고서](../Orca-JARVIS/docs/memory-candidate-intake-2026-09-08.md)에 있다. 독립 검토의 시각 불일치·orphan 지적 두 건을 반영했고 최종 추가 actionable 없음. Second Brain Python 제품 소스는 이번에 변경하지 않았다.

## 실제 연결 검증

하네스에 `--candidate-intake`를 추가해 기존 테스트의 Store 직접 호출 대신 CLI의 JSON 파일 접수로 시작한다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs /var/tmp/jarvis-memory-intake.vnp3_v4g --candidate-intake --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive --after-delete --during-compile --dashboard-progress
```

관측: candidate_intake=true, 민감 record 64개, provider proved, outbox settled, control completed, dashboard_stored=true, 독립 두 번째 MCP 클라이언트 current. 재전송 추가 dispatch 0, review 파일 0개 잔존, cleanup/control 오류 없음, 승인 rollback 복구, 삭제 fence 거부와 삭제 record 회수 0. 컴파일 준비 중 완료/조회 묶음 약 1.381초이며 p95가 아니다. `/var/tmp/sb-jarvis-memory-intake-final-acceptance.log`.

별도 실제 wall clock의 CLI subprocess를 두 번 실행해 한국어 원문 검토 일치·동일 결과 재시도·review 파일 1개·입력 파일 보존을 확인했다. `/var/tmp/jarvis-memory-intake-live-clock.log`. 두 검사는 합성 입력·격리 DB/vault를 사용한다. CLI 프로세스 검사는 실제 시계, MCP 전체 인수는 주입된 시계/승인 fixture다. 실제 Codex/Claude 앱의 자동 수집·주입 검증은 아니다.

회귀: 접수·권한·기존 UI·승인 인계 37 passed / 5 files, 추가 정책·상태·개인정보·동시성 123 passed / 13 files. backend build·변경 ESLint·하네스 Node 구문·diff 검사 통과. 자비스 동시 작업을 섞지 않고 초기 `c4c5c98` archive에 변경을 검증한 뒤 확정된 task completion `7129b9d` 기준의 backend build 및 접수/권한/저장 14개(앞 검사와 중복)도 통과했다. 세부 최종 결과는 자비스 보고서에 기록한다. Python 전체 테스트를 새로 실행했다고 주장하지 않는다.

## 범위 유지·다음 작업

1. **자비스 작업 결과 연결:** 이제 `7129b9d`에 task completion이 커밋됐다. 실제 completion/verification/publication을 기억 내용 digest에 결합하는 검증 계약을 대조해야 한다. 요약을 독립 검증 증거로 만들지 않는다.
2. **approved/no_data 본문 인계:** 유효 authority의 public/personal 입력은 바로 approved 분류가 될 수 있으나 해당 본문의 dispatch publication 연결은 아직 없다. no_data classified 재개도 없다. 이 경로는 저장 가능으로 보고하지 않는다. 새 CLI는 이를 해결한 것으로 표시하지 않는다.
3. **만료/변조 orphan:** 자동 삭제·기한 연장은 보류. 동일하고 유효한 원문만 자동 복구하며, 나머지는 원장 기반 복구/보존 정책을 다음 범위에서 결정한다.
4. **기존 잔여 유지:** 일반 LF/V2 정정, 실제 앱별 공유·수집·주입, project/user 범위, 문맥 예산·전달 이력, 운영 릴리스·readiness·백업 복원, 한국어 검색·부하 평가, 읽기 전용 hybrid.

세컨드브레인 기반/네 OSS 장점 선별 흡수 방향은 유지한다. 새 기억 서버·Proxy·정본 이동·운영 배포·서비스 재시작·push는 없다. 후보 접수 완료를 B4 전체 완료로 축소하지 않는다.
