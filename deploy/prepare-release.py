#!/usr/bin/env python3
"""Build committed HEAD as a locked release without activating it.

Uncommitted and untracked files are excluded; commit intended changes first.

Usage: python deploy/prepare-release.py [app-root]
Activation is an atomic replacement of app-root/current after validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import tarfile

from bundle_python_runtime import bundle_runtime, release_identity, runtime_digest

repo = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('app_root', nargs='?', type=Path, default=Path.home() / '.local/state/second-brain/app')
parser.add_argument('--offline', action='store_true', help='require existing local build/dependency caches; disable uv network access')
args = parser.parse_args()
app = args.app_root.expanduser().absolute()
execution_env = dict(os.environ)
if args.offline:
    execution_env['UV_OFFLINE'] = '1'
os.umask(0o077)

def run(*args):
    return subprocess.run(args, cwd=repo, env=execution_env, check=True, text=True, capture_output=True).stdout

source_commit = run("git", "rev-parse", "HEAD").strip()
source_tree = run("git", "rev-parse", source_commit + "^{tree}").strip()
working_tree_modified = bool(run("git", "status", "--porcelain"))

with tempfile.TemporaryDirectory(prefix='sb-release-', dir='/var/tmp') as temporary:
    temp = Path(temporary)
    # Build only the pinned commit. Untracked backups and local changes never
    # enter the artifact, even when the shared worktree intentionally stays dirty.
    source = temp / 'source'
    source.mkdir()
    archive = temp / 'source.tar'
    with archive.open('wb') as output:
        subprocess.run(['git', 'archive', '--format=tar', source_commit], cwd=repo, stdout=output, check=True)
    with tarfile.open(archive) as packed:
        packed.extractall(source, filter='data')
    build_env = {**execution_env, 'SOURCE_DATE_EPOCH': run('git', 'show', '-s', '--format=%ct', source_commit).strip()}
    def build_run(*args):
        return subprocess.run(args, cwd=source, env=build_env, check=True, text=True, capture_output=True).stdout
    build_run('uv', 'build', '--wheel', '--out-dir', str(temp))
    wheel = next(temp.glob('*.whl'))
    requirements = temp / 'requirements.txt'
    build_run('uv', 'export', '--frozen', '--no-dev', '--no-emit-project', '--no-header', '--format', 'requirements-txt', '--output-file', str(requirements))
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    managed_python = run('uv', 'python', 'find', '--managed-python', '--no-python-downloads', '--system', '3.12').strip()
    runtime_source = Path(run(managed_python, '-I', '-c', 'import sys; print(sys.base_prefix)').strip())
    staged_runtime = temp / 'python-runtime'
    bundle_runtime(runtime_source, staged_runtime)
    runtime_sha256 = runtime_digest(staged_runtime)
    preparation_files = {
        name: hashlib.sha256((repo / 'deploy' / name).read_bytes()).hexdigest()
        for name in ('prepare-release.py', 'bundle_python_runtime.py', 'check-release-contents.py')
    }
    recipe_sha256 = hashlib.sha256(json.dumps(preparation_files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    release_id = release_identity(wheel.read_bytes(), requirements.read_bytes(), runtime_sha256, recipe_sha256)
    release = app / 'releases' / release_id
    if release.exists():
        raise SystemExit(f'Release already exists; inspect it before reuse: {release}')
    release.mkdir(parents=True, mode=0o700)
    runtime = release / 'runtime' / 'python'
    runtime.parent.mkdir()
    shutil.move(staged_runtime, runtime)
    if runtime_digest(runtime) != runtime_sha256:
        raise RuntimeError("PYTHON_RUNTIME_COPY_CHANGED")
    bundled_python = runtime / 'bin' / 'python3.12'
    run(str(bundled_python), '-m', 'compileall', '-q', str(runtime / 'lib'))
    run('uv', 'venv', '--python', str(bundled_python), str(release / '.venv'))
    python = release / '.venv/bin/python'
    # uv emits an absolute interpreter link; the release contract requires
    # relative links entirely within the artifact.
    python.unlink()
    python.symlink_to(os.path.relpath(bundled_python, python.parent))
    installed_wheel = release / wheel.name
    installed_wheel.write_bytes(wheel.read_bytes())
    source_epoch = int(build_env['SOURCE_DATE_EPOCH'])
    os.utime(installed_wheel, (source_epoch, source_epoch))
    run('uv', 'pip', 'install', '--python', str(python), '--compile-bytecode', '-r', str(requirements))
    run(str(bundled_python), '-I', '-m', 'pip', '--isolated', '--python', str(python),
        'install', '--no-deps', '--no-compile', '--no-index', '--disable-pip-version-check', str(installed_wheel))
    # Compile at the final path with source hashes, not installation timestamps.
    subprocess.run(
        [str(python), '-m', 'compileall', '-q', '-f', '--invalidation-mode', 'checked-hash',
         str(runtime / 'lib'), str(release / '.venv' / 'lib')],
        env={**execution_env, 'PYTHONHASHSEED': '0', 'SOURCE_DATE_EPOCH': str(source_epoch)},
        cwd=repo, check=True, capture_output=True,
    )
    (release / 'requirements.txt').write_bytes(requirements.read_bytes())
    bin_dir = release / 'bin'
    bin_dir.mkdir()
    base = '#!/bin/sh\nset -eu\nexport HOME="${HOME:-' + str(Path.home()) + '}"\nexport PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"\nexport SB_CONFIG="${SB_CONFIG:-$HOME/.config/second-brain/config.toml}"\ncd ' + shlex.quote(str(release)) + '\n'
    scripts = {
        'sb': 'exec ' + shlex.quote(str(python)) + ' -m sb.cli "$@"\n',
        'sb-company': 'exec ' + shlex.quote(str(python)) + ' -m sb.company_memory_cli "$@"\n',
        'second-brain-mcp': 'export SB_MCP_CONTRACT_PROFILE="${SB_MCP_CONTRACT_PROFILE:-task32-schema4}"\nexec ' + shlex.quote(str(python)) + ' -m sb.mcp "$@"\n',
        'second-brain-agent-mcp': 'exec ' + shlex.quote(str(python)) + ' -c ' + shlex.quote('import anyio; from sb.config import load_config; from sb.mcp import build_server; anyio.run(build_server(config=load_config()).run_stdio_async)') + '\n',
    }
    for name, command in scripts.items():
        path = bin_dir / name
        path.write_text(base + command)
        path.chmod(0o700)
    manifest = {'schema': 1, 'release_id': release_id, 'wheel_sha256': wheel_hash,
                'release_id_scheme': 'sb-release-inputs-v3',
                'preparation_recipe_sha256': recipe_sha256,
                'preparation_files_sha256': preparation_files,
                'python_runtime_input_sha256': runtime_sha256,
                'source_commit': source_commit, 'source_tree': source_tree, 'source_materialization': 'git-archive',
                'working_tree_modified': working_tree_modified,
                'contract_profile': 'task32-schema4',
                'requirements_sha256': hashlib.sha256(requirements.read_bytes()).hexdigest()}
    (release / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(release)
