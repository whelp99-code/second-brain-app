# Grok 재개 상태

시각: 2026-09-11. **status=ready_for_final_review**

인계 A–F 독립 구현은 격리 증거까지 넣었다. Codex 최종 검증 대상: SB `3b99eff`+이 커밋, 휠 `3d36c40`, JARVIS `eeac005` dist `80e3c6a1…`.

마지막: 복원 dest를 `share/vault`로 맞춰 `remember` EXIT 0 (16.9s). Chrome `--headless=new --dump-dom` 후 `/api/run` 실패해도 이전 compile 실패 행 유지, 토큰 없음.

## 외부 입력 (한 묶음, 지금 전환 아님)

- drain 허가와 운영 중단 창 (W4 / M1 종단만)
- native 클라이언트 인증 (복사 금지)
- live 모델 호출
- 사용자 지정 검색 100–300문
- 실사용자 업무 ID 종단

운영 `current`는 `41f0751`. 자동 rollback은 `check-rollback-compat.py`가 거부한다.
