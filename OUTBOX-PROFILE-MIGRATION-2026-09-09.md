# 자비스 outbox 프로필 구분과 기존 행 보존

2026-09-09. 직전 반환 직전 철회 수정은 진전이었다. 이번 JARVIS `a4ec505`는 scoped 요청 등록의 선행 조건인 기존 worker 소비 경계를 구현했다.

새 migration077은 memory_outbox.request_profile을 추가한다. legacy가 기존 행/등록의 기본값이며 scoped-v4를 명시할 수 있다. 프로필 변경은 불변 trigger로 거부한다. 기존 shipped migration·candidate UNIQUE·승인/처리 guard는 유지한다.

현재 코드의 legacy worker는 dispatch/reconcile claim·불확정 dispatch 복구·control 재조정·목록 조회에서 legacy 프로필만 처리한다. scoped 직접 조회·요청 재구성은 MEMORY_OUTBOX_PROFILE_UNSUPPORTED이며 기존 v2 객체로 잘못 표시하지 않는다. 실제 승인 소비·scoped 등록 API는 아직 연결하지 않았다.

## 검증

- 초기 profile/publication11통과. 확대 outbox/승인/처리/동시성/마이그레이션 **12파일71 passed / 44.38초**. backend 타입·변경 파일 ESLint·격리 emit·helper Ruff·diff 검사 통과.
- SQL routing fixture의 scoped 행에서 runOnce claimed/dispatched/failed/settled0, writer 호출0, 행 불변. 이 fixture는 프로필 분리를 검증하기 위한 행이며 유효한 v4 승인·등록의 증거가 아니다.
- 실제 별도 프로세스2개: migration076까지 적용한 DB의 정상 legacy enqueue1→077 적용. 기존 열 값 모두 불변·queued1 보존·프로필 legacy·migration76→77·FK오류0·quick_check ok. 최신 격리 build로 재실행도 통과했다.
- [JSON 증거](OUTBOX-PROFILE-MIGRATION-2026-09-09.json). `TMPDIR=/var/tmp uv run python scripts/outbox-profile-migration-acceptance.py <격리 JARVIS build> /home/jm/orca/projects/Orca-JARVIS`로 재현한다.

## 다음 작업과 보류

이 분리는 수정된 worker 코드에 적용된다. 실행 중인 이전 바이너리는 새 프로필을 모르므로 v4 등록 전에 worker release/readiness 확인이 필요하다. 새 프로필 값만으로 승인이나 scope 검토 소비를 대신하는 방식은 보류한다.

승인 단일 소비·outbox 원자적 확정·v4 자료 재구성/dispatch·완료 영수증과 실제 provider 권한 및 전체 M1~M14 실사용 인수는 남는다. 운영 DB migration·서비스/설정 변경과 전체 Python/JARVIS 검사 재실행은 하지 않았다.
