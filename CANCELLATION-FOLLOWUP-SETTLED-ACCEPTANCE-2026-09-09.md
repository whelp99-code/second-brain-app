# 취소 후 정상 정정의 실제 서명·관측·로컬 정리·최종 완료 인수

2026-09-09. 인수 코드 `9044f27`. JARVIS 제품 `ea076ae`/테스트 `30cf131`, SB 제품 `9e30115` 유지.

## 완료한 연결

앞 인수 `6031d73`은 실제 MCP 발행과 provider proved까지 연결했지만 자비스 lifecycle observer는 not_proved fixture였다. 이번에는 기존 제품 ProductionMemoryLifecycleObserver와 SecondBrainStatusObservationSource를 실제 MCP 결과에 연결했다. 별도 기억 서버나 새 완료 계약을 추가하지 않았다.

후속 provider는 기존 취소 검사에서 철회한 provider:key를 재활성화하지 않고, 다른 키 재료의 provider:followup으로 실제 결과를 서명한다. 자비스에는 해당 공개키·provider/release·유효 기간을 등록했다. 개인키 없는 MCP 상태 조회로 받은 proof의 서명·요청·순번 바인딩과 실제 관측 manifest를 제품 검증기가 확인했다.

같은 DB의 취소 settlement/cursor1→후속 후보 확인·승인·MCP 대상 조회/발행→provider 실제 실행→서명 검증→provider40개/재유입 guard10개 관측→JARVIS 실제 compaction→정정 settled·명령 completed를 연결했다. 취소 compaction 뒤의 현재 DB 세대에서 새 AuthorityDatabaseRuntime을 열어 정상 정정 compactor를 실행했다.

## 최종 실측

- 실행 Node PID712676, 독립 재조회 Node PID713752.
- 요청 `memeff:req:v2:0e73744f218769bad7c95b7c31654b46e5ae88cf2eff9c5efa1ed501a07ba414`.
- 실제 검증 proof digest `sha256:24ba4dc8f79be2b7d6120618475f981849419f643cb947c79cf39555664e2ad5`.
- 발행1회, delta1개/sequence2, 이전 root가 취소 settlement와 일치. cursor2/active lane 없음.
- provider proved, 커밋된 wiki에 새 정정 내용 존재, 이전 Beta·취소 Alpha 내용 부재. 다음 executor 실행 idle.
- MCP 재시작 후 같은 상태 응답. provider 관측40개, guard10개를 실제 응답에서 검증.
- 자비스 정정 settled, 제어 명령 completed. 전체 catalog 기대70/관측70, 누락0/오류0/본문 일치0.
- 새 Node 프로세스가 DB를 열어 같은 settled record를 정확히 재생했다. 해당 재조회에는 쓰기 transport와 외부 조회를 호출하면 실패하는 대역을 주어 재발행 없이 로컬 완료 기록으로 수렴하는 것을 확인했다.
- 실제 observer 연결 이전 not_proved 대역으로 reconcile했을 때 reconciling 유지도 확인했다. 이 중간 대역 결과를 최종 완료 근거로 사용하지 않는다.

[기계 증거](CANCELLATION-FOLLOWUP-SETTLED-ACCEPTANCE-2026-09-09.json). 원본 `/var/tmp/cancellation-submit-acceptance-t5757y1n/result.json`.
재현: `TMPDIR=/var/tmp .venv/bin/python scripts/cancellation-submit-acceptance.py ISOLATED_JARVIS_BUILD --dispatch-result`.

## 회귀 검사

- JARVIS 직렬 Vitest: memory-correction-control 및 memory-cancellation-followup **12 passed / 43.84초**. 만료 후 완료, 최종 이벤트 실패 rollback, 로컬 복구, 키·fence·취소·철회·binding·서명·purge 증거 누락의 완료 거부를 포함한다.
- SB cancellation executor 및 walking skeleton **11 passed / 9.77초**.
- 전체 sb/tests Ruff, 변경 Node 구문, 변경 Python AST, git diff check 통과.
- 제품 소스·wire 계약·migration 변경 없음. 전체 제품 테스트·실제 운영 배포 검사는 이번에 재실행하지 않았다.

## 전체 목표에서 남는 범위

이 인수는 합성 기억·테스트용 권한 증거·등록 키와 임시 저장소를 사용하는 실제 Node/Python/MCP/SQLite/Git 실행이다. 실제 자비스 앱의 사용자가 낸 작업 결과나 관리 중인 모든 native 세션에서 완료한 결과로 확대하지 않는다. 무작위/합성 데이터와 실제 사용자 기억의 품질 평가는 별개다.

취소 seq1→정상 seq2의 최종 완료 연결은 이 격리 경로에서 인수했다. 다음 P0는 원 요청 외부 전송과 취소의 통합 경합, 여러 runtime·직접 DB 작성자 및 root inode 변경, 사용자/프로젝트 ACL, 원작업→기억 계보, native 세션/WAL/백업 수명, 실제 앱 새 세션 재사용이다. 클라이언트별 자동 수집·주입, 한국어 검색 평가, GUI·운영 복구 인수도 유지한다.

전체 운영 완료는 미선언이다. 운영 서비스·설정·DB·dist·배포·push는 변경하지 않았다.
