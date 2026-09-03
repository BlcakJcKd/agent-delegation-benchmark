"""V2.2 structural calibration, bounded pilot, and private reporting."""
from __future__ import annotations
import csv, fnmatch, hashlib, json, os, signal, statistics, subprocess, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from benchmark.validation_metadata import validation_consistency
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import connect, default_state_dir, finalize_run, record_benchmark_suite, record_benchmark_task, record_cost, record_harness, record_request_metric, record_run, record_task_attempt
from . import ATTEMPT_TIMEOUT_SECONDS, BASELINE_MAXIMUM, BASELINE_TARGET, CALIBRATION_CONFIG, CALIBRATION_SEED, CHECK_COUNT, COMPARISON_CONFIGURATIONS, EVALUATION_CLASS, EVALUATION_SEEDS, FAMILIES, PHASE_CALIBRATION, PHASE_COMPARATIVE, SUITE_NAME, SUITE_VERSION
from .evaluate import evaluate
from .generate import make_instance, materialize, sha256_json, workspace_digest
from .gold_accessibility import audit_tracked_gold_accessibility

SOURCE_PATHS=("benchmark/public_characterization_v22/__init__.py","benchmark/public_characterization_v22/generate.py","benchmark/public_characterization_v22/evaluate.py","benchmark/public_characterization_v22/runner.py","benchmark/public_characterization_v22/gold_accessibility.py","benchmark/validation_metadata.py","benchmark/v2/telemetry.py","benchmark/adapters.py","benchmark/provenance.py","ekalavya/ledger.py","ekalavya/harness_registry.py","pyproject.toml")
ROOT_CLUSTERS={
 "P1_stateful_inventory":[
  {"id":"storage_version_cache","domains":["storage","versioning","derived cache"]},
  {"id":"parsing_domain","domains":["domain models","amount parsing"]},
  {"id":"catalog_index_search","domains":["catalog index","normalized search","ordering"]},
  {"id":"analytics_orchestration","domains":["fractional analytics","service/report composition"]}],
 "P3_scientific_pipeline":[
  {"id":"schema_loader","domains":["schema","loader","row coercion"]},
  {"id":"normalization_ordering","domains":["normalization","chronological ordering"]},
  {"id":"group_split_policy","domains":["group policy","deterministic split","leakage"]},
  {"id":"metrics_reporting_pipeline","domains":["metrics","report","pipeline orchestration"]}]}

def now(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def git_sha():
 try:return subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
 except (OSError,subprocess.CalledProcessError):return None
def state_root():
 root=default_state_dir()/"experiments"/SUITE_NAME; root.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(root,0o700); return root
def _snapshot(w):
 from . import IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES
 return {p.relative_to(w).as_posix():digest(p.read_bytes()) for p in w.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(x in IGNORED_GENERATED_DIRS for x in p.parts)}
def _match(path,pattern): return fnmatch.fnmatch(path,pattern) or ("**/" in pattern and fnmatch.fnmatch(path,pattern.replace("**/","")))
def changed_files(before,after): return sorted({x for x in set(before)|set(after) if before.get(x)!=after.get(x)})
def prohibited_files(changes,scope):
 from . import IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES
 return [p for p in changes if not any(x in IGNORED_GENERATED_DIRS for x in Path(p).parts) and Path(p).suffix not in IGNORED_GENERATED_SUFFIXES and not any(_match(p,x) for x in scope.get("editable",[]))]
def _visible_verify(w):
 try:
  p=subprocess.run([sys.executable,str(w/"verifier/verify.py")],cwd=w,env={**os.environ,"PYTHONPATH":str(w)},text=True,capture_output=True,timeout=30,check=False)
  payload=json.loads(p.stdout); vector=[bool(x) for x in payload["checks"]]
  return {"ok":p.returncode==0 and len(vector)==CHECK_COUNT,"check_vector":vector,"error":p.stderr[-1000:]}
 except (OSError,subprocess.TimeoutExpired,ValueError,KeyError,TypeError) as exc:return {"ok":False,"check_vector":[],"error":type(exc).__name__}
def _baseline(x,w):
 c=evaluate(x,w); v=_visible_verify(w)
 if len(c["check_vector"])!=CHECK_COUNT: raise ValueError("baseline evaluator did not return eight checks")
 return {"family":x.family,"seed":x.seed,"task_id":x.task_id,"baseline_score":c["score"],"baseline_check_vector":c["check_vector"],"visible_check_vector":v["check_vector"],"visible_controller_agree":v["ok"] and c["check_vector"]==v["check_vector"],"generated_workspace_hash":workspace_digest(w),"prompt_hash":digest(x.prompt.encode()),"visible_verifier_hash":x.visible_verifier_hash,"task_spec_hash":x.task_spec_hash,"allowed_edit_manifest_hash":x.edit_scope_hash,"checks":[z["name"] for z in c["checks"]]}
def _load_reference(seed):
 p=state_root()/"validation"/"reference-validation.json"
 if not p.is_file(): return None
 try:
  value=json.loads(p.read_text()); return value.get("variants",{}).get(str(seed)) if "variants" in value else value if value.get("seed")==seed else None
 except (OSError,ValueError): return None
def _reference_ok(result):
 ref=result.get("reference_validation")
 if not ref or not ref.get("passed") or ref.get("suite")!=SUITE_NAME or ref.get("version")!=SUITE_VERSION or ref.get("seed")!=result["seed"] or ref.get("suite_git_sha")!=result["provenance"].get("git_sha"): return False
 if ref.get("temporary_reference_repair_deleted") is not True or ref.get("gold_source_retained") is not False or ref.get("gold_accessibility",{}).get("status")!="pass": return False
 s=ref.get("structural_validation",{})
 if len(s.get("clusters",[]))<4 or not s.get("single_cluster_gate") or not s.get("two_cluster_gate") or len(s.get("distinct_non_full_vectors",[]))<4 or not s.get("integration_dependency_gate"): return False
 items={x.get("family"):x for x in ref.get("tasks",[]) if isinstance(x,dict)}
 return all(items.get(t["family"],{}).get("score")==100.0 and items.get(t["family"],{}).get("check_vector")==[True]*CHECK_COUNT and items.get(t["family"],{}).get("visible_check_vector")==[True]*CHECK_COUNT for t in result["tasks"])
def validate_preflight(*,seed,phase,require_reference=False):
 result={"suite":SUITE_NAME,"version":SUITE_VERSION,"evaluation_class":EVALUATION_CLASS,"phase":phase,"seed":seed,"tasks":[],"provenance":None,"reference_validation":None}
 try: result["provenance"]=validate_git_identity(Path(__file__).resolve().parents[2],SOURCE_PATHS)
 except Exception as exc: result["provenance_error"]=str(exc)
 result["gold_accessibility"]=audit_tracked_gold_accessibility(Path(__file__).resolve().parents[2])
 with tempfile.TemporaryDirectory(prefix="ekalavya-v22-preflight-") as d:
  base=Path(d)
  for i,family in enumerate(FAMILIES):
   x=make_instance(family,seed+i); w=materialize(x,base/family); b=_baseline(x,w); repeat=materialize(x,base/f"repeat-{family}")
   b["headroom_passed"]=b["baseline_score"]<BASELINE_MAXIMUM and BASELINE_TARGET[0]<=b["baseline_score"]<=BASELINE_TARGET[1]; b["deterministic_hash_passed"]=b["generated_workspace_hash"]==workspace_digest(repeat); b["reference_validation_passed"]=None; result["tasks"].append(b)
 ref=_load_reference(seed)
 if ref is not None: result["reference_validation"]=ref
 for task in result["tasks"]:
  if ref is not None:
   item=next((x for x in ref.get("tasks",[]) if x.get("family")==task["family"]),{}); task["reference_validation_passed"]=bool(_reference_ok(result) and item.get("score")==100.0 and item.get("check_vector")==[True]*CHECK_COUNT and item.get("visible_check_vector")==[True]*CHECK_COUNT)
 result["gates"]={"provenance":bool(result.get("provenance")),"gold_accessibility":result["gold_accessibility"].get("status")=="pass","headroom":all(x["headroom_passed"] for x in result["tasks"]),"visible_controller_parity":all(x["visible_controller_agree"] and len(x["baseline_check_vector"])==CHECK_COUNT for x in result["tasks"]),"deterministic_hashes":all(x["deterministic_hash_passed"] for x in result["tasks"]),"reference_validation":_reference_ok(result) if require_reference else "not_required"}
 result["validation_consistency"]=validation_consistency(result,reference_required=require_reference,check_count=CHECK_COUNT); result["gates"]["validation_consistency"]=result["validation_consistency"]["ok"]; result["ok"]=all(x is True for x in result["gates"].values())
 vd=state_root()/"validation"; vd.mkdir(parents=True,exist_ok=True,mode=0o700); (vd/f"preflight-{phase}-{seed}.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n"); (vd/"preflight.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n"); (state_root()/"VALIDATION_REPORT.md").write_text(f"V2.2 {phase} seed {seed} gate={str(result['ok']).lower()}\n")
 return result
def _terminate(p):
 try: os.killpg(p.pid,signal.SIGTERM); p.wait(timeout=5)
 except (OSError,subprocess.TimeoutExpired):
  try: os.killpg(p.pid,signal.SIGKILL)
  except OSError: pass
def _record_suite(conn,instances,prov,baselines,refat):
 sid=record_benchmark_suite(conn,SUITE_NAME,EVALUATION_CLASS,SUITE_VERSION,git_sha=prov["git_sha"],evaluation_class=EVALUATION_CLASS,metadata={"families":FAMILIES,"calibration_seed":CALIBRATION_SEED,"evaluation_seeds":EVALUATION_SEEDS,"source_paths":prov["source_paths"],"source_sha256":prov["source_sha256"]}); ids={}
 for x in instances:
  b=baselines[x.family]; ids[x.task_id]=record_benchmark_task(conn,sid,family=x.family,task_id=x.task_id,variant_seed=str(x.seed),content_hash=sha256_json(x.files),prompt_hash=digest(x.prompt.encode()),evaluator_hash=x.visible_verifier_hash,baseline_score=b["baseline_score"],baseline_check_vector=b["baseline_check_vector"],task_spec_hash=x.task_spec_hash,allowed_edit_manifest_hash=x.edit_scope_hash,reference_validation_passed=True,reference_validation_at=refat)
 return sid,ids
def _attempt(conn,sid,dbtid,x,b,model,reason,hid,root,telemetry,agyver,phase):
 key=f"{phase}-{model}-{x.family}-{x.seed}"; w=root/"workspaces"/key; materialize(x,w); before=_snapshot(w); run_id=f"{SUITE_NAME}:{uuid.uuid4().hex}"; started=now()
 requested={"experiment":SUITE_NAME,"profile":"flash","provider":"gemini","provider_model_id":model,"model":model,"reasoning":reason,"harness":"agy","evaluation_class":EVALUATION_CLASS,"phase":phase,"attempt_timeout_seconds":ATTEMPT_TIMEOUT_SECONDS}
 record_run(conn,run_id,requested,resolved={"provider_model_id":model,"reasoning":reason,"harness":"agy","harness_version":agyver},status="running",evaluation_class=EVALUATION_CLASS,provider="gemini",identity_key=f"gemini:flash:{model}",harness_id=hid,billing_mode="subscription",started_at=started)
 begin=time.monotonic(); code=-1; stdout=stderr=""; timed=False; evdir=root/("calibration-evidence" if phase==PHASE_CALIBRATION else "evidence"); evdir.mkdir(parents=True,exist_ok=True,mode=0o700)
 try:
  p=subprocess.Popen(AntigravityAdapter(model=model,reasoning_effort=None).command(w,x.prompt,evdir/key),cwd=w,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,"BENCHMARK_WORKSPACE":str(w)},start_new_session=True)
  try: stdout,stderr=p.communicate(timeout=ATTEMPT_TIMEOUT_SECONDS); code=p.returncode
  except subprocess.TimeoutExpired: timed=True; _terminate(p); stdout,stderr=p.communicate(); code=-1
 except OSError as exc: stderr=str(exc)
 wall=time.monotonic()-begin; changed=changed_files(before,_snapshot(w)); prohibited=prohibited_files(changed,x.edit_scope); tamper=bool(prohibited); final=None; malformed=False
 if not timed and code==0:
  try: final=evaluate(x,w); malformed=len(final["check_vector"])!=CHECK_COUNT
  except Exception: malformed=True
 requests=parse_trace(stdout); status="explicit_timeout" if timed else ("malformed_evaluator" if malformed else ("evaluator_tampering" if tamper else ("completed" if code==0 else "harness_failure"))); fs=final["score"] if final and not malformed else None; delta=None if fs is None else fs-b["baseline_score"]; norm=None if fs is None or b["baseline_score"]>=100 else delta/(100-b["baseline_score"])
 toks={f:[getattr(z,f) for z in requests if getattr(z,f) is not None] for f in ("input_tokens","output_tokens","cache_read_tokens","reasoning_tokens")}
 ev={"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"phase":phase,"run_id":run_id,"requested":requested,"resolved":{"provider_model_id":model,"reasoning":reason,"harness":"agy","harness_version":agyver},"started_at":started,"ended_at":now(),"wall_seconds":wall,"exit_code":code,"timed_out":timed,"status":status,"changed_files":changed,"evaluator_tampering":tamper,"prohibited_changed_files":prohibited,"baseline_score":b["baseline_score"],"baseline_check_vector":b["baseline_check_vector"],"final_score":fs,"final_check_vector":final["check_vector"] if final and not malformed else None,"delta_score":delta,"normalized_improvement":norm,"full_pass":final["full_pass"] if final and not malformed else None,"request_count":len(requests) or None,"request_metric_semantics":telemetry.get("request_metric_semantics"),"tool_event_telemetry":telemetry.get("tool_event_telemetry"),"tool_events":None,"token_metric_semantics":telemetry.get("token_metric_semantics"),"input_tokens":sum(toks["input_tokens"]) if toks["input_tokens"] else None,"output_tokens":sum(toks["output_tokens"]) if toks["output_tokens"] else None,"cache_read_tokens":sum(toks["cache_read_tokens"]) if toks["cache_read_tokens"] else None,"reasoning_tokens":sum(toks["reasoning_tokens"]) if toks["reasoning_tokens"] else None,"task":{"family":x.family,"task_id":x.task_id,"seed":x.seed,"generated_workspace_hash":b["generated_workspace_hash"],"prompt_hash":b["prompt_hash"],"visible_verifier_hash":b["visible_verifier_hash"],"task_spec_hash":b["task_spec_hash"],"allowed_edit_manifest_hash":b["allowed_edit_manifest_hash"],"suite_git_sha":git_sha()},"stdout_sha256":digest(stdout.encode()),"stderr_sha256":digest(stderr.encode()),"assessment":final}
 ep=evdir/f"{key}.json"; ep.write_text(json.dumps(ev,indent=2,sort_keys=True)+"\n"); record_task_attempt(conn,run_id,task_id=dbtid,score=fs,public_score=fs,invariant_score=fs,scope_compliant=not tamper,wall_seconds=wall,baseline_score=b["baseline_score"],baseline_check_vector=b["baseline_check_vector"],final_check_vector=ev["final_check_vector"],delta_score=delta,normalized_improvement=norm,evaluator_tampering=tamper,prohibited_changed_files=prohibited,metadata=ev)
 for m in requests: record_request_metric(conn,run_id,m.json())
 record_cost(conn,run_id,billing_mode="subscription",cost_source="unavailable: subscription route",input_tokens=ev["input_tokens"],output_tokens=ev["output_tokens"],cached_input_tokens=ev["cache_read_tokens"],reasoning_tokens=ev["reasoning_tokens"]); finalize_run(conn,run_id,ended_at=ev["ended_at"],status=status,raw_evidence_path=str(ep),raw_evidence_sha256=digest(ep.read_bytes())); return ev
def _read_rows(root,phase=None):
 directory=root/("calibration-evidence" if phase==PHASE_CALIBRATION else "evidence"); return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))] if directory.is_dir() else []
def _calibration_useful(rows):
 return len(rows)==2 and all(r["status"]=="completed" and r["final_score"] is not None and r["final_score"]!=r["baseline_score"] and r["final_score"]<100 and 50<=r["final_score"]<=87.5 for r in rows)
def _plot(rows,path,kind,mode):
 obs=[r for r in rows if r["status"]=="completed" and r.get("final_score") is not None]
 if not obs:return {"status":"skipped","reason":"no_completed_observations"}
 import matplotlib.pyplot as plt
 labels=[f"{r['resolved']['provider_model_id'].split('-')[1]} {r['resolved']['reasoning'].title()} ({r['phase']})" for r in obs]; plt.figure(figsize=(9,5))
 if kind=="scatter":
  if mode=="baseline": x=[r["baseline_score"] for r in obs]; y=[r["final_score"] for r in obs]; xlabel="baseline score"; ylabel="final score"
  elif mode=="wall": x=[r["wall_seconds"] for r in obs]; y=[r["final_score"] for r in obs]; xlabel="wall seconds"; ylabel="final score"
  else: x=[r.get("output_tokens") or 0 for r in obs]; y=[r["final_score"] for r in obs]; xlabel="AGY output tokens"; ylabel="final score"
  plt.scatter(x,y)
  for a,b,label in zip(x,y,labels):plt.annotate(label,(a,b),fontsize=8)
  plt.xlabel(xlabel); plt.ylabel(ylabel)
 else: plt.bar(labels,[r["delta_score"] for r in obs]); plt.xticks(rotation=30,ha="right"); plt.ylabel("delta score")
 plt.tight_layout(); plt.savefig(path); plt.close(); return {"status":"created","kind":kind,"observations":len(obs),"labels":labels}
def report(root=None):
 root=(root or state_root()).resolve(); rows=_read_rows(root); cal=_read_rows(root,PHASE_CALIBRATION); allrows=cal+rows
 fields=["model","reasoning","phase","task","status","baseline_score","baseline_check_vector","final_score","final_check_vector"]+[f"check_{i}" for i in range(1,9)]+["passed_checks","delta_score","normalized_improvement","full_pass","evaluator_tampering","prohibited_changed_files","wall_seconds","input_tokens","output_tokens","cache_read_tokens","reasoning_tokens"]
 with (root/"task-check-matrix.csv").open("w",newline="") as h:
  w=csv.DictWriter(h,fieldnames=fields); w.writeheader()
  for r in allrows:
   v=r["final_check_vector"]; w.writerow({"model":r["resolved"]["provider_model_id"],"reasoning":r["resolved"]["reasoning"],"phase":r["phase"],"task":r["task"]["family"],"status":r["status"],"baseline_score":r["baseline_score"],"baseline_check_vector":"".join("P" if x else "F" for x in r["baseline_check_vector"]),"final_score":r["final_score"],"final_check_vector":"".join("P" if x else "F" for x in v) if v else None,**{f"check_{i}":("P" if x else "F") if v else None for i,x in enumerate(v or [],1)},"passed_checks":sum(v) if v else None,"delta_score":r["delta_score"],"normalized_improvement":r["normalized_improvement"],"full_pass":r["full_pass"],"evaluator_tampering":r["evaluator_tampering"],"prohibited_changed_files":json.dumps(r["prohibited_changed_files"]),"wall_seconds":r["wall_seconds"],"input_tokens":r["input_tokens"],"output_tokens":r["output_tokens"],"cache_read_tokens":r["cache_read_tokens"],"reasoning_tokens":r["reasoning_tokens"]})
 (root/"task-check-matrix.md").write_text("# Public Characterization V2.2 task x check matrix\n\nCalibration rows are explicitly excluded from comparative ranking statistics.\n\n"+"\n".join(f"- {r['phase']} / {r['resolved']['provider_model_id']} / {r['task']['family']}: {r['status']}; baseline {''.join('P' if x else 'F' for x in r['baseline_check_vector'])}; final {''.join('P' if x else 'F' for x in r['final_check_vector']) if r['final_check_vector'] else '—'}; delta {r['delta_score'] if r['delta_score'] is not None else '—'}" for r in allrows)+"\n")
 configs=[]
 for model,reason in COMPARISON_CONFIGURATIONS:
  g=[r for r in rows if r["resolved"]["provider_model_id"]==model and r["resolved"]["reasoning"]==reason]; clean=[r for r in g if r["status"]=="completed" and r["final_score"] is not None]
  if g: configs.append({"model":model,"reasoning":reason,"attempted":len(g),"completed":len(clean),"harness_failure":sum(r["status"]=="harness_failure" for r in g),"explicit_timeout":sum(r["status"]=="explicit_timeout" for r in g),"completion_rate":len(clean)/len(g),"quality_on_completed":statistics.mean(r["final_score"] for r in clean) if clean else None,"mean_baseline":statistics.mean(r["baseline_score"] for r in g),"mean_delta":statistics.mean(r["delta_score"] for r in clean) if clean else None,"median_final":statistics.median(r["final_score"] for r in clean) if clean else None,"full_solves":sum(r["full_pass"] is True for r in clean),"mean_wall":statistics.mean(r["wall_seconds"] for r in g),"input_tokens":sum(r["input_tokens"] or 0 for r in g),"output_tokens":sum(r["output_tokens"] or 0 for r in g),"cache_read_tokens":sum(r["cache_read_tokens"] or 0 for r in g),"reasoning_tokens":sum(r["reasoning_tokens"] or 0 for r in g)})
 (root/"configuration-summary.json").write_text(json.dumps({"comparative_statistics_exclude_calibration":True,"configurations":configs},indent=2,sort_keys=True)+"\n")
 (root/"calibration-summary.json").write_text(json.dumps({"phase":PHASE_CALIBRATION,"model":CALIBRATION_CONFIG[0],"reasoning":CALIBRATION_CONFIG[1],"attempted":len(cal),"completed":sum(r["status"]=="completed" for r in cal),"useful_intermediate_difficulty":_calibration_useful(cal)},indent=2,sort_keys=True)+"\n")
 plots={"baseline-vs-final":_plot(allrows,root/"baseline-vs-final.png","scatter","baseline"),"delta-by-configuration":_plot(allrows,root/"delta-by-configuration.png","bar","delta"),"final-vs-wall":_plot(allrows,root/"final-vs-wall.png","scatter","wall"),"final-vs-tokens":_plot(allrows,root/"final-vs-tokens.png","scatter","tokens")}; (root/"plot-metadata.json").write_text(json.dumps(plots,indent=2,sort_keys=True)+"\n")
 lines=[f"# {SUITE_NAME}","",f"Class: {EVALUATION_CLASS}; fixed attempt timeout: {ATTEMPT_TIMEOUT_SECONDS} seconds.","",f"Calibration attempts: {len(cal)}; comparative attempts: {len(rows)}; calibration excluded from rankings.","","## Comparative configuration summary","","| Model | Quality | Mean delta | Full solves | Completed/attempted | Completion | Mean wall | Input/output/cache/reasoning |","|---|---:|---:|---:|---:|---:|---:|---|"]
 for c in configs: lines.append(f"| {c['model']} | {c['quality_on_completed']} | {c['mean_delta']} | {c['full_solves']} | {c['completed']}/{c['attempted']} | {c['completion_rate']} | {c['mean_wall']} | {c['input_tokens']}/{c['output_tokens']}/{c['cache_read_tokens']}/{c['reasoning_tokens']} |")
 lines += ["","Quality is conditional on clean scored completion; reliability and calibration are separate.","","AGY request metric: harness_session; tool telemetry: unavailable; tokens: AGY-reported usage, not verified billing usage.","","No model-quality comparison is authorized if calibration does not show useful intermediate difficulty."]
 (root/"REPORT.md").write_text("\n".join(lines)+"\n"); (root/"telemetry-semantics.md").write_text("# Telemetry semantics\n\nAGY 1.1.25 request metrics are harness_session, not verified provider requests. Tool event telemetry is unavailable, not observable zero.\n"); (root/"token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning values are AGY-reported usage. Billing equivalence and cumulative/session semantics are not verified.\n")
 (root/"AUDIT_REPORT.md").write_text("# Public Characterization V2.2 audit\n\nRoot-cause clusters are controller-side validation metadata, not candidate scoring. Calibration is excluded from comparative statistics.\n\n"+("Calibration passed its intermediate-difficulty gate; comparative execution was authorized." if _calibration_useful(cal) else "Calibration did not demonstrate useful intermediate difficulty; comparative execution was not authorized.")+"\n")
 return {"comparative":configs,"calibration":json.loads((root/"calibration-summary.json").read_text())}
def _public_artifacts(instances,root):
 for x in instances:
  for base in ("task-specifications","verifier-contracts","edit-scopes","baseline-task-snapshots"):(root/base/x.family).mkdir(parents=True,exist_ok=True)
  (root/"task-specifications"/x.family/"README.md").write_text(x.files["README.md"]); (root/"task-specifications"/x.family/"specification.json").write_text(json.dumps(x.specification,indent=2,sort_keys=True)+"\n"); (root/"verifier-contracts"/x.family/"contract.py").write_text(x.files["verifier/contract.py"]); (root/"verifier-contracts"/x.family/"verify.py").write_text(x.files["verifier/verify.py"]); (root/"edit-scopes"/x.family/"allowed-edit-manifest.json").write_text(json.dumps(x.edit_scope,indent=2,sort_keys=True)+"\n")
  for name,value in x.files.items():
   if not name.startswith((".ekalavya/","verifier/")): p=root/"baseline-task-snapshots"/x.family/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(value)
def pilot():
 gate=validate_preflight(seed=CALIBRATION_SEED,phase=PHASE_CALIBRATION,require_reference=True)
 if not gate["ok"]: raise RuntimeError("V2.2 calibration no-inference gates failed; no model started")
 root=state_root()
 if list((root/"calibration-evidence").glob("*.json")) or list((root/"evidence").glob("*.json")): raise RuntimeError("V2.2 pilot already has evidence; retries are prohibited")
 instances=[make_instance(f,CALIBRATION_SEED+i) for i,f in enumerate(FAMILIES)]; baselines={x["family"]:x for x in gate["tasks"]}; prov=gate["provenance"]; conn=connect(); reg=current_registry(); validate_registry(reg); agy=next(x for x in reg if x["name"]=="agy"); agyver=agy.get("observed_version") or agy["version"]
 _public_artifacts(instances,root)
 (root/"discovery.json").write_text(json.dumps({"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"harness":"agy","harness_version":agyver,"calibration_seed":CALIBRATION_SEED,"evaluation_seeds":EVALUATION_SEEDS,"calibration_configuration":{"model":CALIBRATION_CONFIG[0],"reasoning":CALIBRATION_CONFIG[1]},"comparison_configurations":[{"model":m,"reasoning":r} for m,r in COMPARISON_CONFIGURATIONS],"attempt_timeout_seconds":ATTEMPT_TIMEOUT_SECONDS},indent=2,sort_keys=True)+"\n")
 hid=record_harness(conn,"agy",version=agyver,adapter_version="benchmark.public_characterization_v22.runner",transport="agy",capabilities=agy["capabilities"],telemetry=agy["telemetry"],eligibility=agy["eligibility"],evidence_label="public_characterization_non_adversarial",observed_at=now())
 sid,tids=_record_suite(conn,instances,prov,baselines,gate["reference_validation"]["validation_timestamp"]); results=[]
 for family in FAMILIES:
  x=next(z for z in instances if z.family==family); results.append(_attempt(conn,sid,tids[x.task_id],x,baselines[family],CALIBRATION_CONFIG[0],CALIBRATION_CONFIG[1],hid,root,agy["telemetry"],agyver,PHASE_CALIBRATION))
 useful=_calibration_useful(results)
 if useful:
  eval_gates=[validate_preflight(seed=EVALUATION_SEEDS[f],phase=PHASE_COMPARATIVE,require_reference=True) for f in FAMILIES]
  if not all(x["ok"] for x in eval_gates): raise RuntimeError("fresh comparative no-inference gates failed; comparative phase not started")
  eval_instances=[make_instance(f,EVALUATION_SEEDS[f]) for f in FAMILIES]; _public_artifacts(eval_instances,root); eval_baselines={x["family"]:next(g for eg in eval_gates for g in eg["tasks"] if g["family"]==x["family"])}; sid,tids2=_record_suite(conn,eval_instances,eval_gates[0]["provenance"],eval_baselines,eval_gates[0]["reference_validation"]["validation_timestamp"])
  for model,reason in COMPARISON_CONFIGURATIONS:
   for family in FAMILIES:
    x=next(z for z in eval_instances if z.family==family); results.append(_attempt(conn,sid,tids2[x.task_id],x,eval_baselines[family],model,reason,hid,root,agy["telemetry"],agyver,PHASE_COMPARATIVE))
 summary={"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"suite_git_sha":prov["git_sha"],"calibration_seed":CALIBRATION_SEED,"evaluation_seeds":EVALUATION_SEEDS,"calibration_attempts":2,"comparative_attempts":max(0,len(results)-2),"calibration_useful":useful,"comparative_ran":useful,"attempts":len(results),"completed":sum(x["status"]=="completed" for x in results),"harness_failure":sum(x["status"]=="harness_failure" for x in results),"explicit_timeout":sum(x["status"]=="explicit_timeout" for x in results),"malformed_evaluator":sum(x["status"]=="malformed_evaluator" for x in results),"evaluator_tampering":sum(x["status"]=="evaluator_tampering" for x in results)}
 (root/"run-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n"); report(root); return summary

if __name__=="__main__":
 action=sys.argv[1] if len(sys.argv)>1 else "validate"
 if action=="validate":
  r=validate_preflight(seed=CALIBRATION_SEED,phase=PHASE_CALIBRATION,require_reference="--require-reference" in sys.argv); print(json.dumps(r,indent=2,sort_keys=True)); raise SystemExit(0 if r["ok"] else 1)
 if action=="pilot": print(json.dumps(pilot(),indent=2,sort_keys=True))
 elif action=="report": print(json.dumps(report(),indent=2,sort_keys=True))
 else: raise SystemExit(f"unknown action {action}")
