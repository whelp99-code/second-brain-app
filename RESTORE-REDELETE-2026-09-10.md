# 복원 기억 재삭제와 최초 백업 재복원

기준c40eb00. 실제 자비스 chain/효과/처분증명/provider 복원 acceptance에 후속 삭제를 추가했다. 첫 번째 복원에서 남아 있던 KeepBeta를 실제 자비스 효과 경로로 다시 resolve→서명 요청→provider 적용→처분증명/observation 검증한다. 두 번째 삭제 proved, 자비스 이력번호2를 확인했다.

KeepBeta 재조회0 이후 자비스 production fence 발급자가 같은 authority에서 번호2/root를 발급한다. 삭제 전 최초 백업을 같은 sanitizer에 다시 전달하고 격리 store에서만 활성화했다. 두 번째 복원 generation의 번호/root가 fence와 같으며 surviving_page_id=null, blocked_matches=scan_errors=0이다. 자비스 reference reader에서 DeleteAlpha/KeepBeta 모두0기록이었다. 백업이나 삭제 원장을 초기화하지 않았다.

첫 복원 이후 두 scoped client 동시 조회·동일 세대/본문·독립 정책 철회 검증도 기존대로 통과한다. 결과의 first_restore_surviving_records=1과 second_restore_records=0을 구분하고 jarvis_owned_high_water는 최종값2로 기록한다. 첫 복원 값1을 최종 이력으로 오해하지 않도록 결과 필드도 정리했다.

최종실행exit0, 증거 /var/tmp/sb-jarvis-restore-WpBoeQ, [결과](RESTORE-REDELETE-2026-09-10.json). Ruff sb/tests/Python probe, Node 구문·diff 검사 통과. 제품 변경이 없는 acceptance 확장이므로 전체 suite 반복 없음(제품 기준1690통과/2skip).

이 검증은 기존195b1a7 격리 자비스 빌드, 합성 source/authority/session을 사용한다. 최초 백업은 메타데이터까지 검증되는 전체 generation이지만 운영 journal까지 소실된 DR가 아니다. 실제 업무·운영 인증·native 세션 잔존 사본 삭제·모든 에이전트 지원의 완료 증거로 쓰지 않는다. 운영 DB·서비스·다른 리포 변경과 push 없음. 전체 M1–M14 목표는 미완료다.
