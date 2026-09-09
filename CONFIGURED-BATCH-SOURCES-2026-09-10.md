# 원본을 생략한 배치의 설정 밖 커넥터 수집 차단

원본 목록을 생략한 run_all/ingest는 discover된 기본 커넥터와 설정으로 확장한 커넥터를 모두 선택했다. sources에 inbox만 지정해도 기본 세션 커넥터가 포함됐다. 이 동작을 두 회귀에서 재현했다. 원본 변경 감지 검사 자체는 수정하지 않았다.

sources 키가 명시된 설정에서 source_ids=None이면 해당 설정의 source ID만 선택한다. sources=[]는 자동 수집0개다. sources 키 자체가 없는 기존 설정의 기본 탐색과 호출자가 명시적으로 지정한 원본 선택은 유지한다. 따라서 이 변경은 암묵적 배치 선택을 제한하며, sources를 모든 명시적 요청에 대한 권한 목록으로 바꾼 것은 아니다.

최종 관련 configured selection/CLI/run_all/runtime reliability **67 passed / 9.66초**, Ruff/diff 통과. 같은 실제 Claude 기억이 있는 관리형 임시 저장소에서 선택 원본 inbox1개, ingest/compile/batch 모두 ok·errors0·written0으로 재실행했다. 과거 수집 실패와 batch 실패 이력은 남았다. 현 원장의 source_id별 확인에서는 inbox1행만 있었다. 다른 저장소·과거 전체 이력까지 영향이 없었다고 주장하지 않는다.

첫 검증에서는 읽기용 SQLite 연결을 with conn만 사용해 닫지 않은 채 run_all을 호출했다. 세대 처분이 GENERATION_READER_DRAIN_REQUIRED로 거부됐다. 검증 프로세스 종료 후 contextlib.closing으로 연결을 명시적으로 닫아 다시 실행했고 정상 완료했다. reader 보호를 완화하지 않았으며 기존 세대 복구 절차를 사용했다.

새 HTTP 서버에서도 last_batch=ok 및 기존 wiki 검색1건을 확인했다. 다만 일반 웹 검색의 knowledge/approval이 UNKNOWN, verification=UNVERIFIED로 반환됐다. 이 결과는 검색 가능 증거이며 승인·검증 상태까지 정상이라는 의미가 아니다. 관리형 검색의 레지스트리 상태 연결은 후속 대조 대상으로 남긴다. [실행 원본](CONFIGURED-BATCH-SOURCES-2026-09-10.json).

기존 source mutation 오류에서 어느 기본 커넥터의 어떤 파일이 변경됐는지는 원장에 기록되지 않아 특정하지 않았다. 설정 밖 탐색 결함은 재현됐고 선택 제한 후 동일 저장소 배치는 정상이다. 운영 서비스·공용 레지스트리 변경 없음. 최신 설치 후보 반영·전체 운영 M1–M14는 남는다.
