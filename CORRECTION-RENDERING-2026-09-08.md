# V2 정정 원문과 인용 렌더링

2026-09-08. 기존 V2는 LF/CRLF가 있는 content를 허용하지만 현재 구현은 한 citation span에 그대로 삽입한다. 실제 MCP 시험에서 CRLF는 erased source 재결합 시 LF로 바뀌어 PROVIDER_ARTIFACT_INVALID가 발생했다. 마지막 줄에만 기존 citation이 남아 앞선 줄의 schema4 record 회수도 보장되지 않는다.

수정 원칙: V2 요청·승인·digest·tombstone 및 frozen wire 필드는 유지한다. 승인된 원문을 다른 요청으로 분할하지 않는다. 하나의 정정 효과가 기존 remember와 같은 문장별 인용 표현을 만들며 사용자 `[^` 표기는 문자로 escape한다. 줄바꿈 바이트는 유지한다. 삭제된 원본의 출처는 기존 memory-effect snapshot으로 재결합한다. proof artifact는 요청 content의 동일한 결정적 렌더링이 실제 대상 페이지에 한 번 존재하는지 검사한다. 단일 줄·인용 문자 없는 기존 표현은 유지한다.

원문 승인과 렌더링은 구분한다. request의 content digest는 원문을 그대로 결합하고 artifact의 file digest는 렌더링된 페이지를 결합한다. 정정 후 두 클라이언트는 모든 새 문장의 record·인용 span·effect 출처를 회수해야 하며 이전 기억은 조회되지 않아야 한다. V1 신규 remember의 일반 줄바꿈 지원은 별도 버전 작업으로 남는다.

인수: 실제 V2 요청 접수→적용 proved→signed status→LF/CRLF·반복·인용 문자 포함 4개 record의 두 클라이언트 회수→같은 요청 재전송/추가 적용 0. 잘못된 대상·변경한 원문·과거 fence 및 원본 삭제/재유입 규칙을 약화하지 않는다. JARVIS의 실제 사용자 정정 화면·승인 명령·saga settlement와 운영 배포는 별도 완료 증거가 필요하다.

## 구현과 검증 결과

- `correction_rendering.py`는 줄바꿈을 유지하면서 중간 문장에 원래 대상의 citation을 연결한다. 기존 마지막 citation은 span 밖에 유지한다. 사용자 입력의 인용 구문은 remember와 동일하게 문자로 escape한다.
- `Vault.rebind_erased_sources`가 CRLF 및 빈 줄을 유지한다. 남은 문장은 기존 effect snapshot으로 재결합하고 삭제된 원본 출처를 계속 사용하지 않는다.
- 조회용 record 파서를 순수 함수로 분리해 정정 전 prospective 페이지를 검사한다. 65개 record 또는 escape 후 4096바이트를 초과하는 문장으로 페이지를 바꾸려 하면 기존 대상 쓰기 전에 `CORRECTION_RECORDS_INVALID`로 거부한다. 이는 접수/원장까지 되돌리는 기능이 아니며 실행 거부와 최종 완료를 구분한다.
- artifact 검사는 원문 content digest를 그대로 두고, 실제 페이지의 citation으로 동일한 렌더링이 정확히 한 번 존재하는지 확인한다. 파일 digest·tombstone·삭제 표면·재유입 검사와 서명 계약은 유지한다.

실제 인수 명령:

```bash
TMPDIR=/var/tmp node scripts/jarvis-correction-acceptance.mjs /var/tmp/jarvis-memory-intake.vnp3_v4g
```

자비스 소비자는 이전 단위에서 검증한 `7129b9d` 기반과 `b89dab6` 기억 변경을 담은 격리 빌드를 사용했다. 현재 자비스 작업공간의 다른 작업 수정 및 운영 dist를 덮어쓰지 않았다. 새 fixture는 생성한 임시 디렉터리만 사용하고 종료 시 정리한다.

`/var/tmp/sb-jarvis-correction-final.log`: provider proved, 자비스 `verifyMemoryDispositionProof`와 lifecycle observation 파서 통과. 두 독립 stdio MCP 클라이언트 current, 문장 4개의 내용 digest·effect 출처 일치, 이전 기억 0개, 동일 요청 replay=true/추가 apply idle. 바뀐 원문은 거부됐고 이전 tombstone fence는 `TOMBSTONE_SET_STALE`로 거부됐다. 바뀐 원문의 transport 반환은 현재 `SECOND_BRAIN_TOOL_ERROR`라는 일반 코드이므로 구체적 payload 오류를 클라이언트가 분류한 것으로 보고하지 않는다.

정정·record·erasure·observation 집중 **22 passed (20.48초)**. LF, CRLF, 빈 줄, 반복 문장, 사용자 인용 문자, CAS 인용 유효성, record 수/길이 초과 시 기존 바이트 보존을 검사했다. Ruff·변경 소스 타입 검사·Node 구문 검사·diff check 통과, 변경 타입 오류/경고 0.

표준 전체 회귀 **571 passed, 2 skipped (157.58초)**. `/var/tmp/sb-correction-commit-full.log`. 집중 검사는 전체와 중복되므로 합산하지 않는다. 마지막 소스 보강은 frontmatter가 없는 인용 페이지에도 같은 prospective 검증을 적용하는 것이다. 그 뒤 정정/erasure 집중 **7 passed (17.23초)** 및 lint/type/구문 검사를 다시 통과했다. `/var/tmp/sb-correction-final-preflight.log`.

## 남은 완료 조건

1. V1 신규 remember의 일반 Enter 입력은 여전히 거부한다. 기존 V1을 완화하지 않고 명시적 본문 버전/협상과 승인 원문·접수·재조회 계약을 양쪽에 추가해야 한다.
2. 이 인수는 합성 owner delegation과 실제 provider/소비자 경계 검사다. 자비스 후보 확인→정정 대상 선택→사용자 승인→production saga/outbox→control completed의 전체 UI/CLI 인수가 아니다.
3. 정정이 실행에서 거부되거나 uncertain일 때의 재조정, 사용자 오류 분류, 저장 후 삭제·백업 복원 전체 인수를 이어간다. 64개 record/문장별 4096바이트 조회 한계는 유지한다.
4. 공통 프로젝트·사용자 접근 범위, 실제 앱 수집/주입, 문맥 예산/전달 이력, 운영 배포/복구·품질 평가는 기존 B4~B8에 남는다. 작업 원본 차단의 파생 기억 전파 보류도 유지한다.

서비스 재시작·운영 세대 전환·push는 수행하지 않았다.
