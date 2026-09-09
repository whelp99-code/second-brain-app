# 기억 소비자 근거 안내 — 2026-09-09

JARVIS src/phone-memory-client-mcp.ts의 jarvis_memory_context 도구 설명을 수정했다. 기존 untrusted/실행 성공 증거 아님 안내에 다음을 추가했다: 검색 결과 존재와 순위는 질문에 대한 답변 가능성을 보장하지 않는다. 실제 record 본문으로 각 주장을 확인하고 출처를 인용한다. 요청한 사실을 뒷받침하지 못하면 기억으로 확인할 수 없음을 밝히고, 관련된 다른 사실이나 추정값을 대신 답하지 않는다. 명시적 미정 상태와 확정 값을 구분하고 충돌을 임의로 해소하지 않는다.

JARVIS 커밋: 61b8a42. SDK MCP 및 실제 임시 HTTPS 연결을 포함한 phone-memory-client 통합 테스트 15개 통과, ESLint 통과. 첫 실행은 기본 임시 경로의 system error -122로 테스트 수집 전에 실패했고 TMPDIR=/var/tmp 재실행이 성공했다. npm pretest/build는 실행하지 않아 운영 dist를 변경하지 않았다.

이 변경은 모델에 전달되는 도구 메타데이터다. 런타임에서 답변의 의미를 강제 검증하지 않으며 실제 native 모델의 abstention 성공은 이번에 측정하지 않았다. 검색 후보를 임의로 삭제하거나 계약 payload·해시를 바꾸지 않는다. 실제 질문/근거 부족 native 평가와 운영 릴리스 반영은 남는다. 운영 서비스·DB·계정·설정 변경 없음.
