"""Keyword inputs forwarded to the actual remember-page materializer in tests."""
from typing import NotRequired, TypedDict

from sb.source_access import SourceAccess


class RememberArguments(TypedDict):
    content: str
    candidate_id: str
    created_at: str
    release_sha: str
    sensitivity: NotRequired[str]
    source_access: NotRequired[SourceAccess | None]
