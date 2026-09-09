"""Independent internal status reader. Operator-provided scope is a test fixture."""
import json
import sys
from datetime import datetime
from pathlib import Path

from sb.request_store import RequestStore
from sb.scoped_request_status import read_scoped_request_status
from sb.source_access import SourceAccess

root, request_file, scope_file, at = sys.argv[1:]
request = json.loads(Path(request_file).read_text())
def resolve_scope(now):
    value = json.loads(Path(scope_file).read_text())
    if value is None or not now < datetime.fromisoformat(value['valid_until']):
        return None
    return SourceAccess(value['owner'], tuple(value['projects']), value['policy_revision'])
store = RequestStore(Path(root), maintenance_only=True)
try:
    try:
        result = read_scoped_request_status(store, request, expected_provider='provider:fixture',
            clock=lambda: datetime.fromisoformat(at), resolve_scope=resolve_scope)
        print(json.dumps(result))
    except ValueError:
        print(json.dumps({'denied': 'SCOPED_REQUEST_STATUS_DENIED'}))
        sys.exit(1)
finally:
    store.close()
