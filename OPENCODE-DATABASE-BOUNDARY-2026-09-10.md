# OpenCode snapshot DB 참조 경계

실제 SQLite part 테이블 fixture로 절대 경로·../부모 경로·디렉터리 symlink를 통해 snapshot 폴더 밖 DB 본문이 수집되는 것을 재현했다. 기존 최종 파일의 is_symlink만으로는 상위 디렉터리 링크를 막지 못했다. 별도로 export?#.sqlite 파일명은 URI 문자열에 직접 붙여 파일 경로가 잘못 해석되어 정상 수집이 실패했다. 네 회귀 모두 수정 전 실패했다.

DB 참조는 snapshot 폴더 아래의 상대 경로만 허용한다. 절대/부모이탈/빈 경로/역슬래시/NUL 및 경로 구성요소 symlink는 unsafe-database-path로 보고하고 본문을 반환하지 않는다. 선택 경로의 resolve 결과도 기준 폴더 안인지 검사한다. SQLite URI는 Path.as_uri로 인코딩하고 기존 mode=ro&immutable=1을 유지한다. 외부/절대 DB를 요구하는 snapshot은 이 경로로 지원하지 않으며, 독립 export 폴더 안의 상대 참조로 제공해야 한다. 원본 파일을 자동 이동하지 않는다.

검증: 실제 외부 DB3경로 본문0/명시적거부, 특수 문자 파일명 정상 본문1·DB bytes 불변. 관련 OpenCode/세션/교체 **47 passed / 0.63초**, Ruff sb/tests·변경모듈 basedpyright0오류0경고·diff 통과.

이번 수정은 명시적 참조 경로와 현재 symlink 상태를 검사한다. 검증과 SQLite open 사이의 파일/상위 디렉터리 교체까지 descriptor로 고정한 것은 아니며 모든 경합을 차단했다고 주장하지 않는다. 크기 기반 cursor·참조DB 변경 감지·읽기 상한은 남는다. 운영 계정·DB·서비스 변경 없음. 사용자 업무·전체 M1–M14 완료 조건 유지.
