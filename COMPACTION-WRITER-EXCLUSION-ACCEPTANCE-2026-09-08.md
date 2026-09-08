# DB 재구성 중 쓰기 유실 경합 수정

2026-09-08. JARVIS `830ca2d`, Second Brain 제품 `9e30115` 유지.

## 발견과 수정

취소 완료 증거 연결을 검토하던 중 기존 compactor의 runtime 쓰기 배제가 파일 교체 내부에만 있음을 확인했다. fresh DB를 만든 뒤 기존 DB에 쓰기가 들어가면 만들어진 새 DB에는 그 변경이 없으므로 교체 때 유실될 수 있다. 키 철회를 입력한 회귀 검사에서 수정 전 runtime 쓰기가 거부되지 않아 실패했다.

compact 진입 시 진행 중인 runtime lease를 drain하고, authority 확인·검증 재료 수집·fresh DB 생성·사본 처분·파일 교체·전체 검사·완료 저장을 하나의 quiesce 구간에서 수행하도록 수정했다. recover의 검사·완료 저장도 같은 배제 구간에 넣었다. private swap의 중복 quiesce는 제거했다.

기존 진행 중인 쓰기는 먼저 완료하고 그 변경을 새 DB로 복사한다. 구간 중 새 runtime 쓰기는 AUTHORITY_DATABASE_QUIESCING으로 거부한다. 구간 종료 뒤 새 쓰기는 다시 허용된다. 호출자는 이 거부를 처리해야 하며 자동 재전송을 추가하지 않았다.

## 검사와 실제 사용 검증

- 최종 관련 3파일 **15 passed, 75.80초**: 정정 완료/복구/증거 손실 11개, 취소 DB 교체/새 쓰기 거부/기존 쓰기 보존 3개, 독립 프로세스 old-FD drain 복구 1개.
- 수정 전 주입 검사: 새 DB 생성 후 쓰기가 허용되어 기대한 거부 오류가 없었음. 수정 후 동일 지점에서 거부됨.
- TypeScript 격리 emit, 대상 ESLint, git diff check 통과. 운영 dist를 갱신하지 않았다.
- 실제 Node PID450564: 파일시스템 watcher가 실제 .fresh 생성 이벤트를 받은 순간 runtime.write를 호출했다. AUTHORITY_DATABASE_QUIESCING 거부, 실제 inode 교체, integrity_check=ok를 확인했다. 완료 후 키 철회 쓰기는 성공했고 다른 AuthorityDb 연결에서도 revoked를 읽었다.

[실행 증거](COMPACTION-WRITER-EXCLUSION-ACCEPTANCE-2026-09-08.json), [인수 스크립트](scripts/cancellation-compaction-writer-acceptance.mjs).
원본 `/var/tmp/cancellation-compaction-writer-bIOiwp/result.json`. 스크립트는 격리 build 경로를 인수로 받고 JARVIS 루트에서 실행한다. 실제 임시 DB와 runtime·파일 교체를 사용하며 provider/guard inventory는 synthetic fixture다. 실제 provider 취소의 전체 완료 인수로 해석하지 않는다.

## 남은 제한과 후속 순서

이번 배제는 해당 AuthorityDatabaseRuntime의 lease를 사용하는 작업에 적용된다. 직접 DB 연결·다른 runtime 인스턴스·외부 파일 작성자를 전역 차단한다고 주장하지 않는다. native 작성자 등록/정지와 전체 운영 인수는 여전히 필요하다.

이 결함을 먼저 수정했으므로 이번에는 취소 완료 저장·cursor 진행을 구현하지 않았다. 다음은 provider 결과의 범위에 맞는 로컬 DB 교체/검사 증거를 특정 취소에 결합해 저장하고 현재 신뢰와 작성자 배제를 확인하는 경로다. 실제 취소 seq1→정상 V2 seq2, 외부 전송 경합, 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱 재사용, 수집/주입·검색·GUI·복구 목표를 유지한다.

증거 없는 cursor skip·운영 완료 선언은 보류한다. 운영 DB/설정/서비스의 변경·배포·push는 하지 않았다. Second Brain 제품 코드 변경이 없어 Python 전체 검사는 재실행하지 않았다.
