# 취소 후 자비스 실제 발행→MCP→provider 실행 인수

2026-09-08. 인수 코드 `6031d73`, JARVIS 테스트 `30cf131`/제품 `ea076ae`, SB 제품 `9e30115`.

## 이번에 연결한 경로

기존 취소 인수의 같은 자비스 DB에서 provider 취소 결과 저장·로컬 DB 처분·중단 복구·settlement/cursor1을 실행한다. 이후 독립 Beta 기억을 실제 provider executor로 저장한다. 자비스가 실제 schema5 MCP로 페이지의 record ID/digest를 읽고 대상을 resolve한 뒤 후보 확인·정정 준비·실행 승인·claim·dispatch API를 거쳐 새 요청을 발행한다.

발행에는 제품 `createSecondBrainWriteRequestAdapter`와 `SecondBrainEffectService`를 사용했다. generation status, read fence, target resolve, write accepted, request status 응답은 실제 Python MCP에서 온다. 이전 검사처럼 Python factory가 후속 V2 요청을 만들거나 accepted를 테스트 대역으로 반환하지 않는다. 후보의 검증·승인 증거와 기억 내용은 격리 fixture다.

새 테스트 delegation 키는 기존 키와 다른 키 재료·ID로 등록했다. 앞 인수의 철회 키를 활성화하지 않는다. 실제 provider executor는 별도 Python 프로세스에서 같은 request root를 처리한다.

## 최종 실측

- Node PID 692914. 실제 요청 `memeff:req:v2:d0620c38df8e0a1c167761137df49bdc24ccf3739fcde2c54920e1d7c0a71904`.
- 자비스 발행 1회, tombstone delta 1개/sequence2, previous root가 같은 DB의 취소 settlement root와 일치.
- 자비스 cursor의 accepted_through_sequence=2, active_lane_id=null. 취소된 원 요청 writer 호출 0회.
- provider state=proved, tombstone sequence/root가 발행 요청과 일치. 다음 executor 실행은 idle.
- 실제 git HEAD wiki blob에 새 정정 내용 존재, 이전 Beta 및 취소 Alpha 내용 부재.
- 실제 MCP request status=proved. MCP 재시작 후 같은 요청의 상태 응답이 정확히 일치.
- 최종 자비스 상태=reconciling. 관측 대역이 not_proved를 반환하는 reconcile에서 추가 발행 없이 이 상태를 유지.

[기계 증거](CANCELLATION-DISPATCH-MCP-ACCEPTANCE-2026-09-08.json). 원본 `/var/tmp/cancellation-submit-acceptance-q6_6g09a/result.json`.

## 실패에서 수정한 인수 코드

첫 시도는 schema5에 구형 page_id/exact_record 선택자를 보냈고 SECOND_BRAIN_INVALID_ARGUMENTS로 거부됐다. 제품 계약을 완화하지 않고 실제 sb_read_page의 record ID/digest와 세대에 결합한 selector로 수정했다. 그 후 실제 인수를 통과했고 재시작·root 일치·완료 보류 검사를 추가한 최종 실행도 통과했다. 최초 실패는 성공 횟수에 포함하지 않는다.

재현: `TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD --dispatch-result`.
기존 mode는 유지한다. 격리 JARVIS emit을 갱신했으며 운영 dist는 변경하지 않았다.
관련 Python `tests/test_correction_cancellation_executor.py` 및 `tests/integration/test_walking_skeleton.py`: **11 passed / 8.96초**. 전체 sb/tests Ruff, Node syntax, Python AST, git diff check 통과. 제품 소스 변경이 없어 전체 제품 테스트는 재실행하지 않았다.

## 다음 완료 조건과 보류

이제 자비스 실제 발행과 provider 실행은 같은 흐름으로 연결됐다. 하지만 provider의 proved 상태 조회는 자비스의 서명 proof 검증·관리 대상 사본 관측·전체 compaction 완료를 대체하지 않는다. 이 인수의 lifecycle observer는 명시적인 not_proved fixture이며 compactor는 호출 시 실패하는 대역이다. 따라서 최종 settled 또는 실제 앱 인수로 표현하지 않는다.

다음은 ProductionMemoryLifecycleObserver가 요구하는 provider proof·현재 키 신뢰·관측 manifest·provider inventory·재유입 guard를 실제 자료로 연결하고 정상 정정 compaction/settlement까지 검증하는 것이다. 앞 취소 검사에서 의도적으로 철회한 provider 키를 되살려 통과시키지 않는다. 유효한 별도 provider 키 등록과 실제 서명 결과를 준비해야 한다.

원 요청 전송/취소 경합, 다른 runtime/직접 DB 작성자 배제와 root inode 변경, 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션·WAL·백업 수명, 실제 앱 새 세션 재사용, 자동 수집/주입, 검색 평가와 GUI·운영 복구 조건은 그대로 남는다. 운영 서비스·DB·설정·배포·push는 변경하지 않았다.
