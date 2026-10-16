"""Minimal local web console over the existing second-brain service surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from socketserver import BaseServer
from typing import ClassVar, Final, override
from urllib.parse import parse_qs, unquote, urlsplit

from sb.config import Config, load_config
from sb.effect_values import JsonInput, JsonObject
from sb.generation_runtime_models import GenerationOperation
from sb.governance import retention_report, source_status
from sb.inbox import RememberRejected, discard_inbox, write_inbox
from sb.life_actor import LifeActor
from sb.life_contracts import LifeInputError
from sb.life_json import decode_json
from sb.managed_file_inspection import ManagedInspectionError
from sb.mcp import PageNotFoundError, open_conflicts, read_page, recent_changes
from sb.metrics import summary as metrics_summary
from sb.observation_admission import AdmissionError, ObservationReceipt, admit, read
from sb.ops import status_snapshot
from sb.owner_effects import OwnerEffectError, apply_page_effect, page_receipt
from sb.parsers.capabilities import parser_capabilities
from sb.personal_observation import MAX_ENVELOPE_BYTES
from sb.pipeline import run_all
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
from sb.vault_owner import require_vault_owner

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
input,textarea{box-sizing:border-box;width:100%}select{box-sizing:border-box;max-width:100%}textarea{min-height:100px;resize:vertical}button{background:#24292f;color:#fff;cursor:pointer}
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
<h3>기억 정정</h3>
<p class="muted">전체 열기로 현재 영수증을 받은 뒤 정정할 문장을 선택하세요. 삭제는 이 페이지의 기억과 관련 파생본·관리 백업을 지우고 재유입을 차단합니다.</p>
<label for="correctionRecord">정정할 문장</label><select id="correctionRecord" onchange="selectCorrection()"></select>
<label for="correctionContent">정정 내용</label><textarea id="correctionContent"></textarea>
<p><button id="correctPageButton" onclick="correctPage()">정정 저장</button></p>
<pre id="correctionResult" class="muted"></pre>
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
async function api(path,options={}){const response=await fetch(path,{...options,headers:{...authHeaders(),...(options.headers||{})}});const payload=await response.json();if(!response.ok)throw new Error((response.status===404?'404: ':'')+(payload.error||response.statusText));return payload}
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
let pageReceipt=null;
let pageRecords=[];
let editingPage=false;
function clearPageReceipt(){pageReceipt=null;pageRecords=[];byId('correctionRecord').replaceChildren()}
function selectCorrection(){const record=pageRecords.find(row=>row.record_id===byId('correctionRecord').value);if(record)byId('correctionContent').value=record.record_text}
async function search(){const requestId=++searchRequestId;pageRequestId++;clearPageReceipt();byId('pageId').value='';show('pageResult','');show('searchResult','검색 중…');try{const params=new URLSearchParams({q:byId('query').value});if(byId('kind').value)params.append('kind',byId('kind').value);if(byId('searchStatus').value)params.set('status',byId('searchStatus').value);const data=await api('/api/search?'+params.toString());if(requestId!==searchRequestId)return;show('searchResult',data);if(data.results&&data.results.length)byId('pageId').value=data.results[0].page_id}catch(error){if(requestId===searchRequestId)show('searchResult',error.message)}}
async function readPage(){const requestId=++pageRequestId;const pageId=byId('pageId').value;clearPageReceipt();show('pageResult','불러오는 중…');try{const data=await api('/api/pages/'+encodeURIComponent(pageId));if(requestId!==pageRequestId||byId('pageId').value!==pageId)return;show('pageResult',data);pageReceipt=data.receipt;pageRecords=data.records||[];for(const record of pageRecords){const option=document.createElement('option');option.value=record.record_id;option.textContent=record.record_text;byId('correctionRecord').append(option)}selectCorrection()}catch(error){if(requestId===pageRequestId&&byId('pageId').value===pageId)show('pageResult',error.message)}}
async function editPage(operation){
 if(editingPage)return;
 const output=operation==='correct'?'correctionResult':'pageResult';
 const pageId=byId('pageId').value;
 if(!pageReceipt||pageReceipt.page_id!==pageId){show(output,'전체 열기로 현재 페이지 영수증을 먼저 확인하세요.');return}
 const draft={receipt:pageReceipt,...(operation==='correct'?{record_id:byId('correctionRecord').value,content:byId('correctionContent').value}:{})};
 const requestId=++pageRequestId;
 editingPage=true;byId('correctPageButton').disabled=true;byId('forgetPageButton').disabled=true;
 show(output,operation==='correct'?'정정 중…':'삭제 중…');
 try{const data=await api('/api/pages/'+encodeURIComponent(pageId)+'/'+operation,{method:'POST',body:JSON.stringify(draft)});if(requestId===pageRequestId&&byId('pageId').value===pageId){show(output,data);clearPageReceipt();show('searchResult','검색을 다시 실행해 변경 결과를 확인하세요.');if(operation==='correct')show('pageResult','정정됐습니다. 전체 열기로 새 영수증을 확인하세요.')}}
 catch(error){if(requestId===pageRequestId&&byId('pageId').value===pageId)show(output,error.message)}
 finally{editingPage=false;byId('correctPageButton').disabled=false;byId('forgetPageButton').disabled=false}
}
async function forgetPage(){await editPage('forget')}
async function correctPage(){await editPage('correct')}
byId('pageId').addEventListener('input',()=>{pageRequestId++;clearPageReceipt();show('pageResult','')});
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


class WebHandlerContractError(TypeError):
    """The configured native server handler no longer implements this API."""


class SecondBrainHTTPServer(ThreadingHTTPServer):
    daemon_threads: bool = True
    allow_reuse_address: bool = True

    @property
    def handler_class(self) -> type[Handler]:
        handler = self.RequestHandlerClass
        if not isinstance(handler, type) or not issubclass(handler, Handler):
            raise WebHandlerContractError(
                "configured request handler must implement the web Handler"
            )
        return handler


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


def _latest_briefing(root: Path) -> Mapping[str, JsonInput] | None:
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
    data: Mapping[str, JsonInput], key: str, *, required: bool = False, default: str = ""
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    if required and not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _decode_upload(data: Mapping[str, JsonInput]) -> bytes:
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


def _observation_body(receipt: ObservationReceipt) -> dict[str, JsonInput]:
    body = receipt.as_dict()
    body["searchable"] = receipt.searchable
    return body


def _admission_status(exc: AdmissionError) -> HTTPStatus:
    if exc.code == "EMITTER_UNREGISTERED":
        return HTTPStatus.FORBIDDEN
    if exc.code == "OBSERVATION_CONFLICT":
        return HTTPStatus.CONFLICT
    return HTTPStatus.BAD_REQUEST


class Handler(BaseHTTPRequestHandler):
    connection: socket
    _life_actor: LifeActor | None = None
    context: ClassVar[WebContext]
    life_config: Config

    def __init__(
        self, request: socket, client_address: tuple[str, int], server: BaseServer
    ) -> None:
        self.life_config = self.context.config
        super().__init__(request, client_address, server)

    @property
    def life_actor(self) -> LifeActor:
        if self._life_actor is None:
            raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
        return self._life_actor

    close_connection: bool
    server_version: str = "SecondBrain/1"

    @override
    def log_message(self, format: str, *args: JsonInput) -> None:
        del format, args

    def json_response(self, status: HTTPStatus, payload: JsonInput) -> None:
        if (
            200 <= int(status) < 300
            and self._life_actor is not None
            and urlsplit(self.path).path.startswith("/api/life/v1/")
        ):
            from sb.life_auth import admin_token, current_config
            from sb.life_contracts import LifeInputError
            from sb.life_http import authorize

            try:
                fresh = current_config(self.context.config)
                actor = authorize(
                    fresh,
                    self.headers.get("Authorization", ""),
                    admin_token(fresh, self.context.config, self.context.token),
                )
                if actor != self.life_actor or fresh.raw != self.life_config.raw:
                    status, payload = HTTPStatus.FORBIDDEN, {"error": "LIFE_AUTH_CHANGED_RETRY"}
            except LifeInputError:
                status, payload = (
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "LIFE_AUTH_CONFIG_UNAVAILABLE"},
                )
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

    def _authorized(self) -> bool:
        if urlsplit(self.path).path.startswith("/api/life/v1/"):
            from sb.life_auth import admin_token, current_config
            from sb.life_contracts import LifeInputError
            from sb.life_http import authorize, error_status

            try:
                self.life_config = current_config(self.context.config)
                principal = authorize(
                    self.life_config,
                    self.headers.get("Authorization", ""),
                    admin_token(self.life_config, self.context.config, self.context.token),
                )
            except LifeInputError as exc:
                self.json_response(HTTPStatus(error_status(exc.code)), {"error": exc.code})
                return False
            self._life_actor = principal
            if principal is not None:
                return True
            self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False
        if self.context.token is None or not self.path.startswith("/api/"):
            return True
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.context.token}"
        if hmac.compare_digest(supplied, expected):
            return True
        self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def _body(self, maximum: int = MAX_BODY_BYTES) -> JsonObject:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length < 0 or length > maximum:
            raise ValueError("request body too large")
        loaded = decode_json(self.rfile.read(length) or b"{}")
        if not isinstance(loaded, dict):
            raise TypeError("JSON object required")
        return loaded

    def do_GET(self) -> None:
        if not self._authorized():
            return
        try:
            if urlsplit(self.path).path in {"/", "/health", "/ready"}:
                self._get(self.context.root)
            else:
                with read_root(self.context.config) as pinned:
                    self._get(pinned)
        except PageNotFoundError as exc:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (ValueError, PathEscapeError) as exc:
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (OSError, GitCommandError, RuntimeError) as exc:
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

    def get_response(self, root: Path) -> None:
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/api/life/v1/"):
            from sb.life_contracts import LifeInputError
            from sb.life_http import error_status, read_endpoint

            try:
                result = read_endpoint(self.life_config, root, self.life_actor, self.path)
                self.json_response(HTTPStatus.OK, result)
            except LifeInputError as exc:
                self.json_response(HTTPStatus(error_status(exc.code)), {"error": exc.code})
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

            result = readiness(self.context.config)
            self.json_response(
                HTTPStatus.OK if result["status"] == "ready" else HTTPStatus.SERVICE_UNAVAILABLE,
                result,
            )
            return
        if parsed.path == "/health":
            self.json_response(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/api/status":
            pinned_config = replace(
                self.context.config, raw={**self.context.config.raw, "vault_root": str(root)}
            )
            snapshot = status_snapshot(pinned_config)
            last_run = snapshot.get("last_run")
            last_run_status: str | None = None
            summary = "원장에 기록된 실행 없음"
            if last_run is not None:
                candidate = last_run["status"]
                last_run_status = candidate
                summary = f"최근 단계 실행 {last_run.get('run_id')}: {candidate}"
            last_batch = snapshot.get("last_batch")
            if last_batch is not None:
                summary += (
                    f" · 최근 전체 배치 {last_batch.get('run_id')}: "
                    f"{last_batch.get('status')} (오류 {last_batch.get('errors')})"
                )
            self.json_response(
                HTTPStatus.OK,
                {
                    "status": summary,
                    "last_run_status": last_run_status,
                    "last_batch": last_batch,
                    "recent_stages": snapshot["recent_stages"],
                    "failures": {
                        "total": sum(snapshot["failed_by_stage"].values()),
                        "by_stage": snapshot["failed_by_stage"],
                        "items": snapshot["failed_derivations"],
                        "omitted": snapshot["failed_details_omitted"],
                    },
                },
            )
            return
        if parsed.path == "/api/capabilities":
            self.json_response(
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
                    },
                    "intake_max_bytes": MAX_UPLOAD_BYTES,
                    "parsers": decode_json(json.dumps(parser_capabilities())),
                },
            )
            return
        if parsed.path == "/api/briefing/latest":
            self.json_response(HTTPStatus.OK, {"briefing": _latest_briefing(root)})
            return
        if parsed.path == "/api/search":
            values = parse_qs(parsed.query, keep_blank_values=True)
            query = values.get("q", [""])[0]
            hits = SearchIndex(
                root,
                hybrid=self.context.config.search_hybrid,
                registry_path=Path(self.context.config.knowledge_registry)
                if "knowledge_registry" in self.context.config.raw
                else None,
                min_similarity=self.context.config.search_min_similarity,
            ).search(
                query,
                _query_int(values, "limit", 10, 100),
                kinds=_query_many(values, "kind"),
                status=_query_optional(values, "status"),
                updated_from=_query_optional(values, "updated_from"),
                updated_to=_query_optional(values, "updated_to"),
                scope=_query_optional(values, "scope"),
            )
            self.json_response(HTTPStatus.OK, {"results": [hit.as_dict() for hit in hits]})
            return
        if parsed.path.startswith("/api/retracts/"):
            receipt_id = unquote(parsed.path.removeprefix("/api/retracts/")).strip("/")
            receipt = read_retract_receipt(root, receipt_id)
            if receipt is None:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self.json_response(HTTPStatus.OK, receipt.as_dict())
            return
        if parsed.path.startswith("/api/pages/"):
            page_id = unquote(parsed.path.removeprefix("/api/pages/"))
            page = read_page(root, page_id).as_dict()
            self.json_response(HTTPStatus.OK, {**page, **page_receipt(root, page_id)})
            return
        if parsed.path == "/api/changes":
            values = parse_qs(parsed.query, keep_blank_values=True)
            days = _query_int(values, "days", 7, 3650)
            self.json_response(
                HTTPStatus.OK,
                {"changes": [row.as_dict() for row in recent_changes(root, days)]},
            )
            return
        if parsed.path == "/api/conflicts":
            self.json_response(
                HTTPStatus.OK,
                {"conflicts": [row.as_dict() for row in open_conflicts(root)]},
            )
            return
        if parsed.path == "/api/sources":
            self.json_response(
                HTTPStatus.OK,
                {"sources": list(source_status(self.context.config))},
            )
            return
        if parsed.path.startswith("/api/source-observations/"):
            receipt_id = unquote(parsed.path.removeprefix("/api/source-observations/")).strip("/")
            if "/" in receipt_id or not receipt_id:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                receipt = read(root, receipt_id)
            except AdmissionError as exc:
                self.json_response(_admission_status(exc), {"error": exc.code})
                return
            if receipt is None:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self.json_response(HTTPStatus.OK, _observation_body(receipt))
            return
        if parsed.path == "/api/retention":
            self.json_response(HTTPStatus.OK, retention_report(root).as_dict())
            return
        if parsed.path == "/api/metrics":
            values = parse_qs(parsed.query, keep_blank_values=True)
            limit = _query_int(values, "limit", 1000, 10_000)
            self.json_response(HTTPStatus.OK, metrics_summary(root, limit).as_dict())
            return
        self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            self._post()
        except AdmissionError as exc:
            self.json_response(_admission_status(exc), {"error": exc.code})
        except OwnerEffectError as exc:
            self.json_response(HTTPStatus.CONFLICT, {"error": str(exc)})
        except ManagedInspectionError as exc:
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
        except (
            ValueError,
            TypeError,
            RememberRejected,
            UploadRejected,
            FileNotFoundError,
            VaultLintError,
        ) as exc:
            self.json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (OSError, GitCommandError, RuntimeError) as exc:
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

    def _post(self) -> None:
        parsed = urlsplit(self.path)
        maximum = MAX_UPLOAD_REQUEST_BYTES if parsed.path == "/api/uploads" else MAX_BODY_BYTES
        if parsed.path == "/api/source-observations":
            maximum = ((MAX_ENVELOPE_BYTES + 2) // 3) * 4 + 8192
        if parsed.path in {
            "/api/life/v1/events:batch",
            "/api/life/v1/exports/import",
        } or parsed.path.startswith(("/api/life/v1/overland/", "/api/life/v1/health/")):
            maximum = 24 * 1024 * 1024
        data = self._body(maximum)
        if parsed.path.startswith("/api/life/v1/"):
            self._life_post(parsed.path, data)
            return
        if parsed.path == "/api/uploads/retract":
            upload_id = _string_field(data, "upload_id", required=True)
            try:
                receipt = mutate_root(
                    self.context.config,
                    GenerationOperation.INBOX,
                    lambda root: _retract_upload(root, upload_id, self.context),
                )
            except (OSError, TimeoutError, ConnectionError):
                from datetime import UTC, datetime

                checked_at = (
                    datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )
                self.json_response(
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
            self.json_response(HTTPStatus.OK, receipt)
            return
        if parsed.path == "/api/source-observations":
            emitter = _string_field(data, "emitter", required=True)
            encoded = data.get("payload_base64")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError("payload_base64 is required")
            try:
                payload = base64.b64decode(encoded, validate=True)
            except binascii.Error as exc:
                raise ValueError("payload_base64 is invalid") from exc
            receipt = mutate_root(
                self.context.config,
                GenerationOperation.INBOX,
                lambda root: admit(root, payload, emitter=emitter, config=self.context.config),
            )
            status = HTTPStatus.CREATED if receipt.state == "accepted_pending" else HTTPStatus.OK
            self.json_response(status, _observation_body(receipt))
            return
        if parsed.path == "/api/uploads":
            filename = _string_field(data, "filename", required=True)
            relative_path = _string_field(data, "relative_path", default=filename)
            device_id = _string_field(data, "device_id", default="mac")
            declared = _string_field(data, "content_sha256", default="") or None
            receipt = mutate_root(
                self.context.config,
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
            self.json_response(status, receipt.as_dict())
            return
        if parsed.path == "/api/remember":
            content = data.get("content")
            title = data.get("title")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("content is required")
            if title is not None and not isinstance(title, str):
                raise ValueError("title must be a string")
            rel = mutate_root(
                self.context.config,
                GenerationOperation.INBOX,
                lambda root: write_inbox(root, content, title),
            )
            self.json_response(HTTPStatus.CREATED, {"inbox_path": rel.as_posix()})
            return
        if parsed.path == "/api/inbox-discard":
            inbox_path = data.get("inbox_path")
            if not isinstance(inbox_path, str) or not inbox_path.strip():
                raise ValueError("inbox_path is required")
            discarded = mutate_root(
                self.context.config,
                GenerationOperation.INBOX,
                lambda root: discard_inbox(root, inbox_path),
            )
            self.json_response(HTTPStatus.OK, {"discarded": discarded})
            return
        if parsed.path == "/api/run":
            outcome = run_all(self.context.config, self.context.config.configured_source_ids)
            self.json_response(
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
        if parsed.path.startswith("/api/pages/") and parsed.path.endswith(("/forget", "/correct")):
            prefix, _, operation = parsed.path.rpartition("/")
            page_id = unquote(prefix.removeprefix("/api/pages/")).strip("/")
            if not page_id:
                raise ValueError("page_id is required")
            result = apply_page_effect(
                self.context.config,
                page_id,
                "correct" if operation == "correct" else "forget",
                data.get("receipt"),
                record_id=_string_field(data, "record_id"),
                content=_string_field(data, "content"),
            )
            self.json_response(HTTPStatus.OK, result)
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
                    self.context.config,
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
            self.json_response(HTTPStatus.OK, {"commit": commit})
            return
        self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _life_import_request(self, path: str, data: JsonObject) -> bool:
        import base64
        import binascii

        from sb.life_contracts import LifeInputError
        from sb.life_http import error_status, require_source
        from sb.life_values import canonical_bytes, text
        from sb.pipeline import run_life_import

        route = path.removeprefix("/api/life/v1/")
        if not (route == "exports/import" or route.startswith(("overland/", "health/"))):
            return False
        try:
            if self.life_actor.client and not self.life_actor.can_write:
                raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
            if route == "exports/import":
                if set(data) != {"source_id", "format", "filename", "content_base64"}:
                    raise LifeInputError("LIFE_IMPORT_INVALID")
                source = require_source(self.life_actor, data["source_id"])
                kind = text(data["format"], maximum=64)
                filename = text(data["filename"], maximum=512)
                try:
                    encoded = data["content_base64"]
                    if not isinstance(encoded, str):
                        raise LifeInputError("LIFE_IMPORT_INVALID")
                    raw = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError, TypeError) as exc:
                    raise LifeInputError("LIFE_IMPORT_INVALID") from exc
            else:
                kind, _, name = route.partition("/")
                source = require_source(self.life_actor, unquote(name))
                filename = kind + ".json"
                raw = canonical_bytes(data)
            outcome, result = run_life_import(
                self.life_config, source, kind, raw, filename=filename
            )
            if outcome.already_running:
                self.json_response(HTTPStatus.CONFLICT, {"error": "LIFE_WRITER_BUSY"})
            elif outcome.exit_code:
                code = (outcome.failure or "LIFE_IMPORT_FAILED").split(": ")[-1]
                code = (
                    code if code.startswith("LIFE_") and len(code) <= 100 else "LIFE_IMPORT_FAILED"
                )
                self.json_response(
                    HTTPStatus(error_status(code))
                    if code != "LIFE_IMPORT_FAILED"
                    else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": code, "run_id": outcome.run_id},
                )
            else:
                # Overland removes its local queue only for this result.
                self.json_response(
                    HTTPStatus.OK if kind == "overland" else HTTPStatus.ACCEPTED,
                    {"result": "ok", **result, "run_id": outcome.run_id},
                )
        except LifeInputError as exc:
            self.json_response(HTTPStatus(error_status(exc.code)), {"error": exc.code})
        return True

    def _life_workflow_request(self, path: str, data: JsonObject) -> bool:
        from datetime import UTC, datetime

        from sb.life_api_reads import recall_request
        from sb.life_contracts import LifeInputError
        from sb.life_http import error_status
        from sb.pipeline import run_life_workflow

        route = path.removeprefix("/api/life/v1/")
        routes = {
            "questions/generate": "questions_generate",
            "briefings/generate": "briefing_generate",
            "tick": "tick",
            "deliveries/prepare": "delivery_prepare",
            "deliveries/state": "delivery_finish",
            "deliveries/opened": "delivery_opened",
            "relations": "relation_put",
            "entity-aliases": "entity_alias",
            "predictions/issue": "prediction_issue",
            "predictions/evaluate": "prediction_evaluate",
            "models/reserve": "model_reserve",
            "models/settle": "model_settle",
            "views/obsidian/ack": "view_ack",
            "collection/status": "collection_status",
        }
        command = routes.get(route)
        if route.startswith("questions/") and route.endswith("/response"):
            command = "question_response"
            data = {
                **data,
                "question_id": unquote(route[len("questions/") : -len("/response")]),
            }
        if route != "recall" and command is None:
            return False
        clock = datetime.now(UTC)
        try:
            if route == "recall":
                with read_root(self.context.config) as root:
                    result = recall_request(
                        self.life_config, root, self.life_actor, data, now=clock
                    )
                self.json_response(HTTPStatus.OK, result)
                return True
            if command is None:
                return False
            outcome, result = run_life_workflow(
                self.life_config,
                command,
                data,
                source_ids=self.life_actor.source_ids,
                scopes=self.life_actor.scopes,
                now=clock,
                client=self.life_actor.client,
                device_id=self.life_actor.device_id,
                client_can_write=self.life_actor.can_write,
            )
            if outcome.already_running:
                self.json_response(
                    HTTPStatus.CONFLICT, {"error": "LIFE_WRITER_BUSY", "retryable": True}
                )
            elif outcome.exit_code:
                detail = outcome.failure or "LIFE_WORKFLOW_FAILED"
                code = detail.split(": ")[-1]
                if not code.startswith("LIFE_") or len(code) > 100:
                    code = "LIFE_WORKFLOW_FAILED"
                status = error_status(code) if code != "LIFE_WORKFLOW_FAILED" else 503
                self.json_response(HTTPStatus(status), {"error": code, "run_id": outcome.run_id})
            else:
                self.json_response(
                    HTTPStatus.ACCEPTED,
                    {"state": "recorded", "result": result, "run_id": outcome.run_id},
                )
        except LifeInputError as exc:
            self.json_response(HTTPStatus(error_status(exc.code)), {"error": exc.code})
        return True

    def _life_post(self, path: str, data: JsonObject) -> None:
        if self._life_import_request(path, data):
            return
        if self._life_workflow_request(path, data):
            return
        from datetime import UTC, datetime
        from hashlib import sha256

        from sb.life_contracts import LifeInputError
        from sb.life_http import current_event, error_status, require_source
        from sb.life_values import text
        from sb.pipeline import run_life_batch, run_life_forget
        from sb.store.life import read_life_store

        clock = datetime.now(UTC)
        try:
            if self.life_actor.client and not self.life_actor.can_write:
                raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
            if path == "/api/life/v1/events:batch":
                if set(data) != {"source_id", "items"} or not isinstance(data["items"], list):
                    raise LifeInputError("LIFE_BATCH_INVALID")
                source = require_source(self.life_actor, data["source_id"])
                outcome, receipts = run_life_batch(
                    self.life_config, source, data["items"], now=clock
                )
            elif path == "/api/life/v1/corrections":
                allowed = {
                    "event_id",
                    "expected_revision",
                    "replacement",
                    "reason",
                    "idempotency_key",
                    "event_status",
                }
                if set(data) - allowed:
                    raise LifeInputError("LIFE_UNKNOWN_FIELD")
                identity = text(data.get("event_id"), maximum=160)
                key = text(data.get("idempotency_key"), maximum=256)
                replacement = text(data.get("replacement"), maximum=100000, empty=True)
                reason = text(data.get("reason"), maximum=2000)
                expected = data.get("expected_revision")
                if type(expected) is not int or expected < 1:
                    raise LifeInputError("LIFE_REVISION_INVALID")
                with read_root(self.context.config) as root:
                    event = current_event(self.life_config, root, self.life_actor, identity, clock)
                    with read_life_store(root) as store:
                        original = decode_json(
                            store.evidence(
                                identity,
                                scopes=self.life_actor.scopes,
                                now=clock,
                                revision=expected,
                            )
                        )
                if not isinstance(original, dict):
                    raise LifeInputError("LIFE_RECORD_CORRUPT")
                original.update(
                    body=replacement,
                    change_reason=reason,
                    source_version="correction-" + sha256(key.encode()).hexdigest(),
                    evidence_level="user_asserted",
                    review_state="confirmed",
                )
                if "event_status" in data:
                    original["event_status"] = data["event_status"]
                outcome, receipts = run_life_batch(
                    self.life_config,
                    event.source_id,
                    [
                        {
                            "idempotency_key": key,
                            "payload": original,
                            "expected_revision": expected,
                        }
                    ],
                    now=clock,
                )
            elif path == "/api/life/v1/withdrawals":
                if self.life_actor.client:
                    raise LifeInputError("LIFE_SOURCE_NOT_ALLOWED")
                if set(data) != {"source_id", "event_id", "expected_revision"}:
                    raise LifeInputError("LIFE_INPUT_INVALID")
                source = require_source(self.life_actor, data["source_id"])
                identity = text(data.get("event_id"), maximum=160)
                expected = data.get("expected_revision")
                if type(expected) is not int or expected < 1:
                    raise LifeInputError("LIFE_REVISION_INVALID")
                outcome = run_life_forget(self.life_config, source, identity, expected, now=clock)
                receipts = ()
            else:
                raise LifeInputError("LIFE_ROUTE_NOT_FOUND")
            if outcome.already_running:
                self.json_response(
                    HTTPStatus.CONFLICT, {"error": "LIFE_WRITER_BUSY", "retryable": True}
                )
            elif outcome.exit_code != 0:
                detail = outcome.failure or "LIFE_PUBLICATION_FAILED"
                code = detail.split(": ")[-1]
                if not code.startswith("LIFE_"):
                    code = "LIFE_PUBLICATION_FAILED"
                self.json_response(
                    HTTPStatus(error_status(code))
                    if code != "LIFE_PUBLICATION_FAILED"
                    else HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": code, "run_id": outcome.run_id, "state": "not_confirmed"},
                )
            else:
                result = {
                    "receipts": list(receipts),
                    "run_id": outcome.run_id,
                    "state": "published",
                    "device_projected": False,
                }
                if path.endswith("withdrawals"):
                    result.update(physical_raw_erasure=False, offline_copies_recalled=False)
                self.json_response(HTTPStatus.ACCEPTED, result)
        except LifeInputError as exc:
            self.json_response(HTTPStatus(error_status(exc.code)), {"error": exc.code})

    def _json(self, status: HTTPStatus, payload: JsonInput) -> None:
        self.json_response(status, payload)

    def _get(self, root: Path) -> None:
        # Keep the original fault-injection seam while dispatching the public method.
        self.get_response(root)


def _handler(web_context: WebContext) -> type[Handler]:
    class ConfiguredHandler(Handler):
        context: ClassVar[WebContext] = web_context

    return ConfiguredHandler


def build_server(
    config: Config | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> SecondBrainHTTPServer:
    """Build a local console server; non-loopback binding requires a token."""
    chosen = load_config() if config is None else config
    require_vault_owner(Path(chosen.vault_root))
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
