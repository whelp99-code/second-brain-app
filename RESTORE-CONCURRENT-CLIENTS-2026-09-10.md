# 동시 복원 client의 세션 정책 격리

기준4ffe32b. 실제 자비스/provider 복원 acceptance의 두 scoped client를 Promise.allSettled로 동시에 실행한다. 각각 실제 stdio 페이지 조회에 성공한 뒤 rendezvous에서 기다리므로 두 연결이 열린 상태를 확인하고 정책 격리 검사를 수행한다. 실패하더라도 양쪽 helper의 종료를 기다린 후 authority를 닫는다. rendezvous에는20초 실패 제한을 두고 timer를 정리하며 sleep으로 실행 순서를 추측하지 않는다.

첫 세션을 정책에서 철회한 동안 첫 client는 MEMORY_ACCESS_SCOPE_UNAVAILABLE로 거부되고 두 번째 client는1페이지를 반환했다. 정책을 복구한 뒤 반대 방향도 검사했다. 두 독립 철회 모두 통과했고 이후 각 client의 페이지/검색 응답 후 철회·복구, 프로젝트 제한 검사까지 완료했다. 동일 복원 세대/본문 해시 및 삭제0·남은 기억1 조건도 유지했다.

최종 실제 실행exit0. 증거 /var/tmp/sb-jarvis-restore-9P6RFC, [결과](RESTORE-CONCURRENT-CLIENTS-2026-09-10.json): concurrent_clients=2, independent_revocations=2, shared_restored_memory_equal=true. Node 두 변경 파일 구문·diff 검사 통과. 제품 코드 변경 없이 acceptance만 확대했으며 전체 suite 반복 없음(최신제품1690통과/2skip).

이 검증은 두 읽기 연결의 동시 존재와 세션별 정책 격리를 확인한다. 동시 쓰기/운영 부하 성능, 실제 모델 로그인·사용자 업무, 운영 인증이나 모든 에이전트 지원 완료를 증명하지 않는다. 기존 synthetic source/authority/session 및 J195b1a7 격리 빌드 조건을 유지했다. 운영 DB·서비스·다른 리포 변경과 push 없음. 운영/DR·실업무 및 전체M1–M14는 미완료다.
