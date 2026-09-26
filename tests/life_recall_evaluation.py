"""Reproducible 300-case synthetic contract benchmark, not user-question quality.

All queries, expected event revisions, policies and raw evidence are generated
before querying the product. Topic groups keep train/eval/holdout disjoint.
"""
from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sb.life_contracts import SourcePolicyV1
from sb.life_recall import recall
from sb.store.ledger import Ledger

NOW=datetime(2026,9,26,12,tzinfo=UTC)
PAST=datetime(2026,9,1,10,tzinfo=UTC)
SCOPES=("principal:owner","project:alpha")
SOURCES=("benchmark-notes","benchmark-mail","benchmark-calendar")
WORDS=("가람","나래","다온","라온","마루","바람","사랑","아람","자람","차오름",
       "카나리","타래","파랑","하늘","고운","누리","도담","로담","미리내","보람",
       "소담","여울","지음","초롱","코스모","토리","푸름","한울","구름","노을")


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    topic: str
    request: dict[str, object]
    expected: tuple[tuple[str,int], ...]
    split: str


def split(topic: str) -> str:
    value=int(sha256(topic.encode()).hexdigest()[:8],16)%10
    return "train" if value<6 else "evaluation" if value<8 else "holdout"


def policy(secret=False, source=None):
    return SourcePolicyV1(source_id="secret-notes" if secret else source or SOURCES[0],
        scopes=("principal:other","project:secret") if secret else SCOPES,
        enabled=True,allowed_types=("note_saved","decision"),sensitivity="restricted" if secret else "personal",
        external_processing="local_only",retention_days=365,policy_revision="benchmark-v1")


def seed(store, name: str, body: str, *, version=1, at=PAST, event_type="note_saved", secret=False,
         change_reason=None, source=None):
    payload={"source_item_id":name,"source_version":f"v{version}","event_type":event_type,
             "title":name,"body":body,"occurred_start":at.isoformat(),"observed_at":at.isoformat(),
             "timezone":"Asia/Seoul","time_precision":"exact","event_status":"occurred",
             "evidence_level":"user_asserted" if version>1 else "observed",
             "review_state":"confirmed" if version>1 else "unreviewed"}
    if change_reason is not None: payload["change_reason"]=change_reason
    receipt=store.accept(payload,policy(secret,source),key=name+f":{version}",now=at,
                         expected_revision=version-1 if version>1 else None)
    return receipt.event_id


def corpus(store) -> list[Case]:
    cases=[]
    def add(category,topic,query,expected,**request):
        cases.append(Case(f"{category}-{sum(c.category==category for c in cases)+1:03}",category,
                          topic,{"query":query,**request},tuple(expected),split(topic)))
    # 60 exact searches across 30 independent fictional project topics.
    for i,name in enumerate(WORDS):
        topic="exact:"+name
        eid=seed(store,name+" 시범프로젝트",f"{name} 네트워크 이전. 승인된 견적 문서의 관리 번호 DEMO-{i:03}. "
                 f"담당자 표기는 검증용 가상 인물이다. 작업 항목은 백업 점검과 문서 정리다.")
        add("exact",topic,f"DEMO-{i:03}",[(eid,1)])
        add("exact",topic,name+" 네트워크",[(eid,1)])
    # 50 Korean spacing/case cases; no claim to semantic paraphrase coverage.
    for i,name in enumerate(WORDS[:25]):
        topic="korean:"+name
        eid=seed(store,name+" 연결정책",f"{name} 가상 실험의 세컨드 브레인 운영 지침. "
                 f"사용자 메모 보호와 원문 근거 연결을 확인한다. 영문 식별자는 ExampleCase{i:02}.")
        add("korean",topic,name+" 세컨드브레인",[(eid,1)])
        add("korean",topic,f"examplecase{i:02}",[(eid,1)])
    # 60 temporal questions with pre-change and current source snapshots.
    for i,name in enumerate(WORDS[:20]):
        topic="temporal:"+name
        key=name+" 일정결정"
        eid=seed(store,key,f"{name} 계획의 초기안은 구안{i:02}이다.",event_type="decision")
        seed(store,key,f"{name} 계획의 현재안은 신안{i:02}이다.",version=2,
             at=PAST+timedelta(days=10),event_type="decision",change_reason="가상 사용자 일정 변경")
        add("temporal",topic,f"구안{i:02}",[(eid,1)],as_of=(PAST+timedelta(days=1)).isoformat())
        add("temporal",topic,f"신안{i:02}",[(eid,2)])
        add("temporal",topic,f"구안{i:02}",[])
    # 40 multi-source-document retrievals, maintaining both independent origins.
    for i,name in enumerate(WORDS[:20]):
        topic="multiple:"+name
        one=seed(store,name+" 회의기록",f"연결시험{i:02} 가상 회의: {name} 일정 검토와 자료 전달을 논의했다.")
        two=seed(store,name+" 후속기록",f"연결시험{i:02} 가상 후속: {name} 일정 변경과 자료 전달을 기록했다.",source=SOURCES[1])
        three=seed(store,name+" 일정기록",f"연결시험{i:02} 가상 일정: {name} 자료 전달 미팅의 일정 기록.",source=SOURCES[2])
        add("multiple",topic,f"연결시험{i:02}",[(one,1),(two,1),(three,1)])
        add("multiple",topic,f"연결시험{i:02} 자료 전달",[(one,1),(two,1),(three,1)])
    # 40 correction/deletion cases; original rows stay on disk while read paths
    # must exclude withdrawn or obsolete current content.
    for i,name in enumerate(WORDS[:10]):
        topic="lifecycle:"+name
        eid=seed(store,name+" 정정기록",f"정정전{i:02} 가상 납기 기록")
        seed(store,name+" 정정기록",f"정정후{i:02} 가상 납기 기록",version=2,at=PAST+timedelta(days=5),change_reason="원문 정정")
        deleted=seed(store,name+" 폐기기록",f"삭제검증{i:02} 가상 기록")
        store.forget(deleted,scopes=SCOPES,expected_revision=1,now=PAST+timedelta(days=6))
        add("lifecycle",topic,f"정정전{i:02}",[])
        add("lifecycle",topic,f"정정후{i:02}",[(eid,2)])
        add("lifecycle",topic,f"삭제검증{i:02}",[])
        add("lifecycle",topic,f"삭제검증{i:02}",[],as_of=(PAST+timedelta(days=1)).isoformat())
    for i,name in enumerate(WORDS):
        add("no_answer","none:"+name,f"미기록회의{i:02} 확정 결과",[])
    for i,name in enumerate(WORDS[:20]):
        seed(store,"기밀"+name,f"범위검증{i:02} 다른 소유자의 제한 기록",secret=True)
        add("scope","secret:"+name,f"범위검증{i:02}",[])
    assert len(cases)==300
    return cases


def evaluate(output: Path | None = None) -> dict[str, Any]:
    with TemporaryDirectory(prefix="sb2-recall-evaluation-") as folder:
        root=Path(folder)
        with Ledger(root) as ledger:
            store=ledger.life_store()
            cases=corpus(store)
            visible=store.events(scopes=SCOPES,now=NOW,source_ids=SOURCES,limit=10000)
            source_digest=sha256(json.dumps([case.__dict__ for case in cases],sort_keys=True,
                                            ensure_ascii=False).encode()).hexdigest()
            rows=[]
            for case in cases:
                started=time.perf_counter()
                result=recall(store,visible,case.request,scopes=SCOPES,source_ids=SOURCES,now=NOW)
                milliseconds=(time.perf_counter()-started)*1000
                found=[(row["event_id"],row["revision"]) for row in result["hits"]]
                expected=set(case.expected)
                positions=[rank for rank,item in enumerate(found,1) if item in expected]
                no_answer=not expected
                pass_case=(result["state"]=="no_data" and not found) if no_answer else expected.issubset(set(found[:5]))
                rows.append({"case_id":case.case_id,"category":case.category,"split":case.split,
                    "request":case.request,"expected":[list(x) for x in case.expected],"returned":[list(x) for x in found],
                    "pass":pass_case,"no_answer_expected":no_answer,"elapsed_ms":round(milliseconds,3),
                    "hit_at_5":bool(positions and min(positions)<=5) if expected else None,
                    "reciprocal_rank":1/min(positions) if positions else 0,
                    "wrong_revision":any(eid==wanted and revision!=rev for eid,revision in found for wanted,rev in expected),
                    "scope_leak":case.category=="scope" and bool(found)})
            positive=[row for row in rows if not row["no_answer_expected"]]
            negatives=[row for row in rows if row["no_answer_expected"]]
            timings=sorted(row["elapsed_ms"] for row in rows)
            report={"dataset_origin":"synthetic-generated-contract-fixtures","dataset_version":"sb2-recall-300-v1",
                "dataset_sha256":source_digest,"question_count":len(rows),
                "passed":sum(row["pass"] for row in rows),"failed":sum(not row["pass"] for row in rows),
                "hit_at_5":sum(row["hit_at_5"] for row in positive)/len(positive),
                "mrr":sum(row["reciprocal_rank"] for row in positive)/len(positive),
                "abstention_accuracy":sum(row["pass"] for row in negatives)/len(negatives),
                "wrong_revision_cases":sum(row["wrong_revision"] for row in rows),
                "scope_leaks":sum(row["scope_leak"] for row in rows),"p95_ms":timings[int(len(timings)*.95)-1],
                "categories":{name:{"count":sum(row["category"]==name for row in rows),
                                    "passed":sum(row["category"]==name and row["pass"] for row in rows)}
                              for name in sorted({row["category"] for row in rows})},
                "splits":{name:sum(row["split"]==name for row in rows) for name in ("train","evaluation","holdout")},
                "backend":"existing lexical semantics + life temporal revisions; no new reranker",
                "environment":{"python":platform.python_version(),"platform":platform.system()},
                "limitations":["Not actual user questions or independent human relevance judgments",
                    "Spacing/case contract coverage, not semantic synonym quality",
                    "All fixtures were predeclared; topic groups are disjoint across splits",
                    "No real-model quality, production latency, or mobile acceptance claim"],
                "cases":rows}
        if output is not None:
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        return report


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description="Synthetic SB2 contract evaluation; not a user-quality score")
    parser.add_argument("--output",type=Path,required=True)
    arguments=parser.parse_args()
    measured=evaluate(arguments.output)
    print(json.dumps({key:value for key,value in measured.items() if key!="cases"},ensure_ascii=False,indent=2))
    raise SystemExit(0 if measured["failed"]==0 else 1)
