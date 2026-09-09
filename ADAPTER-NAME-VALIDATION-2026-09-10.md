# 기본 원본 ID와 잘못된 adapter 이름 충돌 수정

설정 id=inbox/adapter=missing-adapter가 기본 InboxDocumentsAdapter로 선택되는 결함을 실제 factory 기반 회귀에서 재현했다. 선택기가 source_id만 확인해, 해당 설정을 수락하지 않은 기본 factory 결과를 사용했기 때문이다.

별칭이 있는9개 connector class에 accepted_adapters를 공개했다. 각 모듈의 기존 _ADAPTERS 또는 _MARKDOWN_ADAPTERS 집합을 그대로 참조하므로 별칭 목록을 복제하지 않는다. 선택기는 ID와 명시한 adapter/type 이름이 모두 일치하는지 확인한다. 속성이 없는 connector는 registry key인 정식 ADAPTER_ID만 허용한다. 이름을 생략한 기존 ID 기반 설정과 명시적 source 선택의 기존 규칙은 유지한다. connector registry와 SourceAdapter의 필수 프로토콜을 수정하지 않았다.

새 connector가 별칭을 지원하면 class의 accepted_adapters에 factory가 수락하는 동일한 frozenset을 노출해야 한다. 정식 이름만 사용하는 connector에는 이 선택 속성이 필요 없다. 지원하지 않는 이름을 기본 ID로 우회할 수 없으며 SOURCE_NOT_FOUND로 scan 전에 거부한다.

검증:
- 최초 회귀: 잘못된 기본ID 조합1실패, 정상 inbox별칭1통과.
- 최종 configured selection/예산/CLI/run_all/connector **144 passed, 1 skipped / 6.67초**. 모든 등록 connector의 정식 이름과 공개 별칭에 대해 실제 factory 선택을 대조했다.
- 테스트 대역의 registry key와 adapter 이름을 일치시키고 예산 테스트 목적을 유지했다. Ruff/diff 통과.
- 수정 모듈 basedpyright **0 errors, 1 warning**(기존 registry.put 반환값 미사용).
- 별도 임시 저장소에서 잘못된 이름: exit1/SOURCE_NOT_FOUND: inbox·입력 보존. 같은 원본을 정상 별칭 documents로 다시 실행: exit0·written1. [실제 pipeline 결과](ADAPTER-NAME-VALIDATION-2026-09-10.json).

원본 수집은 합성 파일이며 모델 호출은 없었다. 운영 데이터·서비스 변경 없음. 이전 전체1567통과는 이 변경 전 기준이다. 최신 설치 반영, 관리형 상태 결합, 실제 업무 공유·운영 및 M1–M14 인수는 남는다.
