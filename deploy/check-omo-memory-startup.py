"""Check OMO CLI MCP registration using temporary config and fake credentials.

No prompt or model request is sent. Does not edit the installed client config.
"""

import argparse
import json
import os
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("omo_entry", type=pathlib.Path)
parser.add_argument("jarvis_entry", type=pathlib.Path)
parser.add_argument("--node", default="node")
options = parser.parse_args()
omo_entry = options.omo_entry.resolve(strict=True)
jarvis_entry = options.jarvis_entry.resolve(strict=True)
with tempfile.TemporaryDirectory(prefix="omo-memory-startup-", dir="/var/tmp") as d:
    r = pathlib.Path(d)
    agent = r / "agent"
    agent.mkdir()
    credentials = r / "credentials.json"
    credentials.write_text(
        json.dumps({"origin": "https://127.0.0.1:9", "cookie_id": "c" * 43, "csrf_token": "s" * 43})
    )
    credentials.chmod(0o600)
    entry = str(jarvis_entry)
    config = {
        "settings": {"nativeToolSearch": False, "importConfigs": []},
        "mcpServers": {
            "jarvis_memory": {
                "type": "stdio",
                "enabled": True,
                "command": options.node,
                "args": [entry, str(credentials)],
                "exposure": "direct",
                "lifecycle": "eager",
                "includeTools": ["jarvis_memory_context"],
            }
        },
    }
    config["mcpServers"]["_ast_grep"] = {"enabled": False}
    (agent / "mcp.json").write_text(json.dumps(config))
    env = {
        **os.environ,
        "OMO_CODING_AGENT_DIR": str(agent),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
        "PI_RULES_DISABLED": "1",
    }
    args = [
        options.node,
        str(omo_entry),
        "--mode",
        "rpc",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--no-builtin-tools",
        "--no-themes",
        "--no-approve",
    ]
    p = subprocess.Popen(
        args,
        cwd=r,
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        p.stdin.write(json.dumps({"id": "inventory", "type": "get_loaded_surfaces"}) + "\n")
        p.stdin.flush()
        import select
        import time

        buf = b""
        events = []
        received = 0
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            ready, _, _ = select.select([p.stdout], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                raise RuntimeError("timeout")
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("early exit")
            received += len(chunk)
            if received > 1024 * 1024:
                raise RuntimeError("RPC_OUTPUT_TOO_LARGE")
            buf += chunk
            lines = buf.split(b"\n")
            buf = lines.pop()
            for line in lines:
                event = json.loads(line)
                events.append(event)
            if any(e.get("id") == "inventory" and e.get("type") == "response" for e in events):
                break
        else:
            raise RuntimeError("timeout")
    except BaseException:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        raise
    response = next(e for e in events if e.get("id") == "inventory" and e.get("type") == "response")
    p.stdin.close()
    p.stdin = None
    try:
        out, err = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    assert p.returncode == 0
    assert response.get("success") is True
    inventory = response["data"]["mcpServers"]
    assert [server["name"] for server in inventory if server["status"] != "disabled"] == [
        "jarvis_memory"
    ]
    assert (
        next(server for server in inventory if server["name"] == "jarvis_memory")["toolCount"] == 1
    )

    print(
        json.dumps(
            {
                "exit": p.returncode,
                "inventory": inventory,
                "model_requests": 0,
                "user_config_changed": False,
            },
            indent=2,
        )
    )
