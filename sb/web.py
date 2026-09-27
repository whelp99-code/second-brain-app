"""Minimal local web console over the existing second-brain service surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, cast, override
from urllib.parse import parse_qs, unquote, urlsplit

from sb.config import Config, load_config
from sb.generation_runtime_models import GenerationOperation
from sb.governance import retention_report, source_status
from sb.inbox import RememberRejected, discard_inbox, write_inbox
from sb.life_config import parse_settings
from sb.life_contracts import LifeError, strict_json
from sb.life_http import PREFIX as LIFE_PREFIX
from sb.life_http import read_response as read_life_response
from sb.life_policy import authenticate as authenticate_life
from sb.mcp import PageNotFoundError, open_conflicts, read_page, recent_changes
from sb.metrics import summary as metrics_summary
from sb.ops import status_snapshot
from sb.pipeline import run_all, run_life_operation
from sb.redaction import redact_credentials
from sb.runtime_access import mutate_root, read_root
from sb.search import SearchIndex, committed_paths, committed_text
from sb.uploads import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_REQUEST_BYTES,
    RetractReceiptDict,
    UploadRejected,
    accept_upload,
    read_retract_receipt,
    retract_upload,
    supported_suffixes,
)
from sb.vault import GitCommandError, PathEscapeError, Vault, VaultLintError

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
.dropzone{overflow-wrap:anywhere;border:2px dashed #8c959f;border-radius:12px;padding:28px;text-align:center;background:#f6f8fa;cursor:pointer}.dropzone.active{border-color:#0969da;background:#ddf4ff}
</style>
</head>
<body>
<header><div><h1>Second Brain</h1><div class="muted">로컬 지식 엔진 운영 콘솔</div></div><div id="status" class="muted">상태 확인 중</div></header>
<section>
<h2>API 토큰</h2>
<div class="row"><input id="token" type="password" placeholder="SB_WEB_TOKEN 사용 시 입력"><button class="secondary" onclick="saveToken()">저장</button></div>
</section>
<section>
<h2>운영 준비 상태</h2>
<p id="readinessSummary" role="status">상태 확인 중</p>
<pre id="readinessDetails"></pre>
<p class="muted">백업·원장·처리 상태의 점검 결과입니다. 최근 실행 결과와 함께 확인하세요.</p>
</section>
<section>
<h2>처리 실패</h2>
<p id="failureSummary" role="status">상태 확인 중</p>
<pre id="failureDetails"></pre>
<h3>최근 단계 실행 이력</h3>
<p class="muted">개별 단계의 결과입니다. 마지막 단계의 성공은 전체 배치 성공을 의미하지 않습니다. 과거 실패는 복구 후에도 이력에 남습니다.</p>
<pre id="stageHistory"></pre>
<p class="muted">브리핑 재시도가 보류된 경우 원래 날짜와 입력을 복구해야 합니다. 현재 처리를 다시 실행해도 과거 실패의 복구를 보장하지 않습니다.</p>
</section>
<section>
<h2>기억 추가</h2>
<label for="title">제목</label><input id="title" placeholder="예: 계약 일정">
<label for="content">내용</label><textarea id="content" placeholder="기억할 내용을 입력하세요"></textarea>
<p><button id="rememberButton" onclick="remember()">기억하기</button> <button class="secondary" data-run-button onclick="runPipeline()">지금 처리</button></p>
<pre id="rememberResult" class="muted"></pre>
<label for="inboxPath">영수증 경로</label><div class="row"><input id="inboxPath" placeholder="inbox/....md"><button class="secondary" id="discardButton" onclick="discardInbox()">영수증 삭제</button></div>
<pre id="discardResult" class="muted"></pre>
</section>
<section>
<h2>파일 업로드</h2>
<div id="dropzone" class="dropzone">PDF·DOCX·HWPX·XLSX·Markdown·TXT·JSON·YAML 파일을 여기에 놓으세요</div>
<p><input id="fileInput" type="file" multiple accept=".pdf,.docx,.hwpx,.xlsx,.md,.txt,.json,.yaml"></p>
<p><button class="secondary" onclick="byId('fileInput').click()">파일 선택</button> <button data-run-button onclick="runPipeline()">업로드 후 지금 처리</button></p>
<pre id="uploadResult" class="muted"></pre>
</section>
<section>
<h2>처리 결과</h2>
<p id="runSummary" role="status">아직 이 화면에서 처리를 요청하지 않았습니다.</p>
<pre id="runResult"></pre>
</section>
<section>
<h2>검색</h2>
<div class="row"><input id="query" placeholder="검색어" onkeydown="if(event.key==='Enter')search()"><button onclick="search()">검색</button></div>
<div class="grid">
<div><label for="kind">종류</label><select id="kind"><option value="">전체</option><option value="wiki">Wiki</option><option value="daily">Daily</option><option value="conflicts">Conflicts</option></select></div>
<div><label for="searchStatus">상태</label><input id="searchStatus" placeholder="active / conflicted / resolved"></div>
</div>
<pre id="searchResult" class="muted"></pre>
<label for="pageId">페이지 ID</label><div class="row"><input id="pageId" placeholder="검색 결과의 page_id"><button class="secondary" onclick="readPage()">전체 열기</button><button class="secondary" id="forgetPageButton" onclick="forgetPage()">페이지 삭제</button></div>
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
async function loadReadiness(){try{const response=await fetch('/ready',{headers:authHeaders()});const data=await response.json();if(![200,503].includes(response.status)||!['ready','degraded'].includes(data.status))throw new Error('준비 상태 응답을 확인하지 못했습니다.');show('readinessSummary',data.status==='ready'?'운영 준비 점검 통과':'운영 준비 미완료 — 아래 항목을 확인하세요.');show('readinessDetails',data.reasons||[])}catch(error){show('readinessSummary','운영 준비 상태를 확인하지 못했습니다.');show('readinessDetails',error.message)}}
async function loadStatus(){try{const data=await api('/api/status');byId('status').textContent=data.status;show('stageHistory',data.recent_stages||[]);const failures=data.failures;byId('failureSummary').textContent=failures.total?'미해결 실패 '+failures.total+'건 (단계별: '+Object.entries(failures.by_stage).map(([stage,count])=>stage+' '+count+'건').join(', ')+')':'원장에 기록된 미해결 실패 없음';byId('failureDetails').textContent=failures.items.map(item=>item.stage+' · '+item.key+' · 시도 '+item.attempts+'회\\n'+(item.error||'오류 상세 없음')+(item.retry_hold_reason?'\\n재시도 보류: 원래 브리핑 입력을 복구해야 합니다.':'')).join('\\n\\n')+(failures.omitted?'\\n추가 '+failures.omitted+'건은 상세 목록에서 생략됐습니다.':'')}catch(error){byId('status').textContent=error.message;byId('failureSummary').textContent='실패 상태를 확인하지 못했습니다.';byId('failureDetails').textContent='';show('stageHistory','단계 이력을 확인하지 못했습니다.')}finally{await loadReadiness()}}
let remembering=false;
async function remember(){if(remembering)return;remembering=true;byId('rememberButton').disabled=true;const draft={title:byId('title').value,content:byId('content').value};show('rememberResult','저장 중…');try{const data=await api('/api/remember',{method:'POST',body:JSON.stringify(draft)});show('rememberResult',{message:'받은 편지함에 저장했습니다. 처리 대기 상태이며, 지금 처리 후 검색 결과를 확인하세요.',...data});if(data.inbox_path)byId('inboxPath').value=data.inbox_path;if(byId('title').value===draft.title&&byId('content').value===draft.content)byId('content').value=''}catch(error){show('rememberResult',error.message)}finally{remembering=false;byId('rememberButton').disabled=false}}
async function discardInbox(){show('discardResult','삭제 중…');try{const data=await api('/api/inbox-discard',{method:'POST',body:JSON.stringify({inbox_path:byId('inboxPath').value})});show('discardResult',data)}catch(error){show('discardResult',error.message)}}
let runningPipeline=false;
async function runPipeline(){
 if(runningPipeline)return;
 runningPipeline=true;
 document.querySelectorAll('[data-run-button]').forEach(button=>button.disabled=true);
 show('runSummary','처리 중…');show('runResult','');
 try{
  const data=await api('/api/run',{method:'POST',body:'{}'});
  const messages={ok:'이번 처리가 끝났습니다. 검색 결과와 미해결 실패를 확인하세요.',partial:'일부 처리에 실패했습니다. 처리 실패 목록을 확인하세요.',capped:'처리 한도에 도달했습니다. 남은 입력과 다음 처리 결과를 확인하세요.',failed:'처리에 실패했습니다. 아래 결과와 처리 실패 목록을 확인하세요.'};
  show('runSummary',data.already_running?'다른 처리가 실행 중입니다. 이번 요청은 새 처리를 시작하지 않았습니다.':messages[data.status]||'처리 상태를 판별하지 못했습니다. 아래 결과를 확인하세요.');
  show('runResult',data);
 }catch(error){show('runSummary','처리 결과를 확인하지 못했습니다.');show('runResult',error.message)}
 finally{await loadStatus();runningPipeline=false;document.querySelectorAll('[data-run-button]').forEach(button=>button.disabled=false)}
}
function readBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',',2)[1]||'');reader.onerror=()=>reject(reader.error||new Error('파일 읽기 실패'));reader.readAsDataURL(file)})}
async function uploadFiles(files){const results=[];for(const file of files){try{const payload={filename:file.name,relative_path:file.webkitRelativePath||file.name,device_id:'mac-web',content_base64:await readBase64(file)};results.push(await api('/api/uploads',{method:'POST',body:JSON.stringify(payload)}))}catch(error){results.push({filename:file.name,error:error.message})}}show('uploadResult',results)}
let searchRequestId=0;
let pageRequestId=0;
async function search(){const requestId=++searchRequestId;pageRequestId++;byId('pageId').value='';show('pageResult','');show('searchResult','검색 중…');try{const params=new URLSearchParams({q:byId('query').value});if(byId('kind').value)params.append('kind',byId('kind').value);if(byId('searchStatus').value)params.set('status',byId('searchStatus').value);const data=await api('/api/search?'+params.toString());if(requestId!==searchRequestId)return;show('searchResult',data);if(data.results&&data.results.length)byId('pageId').value=data.results[0].page_id}catch(error){if(requestId===searchRequestId)show('searchResult',error.message)}}
async function readPage(){const requestId=++pageRequestId;const pageId=byId('pageId').value;show('pageResult','불러오는 중…');try{const data=await api('/api/pages/'+encodeURIComponent(pageId));if(requestId===pageRequestId&&byId('pageId').value===pageId)show('pageResult',data)}catch(error){if(requestId===pageRequestId&&byId('pageId').value===pageId)show('pageResult',error.message)}}
async function forgetPage(){const pageId=byId('pageId').value;show('pageResult','삭제 중…');try{const data=await api('/api/pages/'+encodeURIComponent(pageId)+'/forget',{method:'POST',body:'{}'});show('pageResult',data)}catch(error){show('pageResult',error.message)}}
byId('pageId').addEventListener('input',()=>{pageRequestId++;show('pageResult','')});
async function loadConflicts(){try{const data=await api('/api/conflicts');show('conflictResult',data);if(data.conflicts&&data.conflicts.length)byId('conflictId').value=data.conflicts[0].conflict_id}catch(error){show('conflictResult',error.message)}}
async function resolveConflict(){try{const id=byId('conflictId').value;const data=await api('/api/conflicts/'+encodeURIComponent(id)+'/resolve',{method:'POST',body:JSON.stringify({decision:byId('decision').value,note:byId('resolutionNote').value})});show('conflictResult',data);await loadConflicts()}catch(error){show('conflictResult',error.message)}}
async function loadChanges(){try{show('changeResult',await api('/api/changes?days=7'))}catch(error){show('changeResult',error.message)}}
async function loadGovernance(){try{const sources=await api('/api/sources');const retention=await api('/api/retention');const metrics=await api('/api/metrics');show('governanceResult',{...sources,retention,metrics})}catch(error){show('governanceResult',error.message)}}
const dropzone=byId('dropzone');dropzone.addEventListener('dragover',(event)=>{event.preventDefault();dropzone.classList.add('active')});dropzone.addEventListener('dragleave',()=>dropzone.classList.remove('active'));dropzone.addEventListener('drop',(event)=>{event.preventDefault();dropzone.classList.remove('active');uploadFiles(event.dataTransfer.files)});dropzone.addEventListener('click',()=>byId('fileInput').click());byId('fileInput').addEventListener('change',(event)=>uploadFiles(event.target.files));
byId('token').value=localStorage.getItem('sb_token')||'';loadStatus();loadConflicts();loadGovernance();if(location.hash.startsWith('#fix=')){byId('content').value=decodeURIComponent(location.hash.slice(5));remember().then(()=>runPipeline());}else if(location.hash==='#run')runPipeline();
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


def _retract_upload(root: Path, upload_id: str, context: WebContext) -> RetractReceiptDict:
    receipt = retract_upload(root, upload_id)
    if receipt.content_sha256:
        SearchIndex(
            root,
            hybrid=context.config.search_hybrid,
            registry_path=Path(context.config.knowledge_registry)
            if "knowledge_registry" in context.config.raw
            else None,
            min_similarity=context.config.search_min_similarity,
        ).drop_content(receipt.content_sha256)
        vault = Vault(root)
        for folder in ("wiki", "daily", "conflicts"):
            directory = root / folder
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if receipt.content_sha256 in text:
                    page_id = f"{folder}/{path.stem}"
                    try:
                        _ = vault.forget_page(page_id)
                    except (FileNotFoundError, PathEscapeError):
                        continue
    return receipt.as_dict()


def _handler(context: WebContext) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        close_connection: bool
        server_version: str = "SecondBrain/1"

        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _json(self, status: HTTPStatus, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                _ = self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _life_principal(self):
            from datetime import UTC, datetime
            return authenticate_life(parse_settings(context.config.raw),
                self.headers.get("Authorization", ""), datetime.now(UTC), owner_token=context.token)

        def _authorized(self) -> bool:
            if urlsplit(self.path).path.startswith(LIFE_PREFIX + "/"):
                try:
                    self._life_principal()
                    return True
                except LifeError as exc:
                    self._json(exc.status, {"error": exc.code})
                    return False
            if context.token is None and self.path.startswith("/api/") and context.config.raw.get("life"):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "owner_auth_required"})
                return False
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
            payload = self.rfile.read(length) or b"{}"
            loaded = cast(object, strict_json(payload) if self.path.startswith(LIFE_PREFIX + "/") else json.loads(payload))
            if not isinstance(loaded, dict):
                raise TypeError("JSON object required")
            return cast(dict[str, object], loaded)

        def do_GET(self) -> None:
            if not self._authorized():
                return
            try:
                if urlsplit(self.path).path in {"/", "/health", "/ready"}:
                    self._get(context.root)
                else:
                    with read_root(context.config) as pinned:
                        self._get(pinned)
            except LifeError as exc:
                self._json(exc.status, {"error": exc.code})
            except (ValueError, PageNotFoundError, PathEscapeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except (OSError, GitCommandError, RuntimeError) as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

        def _get(self, root: Path) -> None:
            parsed = urlsplit(self.path)
            if parsed.path.startswith(LIFE_PREFIX + "/"):
                from datetime import UTC, datetime
                status, result = read_life_response(root, context.config, parse_settings(context.config.raw),
                    self._life_principal(), parsed.path, parse_qs(parsed.query, keep_blank_values=True), datetime.now(UTC))
                self._life_principal()  # Recheck expiry before returning private content.
                self._json(status, result)
                return
            if parsed.path == "/":
                body = _INDEX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                _ = self.wfile.write(body)
                return
            if parsed.path == "/ready":
                from sb.readiness import readiness

                result = readiness(context.config)
                self._json(
                    HTTPStatus.OK
                    if result["status"] == "ready"
                    else HTTPStatus.SERVICE_UNAVAILABLE,
                    result,
                )
                return
            if parsed.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/api/status":
                pinned_config = replace(
                    context.config, raw={**context.config.raw, "vault_root": str(root)}
                )
                snapshot = status_snapshot(pinned_config)
                last_run = snapshot.get("last_run")
                last_run_status: str | None = None
                summary = "원장에 기록된 실행 없음"
                if isinstance(last_run, dict):
                    candidate = cast(dict[str, object], last_run).get("status")
                    if isinstance(candidate, str):
                        last_run_status = candidate
                        summary = f"최근 단계 실행 {last_run.get('run_id')}: {candidate}"
                last_batch = snapshot.get("last_batch")
                if isinstance(last_batch, dict):
                    summary += (
                        f" · 최근 전체 배치 {last_batch.get('run_id')}: "
                        f"{last_batch.get('status')} (오류 {last_batch.get('errors')})"
                    )
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": summary,
                        "last_run_status": last_run_status,
                        "last_batch": last_batch,
                        "recent_stages": snapshot["recent_stages"],
                        "failures": {
                            "total": sum(
                                cast(dict[str, int], snapshot["failed_by_stage"]).values()
                            ),
                            "by_stage": snapshot["failed_by_stage"],
                            "items": snapshot["failed_derivations"],
                            "omitted": snapshot["failed_details_omitted"],
                        },
                    },
                )
                return
            if parsed.path == "/api/capabilities":
                self._json(
                    HTTPStatus.OK,
                    {
                        "desktop": {
                            "file_upload": True,
                            "folder_sync": True,
                            "file_retract": True,
                            "run_now": True,
                            "latest_briefing": True,
                            "supported_suffixes": list(supported_suffixes()),
                            "max_upload_bytes": MAX_UPLOAD_BYTES,
                        }
                    },
                )
                return
            if parsed.path == "/api/briefing/latest":
                self._json(HTTPStatus.OK, {"briefing": _latest_briefing(root)})
                return
            if parsed.path == "/api/search":
                values = parse_qs(parsed.query, keep_blank_values=True)
                query = values.get("q", [""])[0]
                hits = SearchIndex(
                    root,
                    hybrid=context.config.search_hybrid,
                    registry_path=Path(context.config.knowledge_registry)
                    if "knowledge_registry" in context.config.raw
                    else None,
                    min_similarity=context.config.search_min_similarity,
                ).search(
                    query,
                    _query_int(values, "limit", 10, 100),
                    kinds=_query_many(values, "kind"),
                    status=_query_optional(values, "status"),
                    updated_from=_query_optional(values, "updated_from"),
                    updated_to=_query_optional(values, "updated_to"),
                    scope=_query_optional(values, "scope"),
                )
                self._json(HTTPStatus.OK, {"results": [hit.as_dict() for hit in hits]})
                return
            if parsed.path.startswith("/api/retracts/"):
                receipt_id = unquote(parsed.path.removeprefix("/api/retracts/")).strip("/")
                receipt = read_retract_receipt(root, receipt_id)
                if receipt is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._json(HTTPStatus.OK, receipt.as_dict())
                return
            if parsed.path.startswith("/api/pages/"):
                page_id = unquote(parsed.path.removeprefix("/api/pages/"))
                self._json(HTTPStatus.OK, read_page(root, page_id).as_dict())
                return
            if parsed.path == "/api/changes":
                values = parse_qs(parsed.query, keep_blank_values=True)
                days = _query_int(values, "days", 7, 3650)
                self._json(
                    HTTPStatus.OK,
                    {"changes": [row.as_dict() for row in recent_changes(root, days)]},
                )
                return
            if parsed.path == "/api/conflicts":
                self._json(
                    HTTPStatus.OK,
                    {"conflicts": [row.as_dict() for row in open_conflicts(root)]},
                )
                return
            if parsed.path == "/api/sources":
                self._json(
                    HTTPStatus.OK,
                    {"sources": list(source_status(context.config))},
                )
                return
            if parsed.path == "/api/retention":
                self._json(HTTPStatus.OK, retention_report(root).as_dict())
                return
            if parsed.path == "/api/metrics":
                values = parse_qs(parsed.query, keep_blank_values=True)
                limit = _query_int(values, "limit", 1000, 10_000)
                self._json(HTTPStatus.OK, metrics_summary(root, limit).as_dict())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            try:
                self._post()
            except LifeError as exc:
                self._json(exc.status, {"error": exc.code})
            except (
                ValueError,
                TypeError,
                RememberRejected,
                UploadRejected,
                FileNotFoundError,
                VaultLintError,
            ) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except (OSError, GitCommandError, RuntimeError) as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

        def _post(self) -> None:
            parsed = urlsplit(self.path)
            maximum = MAX_UPLOAD_REQUEST_BYTES if parsed.path == "/api/uploads" else MAX_BODY_BYTES
            data = self._body(maximum)
            if parsed.path.startswith(LIFE_PREFIX + "/"):
                from datetime import UTC, datetime
                principal = self._life_principal()
                if parsed.path == LIFE_PREFIX + "/recall":
                    with read_root(context.config) as pinned:
                        status, result = read_life_response(pinned, context.config, parse_settings(context.config.raw),
                            principal, parsed.path, {}, datetime.now(UTC), body=data)
                    self._life_principal()
                    self._json(status, result)
                    return
                operations = {"/events:batch": "capture", "/corrections": "correct", "/forget": "forget",
                              "/run": "run", "/views/obsidian/ack": "ack",
                              "/predictions": "prediction_issue", "/predictions/actuals": "prediction_actual",
                              "/source-retractions": "source_retract", "/imports": "import"}
                suffix = parsed.path.removeprefix(LIFE_PREFIX)
                operation = operations.get(suffix)
                if suffix.startswith(("/overland/", "/health-import/")):
                    operation = "sensor_location" if suffix.startswith("/overland/") else "sensor_health"
                    data = {"source_id": unquote(suffix.rsplit("/", 1)[1]), "payload": data}
                if suffix.startswith("/questions/") and suffix.endswith("/response"):
                    if "question_id" in data:
                        raise LifeError("LIFE_FIELDS_INVALID")
                    data = {**data, "question_id": unquote(suffix[len("/questions/"):-len("/response")])}
                    operation = "answer"
                if operation is None:
                    raise LifeError("LIFE_ROUTE_NOT_FOUND", 404)
                result = run_life_operation(context.config, operation, data, principal)
                self._life_principal()
                self._json(HTTPStatus.OK if operation in {"run", "ack", "sensor_location", "sensor_health"} else HTTPStatus.ACCEPTED, result)
                return
            if parsed.path == "/api/uploads/retract":
                upload_id = _string_field(data, "upload_id", required=True)
                try:
                    receipt = mutate_root(
                        context.config,
                        GenerationOperation.INBOX,
                        lambda root: _retract_upload(root, upload_id, context),
                    )
                except (OSError, TimeoutError, ConnectionError):
                    from datetime import UTC, datetime

                    checked_at = (
                        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                    )
                    self._json(
                        HTTPStatus.OK,
                        {
                            "deleted": False,
                            "indexed": False,
                            "restored": False,
                            "receipt_id": "",
                            "checked_at": checked_at,
                            "upload_id": upload_id,
                        },
                    )
                    return
                self._json(HTTPStatus.OK, receipt)
                return
            if parsed.path == "/api/uploads":
                filename = _string_field(data, "filename", required=True)
                relative_path = _string_field(data, "relative_path", default=filename)
                device_id = _string_field(data, "device_id", default="mac")
                declared = _string_field(data, "content_sha256", default="") or None
                receipt = mutate_root(
                    context.config,
                    GenerationOperation.INBOX,
                    lambda root: accept_upload(
                        root,
                        filename,
                        _decode_upload(data),
                        device_id=device_id,
                        relative_path=relative_path,
                        declared_sha256=declared,
                    ),
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
                rel = mutate_root(
                    context.config,
                    GenerationOperation.INBOX,
                    lambda root: write_inbox(root, content, title),
                )
                self._json(HTTPStatus.CREATED, {"inbox_path": rel.as_posix()})
                return
            if parsed.path == "/api/inbox-discard":
                inbox_path = data.get("inbox_path")
                if not isinstance(inbox_path, str) or not inbox_path.strip():
                    raise ValueError("inbox_path is required")
                discarded = mutate_root(
                    context.config,
                    GenerationOperation.INBOX,
                    lambda root: discard_inbox(root, inbox_path),
                )
                self._json(HTTPStatus.OK, {"discarded": discarded})
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
                        "failure": redact_credentials(outcome.failure)[:1000]
                        if outcome.failure
                        else None,
                    },
                )
                return
            if parsed.path.startswith("/api/pages/") and parsed.path.endswith("/forget"):
                page_id = unquote(parsed.path[len("/api/pages/") : -len("/forget")]).strip("/")
                if not page_id:
                    raise ValueError("page_id is required")
                try:
                    commit = mutate_root(
                        context.config,
                        GenerationOperation.EFFECT,
                        lambda root: Vault(root).forget_page(page_id),
                    )
                except FileNotFoundError as exc:
                    raise ValueError("compiled page missing") from exc
                self._json(HTTPStatus.OK, {"forgotten": page_id, "commit": commit})
                return
            prefix = "/api/conflicts/"
            suffix = "/resolve"
            if parsed.path.startswith(prefix) and parsed.path.endswith(suffix):
                conflict_id = unquote(parsed.path[len(prefix) : -len(suffix)]).strip("/")
                decision = data.get("decision")
                note = data.get("note", "")
                if not isinstance(decision, str) or not isinstance(note, str):
                    raise ValueError("decision and note must be strings")
                try:
                    commit = mutate_root(
                        context.config,
                        GenerationOperation.EFFECT,
                        lambda root: Vault(root).resolve_conflict(
                            conflict_id,
                            decision,
                            note,
                            f"web-{conflict_id}",
                        ),
                    )
                except FileNotFoundError as exc:
                    raise ValueError("conflict missing") from exc
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
