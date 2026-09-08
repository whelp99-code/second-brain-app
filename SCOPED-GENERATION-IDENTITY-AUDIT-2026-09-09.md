# P0: 접근 범위 차이가 봉인 세대 identity에 반영되지 않음

**2026-09-09 접근 분류 generation identity 수정:** [분류 결합·교체 거부·전체1,222통과](SCOPED-GENERATION-IDENTITY-FIX-2026-09-09.md). 프로젝트/owner/policy 차이가 ID에 반영되고 동일 분류는 재현된다. FIFO 회귀 수정 후 전체1,222통과/2skip/204.85초·Ruff·새 모듈 정적검사 통과. 독립 scope reader4 및 JARVIS/Python8프로세스 인수. 옛 미결합 분류 세대는 거부하며 운영 재생성/reader 전환·자동 완료/전체 목표는 남는다.

2026-09-09. 완료 proof를 독립 세대와 대조하던 중 다른 프로젝트 분류를 가진 기존 인수 결과의 generation ID가 같아 추가 재현했다.

## 확인된 사실

동일 provider/release/시각/본문/원본 candidate를 두 개의 격리 GenerationStore에 저장했다. 한쪽 SourceAccess는 project:a, 다른 쪽은 project:b다. 원본·페이지 분류 결합에는 기존 materialize_remember를 사용했다.

- 두 결과의 **generation_id가 같고 ledger_manifest_digest도 같았다.**
- 별도 프로세스 4개의 classified_page/require_scope 결과는 A에서 A만 허용·B 거부, B에서 B만 허용·A 거부였다.
- 따라서 다른 분류가 실제로 저장됐지만 generation identity가 그 차이를 구분하지 못한다. 이번 결과는 일반 접근 검사에서 불허 프로젝트를 읽었다는 재현이 아니다.
- `sb/generations.py::_logical_derived_digests`의 ledger digest는 head/tree/tombstone/pages를 기반으로 한다. source/page 접근 분류는 입력에 없다. raw ledger file hash는 파생 inventory에 존재하지만 그것만으로 위 generation identity 차이가 생기지는 않는다.

[실행 증거](SCOPED-GENERATION-IDENTITY-AUDIT-2026-09-09.json). 재현: 앱 루트에서 `TMPDIR=/var/tmp PYTHONPATH=. .venv/bin/python scripts/scoped-generation-identity-audit.py`.

## 영향과 보류

세대 ID 일치를 승인된 접근 범위 저장의 단독 증거로 사용하면 안 된다. 동일 ID를 사용하는 분류 cache·독립 read binding·restore/정정의 영향 범위를 추가 확인해야 한다. 이 재현만으로 기존 모든 경로의 노출이나 손상을 확정하지 않는다.

현재 새 자비스 proof 검사 결과는 `proof_consistent`이며 요청·본문·proof/status hash와 관측된 세대의 일치만 표현한다. 이 결과만으로 outbox settled/control completed를 만드는 연결은 보류한다. 기존 scoped artifact 접근 검사를 생략하지 않는다.

## 다음 수정 단위의 필수 조건

1. canonical 원본/페이지 접근 분류를 봉인 세대의 논리 manifest에 결합하고 실제 생성 bytes와 검증 시 재계산값을 대조한다.
2. 기존 세대/새 세대 형식의 명시적 호환·거부 조건을 정한다. 옛 자료를 범위 결합이 검증된 새 자료로 간주하지 않는다.
3. 같은 본문·다른 프로젝트/owner/policy의 generation identity 분리, 같은 분류 재생성 일치, 분류/파생 inventory 교체 거부를 검증한다.
4. 읽기 pin/cache/hybrid·정정·삭제·복원·재색인 경로를 함께 확인한 뒤 scoped 완료 소비와 운영 활성화를 이어간다.

이번 단위는 재현 증거와 보류 판정이다. SB generation 제품 코드는 아직 수정하지 않았다. 전체 M1~M14를 유지하며 이 결함을 M2/M3/M7/M12의 선행 P0로 추가한다.
