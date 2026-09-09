# Scoped 공개 쓰기 연결을 위한 서버 인증 조합과 판정 소비

## 현재 공개 경로와 구현

현재 공개 MCP 쓰기의 입력은 기존 V1/V2 및 plain-text V3이며 scoped V4는 아직 노출되지 않았다. scoped read 프로필은 쓰기를 등록하지 않는다. 내부 provider admission/execution과 자비스의 원래 전송 검증기는 이미 있으므로 이를 재사용한다.

JARVIS createProductionScopedProviderVerifier는 서버가 소유한 인증 세션 callback, 현재 파일 쓰기 정책, authority DB/원래 dispatch/private spool 검증을 조합한다. 요청의 writer 라벨에서 인증 세션을 만들지 않는다. 매 호출 시 정책과 원래 전송을 다시 확인하고 세션/grant/key/transport를 만들지 않는다.

SB validate_scoped_provider_decision은 신뢰된 검증 채널에서 받은 판정의 닫힌 필드 집합, kind/provider/request/scope, outbox 형식, 양의 안전한 정수 fence, 호출 전후 시계와 만료를 확인한다. 호출 전 판정·미래 판정·응답 도중 만료·요청 만료보다 긴 유효기간·뒤로 간 시계·boolean/float fence와 추가 필드를 거절한다. 반환은 frozen dataclass다.

이 parser는 발신자를 인증하지 않는다. 신뢰되지 않은 외부 JSON을 넣고 통과했다고 권한을 부여하는 공개 endpoint로 사용하면 안 된다. 공개 transport에 연결하려면 실제 서버 인증 세션과 고정된 신뢰 채널을 결합해야 한다. 현재 단계에서 요청 본문만 받아 callback을 True로 만드는 공개 노출 방식은 보류한다.

## 검증

- Python 신규 판정/기존 admission 관련25개 통과(2.30초); 최종 타입 명시 보완 후 같은25개 재검사 통과(1.77초, 중복).
- JARVIS 신규 서버 세션 조합/기존 provider 검증11개 통과(12.25초).
- 전체 Ruff 및 JARVIS 격리 TypeScript emit/변경 ESLint 통과.
- 기존 실제 Python→독립 Node admission/execution 인수에 양쪽 새 코드를 연결해 통과했다. 정상은 proved, 수락 중 현재 파일 정책 철회는 수락 원장 없음, 실행 전 철회는 failed/활성 세대 없음이다. 원래 전송 attempt는1건을 유지했다.
- 세컨드브레인 전체1,275개 통과, 2개 건너뜀(297.91초, optional embeddings 테스트 제외). 이후 타입 명시 보완에 대해 위 관련25개 및 전체 Ruff를 재검사했다. 새 Python 모듈 basedpyright는 오류0/경고0이다.

[실제 프로세스 결과](SCOPED-PROVIDER-PRODUCTION-2026-09-09.json). 인증 세션과 시계는 fixture이며, 전송은 로컬 child process와 내부 provider API다. 공개 MCP v4 쓰기 또는 운영 인증 endpoint를 완료했다고 해석하지 않는다.

## 다음 구현

공개 scoped 쓰기 계약과 실제 인증 transport, provider 수락/실행의 동일 세션·현재 정책 검증을 연결하고, 실제 에이전트 A 저장→B 새 세션 회수와 취소/철회·재시작을 확인해야 한다. 최초 활성 세대 이전 status, 원문/spool/로그/백업 삭제와 복원 억제, 에이전트별 수집/주입·검색 평가·운영 복구를 포함한 M1–M14 범위도 유지한다.

JARVIS 구현 커밋 df6d7d4. 운영 DB/서비스/vault·기존 계약과 migration은 변경하지 않았고 push/배포하지 않았다.
