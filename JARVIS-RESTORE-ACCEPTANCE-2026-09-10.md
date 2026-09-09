# 자비스 자체 삭제 이력으로 복원 기억 조회

기준 SB fb1dcf3(제품 전체 회귀 기준0445d7e), JARVIS 격리 빌드 /var/tmp/jarvis-current-pair-_mq15nmd/source/dist. 빌드 receipt의 source_commit은195b1a7이다. 제품 코드는 변경하지 않고 재현 가능한 두 acceptance 스크립트를 추가했다.

실제 실행 순서:

1. 표식이 있는 임시 provider/authority를 초기화하고 삭제할 합성 기억과 남길 합성 기억을 준비한다. 남길 기억은 fixture 전용 세대 생성 경로로 준비했으며 사용자 쓰기 승인 흐름을 통과했다고 주장하지 않는다.
2. 자비스 production reference reader로 원본 record를 읽고 전체 provider 세대를 백업한다.
3. 기존 referenceEffectFixture를 사용해 자비스 MemoryTombstoneChain에 삭제 이력을 추가한다. 실제 target resolve→서명 요청 접수→provider apply→자비스 disposition proof/observation 검증을 거친다. 자비스/ provider 이력 번호1, provider proved다.
4. createProductionMemoryReadFence가 자비스 authority에서 번호1/root를 읽어 발급한 status fence로 실제 sanitizer를 실행한다. provider 값을 자비스 원장에 복사하는 우회는 없다.
5. 검증용 store에서 복원 후보를 명시적으로 활성화한다. 실제 자비스 reference reader의 삭제 기억0개·남은 기억1개를 확인한다. 복원 세대의 번호/root가 자비스 fence와 같고 blocked_matches/scan_errors 모두0이다.

최종 실제 실행 exit0. 증거 디렉터리 /var/tmp/sb-jarvis-restore-xlIAmG, [구조화 결과](JARVIS-RESTORE-ACCEPTANCE-2026-09-10.json). 초기 자료 준비 시 구형 단일 request fixture 재사용은 WRITE_REQUEST_REPLAY_CONFLICT, 여러 줄 payload는 WRITE_REQUEST_INVALID로 거부됐다. 제품 검증 규칙은 바꾸지 않고 단일 별도 합성 페이지를 fixture로 준비했다. 이후 최초 성공 뒤 registry 경로까지 임시 경로로 명시해 최종 실행을 재검증했다.

재실행: `TMPDIR=/var/tmp PYTHONPATH=. node scripts/jarvis-restore-acceptance.mjs /absolute/isolated-jarvis-build/dist`. Python restore-probe는 .jarvis-memory-probe 표식이 있는 격리 경로만 대상으로 하며 운영 CLI의 restore 기능을 추가한 것이 아니다. 실제 시계와 stdio 제품 경로를 사용하고 모델 호출은0이다. 모든 원본·키·권한 근거는 synthetic fixture이며 사용자 실업무·운영 인증/승인의 인수 증거는 아니다.

Ruff sb/tests 및 새 Python 스크립트 통과, Node 구문·diff 검사 통과. 제품 코드 변경이 없어 전체 suite를 반복하지 않았다. 최신 전체 기준은1690통과/2skip이다. 실제 프로젝트별 scoped client에서 복원된 접근 요구사항 소비, 운영 journal 소실 DR, 운영 전환·사용자 업무·native 수명 및 M1–M14는 남는다. 운영 DB·서비스·다른 리포 변경과 push 없음.
