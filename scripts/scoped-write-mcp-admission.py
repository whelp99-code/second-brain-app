"""Drive JARVIS's actual transport and a separate scoped MCP server."""
import json
import shlex
import subprocess
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text())
root = Path(state['provider_root'])
root.mkdir(parents=True, exist_ok=True, mode=0o700)
app = Path(__file__).resolve().parent.parent
config = root / 'mcp-config.toml'
config.write_text('\n'.join([
    'vault_root = ' + json.dumps(str(root / 'share/vault')),
    'request_root = ' + json.dumps(str(root / 'requests')),
    'provider_instance_id = ' + json.dumps(state['request']['provider_instance_id']),
    '[scoped_provider_verifier]', 'credentials_path = ' + json.dumps(state['credentials'])]) + '\n')
config.chmod(0o600)
code = ('from datetime import datetime\nimport sb.mcp as m\nimport sb.scoped_write_mcp as w\n'
    'import sb.scoped_provider_runtime as r\nclass Clock:\n @staticmethod\n def now(tz): return datetime.fromisoformat('
    + repr(state['at']) + ')\nw.datetime=Clock\nr.datetime=Clock\nm.main()\n')
launcher = root / 'scoped-mcp'
launcher.write_text('#!/bin/sh\ncd ' + shlex.quote(str(app)) + '\nexec ' + shlex.quote(sys.executable)
    + ' -c ' + shlex.quote(code) + ' 2>' + shlex.quote(str(root / 'mcp.err')) + '\n')
launcher.chmod(0o700)
result = subprocess.run([state['node'], str(app / 'scripts/scoped-write-mcp-consumer.mjs'), state['build']],
    input=json.dumps({'launcher': str(launcher), 'config': str(config), 'request': state['request'],
        'contract': str(app / 'contracts/second-brain-scoped-write-v1.json'), 'at': state['at']}),
    capture_output=True, text=True, timeout=45, check=False)
assert result.returncode == 0, result.stderr
print(result.stdout.strip())
