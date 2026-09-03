"""Controller-owned V2.1 evaluator with per-check exception isolation."""
from __future__ import annotations
import json, random, sys, tempfile
from pathlib import Path
from typing import Any, Callable
from . import CHECK_COUNT

def _safe(name: str, fn: Callable[[], bool]) -> dict[str, Any]:
    try:
        return {"name": name, "passed": bool(fn()), "detail": ""}
    except Exception as exc:
        return {"name": name, "passed": False, "detail": type(exc).__name__}

def run_checks(specs: list[tuple[str, Callable[[], bool]]]) -> list[dict[str, Any]]:
    if len(specs) != CHECK_COUNT: raise ValueError("controller contract must define exactly eight checks")
    return [_safe(name, fn) for name, fn in specs]

def _clear(prefix: str) -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] == prefix: del sys.modules[name]

def _p1(root: Path) -> list[dict[str, Any]]:
    _clear("app"); items=json.loads((root/"data/items.json").read_text())
    a=float(items[0]["amount"]); b=float(items[1]["amount"])
    def c1():
        from app.store import Store, DerivedTotals
        s=Store({"a":f"{a},{b}","b":"1,2"}); t=DerivedTotals(s); return t.total("a")==a+b and t.total("b")==3
    def c2():
        from app.store import Store, DerivedTotals
        s=Store({"a":f"{a},{b}","b":"1,2"}); t=DerivedTotals(s); old=t.total("a"); s.put("a",f"{a+1},{b}"); return t.total("a")==old+1 and t.total("b")==3
    def c3():
        from app.store import Store, DerivedTotals
        s=Store({"a":f"{a},{b}"}); t=DerivedTotals(s); t.total("a"); t.total("a"); s.put("a",f"{a+1},{b}"); t.total("a"); return t.parse_calls==2
    def c4():
        from app.catalog import find
        return len(find(items," alpha "))==3
    def c5():
        from app.catalog import sorted_ids
        return sorted_ids(items)==sorted(i["id"] for i in items)
    def c6():
        from app.catalog import summarize
        return summarize(items)["total"]==sum(float(i["amount"]) for i in items)
    def c7():
        from app.analytics import catalog_summary
        expected=sum(float(i["amount"]) for i in items); x=catalog_summary(items,"ALPHA"); return x["matches"]==3 and x["summary"]["total"]==expected
    def c8():
        from app.service import report
        return report(root/"data/items.json"," alpha ")["ids"]==sorted(i["id"] for i in items)
    return run_checks([("initial totals",c1),("multi-key version invalidation",c2),("versioned parse counts",c3),("normalized collision lookup",c4),("stable ascending identifiers",c5),("fractional multi-record summary",c6),("analytics composition",c7),("service report propagation",c8)])

def _p2(root: Path) -> list[dict[str, Any]]:
    _clear("settings")
    def c1():
        from settings.loader import load_settings
        return load_settings()=={"mode":"safe","limit":10,"enabled":False,"ratio":1.0}
    def c2():
        import json
        from settings.loader import load_settings
        cfg=Path(tempfile.mkstemp(suffix=".json")[1]); cfg.write_text(json.dumps({"mode":"file","limit":4,"enabled":False,"ratio":.5}))
        try:
            x=load_settings(cfg,{"APP_LIMIT":"7","APP_ENABLED":"false"},["--limit=0","--mode=cli"])
            return x["mode"]=="cli" and x["limit"]==0 and x["enabled"] is False
        finally: cfg.unlink(missing_ok=True)
    def c3():
        import json
        from settings.loader import load_settings
        cfg=Path(tempfile.mkstemp(suffix=".json")[1]); cfg.write_text(json.dumps({"mode":"file","limit":4,"enabled":False,"ratio":.5}))
        try:
            x=load_settings(cfg,{"APP_LIMIT":"0","APP_ENABLED":"false"},[])
            return x["limit"]==0 and x["enabled"] is False and isinstance(x["limit"],int)
        finally: cfg.unlink(missing_ok=True)
    def c4():
        from settings.state import Session
        s=Session(); a=s.load("ada"); b=s.load("lin"); return a["user"]=="ada" and b["user"]=="lin" and a is not b
    def c5():
        from settings.state import Session
        s=Session(); a=s.load("ada"); s.load("lin"); s.invalidate("ada"); return s.load("ada") is not a and s.load("lin")["user"]=="lin"
    def c6():
        from settings.state import Session
        s=Session(); s.load("ada"); s.load("lin"); return s.current["user"]=="lin"
    def c7():
        from settings.state import Session
        s=Session(); s.load("ada")["limit"]=0; s.load("lin")["enabled"]=True; r=Session(); r.restore(s.serialize()); return r.load("ada")["limit"]==0 and r.load("lin")["enabled"] is True
    def c8():
        from settings.state import Session
        s=Session(); s.load("ada"); payload=s.serialize(); s.reset(); s.restore(payload); s.reset(); return s.current is None
    return run_checks([("defaults",c1),("precedence",c2),("typed values",c3),("user isolation",c4),("selective invalidation",c5),("active transitions",c6),("typed multi-user round trip",c7),("reset after restore",c8)])

def _p3(root: Path, instance: Any) -> list[dict[str, Any]]:
    _clear("pipeline")
    from pipeline.core import load_rows
    rows=load_rows(str(root/"data/measurements.csv"))
    def c1():
        from pipeline.core import split_by_group
        t,e=split_by_group(rows); return len(t)+len(e)==len(rows) and {id(x) for x in t+e}=={id(x) for x in rows}
    def c2():
        from pipeline.core import split_by_group
        t,e=split_by_group(rows); return {x["group"] for x in t}.isdisjoint({x["group"] for x in e})
    def c3():
        from pipeline.core import split_by_group
        random.seed(instance.seed); t,e=split_by_group(rows); t2,e2=split_by_group(rows); return t==t2 and e==e2
    def c4():
        from pipeline.metrics import ordered
        ordered_rows=ordered(rows)
        return all([x["timestamp"] for x in ordered_rows if x["group"]==g]==sorted(x["timestamp"] for x in ordered_rows if x["group"]==g) for g in {x["group"] for x in rows})
    def c5():
        from pipeline.core import split_by_group
        random.seed(instance.seed); t,e=split_by_group(rows); pos={id(x):i for i,x in enumerate(rows)}
        return all([pos[id(x)] for x in part]==sorted(pos[id(x)] for x in part) for part in (t,e))
    def c6(): return round(sum(float(x["value"]) for x in rows),6)==60.5
    def c7():
        from pipeline.core import summarize
        return summarize(rows)["count"]==len(rows) and round(summarize(rows)["mean"],6)==round(sum(float(x["value"]) for x in rows)/len(rows),6)
    def c8():
        from pipeline.metrics import report
        x=report(rows); return x.get("rows")==rows and x.get("count")==len(rows)
    return run_checks([("row retention",c1),("group disjointness",c2),("deterministic split",c3),("chronological within-group order",c4),("stable partition order",c5),("numeric preservation",c6),("summary correctness",c7),("report schema and rows",c8)])

def _p4(root: Path) -> list[dict[str, Any]]:
    _clear("compatpkg")
    def c1():
        from compatpkg import Service
        from compatpkg.new_api import service
        return isinstance(service("s"),Service)
    def c2():
        from compatpkg import Client, make_client
        from compatpkg.legacy import old_client
        from compatpkg import Service
        return isinstance(make_client("x"),Client) and isinstance(old_client("x"),Client) and isinstance(make_client("x"),Service)
    def c3():
        from compatpkg import make_client
        c=make_client("x"); before=getattr(c,"timeout",30); return c.request("/x",timeout=7)["timeout"]==7 and getattr(c,"timeout",30)==before
    def c4():
        from compatpkg import make_client
        return make_client("x").request("/x")["timeout"]==30
    def c5():
        from compatpkg import make_client
        from compatpkg.legacy import old_client
        return make_client("x",12).timeout==12 and old_client("x",13).timeout==13
    def c6():
        from compatpkg import Service,decode,encode
        return decode(encode(Service("d")))=={"name":"d","timeout":30} and decode(encode(Service("c",9)))=={"name":"c","timeout":9}
    def c7():
        from compatpkg import decode
        return decode('{"name":"legacy"}')=={"name":"legacy","timeout":30}
    def c8():
        from compatpkg.new_api import service
        return service("new",8).request("/new")["timeout"]==8
    return run_checks([("service type",c1),("legacy Client compatibility",c2),("per-request override and non-mutation",c3),("default timeout",c4),("factory/legacy propagation",c5),("default and non-default codec round trip",c6),("legacy codec default",c7),("new API request propagation",c8)])

def evaluate(instance: Any, workspace: Path) -> dict[str, Any]:
    package={"P1_multi_file_state":"app","P2_config_session":"settings","P3_scientific_pipeline":"pipeline","P4_compatibility":"compatpkg"}[instance.family]
    entry={"P1_multi_file_state":_p1,"P2_config_session":_p2,"P3_scientific_pipeline":_p3,"P4_compatibility":_p4}[instance.family]
    path=str(workspace); sys.path.insert(0,path)
    try:
        checks=entry(workspace,instance) if instance.family=="P3_scientific_pipeline" else entry(workspace)
    except Exception as exc:
        checks=[{"name":f"evaluator setup ({package})","passed":False,"detail":type(exc).__name__}]+[{"name":f"unavailable check {i}","passed":False,"detail":"setup"} for i in range(1,CHECK_COUNT)]
    finally:
        if sys.path and sys.path[0]==path: sys.path.pop(0)
        _clear(package)
    if len(checks)!=CHECK_COUNT: raise ValueError("evaluator returned malformed check vector")
    vector=[bool(x["passed"]) for x in checks]; passed=sum(vector)
    return {"evaluation_class":"public_characterization","objective":True,"checks":checks,"check_vector":vector,"score":100.0*passed/CHECK_COUNT,"maximum":100.0,"full_pass":passed==CHECK_COUNT}
