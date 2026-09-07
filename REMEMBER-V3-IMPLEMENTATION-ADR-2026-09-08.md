---
title: 명시적 일반 텍스트 기억 요청 V3
type: adr
sensitivity: T1
status: implemented-isolated-acceptance-verified
---

# 결정

기존 V1 기억 요청 및 V2 effect와 schema4 MCP 계약을 보존한다. 새 remember 요청은 schema_version=3, root body_profile=`plain-text-v1`이고 명시적 `remember-schema5` MCP 프로필에서만 공개한다. 별도 `contracts/second-brain-mcp-v3.json`에 schema5 계약을 기록한다. 읽기 record/세대/삭제 fence의 의미는 schema4와 같다.

본문에만 새 validator를 사용한다. UTF-8 원문 4096바이트, NFC·유효 Unicode scalar, LF/CR/탭 허용, 나머지 C0·DEL 거부, 가장자리 공백/BOM/NEL을 원문 그대로 유지한다. 기존 Python splitlines/strip 및 사용자 `[^` 이스케이프에 따른 결과는 1~64개 record, 각 4096바이트 이하여야 한다. 제목·식별자·기존 V1의 validator는 넓히지 않는다.

candidate/classification/receipt와 idempotency V1 규칙은 재사용하여 같은 후보를 구/신버전으로 재발행해 중복 저장할 수 없게 한다. request digest domain은 `orca-jarvis/memory-write-request/v3\0`, request ID prefix는 `memreq:pos:v3:`. file digest domain은 `second-brain/inbox-write-request/v3\0`. envelope/result schema3. envelope 내부 request/receipt의 schema 필드 생략은 V1 보관 형식을 따르며 body_profile은 보존한다.

자비스는 새 candidate 입력 schema2/body_profile을 명시적으로 받으며 새 review/dispatch publication에 버전을 영속 결합한다. 과거 승인·publication·pending 요청을 전송 시 V3로 변환하지 않는다. 새 profile 미지원이면 거부하며 줄바꿈 치환이나 V1 fallback을 하지 않는다. 기존 JARVIS 권한 구조를 재사용하고 SB에 새 승인/서명 시스템을 추가하지 않는다.

SB 요청 원장은 기존 (1,2) 제약을 원자적으로 (1,2,3)으로 옮기는 migration과 명시적 처리 분기를 필요로 한다. 원문 CAS·페이지/인용·삭제 억제·generation 단일 writer·복원·완료 관측을 재사용한다. 운영 journal에 이번 개발 도구로 migration을 실행하지 않는다.

# 검증과 완료 조건

구버전 frozen 계약 불변, 신/구 조합 fail-closed, 정확 재시도와 교차 버전 충돌, migration 행/FK/index/trigger 보존 및 중단 rollback, 실제 처리·중단 재개·원문/인용 복원, 자비스 후보→승인→새 요청→proved→재조회→명령 완료를 확인한다. 최종 상태/잔여는 구현 원장에 기록한다. 계약/권한 변경은 JARVIS 헌법에 따라 독립 Reviewer가 검토한다.

구현·검증 결과는 [V3 인수 보고서](REMEMBER-V3-ACCEPTANCE-2026-09-08.md)에 기록했다. 운영 전환은 수행하지 않았다.
