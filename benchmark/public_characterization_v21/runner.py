"""V2.1 preflight, staged pilot, and private reporting."""
from __future__ import annotations
import csv, fnmatch, hashlib, json, os, signal, statistics, subprocess, sys, tempfile, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import connect, default_state_dir, finalize_run, record_benchmark_suite, record_benchmark_task, record_cost, record_harness, record_request_metric, record_run, record_task_attempt
from . import BASELINE_MAXIMUM, BASELINE_TARGET, CHECK_COUNT, EVALUATION_CLASS, FAMILIES, IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, PHASE_A_FAMILIES, PHASE_B_FAMILIES, PILOT_CONFIGURATIONS, SUITE_NAME, SUITE_VERSION
from .evaluate import evaluate
from .generate import TaskInstance, make_instance, materialize, sha256_json, workspace_digest
SEED=20261101
SOURCE_PATHS=("benchmark/public_characterization_v21/__init__.py","benchmark/public_characterization_v21/generate.py","benchmark/public_characterization_v21/evaluate.py","benchmark/public_characterization_v21/runner.py","benchmark/v2/telemetry.py","benchmark/adapters.py","benchmark/provenance.py","ekalavya/ledger.py","ekalavya/harness_registry.py","pyproject.toml")

def now(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def state_root():
    root=default_state_dir()/"experiments"/SUITE_NAME; root.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(root,0o700); return root
def _snapshot(w):
    return {p.relative_to(w).as_posix():digest(p.read_bytes()) for p in w.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(x in IGNORED_GENERATED_DIRS for x in p.parts)}
def changed_files(before,after): return sorted({x for x in set(before)|set(after) if before.get(x)!=after.get(x)})
def _match(path,pattern): return fnmatch.fnmatch(path,pattern) or ("**/" in pattern and fnmatch.fnmatch(path,pattern.replace("**/","")))
def prohibited_files(changes,scope):
    return [p for p in changes if not any(x in IGNORED_GENERATED_DIRS for x in Path(p).parts) and Path(p).suffix not in IGNORED_GENERATED_SUFFIXES and not any(_match(p,x) for x in scope.get("editable",[]))]
def derive_scores(baseline,final):
    if final is None:return {"delta_score":None,"normalized_improvement":None}
    return {"delta_score":final-baseline,"normalized_improvement":(final-baseline)/(100-baseline) if baseline<100 else None}
def _visible_verify(instance,w):
    try:
        p=subprocess.run([sys.executable,str(w/"verifier/verify.py")],cwd=w,env={**os.environ,"PYTHONPATH":str(w)},text=True,capture_output=True,timeout=30,check=False)
        payload=json.loads(p.stdout);vector=[bool(x) for x in payload["checks"]]
        return {"ok":p.returncode==0 and len(vector)==CHECK_COUNT,"check_vector":vector,"error":p.stderr[-1000:]}
    except (OSError,subprocess.TimeoutExpired,ValueError,KeyError,TypeError) as exc:return {"ok":False,"check_vector":[],"error":type(exc).__name__}
def _public_artifacts(x,root):
    for base in ("task-specifications","verifier-contracts","edit-scopes","baseline-task-snapshots"):(root/base/x.family).mkdir(parents=True,exist_ok=True)
    (root/"task-specifications"/x.family/"README.md").write_text(x.files["README.md"])
    (root/"task-specifications"/x.family/"specification.json").write_text(json.dumps(x.specification,indent=2,sort_keys=True)+"\n")
    (root/"verifier-contracts"/x.family/"contract.py").write_text(x.files["verifier/contract.py"])
    (root/"verifier-contracts"/x.family/"verify.py").write_text(x.files["verifier/verify.py"])
    (root/"edit-scopes"/x.family/"allowed-edit-manifest.json").write_text(json.dumps(x.edit_scope,indent=2,sort_keys=True)+"\n")
    for name,value in x.files.items():
        if name.startswith((".ekalavya/","verifier/")):continue
        path=root/"baseline-task-snapshots"/x.family/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
def _baseline(x,w):
    c=evaluate(x,w);v=_visible_verify(x,w)
    if len(c["check_vector"])!=CHECK_COUNT:raise ValueError("baseline evaluator did not return eight checks")
    return {"family":x.family,"seed":x.seed,"task_id":x.task_id,"baseline_score":c["score"],"baseline_check_vector":c["check_vector"],"visible_check_vector":v["check_vector"],"visible_controller_agree":v["ok"] and c["check_vector"]==v["check_vector"],"generated_workspace_hash":workspace_digest(w),"prompt_hash":digest(x.prompt.encode()),"visible_verifier_hash":x.visible_verifier_hash,"task_spec_hash":x.task_spec_hash,"allowed_edit_manifest_hash":x.edit_scope_hash,"checks":[z["name"] for z in c["checks"]]}
def _reference_ok(result,seed):
    ref=result.get("reference_validation") or {};tasks={z.get("family"):z for z in ref.get("tasks",[]) if isinstance(z,dict)}
    return bool(ref.get("passed")) and ref.get("suite")==SUITE_NAME and ref.get("version")==SUITE_VERSION and ref.get("seed")==seed and ref.get("suite_git_sha")==((result.get("provenance") or {}).get("git_sha")) and ref.get("temporary_reference_repair_deleted") is True and ref.get("gold_source_retained") is False and all(tasks.get(x["family"],{}).get("score")==100.0 and tasks.get(x["family"],{}).get("check_vector")==[True]*CHECK_COUNT and tasks.get(x["family"],{}).get("visible_check_vector")==[True]*CHECK_COUNT for x in result["tasks"])
def validate_preflight(*,require_reference=False,seed=SEED):
    result={"suite":SUITE_NAME,"version":SUITE_VERSION,"evaluation_class":EVALUATION_CLASS,"seed":seed,"tasks":[],"provenance":None,"reference_validation":None}
    try:result["provenance"]=validate_git_identity(Path(__file__).resolve().parents[2],SOURCE_PATHS)
    except Exception as exc:result["provenance_error"]=str(exc)
    with tempfile.TemporaryDirectory(prefix="ekalavya-v21-preflight-") as d:
        base=Path(d)
        for i,f in enumerate(FAMILIES):
            x=make_instance(f,seed+i);w=materialize(x,base/f);b=_baseline(x,w)
            b["headroom_passed"]=b["baseline_score"]<BASELINE_MAXIMUM and BASELINE_TARGET[0]<=b["baseline_score"]<=BASELINE_TARGET[1]
            b["deterministic_hash_passed"]=b["generated_workspace_hash"]==workspace_digest(materialize(x,base/f"repeat-{f}"));b["reference_validation_passed"]=False;result["tasks"].append(b)
    rp=state_root()/"validation"/"reference-validation.json"
    if rp.is_file():
        try:result["reference_validation"]=json.loads(rp.read_text())
        except ValueError:result["reference_validation"]={"passed":False}
    rg=_reference_ok(result,seed)
    result["gates"]={"provenance":bool(result.get("provenance")),"headroom":all(x["headroom_passed"] for x in result["tasks"]),"visible_controller_parity":all(x["visible_controller_agree"] and len(x["baseline_check_vector"])==CHECK_COUNT for x in result["tasks"]),"deterministic_hashes":all(x["deterministic_hash_passed"] for x in result["tasks"]),"reference_validation":rg if require_reference else "not_required"}
    result["ok"]=all(x is True for x in result["gates"].values())
    vd=state_root()/"validation";vd.mkdir(parents=True,exist_ok=True,mode=0o700);(vd/"preflight.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n");(state_root()/"VALIDATION_REPORT.md").write_text("# Public Characterization V2.1 validation\n\nOverall gate result: "+str(result["ok"]).lower()+"\n")
    return result
def _terminate(p):
    try:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5)
    except (OSError,subprocess.TimeoutExpired):
        try:os.killpg(p.pid,signal.SIGKILL)
        except OSError:pass
def _record_suite(conn,instances,prov,baselines,refat):
    sid=record_benchmark_suite(conn,SUITE_NAME,EVALUATION_CLASS,SUITE_VERSION,git_sha=prov["git_sha"],evaluation_class=EVALUATION_CLASS,metadata={"families":FAMILIES,"baseline_aware":True,"source_paths":prov["source_paths"],"source_sha256":prov["source_sha256"]});ids={}
    for x in instances:
        b=baselines[x.family];ids[x.task_id]=record_benchmark_task(conn,sid,family=x.family,task_id=x.task_id,variant_seed=str(x.seed),content_hash=sha256_json(x.files),prompt_hash=digest(x.prompt.encode()),evaluator_hash=x.visible_verifier_hash,baseline_score=b["baseline_score"],baseline_check_vector=b["baseline_check_vector"],task_spec_hash=x.task_spec_hash,allowed_edit_manifest_hash=x.edit_scope_hash,reference_validation_passed=True,reference_validation_at=refat)
    return sid,ids
def _attempt(conn,sid,dbtid,x,b,model,reason,hid,root,telemetry,agyver,phase):
    key=f"{model}-{x.family}-{x.seed}";w=root/"workspaces"/key;materialize(x,w);before=_snapshot(w);run_id=f"{SUITE_NAME}:{uuid.uuid4().hex}";started=now();requested={"experiment":SUITE_NAME,"profile":"flash","provider":"gemini","provider_model_id":model,"model":model,"reasoning":reason,"harness":"agy","evaluation_class":EVALUATION_CLASS,"phase":phase}
    record_run(conn,run_id,requested,resolved={"provider_model_id":model,"reasoning":reason,"harness":"agy","harness_version":agyver},status="running",evaluation_class=EVALUATION_CLASS,provider="gemini",identity_key=f"gemini:flash:{model}",harness_id=hid,billing_mode="subscription",started_at=started)
    begin=time.monotonic();code=-1;stdout=stderr="";timed=False;evdir=root/"evidence";evdir.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        p=subprocess.Popen(AntigravityAdapter(model=model,reasoning_effort=None).command(w,x.prompt,evdir/key),cwd=w,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,"BENCHMARK_WORKSPACE":str(w)},start_new_session=True)
        try:stdout,stderr=p.communicate(timeout=900);code=p.returncode
        except subprocess.TimeoutExpired:timed=True;_terminate(p);stdout,stderr=p.communicate();code=-1
    except OSError as exc:stderr=str(exc)
    wall=time.monotonic()-begin;changed=changed_files(before,_snapshot(w));prohibited=prohibited_files(changed,x.edit_scope);tamper=bool(prohibited);final=None;malformed=False
    if not timed and code==0:
        try:final=evaluate(x,w);malformed=len(final["check_vector"])!=CHECK_COUNT
        except Exception:malformed=True
    requests=parse_trace(stdout);status="explicit_timeout" if timed else ("malformed_evaluator" if malformed else ("evaluator_tampering" if tamper else ("completed" if code==0 else "harness_failure")));fs=final["score"] if final and not malformed else None;der=derive_scores(b["baseline_score"],fs)
    toks={f:[getattr(z,f) for z in requests if getattr(z,f) is not None] for f in ("input_tokens","output_tokens","cache_read_tokens","reasoning_tokens")}
    ev={"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"phase":phase,"run_id":run_id,"requested":requested,"resolved":{"provider_model_id":model,"reasoning":reason,"harness":"agy","harness_version":agyver},"started_at":started,"ended_at":now(),"wall_seconds":wall,"exit_code":code,"timed_out":timed,"status":status,"changed_files":changed,"evaluator_tampering":tamper,"prohibited_changed_files":prohibited,"baseline_score":b["baseline_score"],"baseline_check_vector":b["baseline_check_vector"],"final_score":fs,"final_check_vector":final["check_vector"] if final and not malformed else None,"delta_score":der["delta_score"],"normalized_improvement":der["normalized_improvement"],"full_pass":final["full_pass"] if final and not malformed else None,"request_count":len(requests) or None,"request_metric_semantics":telemetry.get("request_metric_semantics"),"tool_event_telemetry":telemetry.get("tool_event_telemetry"),"tool_events":None,"token_metric_semantics":telemetry.get("token_metric_semantics"),"input_tokens":sum(toks["input_tokens"]) if toks["input_tokens"] else None,"output_tokens":sum(toks["output_tokens"]) if toks["output_tokens"] else None,"cache_read_tokens":sum(toks["cache_read_tokens"]) if toks["cache_read_tokens"] else None,"reasoning_tokens":sum(toks["reasoning_tokens"]) if toks["reasoning_tokens"] else None,"task":{"family":x.family,"task_id":x.task_id,"seed":x.seed,"generated_workspace_hash":b["generated_workspace_hash"],"prompt_hash":b["prompt_hash"],"visible_verifier_hash":b["visible_verifier_hash"],"task_spec_hash":b["task_spec_hash"],"allowed_edit_manifest_hash":b["allowed_edit_manifest_hash"]},"stdout_sha256":digest(stdout.encode()),"stderr_sha256":digest(stderr.encode()),"assessment":final}
    ep=evdir/f"{key}.json";ep.write_text(json.dumps(ev,indent=2,sort_keys=True)+"\n");record_task_attempt(conn,run_id,task_id=dbtid,score=fs,public_score=fs,invariant_score=fs,scope_compliant=not tamper,wall_seconds=wall,baseline_score=b["baseline_score"],baseline_check_vector=b["baseline_check_vector"],final_check_vector=ev["final_check_vector"],delta_score=ev["delta_score"],normalized_improvement=ev["normalized_improvement"],evaluator_tampering=tamper,prohibited_changed_files=prohibited,metadata=ev)
    for m in requests:record_request_metric(conn,run_id,m.json())
    record_cost(conn,run_id,billing_mode="subscription",cost_source="unavailable: subscription route",input_tokens=ev["input_tokens"],output_tokens=ev["output_tokens"],cached_input_tokens=ev["cache_read_tokens"],reasoning_tokens=ev["reasoning_tokens"]);finalize_run(conn,run_id,ended_at=ev["ended_at"],status=status,raw_evidence_path=str(ep),raw_evidence_sha256=digest(ep.read_bytes()));return ev
def _rows(root):return [json.loads(p.read_text()) for p in sorted((root/"evidence").glob("*.json"))]
def _discriminates(rows):
    clean=[x for x in rows if x["status"]=="completed" and x["final_score"] is not None]
    return len({tuple(x["final_check_vector"]) for x in clean})>1 or len({x["final_score"] for x in clean})>1 or len({x["full_pass"] for x in clean})>1
def pilot(seed=SEED):
    gate=validate_preflight(require_reference=True,seed=seed)
    if not gate["ok"]:raise RuntimeError("V2.1 no-inference gates failed; pilot not started")
    root=state_root();instances=[make_instance(f,seed+i) for i,f in enumerate(FAMILIES)];baselines={x["family"]:x for x in gate["tasks"]};prov=gate["provenance"];conn=connect();reg=current_registry();validate_registry(reg);agy=next(x for x in reg if x["name"]=="agy");agyver=agy.get("observed_version") or agy["version"]
    for x in instances:_public_artifacts(x,root)
    (root/"discovery.json").write_text(json.dumps({"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"client":"agy","client_version":agyver,"models":[{"provider_model_id":m,"reasoning":r} for m,r in PILOT_CONFIGURATIONS],"phase_a_families":PHASE_A_FAMILIES,"phase_b_families":PHASE_B_FAMILIES},indent=2,sort_keys=True)+"\n")
    hid=record_harness(conn,"agy",version=agyver,adapter_version="benchmark.public_characterization_v21.runner",transport="agy",capabilities=agy["capabilities"],telemetry=agy["telemetry"],eligibility=agy["eligibility"],evidence_label="public_characterization_non_adversarial",observed_at=now());sid,tids=_record_suite(conn,instances,prov,baselines,gate["reference_validation"]["validation_timestamp"]);attempts=[]
    for model,reason in PILOT_CONFIGURATIONS:
        for f in PHASE_A_FAMILIES:
            x=next(y for y in instances if y.family==f);attempts.append(_attempt(conn,sid,tids[x.task_id],x,baselines[f],model,reason,hid,root,agy["telemetry"],agyver,"A"))
    phase_a_discriminates=_discriminates(attempts);phase_b_ran=False
    if phase_a_discriminates and not any(x["status"]!="completed" for x in attempts):
        phase_b_ran=True
        for model,reason in PILOT_CONFIGURATIONS:
            for f in PHASE_B_FAMILIES:
                x=next(y for y in instances if y.family==f);attempts.append(_attempt(conn,sid,tids[x.task_id],x,baselines[f],model,reason,hid,root,agy["telemetry"],agyver,"B"))
    summary={"experiment":SUITE_NAME,"evaluation_class":EVALUATION_CLASS,"suite_git_sha":prov["git_sha"],"seed":seed,"attempts":len(attempts),"phase_a_attempts":6,"phase_b_attempts":len(attempts)-6,"phase_a_discriminates":phase_a_discriminates,"phase_b_ran":phase_b_ran,"completed":sum(x["status"]=="completed" for x in attempts),"evaluator_tampering":sum(x["status"]=="evaluator_tampering" for x in attempts),"malformed_evaluator":sum(x["status"]=="malformed_evaluator" for x in attempts),"harness_failure":sum(x["status"]=="harness_failure" for x in attempts),"explicit_timeout":sum(x["status"]=="explicit_timeout" for x in attempts),"configurations":[list(x) for x in PILOT_CONFIGURATIONS]}
    (root/"run-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n");report(root);return summary
def _plot(rows,path,kind,x,y,xlabel,ylabel):
    obs=[r for r in rows if r["status"]=="completed" and r.get(x) is not None and r.get(y) is not None]
    if not obs:return {"status":"skipped","reason":"no_clean_completed_observations"}
    import matplotlib.pyplot as plt
    labels=[f"{r['resolved']['provider_model_id'].split('-')[1]} {r['resolved']['reasoning'].title()}" for r in obs];plt.figure(figsize=(9,5))
    if kind=="scatter":
        plt.scatter([r[x] for r in obs],[r[y] for r in obs])
        for r,label in zip(obs,labels):plt.annotate(label,(r[x],r[y]),fontsize=8)
    else:plt.bar(labels,[r[y] for r in obs]);plt.xticks(rotation=30,ha="right")
    plt.xlabel(xlabel);plt.ylabel(ylabel);plt.tight_layout();plt.savefig(path);plt.close();return {"status":"created","kind":kind,"observations":len(obs),"labels":labels}
def report(root=None):
    root=(root or state_root()).resolve();rows=_rows(root);fields=["model","reasoning","phase","task","status","baseline_score","baseline_check_vector","final_score","final_check_vector"]+[f"check_{i}" for i in range(1,9)]+["passed_checks","delta_score","normalized_improvement","full_pass","evaluator_tampering","prohibited_changed_files","wall_seconds","input_tokens","output_tokens","cache_read_tokens","reasoning_tokens"]
    with (root/"task-check-matrix.csv").open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader()
        for r in rows:
            v=r["final_check_vector"];w.writerow({"model":r["resolved"]["provider_model_id"],"reasoning":r["resolved"]["reasoning"],"phase":r.get("phase"),"task":r["task"]["family"],"status":r["status"],"baseline_score":r["baseline_score"],"baseline_check_vector":"".join("P" if x else "F" for x in r["baseline_check_vector"]),"final_score":r["final_score"],"final_check_vector":"".join("P" if x else "F" for x in v) if v else None,**{f"check_{i}":("P" if x else "F") if v else None for i,x in enumerate(v or [],1)},"passed_checks":sum(v) if v else None,"delta_score":r["delta_score"],"normalized_improvement":r["normalized_improvement"],"full_pass":r["full_pass"],"evaluator_tampering":r["evaluator_tampering"],"prohibited_changed_files":json.dumps(r["prohibited_changed_files"]),"wall_seconds":r["wall_seconds"],"input_tokens":r["input_tokens"],"output_tokens":r["output_tokens"],"cache_read_tokens":r["cache_read_tokens"],"reasoning_tokens":r["reasoning_tokens"]})
    (root/"task-check-matrix.md").write_text("# Public Characterization V2.1 task x check matrix\n\nC1-C8 are expanded in the CSV. Quality is conditional on clean completed attempts.\n\n"+"\n".join(f"- {r['resolved']['provider_model_id']} / {r['resolved']['reasoning']} / phase {r.get('phase')} / {r['task']['family']}: {r['status']}; baseline {''.join('P' if x else 'F' for x in r['baseline_check_vector'])}; final {''.join('P' if x else 'F' for x in r['final_check_vector']) if r['final_check_vector'] else '—'}; delta {r['delta_score'] if r['delta_score'] is not None else '—'}; tampering {r['evaluator_tampering']}" for r in rows)+"\n")
    grouped={}
    for r in rows:grouped.setdefault((r["resolved"]["provider_model_id"],r["resolved"]["reasoning"]),[]).append(r)
    configs=[]
    for k,g in sorted(grouped.items()):
        clean=[r for r in g if r["status"]=="completed" and r["final_score"] is not None];scored=[r for r in g if r["final_score"] is not None]
        configs.append({"model":k[0],"reasoning":k[1],"attempted":len(g),"completed":len(clean),"tampering":sum(r["status"]=="evaluator_tampering" for r in g),"harness_failure":sum(r["status"]=="harness_failure" for r in g),"explicit_timeout":sum(r["status"]=="explicit_timeout" for r in g),"completion_rate":len(clean)/len(g),"mean_baseline":statistics.mean(r["baseline_score"] for r in g),"quality_on_completed":statistics.mean(r["final_score"] for r in clean) if clean else None,"mean_delta":statistics.mean(r["delta_score"] for r in clean) if clean else None,"median_final":statistics.median(r["final_score"] for r in clean) if clean else None,"full_solves":sum(r["full_pass"] is True for r in clean),"mean_wall":statistics.mean(r["wall_seconds"] for r in g),"input_tokens":sum(r["input_tokens"] or 0 for r in g),"output_tokens":sum(r["output_tokens"] or 0 for r in g),"cache_read_tokens":sum(r["cache_read_tokens"] or 0 for r in g),"reasoning_tokens":sum(r["reasoning_tokens"] or 0 for r in g)})
    (root/"configuration-summary.json").write_text(json.dumps(configs,indent=2,sort_keys=True)+"\n")
    summary=json.loads((root/"run-summary.json").read_text()) if (root/"run-summary.json").is_file() else {}
    lines=["# public-characterization-v2.1","","Class: public_characterization; public, objective, baseline-aware, non-adversarially isolated.","",f"Phase A discrimination: {str(summary.get('phase_a_discriminates')).lower()}. Phase B ran: {str(summary.get('phase_b_ran')).lower()}.","", "| Model | Quality final | Mean delta | Full solves | Completed/attempted | Tampering | Completion | Mean wall | Input/output/cache/reasoning |","|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for c in configs:lines.append(f"| {c['model']} | {c['quality_on_completed']} | {c['mean_delta']} | {c['full_solves']} | {c['completed']}/{c['attempted']} | {c['tampering']} | {c['completion_rate']} | {c['mean_wall']} | {c['input_tokens']}/{c['output_tokens']}/{c['cache_read_tokens']}/{c['reasoning_tokens']} |")
    lines += ["","Quality is conditional on clean scored completion. Infrastructure failures and tampering are separate.","","AGY request semantics: harness_session; tool telemetry: unavailable; tokens: AGY-reported usage, not verified billing.","","No Phase B or repeated sweep is authorized unless Phase A shows configuration-level discrimination."]
    (root/"REPORT.md").write_text("\n".join(lines)+"\n")
    clean=[r for r in rows if r["status"]=="completed" and r["final_score"] is not None];same=bool(clean) and len({tuple(r["final_check_vector"]) for r in clean})==1 and len({r["final_score"] for r in clean})==1
    audit=["# Public Characterization V2.1 audit","","All four baseline variants passed headroom, parity, deterministic-hash, and reference gates before inference.","",f"Phase A clean completed attempts: {sum(r.get('phase')=='A' and r['status']=='completed' for r in rows)}; identical clean final vectors: {str(same).lower()}.", "", "Phase A stop condition: no Phase B was run because Phase A did not show configuration-level discrimination." if not summary.get("phase_b_ran") else "Phase A passed; Phase B ran.", "", "Every evaluator returns exactly eight independent checks. P4 C6 exercises default and non-default codec timeout round trips."]
    (root/"AUDIT_REPORT.md").write_text("\n".join(audit)+"\n")
    plots={"baseline-vs-final":_plot(rows,root/"baseline-vs-final.png","scatter","baseline_score","final_score","baseline score","final score"),"delta-by-configuration":_plot(rows,root/"delta-by-configuration.png","bar","resolved","delta_score","configuration","delta score"),"final-vs-wall":_plot(rows,root/"final-vs-wall.png","scatter","wall_seconds","final_score","wall seconds","final score"),"final-vs-tokens":_plot(rows,root/"final-vs-tokens.png","scatter","input_tokens","final_score","AGY input tokens","final score")};(root/"plot-metadata.json").write_text(json.dumps(plots,indent=2,sort_keys=True)+"\n")
    (root/"telemetry-semantics.md").write_text("# Telemetry semantics\n\nAGY 1.1.25 request metrics are harness_session, not verified provider requests. Tool event telemetry is unavailable, not observable zero.\n")
    (root/"token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning values are AGY-reported usage. Billing equivalence and cumulative/session semantics are not verified.\n")
    return root/"REPORT.md"
def main(argv=None):
    args=argv or sys.argv[1:];action=args[0] if args else "validate"
    if action=="validate":r=validate_preflight(require_reference="--require-reference" in args);print(json.dumps(r,indent=2,sort_keys=True));return 0 if r["ok"] else 1
    if action=="pilot":print(json.dumps(pilot(),indent=2,sort_keys=True));return 0
    if action=="report":print(report());return 0
    raise SystemExit(f"unknown command: {action}")
if __name__=="__main__":raise SystemExit(main())

