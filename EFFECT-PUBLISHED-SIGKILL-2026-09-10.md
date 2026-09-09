# 승인 기억 세대 전환 직후 SIGKILL 복구

기준 제품 432ed11. 기존 실제 spawn/SIGKILL 테스트에 POINTER_RENAME barrier를 추가했다. 제품 소스는 변경하지 않았다.

자식 RequestExecutor가 실제 부분 삭제와 상태 재결합을 마치고 새 generation으로 active 포인터를 바꾼 직후 Event로 도달 사실을 알린다. 부모는 살아 있는 소유 자식을 SIGKILL로 종료하고 exit=-SIGKILL을 확인한다. 저장 전·저장 후 publication 전 기존 두 경우도 유지한다.

복구 전 이미 활성 generation ID가 이전과 다름을 확인한다. 복구 시 ErasureEngine.apply를 호출하면 실패하도록 감시해 실제 효과가 두 번 실행되지 않음을 검증했다. lease 만료 후 같은 request ID는 proved가 되며, 활성 ID는 죽기 직전에 공개된 ID 그대로다. tombstone 순번/루트도 변하지 않는다. retired/staging 디렉터리는 비고 인용 검사를 통과한다. 삭제 대상 검색 결과는 없으며 남은 기억은 active VERIFIED다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_effect_knowledge_sigkill.py --tb=short`: **3 passed / 7.44초**. Ruff 전체·diff 통과. 테스트 시각과 Event를 사용하며 sleep은 없다. 운영 프로세스는 종료하지 않았다.

전원 손실·디스크 fsync 실패, 정정/취소 경쟁의 SIGKILL, 복원 상태·scoped 접근·실제 업무·다른 모델·최신 설치/운영 및 M1–M14는 남는다. 이번 테스트 추가 후 전체 suite를 재실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
