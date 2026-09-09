# 다른 에이전트·세션의 복원 기억 공유

기준4cf7b52. 실제 자비스/ provider 복원 acceptance에 두 번째 agent/session과 별도 scoped client/stdio transport를 추가했다. 각 client의 정책·provider scoped 설정 파일도 별도로 저장한다. 실행은 순차이며 동시 처리 성능이나 병렬 쓰기 시험은 아니다.

agent:restore/session:restore와 agent:restore-peer/session:restore-peer가 동일 복원 generation binding과 동일 page_content_digest를 받는 것을 확인했다. generation_id는 이번 sanitizer가 생성·격리 활성화한 세대 ID와 정확히 같고 본문 digest는 SHA-256 형식이다. 각 client에서 project:a 허용1페이지, project:b 직접 조회 거부/검색0, readPage/search 응답 직후 정책철회 거부 및 정책 복구 후 정상 조회를 검사한다.

최종 실제 실행exit0, 증거 /var/tmp/sb-jarvis-restore-HwIUCj, [결과](RESTORE-MULTI-CLIENT-2026-09-10.json). 삭제 기억0/남은 기억1, shared_restored_memory_equal=true. 상위 환경변수는 의도적으로 scoped-record-read-v5를 유지했고 명시 task32/v3 경로로 정상 실행됐다. Node 두 파일 구문·diff 검사 통과. 제품 소스 변경은 없으며 전체 suite 반복 없음(최신 제품 기준1690통과/2skip).

재현: `TMPDIR=/var/tmp PYTHONPATH=. JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=scoped-record-read-v5 node scripts/jarvis-restore-acceptance.mjs /absolute/isolated-jarvis-build/dist`. 기존195b1a7 receipt의 격리 빌드를 사용했다.

실제 제품 issuer/client/stdio와 삭제·복원 경로지만 두 agent/session은 시험용 식별자이고 session source/정책/권한/자료도 fixture다. 서로 다른 실제 모델의 로그인/사용자 업무를 검증한 것은 아니다. 권한을 전역 공유하거나 에이전트별 별도 정본 DB를 만들지 않는다. 운영 DB·서비스·타 리포 변경과 push 없음. 운영 인증·native 업무·DR/삭제 수명 및 전체 M1–M14 목표는 미완료다.
