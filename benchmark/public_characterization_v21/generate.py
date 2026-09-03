"""Deterministic, public, baseline-aware V2.1 task generation."""
from __future__ import annotations
import hashlib, json, random, shutil, textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from . import FAMILIES, IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, SUITE_NAME, SUITE_VERSION

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

def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def _write(root: Path, files: dict[str, str]) -> None:
    for name, value in files.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")

def _verifier_script(family: str) -> str:
    return f"""#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifier.contract import checks
result = checks(Path(__file__).resolve().parents[1])
print(json.dumps({{"family": {family!r}, "checks": [x["passed"] for x in result], "details": result}}, sort_keys=True))
sys.exit(0 if len(result) == 8 else 2)
"""

def _make(family: str, seed: int, prompt: str, requirements: list[str], files: dict[str, str], names: list[str], editable: list[str]) -> TaskInstance:
    scope = {"editable": editable, "immutable": ["README.md", "tests/**", "verifier/**", ".ekalavya/**", "data/**"], "generated_ignored": [".pytest_cache/**", "__pycache__/**", "*.pyc"]}
    spec = {"suite": SUITE_NAME, "version": SUITE_VERSION, "family": family, "seed": seed, "requirements": requirements, "checks": names, "evaluation_contract": "Eight independent behavioral checks; visible verifier and controller evaluator agree on an unchanged workspace."}
    files = dict(files)
    files["verifier/contract.py"] = CONTRACTS[family]
    files["verifier/verify.py"] = _verifier_script(family)
    files[".ekalavya/edit-scope.json"] = json.dumps(scope, indent=2, sort_keys=True)
    files[".ekalavya/task.json"] = json.dumps({"family": family, "seed": seed}, sort_keys=True)
    return TaskInstance(family, seed, prompt, files, spec, scope, files["verifier/verify.py"])

def _p1(seed: int) -> TaskInstance:
    rng = random.Random(seed)
    items = [{"id": 30, "name": " Alpha ", "amount": rng.randint(2, 8) + .25}, {"id": 10, "name": " beta ", "amount": rng.randint(9, 16) + .5}, {"id": 20, "name": "ALPHA", "amount": 3.75}, {"id": 40, "name": "gamma", "amount": .5}, {"id": 50, "name": "alpha", "amount": 4.25}]
    return _make("P1_multi_file_state", seed, "Repair the inventory repository across store, catalogue, analytics, and service layers. The readable verifier defines eight behavioral requirements. Preserve fixtures and evaluation files.", ["version-aware derived caches across keys and mutations", "stable parsing counts", "normalized collision lookup", "stable ascending identifiers", "fractional aggregation", "composed report behavior"], {
        "README.md": """# Inventory state V2.1
Repair the interacting cache, catalogue, analytics, and report layers. Repeated calls, multiple keys, mutations, normalized names, ordering, and fractional values all matter. Run python verifier/verify.py to inspect the public contract. Do not edit tests, verifier, .ekalavya, or data.
""",
        "tests/test_contract.py": "from app.store import Store\ndef test_import(): assert Store\n",
        "app/__init__.py": "from .store import Store, DerivedTotals\nfrom .catalog import find, sorted_ids, summarize\nfrom .analytics import catalog_summary\nfrom .service import report\n",
        "app/store.py": """class Store:
    def __init__(self, values=None): self.values, self.version = dict(values or {}), 0
    def put(self, key, value): self.values[key] = value; self.version += 1
    def get(self, key): return self.values[key]
class DerivedTotals:
    def __init__(self, store): self.store, self.cache, self.parse_calls = store, {}, 0
    def total(self, key):
        if key in self.cache: return self.cache[key]
        self.parse_calls += 1
        value = sum(float(part.strip()) for part in self.store.get(key).split(','))
        self.cache[key] = value
        return value
""",
        "app/catalog.py": """def find(items, name): return [item for item in items if item['name'] == name]
def sorted_ids(items): return [item['id'] for item in items]
def summarize(items): return {'count': len(items), 'total': sum(int(item['amount']) for item in items)}
""",
        "app/analytics.py": "from .catalog import find, summarize\ndef catalog_summary(items, name): return {'matches': len(find(items, name)), 'summary': summarize(items)}\n",
        "app/service.py": "import json\nfrom pathlib import Path\nfrom .analytics import catalog_summary\nfrom .catalog import sorted_ids\ndef report(path, name):\n items=json.loads(Path(path).read_text()); result=catalog_summary(items,name); result['ids']=sorted_ids(items); return result\n",
        "data/items.json": json.dumps(items, indent=2),
    }, ["initial totals", "multi-key version invalidation", "versioned parse counts", "normalized collision lookup", "stable ascending identifiers", "fractional multi-record summary", "analytics composition", "service report propagation"], ["app/**/*.py"])

def _p2(seed: int) -> TaskInstance:
    return _make("P2_config_session", seed, "Repair configuration and multi-user session state. Keep all source precedence, explicit false and zero values, isolation, invalidation, restoration, and reset behavior. Use the readable verifier.", ["defaults < file < environment < CLI", "typed false and zero values", "partial-source precedence", "independent users", "selective invalidation", "active transitions", "multi-user typed round trip", "reset after restore"], {
        "README.md": """# Configuration and session state V2.1
Implement precedence and typed values across several keys. Sessions must isolate users, transition active users, selectively invalidate state, and preserve typed values through multi-user serialization. Do not edit evaluation files.
""",
        "tests/test_contract.py": "from settings.loader import load_settings\ndef test_import(): assert load_settings()['mode'] == 'safe'\n",
        "settings/__init__.py": "from .loader import load_settings\nfrom .state import Session\n",
        "settings/loader.py": """import json
DEFAULTS={'mode':'safe','limit':10,'enabled':False,'ratio':1.0}
def load_settings(path=None,environ=None,argv=None):
 result=dict(DEFAULTS)
 if path:
  with open(path,encoding='utf-8') as handle: result.update(json.load(handle))
 for key,value in (environ or {}).items():
  if key.startswith('APP_'): result[key[4:].lower()]=value
 for item in argv or []:
  if item.startswith('--') and '=' in item: result[item[2:].split('=',1)[0]]=item.split('=',1)[1]
 return result
""",
        "settings/state.py": """import json
class Session:
 def __init__(self): self.current,self._cache=None,{}
 def load(self,user):
  if self.current is not None: return self.current
  self.current=self._cache.setdefault(user,{'user':user,'limit':10,'enabled':False}); return self.current
 def invalidate(self,user): self._cache.pop(user,None)
 def serialize(self): return json.dumps(self._cache,sort_keys=True)
 def restore(self,payload): self._cache=json.loads(payload)
 def reset(self): self.current=None
""",
        "settings/cli.py": "from .loader import load_settings\ndef effective(path=None,env=None,argv=None): return load_settings(path,env,argv)\n",
    }, ["defaults", "precedence", "typed values", "user isolation", "selective invalidation", "active transitions", "typed multi-user round trip", "reset after restore"], ["settings/**/*.py"])

def _p3(seed: int) -> TaskInstance:
    groups=["A","B","C","D"]; rows=[]
    for gi,g in enumerate(groups):
        for day,value in ((3,10.25+gi),(1,4.5+gi),(4,13.75+gi),(2,8.0+gi)): rows.append((g,f"2024-01-{day:02d}",value))
    rows=[rows[i] for i in (5,0,12,7,3,10,15,1,8,14,4,11,6,2,13,9)]
    fixture="group,timestamp,value\n"+"\n".join(f"{g},{t},{v}" for g,t,v in rows)+"\n"
    return _make("P3_scientific_pipeline", seed, "Repair the scientific pipeline over the supplied four-group dataset. Preserve every row, group separation, deterministic partitioning, chronology, numeric meaning, and report semantics.", ["retain every input row exactly once", "chronological within-group order", "group-disjoint deterministic split", "no leakage or inappropriate global shuffle", "fractional numeric preservation", "correct summary and report schema"], {
        "README.md": """# Scientific data pipeline V2.1
The input contains four groups, multiple unsorted timestamps, and fractional measurements. Implement meaningful chronology and group-disjoint deterministic splitting. The public verifier checks properties over the fixture; do not edit data, tests, or verifier.
""",
        "tests/test_contract.py": "from pipeline.core import load_rows\ndef test_rows(): assert len(load_rows('data/measurements.csv')) == 16\n",
        "pipeline/__init__.py": "from .core import load_rows, split_by_group, summarize\nfrom .metrics import ordered, report\n",
        "pipeline/core.py": """import csv,random
from pathlib import Path
def load_rows(path):
 with Path(path).open(newline='') as handle: return list(csv.DictReader(handle))
def split_by_group(rows,train_fraction=.5):
 rows=list(rows); random.shuffle(rows); cut=int(len(rows)*train_fraction); return rows[:cut],rows[cut:]
def summarize(rows):
 values=[float(row['value']) for row in rows]; return {'count':len(values),'mean':sum(values)/len(values)}
""",
        "pipeline/metrics.py": "def ordered(values): return list(values)\ndef report(rows): return {'rows':list(reversed(rows)),'count':len(rows)}\n",
        "data/measurements.csv": fixture,
    }, ["row retention", "group disjointness", "deterministic split", "chronological within-group order", "stable partition order", "numeric preservation", "summary correctness", "report schema and rows"], ["pipeline/**/*.py"])

def _p4(seed: int) -> TaskInstance:
    return _make("P4_compatibility", seed, "Repair the compatibility package without breaking legacy construction, request, factory, codec, or new API behavior. The readable verifier checks default and non-default combinations independently.", ["Service and legacy Client relationship", "per-request override without mutation", "default timeout", "factory and legacy propagation", "default and non-default codec round trips", "legacy codec default", "new API propagation"], {
        "README.md": """# Compatibility refactor V2.1
Preserve Client and old_client while adding Service and a new API. Request overrides must not mutate defaults. Encode/decode must preserve default and non-default timeout values. The public verifier is the complete behavioral contract.
""",
        "tests/test_contract.py": "from compatpkg import Service\ndef test_service(): assert Service\n",
        "compatpkg/__init__.py": "from .api import Client,Service,make_client\nfrom .codec import encode,decode\n",
        "compatpkg/api.py": """class Service:
 def __init__(self,name,timeout=30): self.name,self.timeout=name,timeout
 def request(self,path,timeout=None): return {'name':self.name,'path':path,'timeout':self.timeout}
class Client:
 def __init__(self,name): self.name=name
def make_client(name,timeout=30): return Client(name)
""",
        "compatpkg/codec.py": "import json\ndef encode(client): return json.dumps({'name':client.name})\ndef decode(value):\n data=json.loads(value); data.setdefault('timeout',30); return data\n",
        "compatpkg/legacy.py": "from .api import Client,make_client\ndef old_client(name,timeout=30): return make_client(name,timeout)\n",
        "compatpkg/new_api.py": "from .api import Service\ndef service(name,timeout=30): return Service(name)\n",
    }, ["service type", "legacy Client compatibility", "per-request override and non-mutation", "default timeout", "factory/legacy propagation", "default and non-default codec round trip", "legacy codec default", "new API request propagation"], ["compatpkg/**/*.py"])

def make_instance(family: str, seed: int) -> TaskInstance:
    if family not in FAMILIES: raise ValueError(f"unknown public characterization family: {family}")
    return {"P1_multi_file_state":_p1,"P2_config_session":_p2,"P3_scientific_pipeline":_p3,"P4_compatibility":_p4}[family](seed)

def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists(): shutil.rmtree(workspace)
    workspace.mkdir(parents=True); _write(workspace,instance.files); return workspace

def workspace_digest(workspace: Path) -> str:
    h=hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(x in IGNORED_GENERATED_DIRS for x in p.parts)):
        h.update(path.relative_to(workspace).as_posix().encode()); h.update(b"\0"); h.update(path.read_bytes())
    return h.hexdigest()

CONTRACTS = {
"P1_multi_file_state": """import json
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
 from app.store import Store,DerivedTotals
 from app.catalog import find,sorted_ids,summarize
 from app.analytics import catalog_summary
 from app.service import report
 items=json.loads((root/'data/items.json').read_text()); a=float(items[0]['amount']); b=float(items[1]['amount'])
 def c1(): s=Store({'a':f'{a},{b}','b':'1,2'}); t=DerivedTotals(s); return t.total('a')==a+b and t.total('b')==3
 def c2(): s=Store({'a':f'{a},{b}','b':'1,2'}); t=DerivedTotals(s); old=t.total('a'); s.put('a',f'{a+1},{b}'); return t.total('a')==old+1 and t.total('b')==3
 def c3(): s=Store({'a':f'{a},{b}'}); t=DerivedTotals(s); t.total('a'); t.total('a'); s.put('a',f'{a+1},{b}'); t.total('a'); return t.parse_calls==2
 return [_safe('initial totals',c1),_safe('multi-key version invalidation',c2),_safe('versioned parse counts',c3),_safe('normalized collision lookup',lambda:len(find(items,' alpha '))==3),_safe('stable ascending identifiers',lambda:sorted_ids(items)==sorted(i['id'] for i in items)),_safe('fractional multi-record summary',lambda:summarize(items)['total']==sum(float(i['amount']) for i in items)),_safe('analytics composition',lambda:catalog_summary(items,'ALPHA')['matches']==3 and catalog_summary(items,'ALPHA')['summary']['total']==sum(float(i['amount']) for i in items)),_safe('service report propagation',lambda:report(root/'data/items.json',' alpha ')['ids']==sorted(i['id'] for i in items))]
""",
"P2_config_session": """import json,tempfile
from pathlib import Path
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
 from settings.loader import load_settings
 from settings.state import Session
 def with_config(environ,argv):
  cfg=Path(tempfile.mkstemp(suffix='.json')[1]); cfg.write_text(json.dumps({'mode':'file','limit':4,'enabled':False,'ratio':.5}))
  try:return load_settings(cfg,environ,argv)
  finally:cfg.unlink(missing_ok=True)
 def c1(): return load_settings()=={'mode':'safe','limit':10,'enabled':False,'ratio':1.0}
 def c2():
  x=with_config({'APP_LIMIT':'7','APP_ENABLED':'false'},['--limit=0','--mode=cli']); return x['mode']=='cli' and x['limit']==0 and x['enabled'] is False
 def c3():
  x=with_config({'APP_LIMIT':'0','APP_ENABLED':'false'},[]); return x['limit']==0 and x['enabled'] is False and isinstance(x['limit'],int)
 def c4(): s=Session(); a=s.load('ada'); b=s.load('lin'); return a['user']=='ada' and b['user']=='lin' and a is not b
 def c5(): s=Session(); a=s.load('ada'); s.load('lin'); s.invalidate('ada'); return s.load('ada') is not a and s.load('lin')['user']=='lin'
 def c6(): s=Session(); s.load('ada'); s.load('lin'); return s.current['user']=='lin'
 def c7(): s=Session(); s.load('ada')['limit']=0; s.load('lin')['enabled']=True; r=Session(); r.restore(s.serialize()); return r.load('ada')['limit']==0 and r.load('lin')['enabled'] is True
 def c8(): s=Session(); s.load('ada'); payload=s.serialize(); s.reset(); s.restore(payload); s.reset(); return s.current is None
 return [_safe('defaults',c1),_safe('precedence',c2),_safe('typed values',c3),_safe('user isolation',c4),_safe('selective invalidation',c5),_safe('active transitions',c6),_safe('typed multi-user round trip',c7),_safe('reset after restore',c8)]
""",
"P3_scientific_pipeline": """import json
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
 from pipeline.core import load_rows,split_by_group,summarize
 from pipeline.metrics import ordered,report
 rows=load_rows(str(root/'data/measurements.csv')); import random; random.seed(json.loads((root/'.ekalavya/task.json').read_text())['seed'])
 def c1(): t,e=split_by_group(rows); return len(t)+len(e)==len(rows) and {id(x) for x in t+e}=={id(x) for x in rows}
 def c2(): t,e=split_by_group(rows); return {x['group'] for x in t}.isdisjoint({x['group'] for x in e})
 def c3(): t,e=split_by_group(rows); t2,e2=split_by_group(rows); return t==t2 and e==e2
 def c4(): return all([x['timestamp'] for x in ordered(rows) if x['group']==g]==sorted(x['timestamp'] for x in ordered(rows) if x['group']==g) for g in {x['group'] for x in rows})
 def c5(): t,e=split_by_group(rows); pos={id(x):i for i,x in enumerate(rows)}; return all([pos[id(x)] for x in part]==sorted(pos[id(x)] for x in part) for part in (t,e))
 def c6(): return round(sum(float(x['value']) for x in rows),6)==60.5
 def c7(): return summarize(rows)['count']==len(rows) and round(summarize(rows)['mean'],6)==round(sum(float(x['value']) for x in rows)/len(rows),6)
 def c8(): return report(rows).get('rows')==rows and report(rows).get('count')==len(rows)
 return [_safe('row retention',c1),_safe('group disjointness',c2),_safe('deterministic split',c3),_safe('chronological within-group order',c4),_safe('stable partition order',c5),_safe('numeric preservation',c6),_safe('summary correctness',c7),_safe('report schema and rows',c8)]
""",
"P4_compatibility": """import json
def _safe(name,fn):
 try:return {'name':name,'passed':bool(fn()),'detail':''}
 except Exception as exc:return {'name':name,'passed':False,'detail':type(exc).__name__}
def checks(root):
 from compatpkg import Client,Service,decode,encode,make_client
 from compatpkg.legacy import old_client
 from compatpkg.new_api import service
 def c1(): return isinstance(service('s'),Service)
 def c2(): return isinstance(make_client('x'),Client) and isinstance(old_client('x'),Client) and isinstance(make_client('x'),Service)
 def c3(): c=make_client('x'); before=getattr(c,'timeout',30); result=c.request('/x',timeout=7); return result['timeout']==7 and getattr(c,'timeout',30)==before
 def c4(): return make_client('x').request('/x')['timeout']==30
 def c5(): return make_client('x',12).timeout==12 and old_client('x',13).timeout==13
 def c6(): return decode(encode(Service('d')))=={'name':'d','timeout':30} and decode(encode(Service('c',9)))=={'name':'c','timeout':9}
 def c7(): return decode('{"name":"legacy"}')=={'name':'legacy','timeout':30}
 def c8(): return service('new',8).request('/new')['timeout']==8
 return [_safe('service type',c1),_safe('legacy Client compatibility',c2),_safe('per-request override and non-mutation',c3),_safe('default timeout',c4),_safe('factory/legacy propagation',c5),_safe('default and non-default codec round trip',c6),_safe('legacy codec default',c7),_safe('new API request propagation',c8)]
"""
}
