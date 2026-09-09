"""Rehearse content-only to page-bound compile keys on disposable classified data.

Both arguments are installed release directories. Uses FakeLLM, never user data.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

PROBE = """
import json,sys
from pathlib import Path
from sb.generation_integrity import load_verified_manifest
from sb.memory_access import classified_page, require_scope, MemoryAccessError
from sb.source_access import SourceAccess
from sb.targets import GenerationIdentityV1
from sb.store.ledger import load_ledger_tables
root=Path(sys.argv[1]).resolve()
m=load_verified_manifest(root)
generation=GenerationIdentityV1(*(str(m[k]) for k in
 ('provider_instance_id','generation_id','generation_digest','head','tree')))
tables=load_ledger_tables(root/'.sb/ledger.db')
rows=[]
for path in sorted((root/'wiki').glob('*.md')):
 page=classified_page(root,path.stem,generation)
 assert len(page.requirements)==1 and len(page.source_refs)==1
 access=page.requirements[0]
 require_scope(page,access)
 other='project:b' if access.projects==('project:a',) else 'project:a'
 try: require_scope(page,SourceAccess('principal:owner',(other,),'1'))
 except MemoryAccessError: pass
 else: raise AssertionError('cross-project read accepted')
 rows.append({'page':path.stem,'projects':list(access.projects),'source_refs':list(page.source_refs)})
print(json.dumps({'pages':rows,'source_items':len(tables.source_items),
 'cursors':{key:value[0] for key,value in tables.cursors.items()},
 'derivations':len(tables.derivations),'head':m['head']}))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous_release", type=Path)
    parser.add_argument("candidate_release", type=Path)
    args = parser.parse_args()
    releases = [
        path.resolve(strict=True) for path in (args.previous_release, args.candidate_release)
    ]
    manifests = [json.loads((path / "release-manifest.json").read_text()) for path in releases]
    with tempfile.TemporaryDirectory(prefix="compile-key-upgrade-", dir="/var/tmp") as directory:
        root = Path(directory)
        vault = root / "share/vault"
        config = root / "config.toml"
        text = f'vault_root = "{vault}"\nshare_root = "{root / "share"}"\nstate_root = "{root / "state"}"\nknowledge_registry = "{root / "registry.db"}"\n'
        for name in ("a", "b"):
            source = root / name
            source.mkdir()
            (source / "same.md").write_text("동일 내용의 독립 프로젝트 기억입니다.")
            text += (
                f'[[sources]]\nid = "docs-{name}"\nadapter = "markdown-vault"\nroot = "{source}"\n'
            )
        for name in ("a", "b"):
            text += f'[source_access.docs-{name}]\nowner = "principal:owner"\nprojects = ["project:{name}"]\npolicy_revision = "1"\n'
        config.write_text(text)
        config.chmod(0o600)
        env = {**os.environ, "SB_CONFIG": str(config), "PYTHONNOUSERSITE": "1"}
        env.pop("PYTHONPATH", None)

        def run(release: Path, *commands: str) -> None:
            subprocess.run(
                [str(release / "bin/sb"), *commands],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )

        def snapshot() -> dict:
            output = subprocess.check_output(
                [str(releases[1] / ".venv/bin/python"), "-c", PROBE, str(vault)],
                cwd=root,
                env=env,
                text=True,
                timeout=30,
            )
            return json.loads(output)

        run(releases[0], "ingest")
        run(releases[0], "compile", "--llm", "fake")
        before = snapshot()
        assert len(before["pages"]) == 1, "fixture requires previous content-only key behavior"
        run(releases[1], "compile", "--llm", "fake")
        after = snapshot()
        assert len(after["pages"]) == 2
        assert {tuple(row["projects"]) for row in after["pages"]} == {
            ("project:a",),
            ("project:b",),
        }
        assert before["pages"][0] in after["pages"]
        assert before["cursors"] == after["cursors"]
        assert before["source_items"] == after["source_items"] == 2
        run(releases[1], "compile", "--llm", "fake")
        replay = snapshot()
        assert replay == after, "second candidate compile changed completed state"
        print(
            json.dumps(
                {
                    "previous_manifest": manifests[0],
                    "candidate_manifest": manifests[1],
                    "before": before,
                    "after": after,
                    "replay_unchanged": True,
                    "cross_project_denied": True,
                    "production_activated": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
