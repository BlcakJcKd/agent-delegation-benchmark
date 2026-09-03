"""Controller-owned V2.2 evaluator; no candidate workspace contains this module."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

CHECK_COUNT = 8
MODULE_PREFIXES = ["domain", "storage", "parsing", "cache", "catalog", "analytics", "service", "dataio", "transform", "ordering", "split", "metrics", "report", "pipeline"]

def _safe(name, fn):
    try:
        return {"name": name, "passed": bool(fn()), "detail": ""}
    except Exception as exc:
        return {"name": name, "passed": False, "detail": type(exc).__name__}

def _clean_modules(prefixes):
    import sys
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            del sys.modules[name]

def _p1(root: Path):
    _clean_modules(["domain","storage","parsing","cache","catalog","analytics","service"])
    import sys
    sys.path.insert(0, str(root))
    from domain.models import item_from_record
    from storage.repository import Repository
    from storage.versioning import current_version
    from parsing.amounts import parse_items
    from cache.derived import DerivedCache
    from catalog.index import CatalogIndex
    from catalog.search import search
    from analytics.summary import summarize
    from service.inventory import InventoryService
    from service.report import build_report
    rows=json.loads((root/"data/items.json").read_text())
    def c1():
        return [item_from_record(x).id for x in rows]==[30,10,20,40,50,60] and all(isinstance(item_from_record(x).amount,float) for x in rows)
    def c2():
        r=Repository(rows); c=DerivedCache(r,parse_items); c.items("all"); c.items("all"); c.items("second"); return c.parse_calls==2
    def c3():
        r=Repository(rows); c=DerivedCache(r,parse_items); before=c.items("all")[0].amount; r.replace(30,{**rows[0],"amount":rows[0]["amount"]+1}); return current_version(r)==1 and c.items("all")[0].amount==before+1 and c.parse_calls==2
    def c4():
        r=Repository(rows); i=CatalogIndex(r,parse_items); found=search(i," alpha ","hardware"); return [x.id for x in found]==[20,30] and len(search(i,"ALPHA"))==3
    def c5():
        items=parse_items(rows); s=summarize(items); return s["count"]==6 and abs(s["total"]-sum(float(x["amount"]) for x in rows))<1e-9 and isinstance(s["total"],float)
    def c6():
        service=InventoryService(rows); first=service.query("alpha","hardware"); service.mutate(30,{**rows[0],"amount":rows[0]["amount"]+1}); second=service.query(" alpha ","hardware"); return [x.id for x in first["items"]]==[20,30] and second["summary"]["total"]==first["summary"]["total"]+1
    def c7():
        service=InventoryService(rows); before=sum(float(x["amount"]) for x in rows if x["name"].strip().lower()=="alpha"); service.query("alpha"); service.mutate(30,{**rows[0],"amount":rows[0]["amount"]+1}); service.mutate(50,{**rows[4],"amount":rows[4]["amount"]+2}); report=build_report(service,[("alpha",None),("beta",None)]); return report["version"]==2 and len(report["queries"])==2 and abs(report["queries"][0]["summary"]["total"]-(before+3))<1e-9
    def c8():
        service=InventoryService(rows); report=build_report(service,[("alpha","hardware"),("alpha","software")]); return set(report)=={"version","queries"} and len(report["queries"])==2 and report["queries"][0]["summary"]["count"]==2 and report["queries"][1]["summary"]["count"]==1
    return [_safe("domain parsing",c1),_safe("versioned cache sequences",c2),_safe("cache invalidation",c3),_safe("normalized catalogue search",c4),_safe("fractional aggregation",c5),_safe("service composition",c6),_safe("stateful report evolution",c7),_safe("report schema and category isolation",c8)]

def _p3(root: Path):
    _clean_modules(["dataio","transform","ordering","split","metrics","report","pipeline"])
    import sys
    sys.path.insert(0, str(root))
    from dataio.loader import load_rows
    from dataio.schema import validate_row
    from transform.normalize import normalize
    from ordering.time import chronological
    from split.groups import partition
    from split.policy import split
    from metrics.summary import summarize
    from report.result import make_report
    from pipeline.run import execute
    path=root/"data/measurements.csv"; raw=load_rows(path); rows=normalize(raw)
    def c1():
        return len(rows)==25 and all(validate_row({"group":r["group"],"timestamp":r["timestamp"],"value":r["value"],"replicate":r["replicate"]}) for r in rows) and all(isinstance(r["value"],float) for r in rows)
    def c2():
        return all(r["group"]==r["group"].strip() and isinstance(r["replicate"],int) for r in normalize(rows)) and len({r["group"] for r in rows})==5
    def c3():
        out=chronological(rows); return all([r["timestamp"] for r in out if r["group"]==g]==sorted(r["timestamp"] for r in out if r["group"]==g) for g in {r["group"] for r in out})
    def c4():
        a,b=split(rows,seed=17); a2,b2=split(rows,seed=17); return a==a2 and b==b2 and {r["group"] for r in a}.isdisjoint({r["group"] for r in b})
    def c5():
        a,b=partition(rows,seed=17); original={(r["group"],r["timestamp"],r["replicate"]) for r in rows}; parts={(r["group"],r["timestamp"],r["replicate"]) for r in a+b}; return len(a)+len(b)==len(rows) and parts==original and all([r["timestamp"] for r in part if r["group"]==g]==sorted(r["timestamp"] for r in part if r["group"]==g) for part in (a,b) for g in {r["group"] for r in part})
    def c6(): raw_total=sum(float(line.split(',')[2]) for line in (root/'data/measurements.csv').read_text().splitlines()[1:]); s=summarize(rows); return s["count"]==25 and abs(s["total"]-raw_total)<1e-9 and abs(s["mean"]-raw_total/25)<1e-9
    def c7():
        result=execute(path,seed=17); return len(result["train"])+len(result["test"])==25 and result["summary"]["count"]==25 and {r["group"] for r in result["train"]}.isdisjoint({r["group"] for r in result["test"]})
    def c8():
        report=make_report(rows,rows[:10],rows[10:],summarize(rows)); return set(report)=={"rows","train","test","summary"} and report["rows"]==rows and len(report["rows"])==25
    return [_safe("schema and parsing",c1),_safe("normalization",c2),_safe("chronological ordering",c3),_safe("group-disjoint deterministic split",c4),_safe("row retention and order",c5),_safe("numeric summary",c6),_safe("pipeline composition",c7),_safe("report schema and rows",c8)]

def evaluate(instance: Any, root: Path) -> dict[str, Any]:
    try:
        checks = _p1(root) if instance.family=="P1_stateful_inventory" else _p3(root)
    except Exception as exc:
        checks = [{"name":"setup", "passed":False, "detail":type(exc).__name__}] + [{"name":f"unavailable-{i}", "passed":False, "detail":"setup_failed"} for i in range(2, CHECK_COUNT+1)]
    finally:
        _clean_modules(MODULE_PREFIXES)
    if len(checks) != CHECK_COUNT:
        raise ValueError("malformed evaluator vector")
    vector=[bool(x["passed"]) for x in checks]
    return {"checks":checks,"check_vector":vector,"score":100.0*sum(vector)/CHECK_COUNT,"full_pass":all(vector)}
