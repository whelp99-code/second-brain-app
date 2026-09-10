# 완료 이동 실패를 배치 실패에 반영하고 재시도 복구

검사 결과 수집기 scan은 매번 _scanned를 초기화하고, pipeline은 이미 원장에 커밋된 source version도 acknowledge에 전달한다. 이 재시도 계약은 유지했다.

실제 run_ingest에서 .done 외부링크로 완료 이동을 차단했으나 기존 _move_done이 OSError를 삼켜 status=ok/errors0/exit0을 반환했다. 새 테스트는 이 상태에서 실패했다. _move_done이 이동 오류를 호출자에게 전달하도록 수정하고 pipeline의 기존 acknowledge 오류 집계에 SOURCE_ACKNOWLEDGEMENT_FAILED 사유를 연결했다.

최종 실제 pipeline 검사: 첫 실행은 오류1/비정상exit/명시적사유, 원문은inbox에남고 외부디렉터리비어있음. 원장 source item1개는커밋되어있다. 링크를제거하고 두번째 run_ingest를 실행하면 오류0/exit0/written0이며 원문이정상.done으로이동하고 source_items가완전히같다. 중복수집없이이미커밋된입력을정리했다. 테스트의원장관측은load_ledger_tables로읽기전용이며 초기테스트가봉인원장을Ledgerwriter로열던실수는수정했다.

관련inbox/재개/walking skeleton포함22passed/5.19초. Ruff전체/diff통과. 변경모듈type검사0오류,기존pipeline461행의미사용반환값경고1개. 전체회귀/설치인수를다시수행한결과로확대하지않는다.

실제운영데이터/서비스변경없음. 원문검증과rename사이의교체경합·기존done파일보존정책·실제업무계보/운영전환및M1–M14전체목표는남는다.
