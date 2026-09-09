from dataclasses import replace

import pytest

from sb.memory_access import MemoryAccessError, classified_page
from sb.page_access_projection import page_access_projection
from tests.test_memory_access import classified  # noqa: F401


@pytest.mark.parametrize('count', [0, 65])
def test_access_response_rejects_empty_or_oversized_source_sets(classified, count):  # noqa: F811
    root, name, generation = classified
    page = classified_page(root, name, generation)
    oversized = replace(page, source_refs=page.source_refs * count, requirements=page.requirements * count)
    with pytest.raises(MemoryAccessError, match='MEMORY_ACCESS_UNAVAILABLE'):
        page_access_projection(oversized)
