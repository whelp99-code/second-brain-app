#!/usr/bin/env python3
"""Build a locked, content-addressed release without activating it.

Usage: python deploy/prepare-release.py [app-root]
Activation is an atomic replacement of app-root/current after validation.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parent.parent
app = Path(sys.argv[1]).expanduser().absolute() if len(sys.argv) > 1 else Path.home() / '.local/state/second-brain/app'
os.umask(0o077)

def run(*args):
    return subprocess.run(args, cwd=repo, check=True, text=True, capture_output=True).stdout

with tempfile.TemporaryDirectory(prefix='sb-release-', dir='/var/tmp') as temporary:
    temp = Path(temporary)
    run('uv', 'build', '--wheel', '--out-dir', str(temp))
    wheel = next(temp.glob('*.whl'))
    requirements = temp / 'requirements.txt'
    run('uv', 'export', '--frozen', '--no-dev', '--no-emit-project', '--no-header', '--format', 'requirements-txt', '--output-file', str(requirements))
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    release_id = hashlib.sha256(wheel.read_bytes() + requirements.read_bytes()).hexdigest()[:40]
    release = app / 'releases' / release_id
    if release.exists():
        raise SystemExit(f'Release already exists; inspect it before reuse: {release}')
    release.mkdir(parents=True, mode=0o700)
    run('uv', 'venv', '--python', '3.12', str(release / '.venv'))
    python = release / '.venv/bin/python'
    run('uv', 'pip', 'install', '--python', str(python), '-r', str(requirements))
    run('uv', 'pip', 'install', '--python', str(python), '--no-deps', str(wheel))
    (release / 'requirements.txt').write_bytes(requirements.read_bytes())
    (release / wheel.name).write_bytes(wheel.read_bytes())
    bin_dir = release / 'bin'
    bin_dir.mkdir()
    base = '#!/bin/sh\nset -eu\nexport HOME="${HOME:-' + str(Path.home()) + '}"\nexport PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"\nexport SB_CONFIG="${SB_CONFIG:-$HOME/.config/second-brain/config.toml}"\ncd ' + shlex.quote(str(release)) + '\n'
    scripts = {
        'sb': 'exec ' + shlex.quote(str(python)) + ' -m sb.cli "$@"\n',
        'second-brain-mcp': 'export SB_MCP_CONTRACT_PROFILE="${SB_MCP_CONTRACT_PROFILE:-task32-schema4}"\nexec ' + shlex.quote(str(python)) + ' -m sb.mcp "$@"\n',
        'second-brain-agent-mcp': 'exec ' + shlex.quote(str(python)) + ' -c ' + shlex.quote('import anyio; from sb.config import load_config; from sb.mcp import build_server; anyio.run(build_server(config=load_config()).run_stdio_async)') + '\n',
    }
    for name, command in scripts.items():
        path = bin_dir / name
        path.write_text(base + command)
        path.chmod(0o700)
    manifest = {'schema': 1, 'release_id': release_id, 'wheel_sha256': wheel_hash,
                'source_commit': run('git', 'rev-parse', 'HEAD').strip(),
                'working_tree_modified': bool(run('git', 'status', '--porcelain')),
                'contract_profile': 'task32-schema4',
                'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest()}
    (release / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(release)
