# P02 — 원장·개정·근거·삭제 계보

명세 등록 / 제품 구현·실행시험 NOT_RUN. Refs #3. 선행 P01 #5. R1 / REQ-01·REQ-06·REQ-08 / Core / 5–8인일 추정. 기준: 개발계획 3.2·4.5·5.2·12·17장. 원문 버전·hash는 #3.

## 목표와 경계
기존 ledger 체계에 생활 사건을 추가한다. CAS 원본, 사건 개정, 처리 원장, 커밋된 Vault의 역할을 보존하며 별도 기억 정본 서버를 만들지 않는다. 접수와 처리·검색·View 완료를 구분한다.

## 구현 체크리스트
- [ ] 기존 migration/transaction 구조를 조사하고 life_events, revisions, evidence_links, 처리 receipt와 projection 계보의 추가형 migration을 설계한다.
- [ ] source_id/item_id/version+멱등키를 검증한다. 동일 키·동일 payload는 같은 receipt, 동일 키·다른 payload는 충돌로 처리한다.
- [ ] 원본과 receipt가 영속 보존된 뒤에만 202/accepted를 반환한다. partial/quarantined/failed를 성공으로 숨기지 않는다.
- [ ] accepted→processed→searchable→projected 상태를 별도 저장하고 retry/replay 시 각 부작용이 중복되지 않게 한다.
- [ ] event_id는 유지하면서 revision을 증가시킨다. expected_revision 불일치는 409, 원본은 자동 overwrite하지 않는다.
- [ ] 사건 revision과 기존 record ID/digest/source/span을 연결한다. 기존 기억 식별자를 전면 재계산하지 않는다.
- [ ] 정정·삭제·출처 정책 철회를 검색/타임라인/관계/브리핑/예측 입력/View manifest까지 전파한다.
- [ ] Tombstone과 단말 ACK high-water를 보존하고 복원 시 오래된 개정보다 삭제 의도를 먼저 적용한다.
- [ ] 단일 writer 및 세대 게시 경계의 종료·재시작을 결정적으로 재현한다. 새 상주 queue/event bus는 추가하지 않는다.

## 데이터·인터페이스
예상 API는 events:batch와 receipts/{id}, corrections adapter이며 기존 인증·요청 경로와 충돌을 먼저 확인한다. 날짜만 cursor로 사용하지 않고 동률을 깨는 ID와 generation을 결합한다. 상태 조회는 빈 성공 대신 원인·재시도 가능 여부를 준다. 임의 raw path를 외부에 노출하지 않는다.

## 예상 코드·소유
`sb/store/ledger.py`와 기존 migration/접수/정정 경로를 통합 담당이 소유한다. 작은 life 저장 helper는 필요할 때 추가한다. `sb/vault.py`, `sb/pipeline.py`는 지정 통합 담당만 수정한다. 현 PR diff는 이 명세 파일 1개다.

## 인수시험
- AC-01/02: 10회 재전송 후 사건 1개; 다른 날짜 사건 2개.
- AC-09: 같은 사건 정정 후 검색·타임라인·브리핑·관계·Obsidian에 동일 개정 적용.
- AC-16: receipt/원장/게시/ACK 직전 종료와 새 프로세스 재개 후 영속 수락 유실 0, 허위 완료 0.
- AC-18/21: 삭제→백업 복원/오프라인 단말 재접속에서 부활 방지, pending replica 상태 보고.
- 동일 시각 다른 ID, 순서 역전, disk-full/transaction 실패, revision 경합, 중복 키 다른 본문을 시험한다.

## 이관과 롤백
기존 원본 hash와 MemoryRecord ID/digest를 고정 비교한다. 처음에는 선택 100건 dry-run으로 시간 미상/격리/중복/삭제 상태를 보고한 뒤 승인된 범위만 backfill한다. 코드 rollback과 DB 복원을 구분하고 백업 이후 수락 원본과 tombstone을 보존한다. feature OFF도 철회 적용을 멈추지 않는다.

## 완료 증거
migration 전후 schema/count/ID 비교, 요청-원본-사건-파생 lineage, 장애 주입 로그, fresh restore, 기본 pytest/Ruff, 독립 검토. 현재 모두 NOT_RUN. 문서 merge는 구현 인수가 아니다.
