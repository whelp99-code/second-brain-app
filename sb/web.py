"""Minimal local web console over the existing second-brain service surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, cast, override
from urllib.parse import parse_qs, unquote, urlsplit

from sb.config import Config, load_config
from sb.governance import retention_report, source_status
from sb.inbox import RememberRejected, write_inbox
from sb.mcp import PageNotFoundError, open_conflicts, read_page, recent_changes
from sb.metrics import summary as metrics_summary
from sb.pipeline import read_status, run_all
from sb.search import SearchIndex, committed_paths, committed_text
from sb.uploads import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_REQUEST_BYTES,
    UploadRejected,
    accept_upload,
    supported_suffixes,
)
from sb.vault import GitCommandError, PathEscapeError, Vault, VaultLintError
from sb.write_requests import provider_status

MAX_BODY_BYTES: Final = 1024 * 1024
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765

_INDEX_HTML: Final = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Second Brain</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1f2328;background:#f6f7f8}
body{max-width:980px;margin:0 auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center;gap:12px}
section{background:#fff;border:1px solid #d8dee4;border-radius:14px;padding:18px;margin:16px 0;box-shadow:0 2px 8px #0000000a}
h1,h2{margin-top:0}input,textarea,select,button{font:inherit;border-radius:8px;border:1px solid #aeb7c2;padding:9px}
input,textarea{box-sizing:border-box;width:100%}textarea{min-height:100px;resize:vertical}button{background:#24292f;color:#fff;cursor:pointer}
button.secondary{background:#fff;color:#24292f}.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}.row button{flex:0 0 auto}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;border-radius:8px;padding:12px;min-height:40px}.muted{color:#66707b}
label{display:block;margin:8px 0 4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.dropzone{border:2px dashed #8c959f;border-radius:12px;padding:28px;text-align:center;background:#f6f8fa;cursor:pointer}.dropzone.active{border-color:#0969da;background:#ddf4ff}
</style>
</head>
<body>
<header><div><h1>Second Brain</h1><div class="muted">로컬 지식 엔진 운영 콘솔</div></div><div id="status" class="muted">상태 확인 중</div></header>
<section>
<h2>API 토큰</h2>
<div class="row"><input id="token" type="password" placeholder="SB_WEB_TOKEN 사용 시 입력"><button class="secondary" onclick="saveToken()">저장</button></div>
</section>
<section>
<h2>기억 추가</h2>
<label for="title">제목</label><input id="title" placeholder="예: 계약 일정">
<label for="content">내용</label><textarea id="content" placeholder="기억할 내용을 입력하세요"></textarea>
<p><button onclick="remember()">기억하기</button> <button class="secondary" onclick="runPipeline()">지금 처리</button></p>
<pre id="rememberResult" class="muted"></pre>
</section>
<section>
<h2>파일 업로드</h2>
<div id="dropzone" class="dropzone">PDF·DOCX·HWPX·XLSX·Markdown·TXT·JSON·YAML 파일을 여기에 놓으세요</div>
<p><input id="fileInput" type="file" multiple accept=".pdf,.docx,.hwpx,.xlsx,.md,.txt,.json,.yaml"></p>
<p><button class="secondary" onclick="byId('fileInput').click()">파일 선택</button> <button onclick="runPipeline()">업로드 후 지금 처리</button></p>
<pre id="uploadResult" class="muted"></pre>
</section>
<section>
<h2>검색</h2>
<div class="row"><input id="query" placeholder="검색어" onkeydown="if(event.key==='Enter')search()"><button onclick="search()">검색</button></div>
<div class="grid">
<div><label for="kind">종류</label><select id="kind"><option value="">전체</option><option value="wiki">Wiki</option><option value="daily">Daily</option><option value="conflicts">Conflicts</option></select></div>
<div><label for="searchStatus">상태</label><input id="searchStatus" placeholder="active / conflicted / resolved"></div>
</div>
<pre id="searchResult" class="muted"></pre>
<label for="pageId">페이지 ID</label><div class="row"><input id="pageId" placeholder="검색 결과의 page_id"><button class="secondary" onclick="readPage()">전체 열기</button></div>
<pre id="pageResult" class="muted"></pre>
</section>
<section>
<h2>열린 충돌</h2>
<p><button class="secondary" onclick="loadConflicts()">새로고침</button></p>
<pre id="conflictResult" class="muted"></pre>
<div class="grid">
<div><label for="conflictId">충돌 ID</label><input id="conflictId"></div>
<div><label for="decision">결정</label><select id="decision"><option value="note">검토 메모</option><option value="keep-left">왼쪽 유지</option><option value="keep-right">오른쪽 유지</option></select></div>
</div>
<label for="resolutionNote">해결 메모</label><input id="resolutionNote" placeholder="사람이 확인한 근거">
<p><button onclick="resolveConflict()">해결 기록</button></p>
</section>
<section>
<h2>최근 변경</h2><p><button class="secondary" onclick="loadChanges()">7일 변경 조회</button></p><pre id="changeResult" class="muted"></pre>
</section>
<section>
<h2>소스·보존</h2><p><button class="secondary" onclick="loadGovernance()">상태 조회</button></p><pre id="governanceResult" class="muted"></pre>
</section>
<script>
const byId=(id)=>document.getElementById(id);
function authHeaders(){const token=localStorage.getItem('sb_token')||'';return {'Content-Type':'application/json',...(token?{'Authorization':'Bearer '+token}:{})}}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{...authHeaders(),...(options.headers||{})}});const payload=await response.json();if(!response.ok)throw new Error(payload.error||response.statusText);return payload}
function show(id,value){byId(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)}
function saveToken(){localStorage.setItem('sb_token',byId('token').value);show('rememberResult','토큰을 이 브라우저에 저장했습니다.')}
async function loadStatus(){try{const data=await api('/api/status');byId('status').textContent=data.status}catch(error){byId('status').textContent=error.message}}
async function remember(){try{const data=await api('/api/remember',{method:'POST',body:JSON.stringify({title:byId('title').value,content:byId('content').value})});show('rememberResult',data);byId('content').value=''}catch(error){show('rememberResult',error.message)}}
async function runPipeline(){try{show('rememberResult',await api('/api/run',{method:'POST',body:'{}'}));await loadStatus()}catch(error){show('rememberResult',error.message)}}
function readBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]||'');reader.onerror=()=>reject(reader.error||new Error('파일 읽기 실패'));reader.readAsDataURL(file)})}
async function uploadFiles(files){const results=[];for(const file of files){try{const payload={filename:file.name,relative_path:file.webkitRelativePath||file.name,device_id:'mac-web',content_base64:await readBase64(file)};results.push(await api('/api/uploads',{method:'POST',body:JSON.stringify(payload)}))}catch(error){results.push({filename:file.name,error:error.message})}}show('uploadResult',results)}
async function search(){try{const params=new URLSearchParams({q:byId('query').value});if(byId('kind').value)params.append('kind',byId('kind').value);if(byId('searchStatus').value)params.set('status',byId('searchStatus').value);const data=await api('/api/search?'+params.toString());show('searchResult',data);if(data.results&&data.results.length)byId('pageId').value=data.results[0].page_id}catch(error){show('searchResult',error.message)}}
async function readPage(){try{show('pageResult',await api('/api/pages/'+encodeURIComponent(byId('pageId').value)))}catch(error){show('pageResult',error.message)}}
async function loadConflicts(){try{const data=await api('/api/conflicts');show('conflictResult',data);if(data.conflicts&&data.conflicts.length)byId('conflictId').value=data.conflicts[0].conflict_id}catch(error){show('conflictResult',error.message)}}
async function resolveConflict(){try{const id=byId('conflictId').value;const data=await api('/api/conflicts/'+encodeURIComponent(id)+'/resolve',{method:'POST',body:JSON.stringify({decision:byId('decision').value,note:byId('resolutionNote').value})});show('conflictResult',data);await loadConflicts()}catch(error){show('conflictResult',error.message)}}
async function loadChanges(){try{show('changeResult',await api('/api/changes?days=7'))}catch(error){show('changeResult',error.message)}}
async function loadGovernance(){try{const sources=await api('/api/sources');const retention=await api('/api/retention');const metrics=await api('/api/metrics');show('governanceResult',{...sources,retention,metrics})}catch(error){show('governanceResult',error.message)}}
const dropzone=byId('dropzone');dropzone.addEventListener('dragover',(event)=>{event.preventDefault();dropzone.classList.add('active')});dropzone.addEventListener('dragleave',()=>dropzone.classList.remove('active'));dropzone.addEventListener('drop',(event)=>{event.preventDefault();dropzone.classList.remove('active');uploadFiles(event.dataTransfer.files)});dropzone.addEventListener('click',()=>byId('fileInput').click());byId('fileInput').addEventListener('change',(event)=>uploadFiles(event.target.files));
byId('token').value=localStorage.getItem('sb_token')||'';loadStatus();loadConflicts();loadGovernance();
</script>
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class WebContext:
    config: Config
    root: Path
    token: str | None


class SecondBrainHTTPServer(ThreadingHTTPServer):
    daemon_threads: bool = True
    allow_reuse_address: bool = True


def _query_int(values: dict[str, list[str]], key: str, default: int, maximum: int) -> int:
    raw = values.get(key, [str(default)])[0]
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    return min(max(parsed, 0), maximum)


def _query_optional(values: dict[str, list[str]], key: str) -> str | None:
    value = values.get(key, [""])[0].strip()
    return value or None


def _query_many(values: dict[str, list[str]], key: str) -> tuple[str, ...] | None:
    items = tuple(item for item in values.get(key, ()) if item)
    return items or None


def _is_loopback(host: str) -> bool:
    normalized = host.strip().casefold()
    return normalized in {"localhost", "127.0.0.1", "::1"}


def _latest_briefing(root: Path) -> dict[str, object] | None:
    paths = committed_paths(root, ("daily/",))
    if not paths:
        return None
    rel = max(paths)
    text = committed_text(root, rel)
    if text is None:
        return None
    page_id = rel.removesuffix(".md")
    page = read_page(root, page_id)
    return {
        "page_id": page_id,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "frontmatter": page.frontmatter,
        "body": page.body,
    }


def _string_field(
    data: dict[str, object], key: str, *, required: bool = False, default: str = ""
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    if required and not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _decode_upload(data: dict[str, object]) -> bytes:
    encoded = _string_field(data, "content_base64", required=True)
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("content_base64 is invalid") from exc


def _handler(context: WebContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version: str = "SecondBrain/1"

        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            _ = self.wfile.write(body)

        def _authorized(self) -> bool:
            if context.token is None or not self.path.startswith("/api/"):
                return True
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {context.token}"
            if hmac.compare_digest(supplied, expected):
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False

        def _body(self, maximum: int = MAX_BODY_BYTES) -> dict[str, object]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > maximum:
                raise ValueError("request body too large")
            loaded = cast(object, json.loads(self.rfile.read(length) or b"{}"))
            if not isinstance(loaded, dict):
                raise TypeError("JSON object required")
            return cast(dict[str, object], loaded)

        def do_GET(self) -> None:
            if not self._authorized():
                return
            try:
                self._get()
            except (ValueError, PageNotFoundError, PathEscapeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (OSError, GitCommandError) as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

        def _get(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                body = _INDEX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                _ = self.wfile.write(body)
                return
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/api/status":
                self._json(HTTPStatus.OK, {"status": read_status(context.config)})
                return
            if parsed.path == "/api/capabilities":
                self._json(
                    HTTPStatus.OK,
                    {
                        "desktop": {
                            "file_upload": True,
                            "folder_sync": True,
                            "run_now": True,
                            "latest_briefing": True,
                            "supported_suffixes": list(supported_suffixes()),
                            "max_upload_bytes": MAX_UPLOAD_BYTES,
                        },
                        "provider": provider_status(context.root),
                    },
                )
                return
            if parsed.path == "/api/briefing/latest":
                self._json(HTTPStatus.OK, {"briefing": _latest_briefing(context.root)})
                return
            if parsed.path == "/api/search":
                values = parse_qs(parsed.query, keep_blank_values=True)
                query = values.get("q", [""])[0]
                hits = SearchIndex(context.root).search(
                    query,
                    _query_int(values, "limit", 10, 100),
                    kinds=_query_many(values, "kind"),
                    status=_query_optional(values, "status"),
                    updated_from=_query_optional(values, "updated_from"),
                    updated_to=_query_optional(values, "updated_to"),
                )
                self._json(HTTPStatus.OK, {"results": [hit.as_dict() for hit in hits]})
                return
            if parsed.path.startswith("/api/pages/"):
                page_id = unquote(parsed.path.removeprefix("/api/pages/"))
                self._json(HTTPStatus.OK, read_page(context.root, page_id).as_dict())
                return
            if parsed.path == "/api/changes":
                values = parse_qs(parsed.query, keep_blank_values=True)
                days = _query_int(values, "days", 7, 3650)
                self._json(
                    HTTPStatus.OK,
                    {"changes": [row.as_dict() for row in recent_changes(context.root, days)]},
                )
                return
            if parsed.path == "/api/conflicts":
                self._json(
                    HTTPStatus.OK,
                    {"conflicts": [row.as_dict() for row in open_conflicts(context.root)]},
                )
                return
            if parsed.path == "/api/sources":
                self._json(
                    HTTPStatus.OK,
                    {"sources": list(source_status(context.config))},
                )
                return
            if parsed.path == "/api/retention":
                self._json(HTTPStatus.OK, retention_report(context.root).as_dict())
                return
            if parsed.path == "/api/metrics":
                values = parse_qs(parsed.query, keep_blank_values=True)
                limit = _query_int(values, "limit", 1000, 10_000)
                self._json(HTTPStatus.OK, metrics_summary(context.root, limit).as_dict())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            try:
                self._post()
            except (
                ValueError,
                TypeError,
                RememberRejected,
                UploadRejected,
                FileNotFoundError,
                VaultLintError,
            ) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (OSError, GitCommandError) as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

        def _post(self) -> None:
            parsed = urlsplit(self.path)
            maximum = MAX_UPLOAD_REQUEST_BYTES if parsed.path == "/api/uploads" else MAX_BODY_BYTES
            data = self._body(maximum)
            if parsed.path == "/api/uploads":
                filename = _string_field(data, "filename", required=True)
                relative_path = _string_field(data, "relative_path", default=filename)
                device_id = _string_field(data, "device_id", default="mac")
                declared = _string_field(data, "content_sha256", default="") or None
                receipt = accept_upload(
                    context.root,
                    filename,
                    _decode_upload(data),
                    device_id=device_id,
                    relative_path=relative_path,
                    declared_sha256=declared,
                )
                status = HTTPStatus.CREATED if receipt.state == "queued" else HTTPStatus.OK
                self._json(status, receipt.as_dict())
                return
            if parsed.path == "/api/remember":
                content = data.get("content")
                title = data.get("title")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("content is required")
                if title is not None and not isinstance(title, str):
                    raise ValueError("title must be a string")
                rel = write_inbox(context.root, content, title)
                self._json(HTTPStatus.CREATED, {"inbox_path": rel.as_posix()})
                return
            if parsed.path == "/api/run":
                outcome = run_all(context.config, context.config.configured_source_ids)
                self._json(
                    HTTPStatus.OK,
                    {
                        "run_id": outcome.run_id,
                        "status": outcome.status,
                        "pages": outcome.pages,
                        "conflicts": outcome.conflicts,
                        "errors": outcome.errors,
                        "exit_code": outcome.exit_code,
                        "already_running": outcome.already_running,
                    },
                )
                return
            prefix = "/api/conflicts/"
            suffix = "/resolve"
            if parsed.path.startswith(prefix) and parsed.path.endswith(suffix):
                conflict_id = unquote(parsed.path[len(prefix) : -len(suffix)]).strip("/")
                decision = data.get("decision")
                note = data.get("note", "")
                if not isinstance(decision, str) or not isinstance(note, str):
                    raise ValueError("decision and note must be strings")
                commit = Vault(context.root).resolve_conflict(
                    conflict_id,
                    decision,
                    note,
                    f"web-{conflict_id}",
                )
                self._json(HTTPStatus.OK, {"commit": commit})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def build_server(
    config: Config | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> SecondBrainHTTPServer:
    """Build a local console server; non-loopback binding requires a token."""
    chosen = load_config() if config is None else config
    token = os.environ.get("SB_WEB_TOKEN") or None
    if not _is_loopback(host) and token is None:
        raise ValueError("non-loopback web binding requires SB_WEB_TOKEN")
    context = WebContext(chosen, Path(chosen.vault_root).expanduser(), token)
    return SecondBrainHTTPServer((host, port), _handler(context))


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the local web console until interrupted."""
    server = build_server(host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
