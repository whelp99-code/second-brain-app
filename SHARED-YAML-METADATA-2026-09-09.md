# 검색과 페이지 읽기의 공통 YAML 스칼라 해석

MCP제목 수정 후에도 검색의 page_metadata.frontmatter_value는 이전 문자열strip방식을 사용했습니다. 실제커밋자료에서 따옴표/여러줄제목3경우의 검색메타데이터와read_page제목 불일치를 재현했습니다.

YAML scalar_frontmatter를 sb/page_metadata.py로 옮기고 mcp와검색이 공통함수를 사용하도록 통합했습니다. 검색이 mcp상위모듈을 import하지 않으며 기존scalar문자열계약을 유지합니다. 중첩source정보를 임의공개하거나 정책을변경하지않았습니다.

검색/MCP/web 및제목회귀51 passed(10.61초), Ruff통과. 추가실제 SearchIndex→read_page회수까지제목9개테스트통과. 추가검사 초안은snippet이전체제목과같다고가정해실패했으나 snippet은발췌문이므로검증을title섹션검색및원문제목회수로수정했습니다. snippet전체문자열동일성을보장한다고주장하지않습니다.

기존저장소나운영서비스를변경하지않았습니다. 이변경은검색입력의YAML스칼라해석을교정하며, 기존검색색인의업그레이드갱신정책및대규모재색인성능은별도검증이필요합니다.
