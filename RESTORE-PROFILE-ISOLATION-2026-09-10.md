# 복원 acceptance의 계약 프로필 고정

기준489504a. JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=scoped-record-read-v5를 지정해 기존 복원 acceptance를 실행하자 reference 읽기에서 MEMORY_REFERENCE_PROVIDER_UNAVAILABLE, exit1을 재현했다. reference/effect fixture가 contractProfile을 생략해 외부 환경변수에 따라 다른 계약으로 실행됐다.

reference transport_options와 공유 referenceEffectFixture에 task32-schema4를 명시했다. 기존 scoped client는 scoped-record-read-v3 명시를 유지한다. 제품의 사용자 환경변수 처리나 계약 자체를 변경하지 않고 acceptance가 검증하려는 경로를 고정한 수정이다.

같은 상위 v5 환경변수를 유지한 최종 전체 acceptance exit0. 실제 삭제/증명/복원/highwater1, 삭제0/유지1, scoped 허용1/제한0, 응답 직후 페이지/검색 정책철회2경계 거부와 정책복구 성공을 확인했다. [결과](RESTORE-PROFILE-ISOLATION-2026-09-10.json), 증거 /var/tmp/sb-jarvis-restore-tIR8e1. Node 두 변경 파일 구문 및 diff 검사 통과. 제품 코드 변경이 없어 전체 suite 반복 없음.

재현: `TMPDIR=/var/tmp PYTHONPATH=. JARVIS_SECOND_BRAIN_CONTRACT_PROFILE=scoped-record-read-v5 node scripts/jarvis-restore-acceptance.mjs /absolute/isolated-jarvis-build/dist`. 실제 실행은 기존195b1a7 격리 빌드를 사용했다. 합성 세션·권한·자료라는 기존 제한을 유지한다. 운영 DB·서비스·타 리포 변경과 push 없음. 실제 업무·운영 인증/배포·DR 및 전체 목표는 미완료다.
