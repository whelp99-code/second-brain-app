# 효과 이후 제한 접근 분류 재결합

기준 c3417a3. 실제 부분 forget에서 같은 owner/project/policy의 classified_page가 MEMORY_ACCESS_UNCLASSIFIED로 실패함을 재현했다. knowledge 상태는 새 본문에 결합됐으나 page_access는 과거 digest에만 남아 있었기 때문이다.

## 변경

새 effect_access는 effect 직전 실제 본문 digest와 일치하는 PageAccess를 캡처한다. 이미 접수된 effect와 지식 상태 기록이 성공하면, 남은 변경 본문에 기존 source_refs 전체와 complete 값을 그대로 다시 결합한다. 삭제한 source의 요구사항도 임의로 줄이지 않는다. 이는 보수적인 접근 제한 유지이며 삭제된 CAS 원본이 아직 존재한다고 주장하는 새 인용은 아니다. 인용 출처는 기존 erasure의 memory-effect 재결합 경로를 따른다.

지식 승인 여부와 접근 요구사항은 독립적으로 처리한다. 미분류는 새 권한을 얻지 않고 incomplete는 그대로 incomplete다. 저장 충돌·오류는 EffectAccessRebindError로 구분하여 기존 lease/요청 파일을 보존하는 reconciling 경로에 연결한다. 실패 staging은 공개하지 않는다. 기본 요청 접수·scope·tombstone·세대 계약 검사나 권한을 완화하지 않았다.

## 검증

- 실제 부분 삭제 후 동일 owner/project/policy의 classified_page와 require_scope 성공, 다른 owner/project/policy 모두 거부. 최초 결함 1건 실패를 재현하고 수정했다.
- 초기 실제 부분 삭제/기존 memory_access/page_access 회귀: **22 passed / 24.44초**.
- 새 helper 7분기(complete/incomplete/missing/stale/deleted/failed/conflict), 실제 정정 lifecycle 및 SIGKILL 회귀: **16 passed / 37.79초**.
- 최종 실제 부분 삭제 lexical/hybrid×외부 철회×정상/knowledge 저장 실패/access 저장 실패: **12 passed / 25.20초**. 실패 시 reconciling, 새 executor의 재처리 proved, tombstone 중복 없음과 접근 제한 보존을 함께 확인했다.
- Ruff 전체·diff, 새 effect_access 및 request_executor 타입 0오류/0경고.

이는 실제 provider 분류/read gate 검증이며 새 JARVIS 인증 세션에서 서명된 claim을 발급해 끝까지 회수한 인수는 아직 아니다. 계층별 기존 검사와 네트워크 실사용 인수는 구분한다. source_refs 전체를 보존하므로 부분 삭제 이후에도 더 엄격한 과거 요구사항이 남을 수 있으며, 안전한 요구사항 축소는 이번에 구현하지 않았다.

정상 복원 접근/지식 상태, 미검증 페이지의 부분 기록 정책, 취소와의 경쟁, 최신 설치 쌍·실제 사용자 업무·운영 및 M1–M14는 남는다. 이번 제품 변경 후 전체 suite 재실행은 아직이다. 운영 DB·서비스·공용 registry 변경과 push 없음.
