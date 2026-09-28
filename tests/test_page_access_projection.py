from dataclasses import replace
from pathlib import Path

import pytest

from sb.memory_access import MemoryAccessError, classified_page
from sb.page_access_projection import page_access_projection
from sb.targets import GenerationIdentityV1
from tests import test_memory_access

classified = test_memory_access.classified


@pytest.mark.parametrize('count', [0, 65])
def test_access_response_rejects_empty_or_oversized_source_sets(classified: tuple[Path, str, GenerationIdentityV1], count: int):
    root, name, generation = classified
    page = classified_page(root, name, generation)
    oversized = replace(page, source_refs=page.source_refs * count, requirements=page.requirements * count)
    with pytest.raises(MemoryAccessError, match='MEMORY_ACCESS_UNAVAILABLE'):
        _ = page_access_projection(oversized)
