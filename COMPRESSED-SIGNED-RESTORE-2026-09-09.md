# 실제 gzip 백업의 서명 복원 통합 검증

기존 위치 변경·복제·이동 복원 사례는 디렉터리 입력에 한정됐습니다. 같은 원본에서 실제 gzip tar를 만들고, 원본 파일에서 계산한 manifest와 실제 서명 fence를 사용해 GenerationRestoreSanitizer.sanitize 전체 경로를 실행하도록 테스트를 확장했습니다.

위치 변경/복사/이동 각각에서 삭제 대상 바이트가 최종 후보 전체에 없고, 정상 기억이 유지됐습니다. 성공 proof의 blocked_matches=0, staging 비어 있음, 기존 active 세대 유지도 확인했습니다. 디렉터리와 gzip6개 조합입니다. 실제 서명과 SQLite 처리를 사용하며 업무 내용과 키는 테스트 fixture입니다.

별도 실패 사례에서는 실제 gzip 추출 직후 archive에 바이트를 추가했습니다. RESTORE_ARCHIVE_UNSAFE로 거부하고, 실행 전후 generation 디렉터리 집합 동일, staging 비어 있음, active 세대 동일을 확인했습니다. 원본 변경 주입만 통제했고 압축·파일 읽기·서명·DB는 실제 경로입니다.

검증 명령: uv run pytest -q tests/test_restore.py tests/test_restore_archive_members.py tests/integration/test_memory_restore_reingress.py —30 passed,19.54초. Ruff sb/tests 통과. 제품 코드 변경은 없으며 검증 범위 확장입니다. 실제 사용자 백업 전체, 운영 배포, 여러 native 에이전트 인수는 여전히 남아 있습니다.
