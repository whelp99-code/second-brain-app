# 삭제 후 유지된 관리 백업의 복원·조회

기준4e00cac. 관리형 runtime 백업 선택적 처분 검증을 확장했다. 무관한 백업은 inbox 대기 파일만 담는 대신 실제 기억 페이지를 generation mutation/materialize_remember로 생성한 뒤 backup_runtime으로 보관한다. 다른 provider의 실제 forget 완료 후 유지된 tar bytes가 그대로임을 확인하고, restore_backup으로 새 격리 폴더에 해제해 SearchIndex reference 검색을 실행한다.

결과: 무관한 'preserve unrelated archived memory'1건과 실제 본문 회수, 삭제 대상 ExampleAlpha 검색0건. 대상 백업 제거·무관한 백업 전체 bytes 동일·삭제 high water1 검사는 유지했다. 관련23 passed/7.46초, Ruff sb/tests 및 diff 통과. 제품 코드 변경 없음.

이것은 합성 두 provider/실제 라이브러리·SQLite·tar·검색 경로의 검사다. 유지된 백업의 raw restore 및 reference 조회를 확인했으며 sanitizer 권한 검증이나 운영 활성화까지 수행하지 않는다. 백업의 archived control journal을 현재 권한으로 승계하는 근거가 아니다. 운영 사용자 백업이나 서비스를 변경하지 않았다.

운영 전환·원장소실 DR·native 세션 전체 삭제 수명·실사용 질문/업무 등 전체 M1–M14는 미완료다. push 없음.
