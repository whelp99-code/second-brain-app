# 공유 읽기 연결의 원장 변경 차단 검증

연결 재사용 이후 검증 공백을 확인했다. 기존 batch inventory 변경 검사는 scope 없는 경로만 직접 시험했으므로 동일 테스트를 scope 유무 두 경로로 확장했다. 실제 페이지를 읽은 다음 같은 원장의 page_access를 삭제하고 커밋하면 두 경로 모두 context 종료 시 MEMORY_ACCESS_UNAVAILABLE이며 reader 재사용도 거부한다.

scoped 검색 결과 버퍼링 검사도 manifest 삭제와 실제 page_access 삭제 두 경우로 확장했다. 기존 권한 검사가 통과한 직후 실제 파일/SQLite 변경을 주입하며 search_scoped_records는 결과 목록을 반환하지 않고 실패해야 한다. 변경은 봉인 fixture의 권한을 시험에서 명시적으로 해제해 수행했다. 정상 운영 writer가 sealed 원장을 변경한다는 뜻은 아니다.

관련 memory access/scoped search/독립 writer 동시성 **21 passed / 13.96초**, Ruff sb/tests 및 diff 통과. 제품 수정 없이 현재8e5b4a3의 실제 shared connection 경로를 검증했다. 지속된 변조를 확인한 것이며 일시 변조 후 원상복구하는 모든 경합·운영 쓰기 권한·사용자 업무 인수를 증명하지 않는다. M1–M14 전체 목표 유지.
