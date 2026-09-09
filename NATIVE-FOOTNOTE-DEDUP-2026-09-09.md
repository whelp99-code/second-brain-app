# 실제 모델 각주와 vault 자동 각주 중복 수정

실제 관리형 Claude 생성 페이지에서 같은 sid의 `origin span=0-33`과 vault가 붙인 `origin` 정의가 함께 나타났다. sb/vault.py의 렌더러는 본문 정의 존재 여부와 무관하게 모든 정의를 추가했다.

## 변경

vault 렌더링에서 SourceCite의 sid·origin과 정확히 일치하는 정의 및 단일 숫자 span 주석을 식별한다. 기존 span 정의를 우선 보존하고 동일 정의 또는 정보가 적은 자동 정의만 제거한다. 없는 출처 정의만 추가한다. backtick/tilde fenced code와 4칸 들여쓴 예시는 정의로 간주하지 않는다. SourceCite의 원문 hash·spans 메타데이터는 변경하지 않는다.

서로 다른 span 주석, 다른 origin, 임의 설명이 붙은 정의는 의미를 추측해 삭제하지 않는다. 이들의 통합·충돌 진단은 후속 항목으로 보류한다. 일반 Markdown 전체를 새로 파싱하는 기능을 구현한 것은 아니다. 운영의 과거 페이지를 일괄 재작성하지 않았다.

## 검증

- 수정 전 새 회귀: 2실패/1통과로 중복 재현.
- 최종 vault/compile/conflict retry/MCP/walking skeleton: **47 passed / 8.25초**, Ruff 및 diff 검사 통과.
- span 정의의 앞뒤 순서, 코드 예시, 서로 다른 span 보존, 읽기→재저장 시 추가 커밋 없음 검증.
- 실제 Claude를 새 임시 관리형 저장소에서 다시 호출했다. ingest/compile exit0, 기본 `python -m sb.mcp` 별도 서버2회 검색/본문 회수 성공. 각주1개·사실·출처·span=0-33 보존. [실행 증거](NATIVE-FOOTNOTE-DEDUP-2026-09-09.json).
- 후속 서로 다른 span 보존 가드 추가 뒤 최종 렌더러로 같은 실제 생성 본문을 다시 읽고 동일 결과를 확인했다. 이 마지막 가드 뒤 모델을 다시 호출하지 않았다.

모든 저장소·상태·registry 경로는 임시 경로였다. 실제 업무 사례·다른 모델 에이전트·자비스 운영 전환 인수는 남는다. 이전 전체1,551통과는 수정 전 기준이며 이번 변경 후 전체 재실행 결과로 표현하지 않는다.
