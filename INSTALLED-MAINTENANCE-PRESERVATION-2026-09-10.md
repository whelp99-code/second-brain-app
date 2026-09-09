# 설치 유지관리 후 실제 기억 조회 보존

제품은 기존 eea2c23 설치 후보 8b25969e345af2b11fef8ab60272a0100c5e859c, 검사 스크립트만 개선했다. inbox 파일 존재 검사에서 더 나아가 materialize_remember로 합성 기억 페이지를 활성 세대에 만들고 설치된 SearchIndex의 reference 조회로 한 기록과 실제 본문을 확인한다. 사용자 승인/작업 결과의 증거를 위조하는 시험은 아니며 ACTIVE 승인 조회 인수로 표현하지 않는다.

독립 설치 Python(-I, 임시 cwd)에서 초기 snapshot 이후 다음 세 지점마다 새 프로세스로 조회한다: 살아 있는 복원의 CLI busy 이후, SIGKILL 사본 정리 이후, 정리 재실행 이후. 세 지점에서 활성 generation ID·본문 SHA256·ledger SHA256·삭제 high water·조회1건이 모두 동일했다. 사본 정리1→재실행0, worker exit=-9, 최종 스크립트 exit0.

실제 관측 generation은 sbgen:v1:429ab07d9c2f7e68e0bec8f7081dcc4d7ad593fa8bb19104299550bc9ba1602a, 본문 SHA256 b680c80b76f8cfb13fa0e7917e710e780c0277880b40b788177649e366628b14, ledger SHA256 9318eb37cf50a1194ecac204fa83ad8c8a98f68ca92315ef2ab6bcc855fbc94f. 삭제 high water는0인 격리 fixture이며 삭제2 연동 검사를 대신하지 않는다.

초기 실행은 fixture created_at에 datetime을 전달해 타입 오류로 실패했다. 설치 제품이 요구하는 문자열로 수정 후 통과했다. 제품 계약은 변경하지 않았다. Ruff sb/tests/스크립트 및 diff 통과. 제품 변경이 없어 전체 suite는 반복하지 않았다.

재현: python deploy/check-release-maintenance.py /absolute/installed/release. 설치 후보 경로는 INSTALLED-MAINTENANCE-2026-09-10.md를 따른다. 운영 설치·서비스·DB 변경 없음. 실제 업무·다중 모델·운영 전환과 전체 M1–M14 목표는 미완료다.
