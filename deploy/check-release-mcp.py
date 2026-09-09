"""Check installed MCP initialization/tool lists with temporary, non-operational fixtures."""
import base64,json,os,tempfile,sys
from pathlib import Path
import anyio
from mcp import StdioServerParameters
from mcp.client import Client
if len(sys.argv) != 2:
 raise SystemExit('usage: check-release-mcp.py ABSOLUTE_RELEASE_PATH')
release=Path(sys.argv[1]).resolve(strict=True)
async def main():
 results=[]
 with tempfile.TemporaryDirectory(dir='/var/tmp') as directory:
  root=Path(directory);root.chmod(0o700)
  (root/"generation-vault").mkdir()
  (root/"vault").symlink_to(root/"generation-vault", target_is_directory=True)
  credentials=root/'credentials.json';credentials.write_text(json.dumps({'origin':'https://127.0.0.1:9','cookie_id':'c'*43,'csrf_token':'s'*43},sort_keys=True,separators=(',',':')));credentials.chmod(0o600)
  for profile in ['scoped-record-read-v2','scoped-record-read-v5','scoped-request-status-v1','scoped-request-write-v1']:
   config=root/(profile+'.toml')
   config.write_text('\n'.join([f'vault_root = "{root / "vault"}"',f'state_root = "{root / "state"}"',f'request_root = "{root / "requests"}"',f'share_root = "{root / "share"}"','provider_instance_id = "provider:fixture"',
    'jarvis_public_keys = { "jarvis:fixture" = "'+base64.urlsafe_b64encode(bytes(range(32))).rstrip(b'=').decode()+'" }'])+'\n'+
    (f'[scoped_provider_verifier]\ncredentials_path = "{credentials}"\n' if profile=='scoped-request-write-v1' else '[mcp_scoped_read]\nprincipal = "principal:owner"\nagent = "agent:fixture"\nsession = "session:fixture"\npolicy_revision = "policy:1"\n'))
   config.chmod(0o600)
   params=StdioServerParameters(command=str(release/'bin/second-brain-mcp'),args=[],cwd=str(root),env={**os.environ,'SB_CONFIG':str(config),'SB_MCP_CONTRACT_PROFILE':profile,'TMPDIR':'/var/tmp'})
   async with Client(params,mode='legacy',cache=None,read_timeout_seconds=15) as client:
    names=[tool.name for tool in (await client.list_tools()).tools]
    expected={'scoped-record-read-v2':['sb_read_page','sb_search','sb_generation_status'],'scoped-record-read-v5':['sb_read_page','sb_search','sb_generation_status','sb_request_status'],'scoped-request-status-v1':['sb_request_status'],'scoped-request-write-v1':['sb_write_request']}[profile]
    assert set(names)==set(expected),(profile,names)
    results.append({'profile':profile,'tools':names,'installed_release':True})
 print(json.dumps(results,indent=2))
anyio.run(main)
