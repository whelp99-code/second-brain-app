"""Actual sealed CLI output through classified record reads and local scope checks."""
import hashlib
import json
import runpy
from pathlib import Path

from sb.generation_integrity import load_verified_manifest
from sb.memory_access import MemoryAccessError, classified_page, require_scope
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1

setup = runpy.run_path(str(Path(__file__).with_name("page-access-acceptance.py")))
work = setup["work"]
root = (work / "share" / "vault").resolve()
manifest = load_verified_manifest(root)
generation = GenerationIdentityV1(*(str(manifest[name]) for name in (
    "provider_instance_id", "generation_id", "generation_digest", "head", "tree")))
name = next((root / "wiki").glob("*.md")).stem
ledger = root / ".sb" / "ledger.db"
before = hashlib.sha256(ledger.read_bytes()).hexdigest()
page = classified_page(root, name, generation)
assert len(page.source_refs) == 2 and page.records
require_scope(page, SourceAccess("principal:owner", ("project:alpha",), "policy:1"))
denied = []
for label, scope in [
    ("other_owner", SourceAccess("principal:other", ("project:alpha",), "policy:1")),
    ("other_project", SourceAccess("principal:owner", ("project:beta",), "policy:1")),
    ("other_policy", SourceAccess("principal:owner", ("project:alpha",), "policy:2")),
    ("empty_projects", SourceAccess("principal:owner", (), "policy:1")),
]:
    try:
        require_scope(page, scope)
    except MemoryAccessError as exc:
        assert str(exc) == "MEMORY_ACCESS_DENIED"
        denied.append(label)
    else:
        raise AssertionError(label)
assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before
assert classified_page(root, name, generation) == page
report = {"work": str(work), "generation_id": generation.generation_id,
    "page_id": page.page_id, "content_digest": page.content_digest,
    "source_requirements": len(page.source_refs), "records": len(page.records),
    "denied": denied, "ledger_unchanged": True, "repeat_equal": True,
    "scope": "actual isolated CLI with fake LLM and internal scope evaluator; caller authentication and scoped MCP are not implemented"}
output = work / "memory-access-result.json"
output.write_text(json.dumps(report, indent=2) + "\n")
print(output)
print(json.dumps(report))
