# PAYG candidate crossover — August 2026

## Status

**COMPLETE FOR NOW.** Both objective screens (stage 1: `research_python` /
`diagnostic_plot` / `debug_package`; stage 2: `scientific_writing`) and
both blind qualitative reviews (diagnostic-plot, scientific-writing) are
finished and scored; both mappings have been revealed (§11, §15). This is
not a claim of universal conclusiveness — see §16 for what is and is not
supported, and §17 for what would justify a future stage.

This is a selected crossover, not a new tier. It adds three experimental
pay-as-you-go (PAYG) candidates — DeepSeek V4 Pro, DeepSeek V4 Flash, and
MiniMax M3, all routed through the Codex-transport provider-profile
launchers (`codex-deepseek`, `codex-minimax`; see
[PAYG_DELEGATES.md](PAYG_DELEGATES.md)). Stage 1 (§1–§14 below) covers the
three clean Tier A tasks reused unmodified: `research_python`,
`diagnostic_plot`, `debug_package`. Stage 2 (§15) adds the single frozen
`scientific_writing` task, approved specifically because it is the one
existing valid task with demonstrated blind-review discriminating power
(§12/§15). `repository_review` v1 remains excluded per its known evaluator
defect (handbook §6); `pandoc_pdf` was deliberately not run in either
stage. No historical contestant (Terra, Sonnet, Gemini Pro Low, Luna,
Haiku, Flash) was rerun in either stage.

Raw evidence: `runs/payg-crossover-001/` (stage 1),
`runs/payg-stage2-writing-001/` (stage 2). Stage 1 run record:

```text
crossover = payg-candidate-crossover
source_tier_reference = tier-a-medium
```

Stage 2 run record:

```text
crossover = payg-stage2-writing
source_tier_reference = tier-a-medium
```

Two independent blind-review packets were used for this crossover, with
distinct, non-corresponding label sets: the stage-1 diagnostic-plot
packet (`Candidate A/B/C`, §11) and the stage-2 writing packet
(`Writing W1/W2/W3`, §15). Both reviews were scored before either mapping
was revealed; both mappings were confirmed frozen and revealed only after
both sets of scores were in hand.

## 1. Purpose

Screen three new PAYG-billed candidates for basic competence on this
project's existing frozen, routine-work fixtures before considering any
harder or more expensive experiment, and before any consideration of
enabling them as ordinary delegation routes (`delegate-config`). This is a
workflow-fit screen, not a claim about which underlying model is "best."

## 2. Candidates and exact configuration

All three are pinned in `delegation/core.py::DELEGATES` and were launched
exactly as recorded in `runs/payg-crossover-001/run.json` /
`result/execution.json`. Transport CLI version for all three:
`codex-cli 0.147.0`.

| Agent | Provider | Requested model | Reasoning effort | Sandbox | Transport |
|---|---|---|---|---|---|
| `deepseek-pro` | DeepSeek | `deepseek-v4-pro` | `high` | `workspace-write` | `codex-deepseek` |
| `deepseek-flash` | DeepSeek | `deepseek-v4-flash` | `high` | `workspace-write` | `codex-deepseek` |
| `minimax-m3` | MiniMax | `MiniMax-M3` | `high` | `workspace-write` | `codex-minimax` |

Effort is pinned to `high` for both providers: DeepSeek's catalog exposes
low/high/max (no "medium"), and MiniMax's local profile is already pinned
to `high` — neither is an invented setting (see
[PAYG_DELEGATES.md](PAYG_DELEGATES.md)).

**Evidence caveat:** every `execution.json` in this run has
`"observed_model": null`. The runner's `_observed_model()` scans CLI stdout
JSONL for a `model`/`resolved_model`-shaped field; the codex-deepseek and
codex-minimax transports do not directly echo one, so the *requested*
model (recorded verbatim in `command`/`requested_configuration`) is not
independently confirmed by a resolved-model field in the transcript. This
matches the existing precedent for Claude (`benchmark/preflight.py` notes
"Claude CLI exposes no local model-list command"); it is a transport
limitation, not evidence of a substitution.

## 3. Tasks and frozen-input verification

All three tasks are byte-identical to the Tier A/Tier B originals — same
prompt files, same fixtures, same fixture-lock hash.

| Task | Prompt SHA-256 | Fixture SHA-256 |
|---|---|---|
| `research_python` | `9d0c2190bf28e2ab57ba6f11d54ba729b7e5d0bdcc3e1c1ba95578845e244d4e` | `data/observations.csv`: `bf8c0928ddbf1ea55971e3f38c121e734d9ae8ab4dceb74a5e3d3e6620ecf9cf` |
| `diagnostic_plot` | `ae1aaaa72db08f09ab1bf17c96f389487260ce09339752ee7c854749a4389e86` | `data/qc_metrics.csv`: `d5854669e99e24f58557291a92897468ce2b223e260dcdbba6a3574ef0ddffe5` |
| `debug_package` | `203ca7418a4f685ae652eb503581a82987e7e5192b38f25b3e904d3e1d59cf49` | four frozen package/test files verified by the fixture lock |

Whole-lock hash `fixtures.lock.json` = `e1c2deb3d98d7bbd2b3e03456dd70d582966154265ea76829a25bb03dd73fe3c`, identical to the value recorded for Tier A/Tier B in `benchmark_methodology.json`. All hashes above were independently recomputed from the current repository tree for this report, not copied from prior docs.

## 4. Evidence audit

Every one of the nine `result/execution.json` records was inspected directly (not summarized from stdout alone):

- `exit_code: 0` and `execution_status: "completed"` for all nine attempts; `harness_failure_reasons: []`, `interaction_blocked: false`, `permission_denials: []`, `required_output_missing: false` for all nine.
- `runs/payg-crossover-001/` contains exactly the three task directories, `run.json`, `blind/`, and `blind_map.json` — no `unavailable.json`, no stray fourth agent directory, no leftover directory from an earlier smoke/harness attempt.
- Each contestant workspace contains only `TASK.md`, `.benchmark-agent.txt`, the task fixture files, and the contestant's own output — no `private_admin` material, no symlink, no other contestant's output (consistent with the runner's own workspace-isolation preflight check, which passed before this run).
- Deliverables verified present and evaluator-scored: `analysis.py`/`answer.json` (research), `diagnostic.py`/`diagnostic.png`/`summary.json` (plot), modified `calcpack/numbers.py`+`calcpack/text.py` with all five package tests passing (debug).
- `answer.json` is byte-identical across all three candidates (`n: 12, mean_response: 15.25, control_mean: 12.0, treatment_mean: 18.5, difference: 6.5`); `summary.json` is byte-identical across all three (`outlier_sample: "S08", outlier_reason: "low_library_size"`).

**Conclusion: this is a clean, valid, complete run.** No repair, no partial evidence, no harness classification issue found.

## 5. Objective results

| Task | DeepSeek Pro / high | DeepSeek Flash / high | MiniMax M3 / high |
|---|---:|---:|---:|
| `research_python` | 5/5 | 5/5 | 5/5 |
| `diagnostic_plot` | 3/3 | 3/3 | 3/3 |
| `debug_package` | 5/5 | 5/5 | 5/5 |

All nine attempts scored the maximum available point. The `debug_package` fixture seeds four defects (mean denominator, reversed clamp bounds, moving-average off-by-one, trailing-hyphen slug normalization); a direct diff against the fixture confirms all three candidates corrected all four, changed only `calcpack/numbers.py` and `calcpack/text.py` (plus generated bytecode), and added no regression tests — the same minimal-fix pattern seen historically for Luna/Haiku/Flash. DeepSeek Pro used `max(min(value, upper), lower)` for the clamp fix; DeepSeek Flash and MiniMax M3 both used `min(max(value, lower), upper)` — functionally equivalent, a style difference only.

## 6. Timing

Wall-clock time is harness-measured (Python `time.monotonic()` around the subprocess call), not a provider-reported or equal-compute figure.

| Task | DeepSeek Pro | DeepSeek Flash | MiniMax M3 |
|---|---:|---:|---:|
| `research_python` | 21.25 s | 17.62 s | 38.98 s |
| `diagnostic_plot` | 99.80 s | 34.11 s | 44.33 s |
| `debug_package` | 31.09 s | 18.40 s | 25.78 s |
| **Aggregate (sum of raw, unrounded seconds)** | **152.1 s** | **70.1 s** | **109.1 s** |

Note on the Pro aggregate: summing the three *pre-rounded* per-task figures (21.3 + 99.8 + 31.1) gives 152.2 s; summing the raw unrounded `wall_clock_seconds` values from `execution.json` gives 152.15 s, which rounds to 152.1 s. This report uses the value computed directly from raw evidence (152.1 s); the discrepancy is a rounding artifact, not a data disagreement.

DeepSeek Flash was the fastest PAYG candidate in aggregate; DeepSeek Pro was the slowest, driven almost entirely by `diagnostic_plot` (99.8 s vs. 34.1 s / 44.3 s) rather than a uniform per-task slowdown.

## 7. Token usage (provider-reported, via CLI JSONL)

No dollar cost field is present in any of the nine `execution.json` records for any of the three candidates — consistent with the existing pattern for the Codex-transport family locally (Claude is the only CLI in this project that reports a dollar figure). **Distinguishing the three categories requested:**

- **Provider-reported charge:** unavailable — none of the three CLIs emitted one locally.
- **Calculated estimate:** not computed — this repository has no versioned DeepSeek/MiniMax pricing metadata to calculate from, and none was fetched for this report (no provider/API call was made to obtain pricing).
- **Available:** raw token usage, reported per-call by the CLI itself.

| Agent | Task | Input (of which cached) | Output | Reasoning |
|---|---|---:|---:|---:|
| DeepSeek Pro | research | 67,883 (54,144) | 1,222 | 225 |
| DeepSeek Pro | plot | 177,572 (165,248) | 6,925 | 3,440 |
| DeepSeek Pro | debug | 89,247 (85,376) | 2,504 | 130 |
| **DeepSeek Pro total** | | **334,702 (304,768)** | **10,651** | **3,795** |
| DeepSeek Flash | research | 66,794 (58,240) | 1,219 | 216 |
| DeepSeek Flash | plot | 130,924 (126,976) | 2,590 | 617 |
| DeepSeek Flash | debug | 86,404 (82,432) | 1,699 | 611 |
| **DeepSeek Flash total** | | **284,122 (267,648)** | **5,508** | **1,444** |
| MiniMax M3 | research | 378,082 (148,736) | 4,970 | 0 |
| MiniMax M3 | plot | 428,352 (208,000) | 5,736 | 0 |
| MiniMax M3 | debug | 278,580 (242,628) | 1,854 | 769 |
| **MiniMax M3 total** | | **1,085,014 (599,364)** | **12,560** | **769** |

`cache_write_input_tokens` was `0` for all nine calls. MiniMax M3's `input_tokens` is roughly 3–4x DeepSeek's for the same tasks with a substantially lower cached fraction; whether this reflects a different context-construction strategy by the `codex-minimax` transport/profile or by the model itself is not determined by this evidence alone.

## 8. Cost/success metrics

**Dollar cost per attempted/valid/successful task is NOT calculable from current evidence** (§7) — reporting one would require either a provider-reported charge (absent) or a versioned local price table (absent), and this task explicitly required not fabricating one.

Available in token terms, since every attempt here was both valid and successful (9/9, no repair needed, so "attempted," "valid," and "successful" denominators are identical for this run):

| Agent | Total input tokens / successful task | Total output tokens / successful task |
|---|---:|---:|
| DeepSeek Pro | 111,567 | 3,550 |
| DeepSeek Flash | 94,707 | 1,836 |
| MiniMax M3 | 361,671 | 4,187 |

## 9. Comparison with preserved historical evidence

No historical contestant was rerun. All figures below were independently re-derived from the raw `execution.json` files in `runs/tier-a-controlled-001/` and the Tier B composite sources (`tier-b-controlled-001/002/003`, `tier-b-flash-python`, `tier-b-haiku-python-final`), not copied from prior report prose, and matched the previously published figures exactly.

### Tier A (`gpt-5.6-terra` medium / `claude-sonnet-5` medium / `gemini-3.1-pro-low`)

| Task | Terra | Sonnet | Gemini 3.1 Pro Low |
|---|---:|---:|---:|
| `research_python` | 5/5, 31.40 s | 5/5, 19.24 s | 5/5, 62.81 s |
| `diagnostic_plot` | 3/3, 45.89 s | 3/3, 31.64 s | 3/3, 49.43 s |
| `debug_package` | 5/5, 36.53 s | 5/5, 17.02 s | 5/5, 46.13 s |
| **Aggregate** | **113.82 s** | **67.90 s** | **158.37 s** |

### Tier B (`gpt-5.6-luna` medium / `claude-haiku-4-5-20251001` medium / `gemini-3.7-flash-medium`)

| Task | Luna | Haiku | Flash Medium |
|---|---:|---:|---:|
| `research_python` | 5/5, 32.89 s | 5/5, 20.81 s | 5/5, 38.76 s |
| `diagnostic_plot` | 3/3, 59.09 s | 3/3, 34.89 s | 3/3, 25.62 s |
| `debug_package` | 5/5, 37.14 s | 5/5, 33.69 s | 5/5, 64.26 s |
| **Aggregate** | **129.12 s** | **89.39 s** | **128.64 s** |

### PAYG candidates (this run)

| Task | DeepSeek Pro | DeepSeek Flash | MiniMax M3 |
|---|---:|---:|---:|
| `research_python` | 5/5, 21.25 s | 5/5, 17.62 s | 5/5, 38.98 s |
| `diagnostic_plot` | 3/3, 99.80 s | 3/3, 34.11 s | 3/3, 44.33 s |
| `debug_package` | 5/5, 31.09 s | 5/5, 18.40 s | 5/5, 25.78 s |
| **Aggregate** | **152.1 s** | **70.1 s** | **109.1 s** |

**Environment/provider differences are explicit and material, not incidental:** all nine historical Tier A/B contestants above ran through their own native subscription CLI (`codex`/`claude`/`agy`) directly; all three PAYG candidates here ran through the `codex-deepseek`/`codex-minimax` provider-profile relay on top of the Codex CLI transport, on a different machine/session than the original Tier A/B evidence, at a different point in time, against different upstream provider load/latency conditions. **These aggregate wall-clock numbers are not an equal-compute or equal-conditions benchmark of the underlying models** — they are harness-measured wall time for this specific local setup, at this specific time, and should be read as such. In particular, DeepSeek Flash's 70.1 s aggregate being faster than every historical Tier A/B aggregate, and DeepSeek Pro's 152.1 s being slower than Tier B Luna/Flash but faster than Tier A Gemini 3.1 Pro Low, are observations about this run, not portable claims about the models in general.

All twelve contestants (9 historical + 3 PAYG) that attempted these three tasks retained full objective correctness (5/5, 3/3, 5/5). This is now true for every configuration this project has ever run on these three fixtures.

## 10. Objective interpretation

All three PAYG candidates saturated this screen:

```text
research_python     5/5  (all three)
diagnostic_plot      3/3  (all three)
debug_package        5/5  (all three)
```

**Objective quality on this screen cannot currently distinguish DeepSeek V4 Pro, DeepSeek V4 Flash, and MiniMax M3.** This establishes competence on routine, well-specified, small-scope tasks for all three — it does not establish that they are equal models. It is consistent with three distinct hypotheses this screen cannot separate: (a) all three are genuinely close in capability on tasks of this size, (b) all three exceed the difficulty ceiling of these three fixtures, or (c) some combination. Latency, cost (once available), and qualitative output quality remain discriminating dimensions on this screen; harder-task behavior is undetermined and is exactly what §12 proposes to test.

### Cautious per-candidate reading

- **DeepSeek V4 Flash:** very strong first routine-work result — maximum objective score on all three tasks, fastest PAYG aggregate wall time (70.1 s), lowest token usage of the three. Qualitative and cost review still pending; this is not yet evidence that it is "as good as" Pro on harder work.
- **DeepSeek V4 Pro:** also maximum objective score on all three tasks, but materially slower than Flash in aggregate (152.1 s vs. 70.1 s, more than double) on this routine screen, and used ~3x Flash's reasoning-token budget on `diagnostic_plot` specifically (3,440 vs. 617). No demonstrated quality advantage over Flash is established by this screen; a harder discriminating task is needed before any premium (in time or, once known, cost) can be assessed as justified.
- **MiniMax M3:** maximum objective score on all three tasks, intermediate aggregate latency (109.1 s), and notably higher raw input-token consumption (1,085,014 total vs. 334,702 / 284,122 for the two DeepSeek variants) with a lower cached fraction — a potentially useful independent provider/model family for this workflow, worth continued screening, but its token-usage profile is worth understanding better before drawing conclusions about it.

**No permanent routing role is assigned to any of the three from this evidence.** PAYG routes remain disabled for ordinary delegation (§13).

## 11. Qualitative review — complete

Blind diagnostic-plot packet: `runs/payg-blind-packet-20260816/` (see its
`README.md` for the reviewer instructions and scoring criteria that were
used). It contained three anonymously renamed PNGs (`Candidate A/B/C`, no
identifying metadata, timestamps normalized) and no mapping file. The
mapping was generated with a real (OS-entropy) random shuffle, not a
deterministic or alphabetical assignment, and was kept private
(`runs/payg-crossover-001/PACKET_BLIND_MAP.json`) until the independent
reviewer had scored all three candidates, per this project's standing
blind-review protocol (handbook §2, "objective and blind evaluation are
separate"). Scores were frozen before the mapping was revealed.

| Label | Score /10 | Revealed identity |
|---|---:|---|
| Candidate A | 8.5 | MiniMax M3 |
| Candidate C | 8.0 | DeepSeek V4 Flash |
| Candidate B | 7.0 | DeepSeek V4 Pro |

By identity:

| Agent | Blind plot score /10 |
|---|---:|
| MiniMax M3 | 8.5 |
| DeepSeek V4 Flash | 8.0 |
| DeepSeek V4 Pro | 7.0 |

Reviewer's qualitative note: MiniMax M3 produced the strongest diagnostic
plot of the three, with particularly good diagnostic communication and
outlier annotation. DeepSeek V4 Pro's plot was the weakest of the three —
this is a visual/qualitative judgment, distinct from and not contradicted
by its objective 3/3 PNG-validity score (§5), which does not assess visual
quality at all.

This is one anonymized reviewer's scoring of three plots from a tiny
sample — informative, not statistically powered evidence (handbook §11).

## 12. Proposed second-stage benchmark — NOT RUN

Recommendation: run **`scientific_writing`** (already a frozen, valid task
— unlike `repository_review` v1, which is excluded for a hidden-manifest
evaluator defect per handbook §6) against all three PAYG candidates. This
is the smallest useful next experiment, for two evidence-backed reasons:

1. It is the one existing valid frozen task that has already demonstrated
   discriminating power in this project's own history: the historical
   blind review spread from 9.5 (Terra) down to 7.0 (Gemini 3.1 Pro Low)
   on the same rubric, driven specifically by epistemic calibration under
   ambiguous evidence ("does the model claim a benefit the data doesn't
   establish?") — exactly the kind of reasoning-quality axis that a
   routine, easily-specified coding task like the three above cannot
   exercise.
2. It requires no new fixture, evaluator, or manifest work — it reuses
   `tasks/prompts/scientific_writing.md` and its automated-rubric evaluator
   unchanged, keeping this a three-call addition (one per PAYG candidate),
   not a new benchmark suite.

This single task is proposed specifically to discriminate DeepSeek Pro
from DeepSeek Flash (both already tied objectively; Pro's much higher
per-task reasoning-token spend on `diagnostic_plot` is a testable
hypothesis for whether it also produces more careful, better-calibrated
prose) and to test whether MiniMax M3 remains competitive once the task
requires calibrated judgment rather than a single deterministic correct
answer.

`pandoc_pdf` is deliberately **not** proposed alongside it: its historical
blind review showed only minor visual differences across four candidates
(8.0/8.0/8.0/7.5) and is a build/tooling-reproducibility check more than a
reasoning discriminator, so it would add less information per paid call
than `scientific_writing`. A corrected `repository_review_v2` is a
reasonable future option but is explicitly out of scope for "the smallest
useful next experiment" — it requires first repairing the seeded-issue
manifest/evaluator, which is separate work, not a three-call addition to
an existing valid task.

**Do not run this without first re-verifying no-model preflight and
obtaining explicit approval, per the standing PAYG launcher protocol
(`scripts/run-payg-crossover.sh`).**

## 13. Prior incidents — explicitly excluded from this run's evidence

Two unrelated infrastructure incidents occurred in earlier sessions of
this project and are called out here only to state clearly that neither
affects the evidence in this report:

- **Bubblewrap/AppArmor sandbox failure.** An earlier session on this
  machine hit a `bwrap` user-namespace failure caused by Ubuntu's
  `kernel.apparmor_restrict_unprivileged_userns` sysctl folding
  unconfined `bwrap` invocations into a restrictive generic profile. It
  was resolved by enabling Ubuntu's packaged, application-specific
  `bwrap-userns-restrict` AppArmor profile (documented in
  [NEW_MACHINE_SETUP.md](NEW_MACHINE_SETUP.md), §"AppArmor-restricted
  unprivileged user namespaces"), confirmed working (`bwrap
  --unshare-net --dev /dev --ro-bind / / /bin/true` exits 0, `aa-status`
  lists both `bwrap` and `unpriv_bwrap`, no fresh `DENIED` events). All
  nine PAYG calls in this run completed normally through the same Codex
  sandbox transport, which is direct evidence the fix held; it is not
  itself benchmark evidence about any candidate model.
- **Accidental `agy models` model call.** A separate, unrelated
  infrastructure incident: a discovery/version/help probe inside
  `delegation.preflight`/`benchmark.preflight` was found to inherit
  caller stdin, and piped stdin content once caused `agy models` (the
  *Antigravity/Gemini Flash* discovery check, unrelated to DeepSeek/
  MiniMax) to make a live conversational reply instead of listing
  models. This was fixed by isolating that subprocess's stdin
  (`stdin=subprocess.DEVNULL`; see
  [DELEGATION_FAILURE_MODES.md](DELEGATION_FAILURE_MODES.md)). It
  involved no PAYG contestant, no `runner.py run`, and is unrelated to
  the results in this report; it is noted here only for completeness,
  as instructed.

## 14. Fairness and security caveats

- No PAYG candidate accessed `private_admin/`, another contestant's
  workspace, or a symlink — confirmed both by the runner's own
  workspace-isolation preflight (passed before this run) and by direct
  inspection of each retained workspace (§4).
- This is a single attempt per candidate per task (project-wide "one
  attempt" rule, handbook §2); a wrong/incomplete answer would have stood
  as performance evidence rather than being silently retried. All nine
  happened to be correct.
- Objective `diagnostic_plot` evaluation verifies PNG validity and the two
  `summary.json` fields only, not visual quality — §11's pending blind
  review is required before any aesthetic/usability claim.
- This remains a tiny synthetic sample (three tasks, one attempt each,
  same machine/session/time window) with no statistical power, per the
  project's standing limitations (handbook §11). It measures fit for this
  specific workflow, not general model capability.

## 15. Second stage: scientific_writing

**STATUS: OBJECTIVE SCREEN COMPLETE; QUALITATIVE (BLIND) REVIEW PENDING.**

This is the second-stage experiment proposed in §12, approved and run as a
single, separate, additional benchmark — not a rerun or extension of
stage 1. It ran exactly one frozen task (`scientific_writing`) against
exactly the same three PAYG candidates, exactly one attempt each (3 paid
calls total). `research_python`, `diagnostic_plot`, `debug_package`,
`pandoc_pdf`, `repository_review`, and every historical contestant were
correctly **not** rerun. No third-stage task was run.

Raw evidence: `runs/payg-stage2-writing-001/`. Run record:

```text
crossover = payg-stage2-writing
source_tier_reference = tier-a-medium
```

### Configuration (identical to stage 1, re-verified for this run)

| Agent | Provider | Requested model | Reasoning effort | Sandbox | Transport |
|---|---|---|---|---|---|
| `deepseek-pro` | DeepSeek | `deepseek-v4-pro` | `high` | `workspace-write` | `codex-deepseek` |
| `deepseek-flash` | DeepSeek | `deepseek-v4-flash` | `high` | `workspace-write` | `codex-deepseek` |
| `minimax-m3` | MiniMax | `MiniMax-M3` | `high` | `workspace-write` | `codex-minimax` |

No substitution occurred (no "Pro Max," no silent model change) —
confirmed directly from each `execution.json`'s `command` and
`requested_configuration` fields, matching `run.json` exactly. The same
`observed_model: null` transport-limitation caveat noted in §2 applies
here too.

### Evidence audit

All three `result/execution.json` records show `exit_code: 0`,
`execution_status: "completed"`, `harness_failure_reasons: []`, no
permission denials, no missing required output. `runs/payg-stage2-writing-001/`
contains exactly one task directory (`scientific_writing`) with exactly
three agent subdirectories — no stray fourth entry, no other task
directory. Each `RESULTS_DISCUSSION.md` was produced inside its own
isolated workspace containing only the task fixtures
(`data/evidence.csv`, `study_context.md`) and `TASK.md` — no
`private_admin` material, no other contestant's output. **Clean, valid,
complete run — same conclusion as stage 1's evidence audit (§4).**

Frozen-input verification: `tasks/prompts/scientific_writing.md` SHA-256
`cfa1f4cd4f6ad3b9965678e40a63ce1fd2c9cbf081b53cd27652f04a4ec50f83` and both
fixture files' hashes were independently recomputed for this stage and
matched `fixtures.lock.json` and the historical Tier A/Flash-crossover
record exactly — the task contract and evidence given to these three PAYG
candidates is byte-identical to what Terra, Sonnet, Gemini 3.1 Pro Low,
and Gemini 3.7 Flash Medium received.

### Objective results, timing, and usage

| Agent | Score | Wall time | Input (of which cached) | Output | Reasoning |
|---|---:|---:|---:|---:|---:|
| DeepSeek Pro | 6/6 | 26.35 s | 69,297 (66,176) | 1,616 | 301 |
| DeepSeek Flash | 6/6 | 15.07 s | 66,980 (64,128) | 1,036 | 154 |
| MiniMax M3 | 6/6 | 28.04 s | 206,254 (170,898) | 2,218 | 0 |

All three scored the maximum rubric point (6/6: separate Results/Discussion
sections present, and the effect estimate, both means, CI, p-value, and a
limitation all correctly stated). As in stage 1, **cost is unavailable**:
no dollar figure was reported by either transport CLI, and no versioned
DeepSeek/MiniMax pricing metadata exists in this repository to calculate
one — this is stated as "unavailable," not estimated.

DeepSeek Flash was again the fastest of the three; MiniMax M3 again used
substantially more input tokens (≈3x DeepSeek's, with a lower cached
fraction) than either DeepSeek variant, consistent with the pattern
observed in stage 1 (§7).

### Historical comparator (re-verified from raw evidence, not rerun)

| Configuration | Objective score | Wall time |
|---|---:|---:|
| Codex Terra / medium | 5/6 | 25.09 s |
| Claude Sonnet / medium | 5/6 | 11.64 s |
| Gemini 3.1 Pro Low | 6/6 | 95.98 s |
| Gemini 3.7 Flash Medium | 6/6 | 33.50 s |
| DeepSeek V4 Pro / high (this stage) | 6/6 | 26.35 s |
| DeepSeek V4 Flash / high (this stage) | 6/6 | 15.07 s |
| MiniMax M3 / high (this stage) | 6/6 | 28.04 s |

All figures above were re-derived directly from each source run's raw
`execution.json`/`evaluation.json` (`runs/tier-a-controlled-001/` for
Terra/Sonnet/Gemini 3.1 Pro Low, `runs/flash-crossover-scientific-writing/`
for Gemini 3.7 Flash Medium), not copied from prior report prose, and
matched the previously published figures exactly. As with stage 1, this is
not an equal-compute or equal-conditions comparison — different CLIs,
machines, sessions, and time windows.

All three PAYG candidates matched the objective ceiling already reached by
Gemini 3.1 Pro Low and Gemini 3.7 Flash Medium here, and exceeded Terra's
and Sonnet's 5/6 (both of which historically omitted one required rubric
token). **The automated rubric only checks for the presence of specific
values/section headers, not calibration or overclaiming** — exactly the
axis this stage's blind review (below) is required to assess before any
quality claim is made. Objective score alone does not distinguish the
three PAYG candidates from each other, or from Gemini 3.1 Pro Low / Flash
Medium, on this stage either.

### Qualitative review — complete

Blind writing-review packet: `runs/payg-writing-blind-packet-20260816/`
(see its `README.md` for the common task/evidence brief given to every
contestant and the reviewer scoring criteria that were used). It contained
three anonymously labelled files (`Writing W1/W2/W3` — deliberately
distinct from the stage-1 plot packet's `Candidate A/B/C` labels, so the
two cannot be confused or cross-referenced), each containing one
candidate's `RESULTS_DISCUSSION.md` verbatim, with file timestamps
normalized and no provider/model/timing/token/path metadata included. No
historical contestant's response was included in the packet. The mapping
was generated with a real (OS-entropy) random shuffle and was kept private
(`runs/payg-stage2-writing-001/WRITING_BLIND_MAP.json`) until the
independent reviewer had scored all three candidates and the stage-1 plot
review was also frozen. Scores were frozen before the mapping was revealed.

| Label | Score /10 | Revealed identity |
|---|---:|---|
| Writing W1 | 9.5 | DeepSeek V4 Flash |
| Writing W3 | 9.0 | DeepSeek V4 Pro |
| Writing W2 | 8.5 | MiniMax M3 |

By identity:

| Agent | Blind writing score /10 |
|---|---:|
| DeepSeek V4 Flash | 9.5 |
| DeepSeek V4 Pro | 9.0 |
| MiniMax M3 | 8.5 |

Reviewer's qualitative note: DeepSeek V4 Flash's submission was the
strongest of the three — excellent causal restraint and evidence
calibration, and it directly engaged with the width of the confidence
interval rather than just restating it. DeepSeek V4 Pro was also
scientifically strong and restrained. MiniMax M3's writing remained good
but used slightly more interpretive wording than the other two, and was
notably the most token-hungry of the three on this task (§7 pattern
repeated here — see the objective table above).

This confirms the automated rubric's blind spot flagged in the section
above: all three scored 6/6 objectively, but the blind review separates
them meaningfully on calibration and restraint — exactly the axis the
rubric cannot see. This remains one anonymized reviewer's scoring of a
tiny sample (handbook §11).

### Stopping rule confirmation

Per the approved scope for this stage: no `pandoc_pdf`, no
`repository_review`/`repository_review_v2`, no "Pro Max" or alternate
reasoning-effort variant, no implementation task, and no third-stage
benchmark was run. Exactly three new paid contestant calls were made in
total for this stage.

## 16. Final interpretation and routing recommendation

Combining both objective screens (§5, §15) and both now-revealed blind
reviews (§11, §15): all three candidates matched each other on every
objective check across both stages (13/13 routine, 6/6 writing, for all
three). The blind reviews are what actually separate them, and they
separate consistently with the timing/token evidence already reported.

**DeepSeek V4 Flash / high** is, on this evidence, the strongest
general-purpose PAYG candidate of the three tested. It has maximum
objective correctness across both stages, the fastest aggregate time in
both the routine screen (70.1 s) and the writing screen (15.07 s), the
best blind scientific-writing score (9.5/10), a strong (second-place,
8.0/10) blind plot score, and substantially lower token consumption than
MiniMax on the writing task. This supports considering it for routine
coding, debugging, repository analysis, plotting/data work, scientific
drafting, bounded reasoning, and independent review — **once explicitly
enabled by the user** (§18). It is not evidence that Flash is globally
equivalent to a frontier model, and this is a two-task, single-attempt,
single-reviewer sample (handbook §11).

**MiniMax M3 / high** is, on this evidence, a credible independent PAYG
alternative — maximum objective correctness across both stages and the
best blind diagnostic-plot score (8.5/10), with particularly good
diagnostic communication/outlier annotation. It was slower than Flash in
both stages and used substantially more input tokens on the writing task
(with a lower cached fraction), and scored slightly lower than Flash and
Pro on blind writing calibration. This supports it as a useful choice
specifically for plotting/visual diagnostics, implementation alternatives,
second opinions, and provider/model diversity, rather than as a default.

**DeepSeek V4 Pro / high** remains, on this evidence, a specialist/
experimental route rather than a routine default. It matched Flash and
MiniMax objectively on both stages and scored well on blind writing
(9.0/10, scientifically restrained), but was materially slower than Flash
on the routine screen (152.1 s vs. 70.1 s aggregate) and scored lowest of
the three on the blind plot review (7.0/10). **Current evidence does not
justify preferring Pro over Flash for routine delegated work.** It remains
worth keeping available for genuinely difficult tasks this small screen
cannot exercise — architecture reasoning, subtle numerical reasoning,
difficult cross-file debugging, adversarial review, complex scientific
reasoning — but that use case has not itself been tested, and a synthetic
benchmark should not be run merely to justify choosing Pro (§17).

These findings **supplement, not replace**, this project's existing
evidence-based routing (`docs/DELEGATION_POLICY.md`): Gemini 3.7 Flash
Medium remains a proven, subscription/quota-backed cheap delegate; Claude
Sonnet/Haiku and Codex Terra/Luna retain their existing roles. PAYG routes
are metered, opt-in, disabled-by-default capacity, not a replacement for
those routes, and should not be mechanically preferred for every task
merely because DeepSeek Flash won this crossover — task fit, native-vs-
external routing, verification cost, provider diversity, subscription
quota, and PAYG spending all remain relevant per-task considerations (see
`docs/DELEGATION_POLICY.md` for the updated guidance this evidence now
informs).

## 17. Benchmark status: complete for now

This PAYG crossover experiment is **complete for now** — routine crossover
complete, scientific-writing discriminator complete, blind plot review
complete, blind writing review complete. It is not being declared
universally conclusive: it is a tiny, single-attempt, single-reviewer,
two-task sample on one machine at one point in time (handbook §11).

No further PAYG benchmarking is approved by this record. A future stage
should be triggered by a real operational decision need — for example,
"is DeepSeek Pro worth using for genuinely difficult work Flash may fail
at?" — rather than run automatically or speculatively. If that need
arises, follow the same protocol used for both stages here: smallest
useful next experiment, no-model preflight first, explicit human
confirmation immediately before any paid call, and a fresh, immutable run
label.

## 18. Fresh-install and current-machine defaults

Completing this benchmark changes **routing knowledge, not spending
permission**. All three PAYG routes (`deepseek-pro`, `deepseek-flash`,
`minimax-m3`) remain **disabled by default** on a fresh install of this
project, and this record does not enable any of them — enabling a route is
always an explicit, per-machine `delegate-config` action taken by the user
who will pay for it, never something this repository or an agent does
automatically. See `docs/DELEGATE_CONFIGURATION.md` for the enable/disable
commands.
