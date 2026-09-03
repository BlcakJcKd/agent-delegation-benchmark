"""Hidden-side evaluator for V2 generated tasks.

The runner passes the instance and candidate workspace directly; no evaluator
files are copied into a candidate workspace.  Each score keeps correctness
dimensions separate so latency/tool efficiency cannot mask functional errors.
"""
from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .generate import TaskInstance


def _run(root: Path, code: str, timeout: int = 15) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="v2-hidden-") as d:
        script = Path(d) / "hidden_check.py"
        script.write_text(code)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(script)], cwd=root, env=env, text=True, capture_output=True, timeout=timeout)
        return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


def _checks(family: str, root: Path, variant: dict[str, object] | None = None) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    if family == "C1_config_precedence":
        code = """
from app.config import load_settings
import json,tempfile
with tempfile.NamedTemporaryFile('w', suffix='.json') as f:
 json.dump({'port':'7000','debug':'false','label':'file'},f); f.flush()
 s=load_settings(f.name, {'APP_PORT':'7100','APP_DEBUG':'true','APP_LABEL':'env'}, ['--port=7200'])
 assert s == {'host':'127.0.0.1','port':7200,'debug':True,'retries':2,'label':'env'}, s
 assert load_settings(f.name)['port']==7000
"""
        ok, note = _run(root, code); checks.append(("hidden_precedence_types", ok, note))
    elif family == "C2_cache_invalidation":
        code = """
from state.store import MutableStore
from state.parser import Parser
from state.derived import derived_total
s=MutableStore({'a':'1,2,3'}); p=Parser(s)
assert derived_total(p,'a')==12; assert derived_total(p,'a')==12; assert p.parse_calls==1
s.put('a','10,1'); assert derived_total(p,'a')==22; assert p.parse_calls==2; assert derived_total(p,'a')==22; assert p.parse_calls==2
"""
        ok, note = _run(root, code); checks.append(("versioned_cache", ok, note))
    elif family == "C3_retry_idempotency":
        code = """
from service.client import Client
from service.transport import FakeTransport, Timeout, PermanentFailure
t=FakeTransport(['timeout']); c=Client(t); r=c.create({'x':1},'k'); assert r['ok'] and len(t.effects)==1
t=FakeTransport(['permanent']);
try: Client(t).create({'x':1},'k')
except PermanentFailure: pass
else: raise AssertionError('permanent retried/accepted')
assert not t.effects
"""
        ok, note = _run(root, code); checks.append(("retry_classification", ok, note))
    elif family == "C4_timeseries_leakage":
        code = """
from forecast.pipeline import prepare
values=list(range(20)); x,y,cut,scale=prepare(values,split=.6,width=3)
assert cut==12
assert scale==(0,11), scale
assert x.shape==(17,3) and y.shape==(17,), (x.shape,y.shape)
assert max(x[:cut-3].ravel()) <= 1.0
"""
        ok, note = _run(root, code); checks.append(("chronological_split_no_leakage", ok, note))
    elif family == "C5_state_transition":
        code = """
from sim.engine import step
from sim.state import State
s=State(); step(s,3); assert s.energy+s.total_output==s.total_input
step(s,-10); assert s.level==0 and s.energy+s.total_output==s.total_input
for a in [2,2,2,2]: step(s,a)
assert 0<=s.level<=10 and s.energy+s.total_output==s.total_input
"""
        ok, note = _run(root, code); checks.append(("transition_accounting_bounds", ok, note))
    elif family == "C6_compat_refactor":
        code = """
import json
from compatpkg import Client, make_client, encode, decode
c=make_client('old', 7); assert c.request('/x')['timeout']==7
assert Client is type(c); assert decode('{"name":"legacy"}')=={'name':'legacy','timeout':30}
assert make_client('x').request('/x',timeout=2)['timeout']==2
assert json.loads(encode(c))=={'name':'old','timeout':7}
"""
        ok, note = _run(root, code); checks.append(("legacy_and_new_api", ok, note))
    elif family == "C7_diagnostic_artifact":
        code = """
import json, tempfile
from pathlib import Path
from analysis import run
with tempfile.TemporaryDirectory() as d:
 p=Path(d); s=run('data/measurements.csv',p/'plot.png',p/'summary.json')
 assert (p/'plot.png').read_bytes().startswith(b'\\x89PNG')
 data=json.loads((p/'summary.json').read_text())
assert data['rows']==7 and data['outlier_sample']=='S%s' and data['outlier_reason']=='high_treatment_score'
assert abs(data['control_mean']-10.35)<1e-6
""" % (int((variant or {}).get('limit', 7)) + 1)
        ok, note = _run(root, code); checks.append(("artifact_and_summary", ok, note))
    return checks


def evaluate(instance: TaskInstance, workspace: Path, hidden_root: Path | None = None) -> dict[str, Any]:
    checks = _checks(instance.family, workspace, instance.variant)
    passed = sum(ok for _, ok, _ in checks)
    score = round(100 * passed / len(checks), 2) if checks else 0.0
    public = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=workspace, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, text=True, capture_output=True, timeout=30)
    invariant = passed == len(checks)
    api = invariant
    scope = not any(p.name.startswith("hidden_") for p in workspace.rglob("*"))
    return {"family": instance.family, "task_id": instance.task_id, "correctness": score, "maximum": 100,
            "public_tests": {"passed": public.returncode == 0, "stdout": public.stdout[-1000:], "stderr": public.stderr[-1000:]},
            "hidden_tests": {"passed": passed, "total": len(checks), "checks": [{"name": n, "passed": ok, "note": note} for n, ok, note in checks]},
            "invariant_checks": invariant, "api_compatibility": api, "scope_compliance": scope,
            "hidden_evaluator_outside_candidate": hidden_root is None or not str(hidden_root.resolve()).startswith(str(workspace.resolve()) + os.sep)}


def reference_fix(instance: TaskInstance, workspace: Path) -> None:
    """Authoritative private-side repair used only by pre-inference validation."""
    replacements = {
        "C1_config_precedence": [("    result.update(read_env(environ))\n    result.update(read_file(config_path))", "    result.update(read_file(config_path))\n    result.update(read_env(environ))")],
        "C2_cache_invalidation": [("self.cache = {}; self.parse_calls = 0", "self.cache = {}; self.parse_calls = 0"), ("if key in self.cache: return self.cache[key]", "if key in self.cache and self.cache[key][0] == self.store.version: return self.cache[key][1]"), ("self.cache[key] = value", "self.cache[key] = (self.store.version, value)")],
        "C3_retry_idempotency": [("def __init__(self, failures=None): self.failures=list(failures or []); self.effects=[]", "def __init__(self, failures=None): self.failures=list(failures or []); self.effects=[]; self.completed={} "), ("if outcome == 'timeout':\n                        self.effects.append((key, dict(payload)))\n                        raise Timeout('response lost')", "if outcome == 'timeout':\n                        if key not in self.completed: self.effects.append((key, dict(payload))); self.completed[key]=True\n                        raise Timeout('response lost')"), ("self.effects.append((key, dict(payload)))\n                return", "if key in self.completed: return {'ok': True, 'effect_count': len(self.effects)}\n                self.effects.append((key, dict(payload)))\n                return")],
        "C4_timeseries_leakage": [("scale=fit_scale(values)\n", "scale=fit_scale(values[:cut])\n"), ("x,y=make_windows(values,width)\n    cut=max(1,int(len(values)*split))", "cut=max(1,int(len(values)*split))\n    x,y=make_windows(values,width)")],
        "C5_state_transition": [("state.energy += action\n", "state.energy += action - produced\n")],
        "C6_compat_refactor": [("from .api import Client, encode, decode", "from .api import Client, make_client, encode, decode"), ("'timeout':self.timeout}", "'timeout':self.timeout if timeout is None else timeout}")],
        "C7_diagnostic_artifact": [("values=[float(r['score']) for r in rows if r['condition']=='control']", "values=[float(r['score']) for r in rows if r['condition']=='control']"), ("summary={'mean_score':sum(values)/len(values),'outlier_sample':'S08','outlier_reason':'low_library_size'}", "control=[float(r['score']) for r in rows if r['condition']=='control']\n            treatment=[r for r in rows if r['condition']=='treatment']\n            outlier=max(treatment,key=lambda r:float(r['score']))\n            summary={'rows':len(rows),'control_mean':sum(control)/len(control),'outlier_sample':outlier['sample'],'outlier_reason':'high_treatment_score'}"), ("Path(output_png).write_bytes(b'not a png')", "from plotting import save_plot\n            save_plot(rows, output_png)")],
    }
    for old, new in replacements.get(instance.family, []):
        for path in workspace.rglob("*.py"):
            text = path.read_text()
            if old in text:
                path.write_text(text.replace(old, new))
    if instance.family == "C3_retry_idempotency":
        path = workspace / "service/transport.py"
        text = path.read_text()
        text = text.replace("if outcome == 'timeout':\n                self.effects.append((key, dict(payload)))\n                raise Timeout('response lost')", "if outcome == 'timeout':\n                if key not in self.completed:\n                    self.effects.append((key, dict(payload))); self.completed[key] = True\n                raise Timeout('response lost')")
        text = text.replace("self.effects.append((key, dict(payload)))\n        return", "if key in self.completed: return {'ok': True, 'effect_count': len(self.effects)}\n        self.effects.append((key, dict(payload)))\n        return")
        path.write_text(text)
    elif instance.family == "C4_timeseries_leakage":
        path = workspace / "forecast/pipeline.py"
        path.write_text("""import numpy as np
from .scaling import fit_scale, apply_scale
def make_windows(values, width=3):
    x=[]; y=[]
    for i in range(len(values)-width): x.append(values[i:i+width]); y.append(values[i+width])
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
def prepare(values, split=0.7, width=3):
    cut=max(1,int(len(values)*split))
    train_x, train_y=make_windows(values[:cut], width)
    eval_x, eval_y=make_windows(values[max(0,cut-width):], width)
    scale=fit_scale(values[:cut])
    x=np.concatenate([train_x, eval_x]); y=np.concatenate([train_y, eval_y])
    return apply_scale(x,scale), y, cut, scale
def evaluate(values, split=0.7, width=3):
    x,y,cut,scale=prepare(values,split,width)
    return {'train_shape': list(x.shape), 'eval_shape': list(x.shape), 'train_mean': float(x[:max(0,cut-width)].mean()), 'eval_mean': float(x[max(0,cut-width):].mean()), 'scale_max': scale[1]}
""")
    elif instance.family == "C7_diagnostic_artifact":
        (workspace / "analysis.py").write_text("""import csv, json
from pathlib import Path
def run(input_path='data/measurements.csv', output_png='diagnostic.png', output_json='summary.json'):
    rows=list(csv.DictReader(Path(input_path).open()))
    control=[float(r['score']) for r in rows if r['condition']=='control']
    treatment=[r for r in rows if r['condition']=='treatment']
    outlier=max(treatment,key=lambda r:float(r['score']))
    summary={'rows':len(rows),'control_mean':sum(control)/len(control),'outlier_sample':outlier['sample'],'outlier_reason':'high_treatment_score'}
    Path(output_json).write_text(json.dumps(summary, sort_keys=True))
    from plotting import save_plot
    save_plot(rows, output_png)
    return summary
if __name__ == '__main__': run()
""")
