# 충돌 판정 형식 수정과 현재 자비스 읽기 연결 재검증

기준 SB 94d6095 이후 수정. JARVIS 작업공간 HEAD는 195b1a7. 사용한 격리 빌드는 /var/tmp/jarvis-current-pair-_mq15nmd/source/dist이며 build-receipt.json의 source_commit은 195b1a7d4588a8386def5e7dce2067a141942708, build_exit_code=0이다. 이번에 이 빌드를 재생성하거나 운영 실행물을 변경하지 않았다.

실제 scripts/scoped-mcp-acceptance.py를 실행했더니 선행 CLI fixture의 소스 업데이트 후 compile이 실패했다. 격리 원장에서 conflict derivation의 invalid conflict verdict를 확인했다. 기본 --llm fake는 JSON 판정 요청에도 Cited 문장을 반환했고, 충돌 프롬프트는 relation/confidence/rationale만 요구했다. 후속 확인 정정: parser는 cites 생략을 빈 배열로 처리하므로 cites가 필수라는 최초 설명은 잘못됐다. 실제 실패 원인은 fake의 비JSON 응답이었다.

수정: fake의 JSON 요청은 명시적인 모의 unrelated 판정과 빈 cites를 반환한다. 이는 의미 판단을 수행했다는 주장이 아니다. 충돌 프롬프트에 cites 배열 요구를 추가해 parser와 맞췄다. acceptance fixture의 knowledge_registry 경로를 임시 작업공간으로 명시했다. 최초 실행은 경로가 명시되지 않았으므로 최초 실행까지 완전히 격리된 registry 증거로 확대하지 않는다. 운영 registry를 수정/정리하는 작업은 하지 않았다.

새 회귀 테스트는 실제 managed ingest→fake compile→소스 변경→compile→반복 compile을 통과시킨다. conflict 포함 16통과/3.06초, compile·walking skeleton 12통과/3.89초, 총28통과. Ruff 전체·diff 검사 통과. 전체 suite는 이번 제품 변경 이후 재실행하지 않았다.

수정 후 실제 acceptance 스크립트 exit0. 자비스의 production issuer 코드를 격리 authority DB/정책에 연결하고, provider stdio와 자비스 consumer validator, HTTPS/gateway/CLI/provider 및 독립 stdio 클라이언트2개를 통과했다. 각2records, 다른 agent 공유 기록 동일, 제한 peer0records, 정책 철회·잘못된 요청/서명·설정 변경/누락 거부가 확인됐다. [구조화 결과](CURRENT-JARVIS-READ-2026-09-10.json).

재현 명령: `TMPDIR=/var/tmp SB_MCP_CONTRACT_PROFILE=scoped-record-read-v1 .venv/bin/python scripts/scoped-mcp-acceptance.py /var/tmp/jarvis-current-pair-_mq15nmd/source/dist`.

이번 실제 실행은 격리 source/authority/policy/clock과 TLS identity mapper를 사용하며 모델 호출은 0이다. 합성 데이터이며 사용자 실업무와 운영 Tailnet 인증 완료가 아니다. 또한 source 업데이트 읽기 시나리오로, 삭제 이력이 증가한 복원 세대에 실제 JARVIS 권한을 발급·소비하는 후속 인수는 남는다. 운영 DB/서비스 전환, DR 및 M1–M14 목표도 미완료다. push 없음.
