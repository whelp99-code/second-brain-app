# M14 관계(hybrid) 검색 결정 — 2026-09-15

결정: **hybrid 기본 off 유지, 새 그래프/관계 검색 구현 없음.** (사용자 위임에 따른 결정)

근거:
- 고정 질의 측정(`scripts/m14-relation-search-measure.py`, Grok 실행 `/var/tmp/m14-relation-search-2026-09-14.json`, Claude 재실행 동일): 한글 관계 질의 `배포 일정 게이트웨이`에서 lexical/hybrid 모두 0건, 통제 질의 `gateway`는 lexical만으로 회수. hybrid 추가 회수 0, 지연 lexical 0.0025s vs hybrid 0.0143s.
- 과거 검토(`IMPLEMENTATION-STATUS` M14): hybrid는 무근거 후보를 늘리고 정정/삭제 일관성 증거가 없음.
- 실사용자 한글 gold(M10)가 없어 가치 판단의 입력이 부족함. gold가 제공되면 같은 스크립트로 재측정해 결정을 갱신한다.

상태: `M14 = decided_off (measured; revisit when M10 gold exists)`.
