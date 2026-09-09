# OMO/GJC 부분 기록 및 GJC 헤더 재개 우회 수정

두 수집기도 작성 중인 JSONL 마지막 줄을 malformed-json으로 소비하고 cursor를 파일 끝으로 옮겨 완성된 기록을 놓쳤다. 실제 소비 위치를 반환하고, 개행 없는 불완전 JSON/UTF-8 줄 앞에서 cursor를 보존하도록 수정했다.

GJC는 header_pending을 start==0에서만 활성화했다. 처음 live-session-store 또는 unsupported-version으로 거절된 파일에도 전체 크기를 cursor로 저장했기 때문에, 이후 본문이 추가되면 재개 시 헤더를 검사하지 않고 수집했다. 이제 실제 파일 읽기를 재개할 때 첫 비어 있지 않은 줄을 다시 검증한다. cursor는 export 허용의 증거가 아니다. 과거 방식의 파일 끝 cursor를 명시적으로 전달하는 경우도 차단한다.

부분 헤더는0에서 보류하고, 유효한 헤더가 완성되면 이어서 처리한다. 개행으로 끝난 잘못된 헤더는 malformed-json, 비공개 세션 헤더는 live-session-store, 미지원 export 버전은 unsupported-version으로 거절한다. 거절 시 cursor0을 유지하므로 변경되지 않은 잘못된 파일도 후속 검사에서 다시 거절될 수 있다.

검증:
- 초기 회귀4실패→관련35통과. 부분 한글/JSON, 부분 헤더, 정상 resume, 기존 golden/secrets/unsupported, 과거 cursor를 통한 우회를 포함한다.
- 전체 **1,367 passed / 2 skipped / 231.54초**, 선택 embeddings 제외. 관련35개는 전체에 포함한다.
- 변경 모듈 basedpyright 0 errors/0 warnings. Ruff check 통과. GJC의 기존 MATCH_OK noqa 표기2곳에 대한 형식 경고는 유지돼 있으며 이번에 도입한 것은 아니다.
- 독립 프로세스10개: OMO/GJC 각각 부분기록0→완성1→재조회0(각3프로세스), GJC의 live/unsupported 각각 첫 거절→본문 추가·과거 cursor 재개도 거절(각2프로세스). 합성 공개 export 입력의 실제 connector 프로세스 검증이며 실제 OMO/GJC 앱 세션·자비스 공유 완료의 증거는 아니다.

[결과 JSON](EXPORT-SESSION-RESUME-2026-09-09.json), [회귀 검사](tests/test_session_export_resume.py).

이로써 확인한 Codex/Claude/OMO/GJC의 부분 줄 cursor 문제를 수정했다. 동일 크기 파일 교체, 다중 root의 상대 경로 충돌, 과거에 이미 잃은 기록 복원 등 모든 수집 수명주기를 검증한 것은 아니다. 영구 손상된 개행 없는 tail도 자동 건너뛰지 않는다. 운영 cursor/vault/서비스는 변경하지 않았다. 실제 인증 A→B 공유·클라이언트별 자동 주입·삭제/복원·검색·GUI와 전체 M1–M14는 남는다.
