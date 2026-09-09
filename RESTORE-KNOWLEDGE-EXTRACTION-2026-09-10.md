# 검증된 복원 원장의 지식 상태 추출

기준 제품 f1b9827. restore_source.read_restore_knowledge를 구현했다. 운영 원장과 백업 세대 검증을 먼저 수행하고, read-only SQLite snapshot에서 bound_knowledge와 records의 page_id/content_digest가 모두 일치하는 행만 불변 BoundKnowledge 값으로 추출한다. 외부 registry의 승인이나 오래된 본문 상태를 가져오지 않는다. 상태가 없으면 빈 tuple을 반환한다.

추출 후 같은 source 검증을 다시 수행해 읽는 동안의 원장 변조를 거부한다. SQLite 파일을 destination으로 복사하거나 내용을 갱신하지 않는다. 반환 상태는 원본 sealed records의 bytes에 대한 것이며, sanitized 복원 결과의 실제 bytes가 같은지는 후속 단계에서 반드시 대조해야 한다.

실제 GenerationStore로 봉인한 원장의 정상 상태, 같은 ID의 과거 digest 제외, 무상태 세대, 행 추출 직후 원장 bytes 변조를 테스트했다. 기존 source 주장/anchor/원장 변조 테스트 포함 **11 passed / 1.76초**, Ruff 전체·diff와 restore_source 타입 0오류/0경고.

실제 sanitizer에 상태 쓰기 연결, 접근 요구사항/source 분류 추출, 정제 본문 digest 대조, metadata 재유입·철회/정책 검사, 운영 원장까지 소실된 DR는 아직 남는다. 이 단계만으로 정상 백업의 상태 복원이 완료된 것은 아니다. 새 계약/승인 흐름 변경 없음. 실제 JARVIS 세션·업무·설치/운영 및 M1–M14도 남는다. 전체 suite 재실행 없음. 운영 DB·서비스·공용 registry 변경과 push 없음.
