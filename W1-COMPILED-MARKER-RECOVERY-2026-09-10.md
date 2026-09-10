# W1 compiled marker 복구

결함: marker가 없으면 `last_compiled_hash`가 None이라 기존 페이지 SHA와 비교가 항상 실패하고 `_proposed`로 새었다.

복구: marker가 없을 때는 `parse_page_frontmatter`로 **이미 컴파일된 SB 페이지**인지 본다. `compiled_by`가 있는 페이지는 dest에 정정을 쓴다. frontmatter가 없는 손편집과, marker가 있는데 SHA가 다른 손편집은 계속 `_proposed`. SHA를 만들어 넣거나 `_proposed`를 일괄 승격하지 않는다.

검증: `tests/test_compiled_marker_recovery.py` + `tests/test_vault.py` **36 passed**. 제품 `sb/vault.py`. 운영 전환·운영 vault 컴파일 없음.

세대 전이 시 `_copy_compiled_markers`는 후보에 이미 있다. 이번 수정은 **이미 marker가 없는 세대**의 다음 compile이다.
