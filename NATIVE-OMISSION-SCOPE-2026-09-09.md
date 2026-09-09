# 실제 모델의 검색 완전성 과장 수정 — 2026-09-09

JARVIS f0394b9: jarvis_memory_context 도구 안내에서 답변 근거를 ‘available memory’ 전체 대신 ‘returned records’로 한정했다. omission counts는 이번 응답의 필터/예산 정보이며 0이라고 전체 관련 기억 회수나 다른 정보 부재를 증명하지 않는다고 명시했다. payload·계약·검색 임계값 변경 없음.

검증: phone-memory-client 통합 15개, ESLint 통과. git archive 기반 별도 후보 `/var/tmp/jarvis-omission-guidance-3athmydg/source/dist`를 생성해 TypeScript emit/migration 복사를 완료했다. 기존 잠금 의존성 7개 일치 검사 통과. 운영 dist/current는 변경하지 않았다.

새 후보로 실제 Claude Code 2.1.261의 claude-abstention 인수를 실행했다. 쓰기→완료→별도 reader·독립 SDK2개/Claude 도구1회·4경로 전체 exit0. 실제 응답은 insufficient_evidence/value null이며, 설명에 ‘those counts describe this response’s filtering only and do not prove that no such information exists elsewhere in memory’라고 명시했다. 기록 원문에 주소가 없다는 설명도 확인했다. 이전의 ‘nothing relevant was withheld’ 과장은 이번 응답에서 반복되지 않았다. 전체 응답은 동명 JSON에 보존했다.

한계: 하나의 고정 fixture와 한 번의 최종 모델 응답이다. 안내 변경이 모든 모델/질의에서 작동함이나 안정적 성공률을 증명하지 않는다. 호출 query는 fixture의 ‘결정’으로 고정되어 있으며 자율적인 검색 전략은 평가하지 않는다. 모델 의미 평가는 원문 검토이며 자동 검증기는 status/null과 정상 도구 회수만 검사한다. 운영 반영·다른 모델 계열·사용자 기반 gold 평가·전체 M1–M14 인수는 남는다.
