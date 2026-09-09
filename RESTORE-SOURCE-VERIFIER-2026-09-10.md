# 복원 source 세대 내부 검증기 구현

기준 0403546. sb/restore_source.py의 verified_restore_source를 추가했다. 아직 GenerationRestoreSanitizer의 상태 가져오기 경로에는 연결하지 않았다.

호출자는 소유한 격리 추출 디렉터리와 기존 GenerationStore를 전달한다. 함수는 사용자 지정 해시 대신 store의 activations 원장에서 source_generation_id의 manifest_digest를 직접 조회한다. provider·원장 digest를 먼저 대조하고, 기존 load_verified_manifest로 백업 generation identity·파생 파일 inventory·원장 결합 digest를 검증한다. 그 뒤 source generation ID/digest/provider/tombstone sequence/root를 아카이브 주장과 모두 대조한다. 결과는 검증된 manifest이며 상태를 쓰거나 세대를 활성화하지 않는다.

운영 원장에 세대가 없으면 RESTORE_SOURCE_ANCHOR_MISSING, 주장 불일치는 RESTORE_SOURCE_MISMATCH, 파일/원장 검증 실패는 RESTORE_SOURCE_INVALID로 거부한다. 알려진 세대라는 사실이 과거 publication 완료를 증명하는 것은 아니며 activation phase를 승인 권한으로 해석하지 않는다. 최종 상태 승계 정책에서 필요한 publication 조건은 별도로 결정해야 한다.

## 검증

실제 GenerationStore로 지식 상태가 봉인된 세대를 만들고 별도 디렉터리에 백업한다. 정상 검증, provider/ID/digest/sequence/root 변경, ledger 변조, 자기 해시는 맞지만 독립 운영 원장이 없는 경우를 검사했다. 관련 기존 복원 검증과 함께 **13 passed / 7.72초**. Ruff 전체·diff, 새 모듈 타입 0오류/0경고. 초기 타입 Any 경고는 명시적 row 타입으로 수정했다.

## 남은 구현

검증된 원장에서 구조화된 지식/접근 상태 추출, sanitized 현재 본문과 exact digest 대조, metadata 재유입 검사, 현재 철회/정책 적용 및 실제 restore mutation에 연결해야 한다. 현재 함수만으로 raw/본문 전체가 복원용으로 안전해지는 것은 아니며 기존 tombstone sanitation을 대체하지 않는다. 운영 원장 소실 DR의 독립 보관 근거와 전체 복원 인수도 남는다.

기존 복원 계약·MCP·승인 흐름 변경 없음. 실제 JARVIS 세션·최신 설치/사용자 업무·운영 및 M1–M14 미완료. 전체 suite는 이번 추가 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
