"""Deterministic public V2.2 task generation with layered dependencies."""
from __future__ import annotations
import hashlib, json, random, shutil, textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from . import IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, SUITE_NAME, SUITE_VERSION

def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

@dataclass(frozen=True)
class TaskInstance:
    family: str
    seed: int
    prompt: str
    files: dict[str, str]
    specification: dict[str, Any]
    edit_scope: dict[str, list[str]]
    verifier: str
    @property
    def task_id(self) -> str: return f"{SUITE_NAME}:{self.family}@{self.seed}"
    @property
    def task_spec_hash(self) -> str: return sha256_json(self.specification)
    @property
    def edit_scope_hash(self) -> str: return sha256_json(self.edit_scope)
    @property
    def visible_verifier_hash(self) -> str: return hashlib.sha256(self.verifier.encode()).hexdigest()

def _write(root: Path, files: dict[str, str]) -> None:
    for name, value in files.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")

def _verifier_script(family: str) -> str:
    return f'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifier.contract import checks
result = checks(Path(__file__).resolve().parents[1])
print(json.dumps({{"family": {family!r}, "checks": [x["passed"] for x in result], "details": result}}, sort_keys=True))
sys.exit(0 if len(result) == 8 else 2)
'''

def _make(family, seed, prompt, requirements, files, names, editable):
    scope={"editable":editable,"immutable":["README.md","tests/**","verifier/**",".ekalavya/**","data/**"],"generated_ignored":[".pytest_cache/**","__pycache__/**","*.pyc"]}
    specification={"suite":SUITE_NAME,"version":SUITE_VERSION,"family":family,"seed":seed,"requirements":requirements,"checks":names,"evaluation_contract":"Eight independent behavioral checks; the visible verifier and controller evaluator implement the same public contract."}
    files=dict(files); files["verifier/contract.py"]=CONTRACTS[family]; files["verifier/verify.py"]=_verifier_script(family)
    files[".ekalavya/edit-scope.json"]=json.dumps(scope,indent=2,sort_keys=True)
    files[".ekalavya/task.json"]=json.dumps({"family":family,"seed":seed,"suite":SUITE_NAME,"version":SUITE_VERSION},sort_keys=True)
    return TaskInstance(family,seed,prompt,files,specification,scope,files["verifier/verify.py"])

def _p1(seed):
    rng=random.Random(seed)
    rows=[
      {"id":30,"name":" Alpha ","category":"hardware","amount":round(rng.uniform(2,8)+.25,2)},
      {"id":10,"name":" beta ","category":"software","amount":round(rng.uniform(9,16)+.5,2)},
      {"id":20,"name":"ALPHA","category":"hardware","amount":3.75},
      {"id":40,"name":"gamma","category":"hardware","amount":.5},
      {"id":50,"name":"alpha","category":"software","amount":4.25},
      {"id":60,"name":" Delta ","category":"software","amount":1.125}]
    files={
      "README.md":"""# Stateful inventory service V2.2
Repair the interacting domain, storage, parsing, cache, catalogue, analytics, and service layers. The repository must remain correct through repeated queries, multiple mutations, normalized collisions, category filters, fractional amounts, and composed reports. Run python verifier/verify.py to inspect the complete public contract. Do not edit tests, verifier, .ekalavya, or data.
""",
      "tests/test_contract.py":"from service.inventory import InventoryService\ndef test_import(): assert InventoryService\n",
      "domain/__init__.py":"from .models import Item, item_from_record\n",
      "domain/models.py":"""from dataclasses import dataclass
@dataclass(frozen=True)
class Item:
 id:int
 name:str
 category:str
 amount:float
def item_from_record(record): return Item(int(record['id']),record['name'],record['category'],int(float(record['amount'])))
""",
      "storage/__init__.py":"from .repository import Repository\nfrom .versioning import current_version\n",
      "storage/repository.py":"""from copy import deepcopy
class Repository:
 def __init__(self,records): self._records=deepcopy(list(records)); self._version=0
 def all(self): return deepcopy(self._records)
 def replace(self,item_id,record):
  for i,item in enumerate(self._records):
   if int(item['id'])==int(item_id): self._records[i]=deepcopy(record); self._version+=1; return
  raise KeyError(item_id)
 def version(self): return self._version
""",
      "storage/versioning.py":"def current_version(repository): return 0\n",
      "parsing/__init__.py":"from .amounts import parse_amount, parse_items\n",
      "parsing/amounts.py":"""from domain.models import item_from_record
def parse_amount(value): return float(value)
def parse_items(records): return [item_from_record(record) for record in records]
""",
      "cache/__init__.py":"from .derived import DerivedCache\n",
      "cache/derived.py":"""class DerivedCache:
 def __init__(self,repository,parser): self.repository,self.parser=repository,parser; self._cache={}; self.parse_calls=0
 def items(self,key):
  if key in self._cache: return self._cache[key]
  self.parse_calls+=1; value=self.parser(self.repository.all()); self._cache[key]=value; return value
""",
      "catalog/__init__.py":"from .index import CatalogIndex\nfrom .search import search\n",
      "catalog/index.py":"""class CatalogIndex:
 def __init__(self,repository,parser): self.repository,self.parser=repository,parser; self._items=None
 def refresh(self): self._items=self.parser(self.repository.all()); return self._items
 def find(self,name,category=None):
  if self._items is None: self.refresh()
  return [x for x in self._items if x.name==name and (category is None or x.category==category)]
""",
      "catalog/search.py":"def search(index,name,category=None): return index.find(name,category)\n",
      "analytics/__init__.py":"from .summary import summarize\n",
      "analytics/summary.py":"""def summarize(items):
 return {'count':len(items),'total':sum(int(item.amount) for item in items),'mean':sum(int(item.amount) for item in items)/len(items) if items else 0.0}
""",
      "service/__init__.py":"from .inventory import InventoryService\nfrom .report import build_report\n",
      "service/inventory.py":"""from cache.derived import DerivedCache
from catalog.index import CatalogIndex
from catalog.search import search
from parsing.amounts import parse_items
from analytics.summary import summarize
class InventoryService:
 def __init__(self,records):
  self.repository=__import__('storage.repository',fromlist=['Repository']).Repository(records)
  self.cache=DerivedCache(self.repository,parse_items); self.index=CatalogIndex(self.repository,parse_items)
 def mutate(self,item_id,record): self.repository.replace(item_id,record)
 def query(self,name,category=None):
  items=search(self.index,name,category); return {'items':items,'summary':summarize(items),'version':self.repository.version()}
""",
      "service/report.py":"""def build_report(service,queries):
 return {'version':service.repository.version(),'queries':[service.query(name,category) for name,category in queries]}
""",
      "data/items.json":json.dumps(rows,indent=2)}
    return _make("P1_stateful_inventory",seed,"Repair the layered stateful inventory service across domain, storage/versioning, parsing, derived cache, catalogue index/search, analytics, and service/report orchestration. Preserve fixtures and evaluation files.",["versioned cache sequences","normalized collision search","fractional summaries","cross-layer stateful reports"],files,["domain parsing","versioned cache sequences","cache invalidation","normalized catalogue search","fractional aggregation","service composition","stateful report evolution","report schema and category isolation"],["domain/**/*.py","storage/**/*.py","parsing/**/*.py","cache/**/*.py","catalog/**/*.py","analytics/**/*.py","service/**/*.py"])

def _p3(seed):
    groups=["A","B","C","D","E"]; rows=[]
    for gi,g in enumerate(groups):
        for day,value in ((4,10.25+gi),(1,4.5+gi/10),(5,13.75+gi),(2,8.0+gi/10),(3,6.125+gi)):
            rows.append({"group":g,"timestamp":f"2024-02-{day:02d}","value":round(value,3),"replicate":gi+1})
    rows=[rows[i] for i in (7,0,19,12,3,21,9,14,24,1,16,5,10,22,4,18,8,13,2,23,6,11,17,15,20)]
    fixture="group,timestamp,value,replicate\n"+"\n".join(f"{r['group']},{r['timestamp']},{r['value']},{r['replicate']}" for r in rows)+"\n"
    files={
      "README.md":"""# Scientific experiment pipeline V2.2
Repair the layered schema, loader, normalization, ordering, group policy, split, metrics, report, and pipeline orchestration components. The data contains five groups, multiple unsorted timestamps, fractional values, and a replicate field. The public verifier checks properties over every row; do not edit data, tests, or verifier.
""",
      "tests/test_contract.py":"from pipeline.run import execute\ndef test_import(): assert execute\n",
      "dataio/__init__.py":"from .loader import load_rows\nfrom .schema import validate_row\n",
      "dataio/schema.py":"""def validate_row(row): return set(row)=={'group','timestamp','value','replicate'}
def coerce_row(row): return {'group':row['group'],'timestamp':row['timestamp'],'value':int(float(row['value'])),'replicate':int(row['replicate'])}
""",
      "dataio/loader.py":"""import csv
from pathlib import Path
from .schema import coerce_row
def load_rows(path):
 with Path(path).open(newline='') as handle: return [coerce_row(row) for row in csv.DictReader(handle)]
""",
      "transform/__init__.py":"from .normalize import normalize\n",
      "transform/normalize.py":"def normalize(rows): return list(rows)\n",
      "ordering/__init__.py":"from .time import chronological\n",
      "ordering/time.py":"def chronological(rows): return list(rows)\n",
      "split/__init__.py":"from .groups import partition\nfrom .policy import split\n",
      "split/groups.py":"""import random
def partition(rows,fraction=.6,seed=0):
 rows=list(rows); random.shuffle(rows); cut=int(len(rows)*fraction); return rows[:cut],rows[cut:]
""",
      "split/policy.py":"def split(rows,seed=0): return __import__('split.groups',fromlist=['partition']).partition(rows,seed=seed)\n",
      "metrics/__init__.py":"from .summary import summarize\n",
      "metrics/summary.py":"""def summarize(rows):
 values=[row['value'] for row in rows]; return {'count':len(values),'total':sum(int(v) for v in values),'mean':sum(int(v) for v in values)/len(values) if values else 0.0}
""",
      "report/__init__.py":"from .result import make_report\n",
      "report/result.py":"def make_report(rows,train,test,summary): return {'rows':list(reversed(rows)),'train':train,'test':test,'summary':summary}\n",
      "pipeline/__init__.py":"from .run import execute\n",
      "pipeline/run.py":"""from dataio.loader import load_rows
from transform.normalize import normalize
from ordering.time import chronological
from split.policy import split
from metrics.summary import summarize
from report.result import make_report
def execute(path,seed=0):
 rows=normalize(load_rows(path)); ordered=chronological(rows); train,test=split(ordered,seed); return make_report(ordered,train,test,summarize(ordered))
""",
      "data/measurements.csv":fixture}
    return _make("P3_scientific_pipeline",seed,"Repair the multi-stage scientific experiment pipeline across schema, loading, normalization, chronological ordering, group policy, deterministic split, metrics, reporting, and orchestration. Preserve data and evaluation files.",["schema-preserving parsing","group-disjoint deterministic splitting","numeric summaries","pipeline/report composition"],files,["schema and parsing","normalization","chronological ordering","group-disjoint deterministic split","row retention and order","numeric summary","pipeline composition","report schema and rows"],["dataio/**/*.py","transform/**/*.py","ordering/**/*.py","split/**/*.py","metrics/**/*.py","report/**/*.py","pipeline/**/*.py"])

CONTRACTS={
"P1_stateful_inventory":"""import json
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
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
 rows=json.loads((root/'data/items.json').read_text())
 def c1(): return [item_from_record(x).id for x in rows]==[30,10,20,40,50,60] and all(isinstance(item_from_record(x).amount,float) for x in rows)
 def c2():
  r=Repository(rows); c=DerivedCache(r,parse_items); c.items('all'); c.items('all'); c.items('second'); return c.parse_calls==2
 def c3():
  r=Repository(rows); c=DerivedCache(r,parse_items); before=c.items('all')[0].amount; r.replace(30,{**rows[0],'amount':rows[0]['amount']+1}); return current_version(r)==1 and c.items('all')[0].amount==before+1 and c.parse_calls==2
 def c4():
  r=Repository(rows); i=CatalogIndex(r,parse_items); found=search(i,' alpha ','hardware'); return [x.id for x in found]==[20,30] and len(search(i,'ALPHA'))==3
 def c5():
  items=parse_items(rows); s=summarize(items); return s['count']==6 and abs(s['total']-sum(float(x['amount']) for x in rows))<1e-9 and isinstance(s['total'],float)
 def c6():
  service=InventoryService(rows); first=service.query('alpha','hardware'); service.mutate(30,{**rows[0],'amount':rows[0]['amount']+1}); second=service.query(' alpha ','hardware'); return [x.id for x in first['items']]==[20,30] and second['summary']['total']==first['summary']['total']+1
 def c7():
  service=InventoryService(rows); before=sum(float(x['amount']) for x in rows if x['name'].strip().lower()=='alpha'); service.query('alpha'); service.mutate(30,{**rows[0],'amount':rows[0]['amount']+1}); service.mutate(50,{**rows[4],'amount':rows[4]['amount']+2}); report=build_report(service,[('alpha',None),('beta',None)]); return report['version']==2 and len(report['queries'])==2 and abs(report['queries'][0]['summary']['total']-(before+3))<1e-9
 def c8():
  service=InventoryService(rows); report=build_report(service,[('alpha','hardware'),('alpha','software')]); return set(report)=={'version','queries'} and len(report['queries'])==2 and report['queries'][0]['summary']['count']==2 and report['queries'][1]['summary']['count']==1
 return [_safe('domain parsing',c1),_safe('versioned cache sequences',c2),_safe('cache invalidation',c3),_safe('normalized catalogue search',c4),_safe('fractional aggregation',c5),_safe('service composition',c6),_safe('stateful report evolution',c7),_safe('report schema and category isolation',c8)]
""",
"P3_scientific_pipeline":"""import json
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
 from dataio.loader import load_rows
 from dataio.schema import validate_row
 from transform.normalize import normalize
 from ordering.time import chronological
 from split.groups import partition
 from split.policy import split
 from metrics.summary import summarize
 from report.result import make_report
 from pipeline.run import execute
 path=root/'data/measurements.csv'; raw=load_rows(path); rows=normalize(raw)
 def c1(): return len(rows)==25 and all(validate_row({'group':r['group'],'timestamp':r['timestamp'],'value':r['value'],'replicate':r['replicate']}) for r in rows) and all(isinstance(r['value'],float) for r in rows)
 def c2(): return all(r['group']==r['group'].strip() and isinstance(r['replicate'],int) for r in normalize(rows)) and len({r['group'] for r in rows})==5
 def c3():
  out=chronological(rows); return all([r['timestamp'] for r in out if r['group']==g]==sorted(r['timestamp'] for r in out if r['group']==g) for g in {r['group'] for r in out})
 def c4():
  a,b=split(rows,seed=17); a2,b2=split(rows,seed=17); return a==a2 and b==b2 and {r['group'] for r in a}.isdisjoint({r['group'] for r in b})
 def c5():
  a,b=partition(rows,seed=17); original={(r['group'],r['timestamp'],r['replicate']) for r in rows}; parts={(r['group'],r['timestamp'],r['replicate']) for r in a+b}; return len(a)+len(b)==len(rows) and parts==original and all([r['timestamp'] for r in part if r['group']==g]==sorted(r['timestamp'] for r in part if r['group']==g) for part in (a,b) for g in {r['group'] for r in part})
 def c6(): raw_total=sum(float(line.split(',')[2]) for line in (root/'data/measurements.csv').read_text().splitlines()[1:]); s=summarize(rows); return s['count']==25 and abs(s['total']-raw_total)<1e-9 and abs(s['mean']-raw_total/25)<1e-9
 def c7():
  result=execute(path,seed=17); return len(result['train'])+len(result['test'])==25 and result['summary']['count']==25 and {r['group'] for r in result['train']}.isdisjoint({r['group'] for r in result['test']})
 def c8():
  report=make_report(rows,rows[:10],rows[10:],summarize(rows)); return set(report)=={'rows','train','test','summary'} and report['rows']==rows and len(report['rows'])==25
 return [_safe('schema and parsing',c1),_safe('normalization',c2),_safe('chronological ordering',c3),_safe('group-disjoint deterministic split',c4),_safe('row retention and order',c5),_safe('numeric summary',c6),_safe('pipeline composition',c7),_safe('report schema and rows',c8)]
"""
}

def make_instance(family: str, seed: int) -> TaskInstance:
    if family=="P1_stateful_inventory": return _p1(seed)
    if family=="P3_scientific_pipeline": return _p3(seed)
    raise ValueError(f"unknown V2.2 family: {family}")

def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists(): shutil.rmtree(workspace)
    workspace.mkdir(parents=True); _write(workspace,instance.files); return workspace

def workspace_digest(workspace: Path) -> str:
    h=hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(x in IGNORED_GENERATED_DIRS for x in p.parts)):
        h.update(path.relative_to(workspace).as_posix().encode()); h.update(b"\0"); h.update(path.read_bytes())
    return h.hexdigest()
