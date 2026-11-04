# Source audit, verification, and usefulness gate

**Original source:** [joohyung00/failure_is_feedback](https://github.com/joohyung00/failure_is_feedback) at commit `990c068358126ed39ec9a345ac5932bc37cace5f` (2026-11-04 inspection). No upstream files were changed.

## Serialization and action mapping

| Source at pinned commit | Audited behavior | Implementation choice |
| --- | --- | --- |
| [`fif_retriever.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/fif_retriever.py) lines 430–630 | Initial retrieval has no action decision; subsequent loop records `stop`, `replan`, `retry`, or search; final rerank is appended as another step; details written to `details/<qidx>.json`. | Initial/search/retry with a component result count as retrievals; stop/replan and mode `rerank` do not. |
| [`memory.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/data_structure/memory.py) `to_dict` and `aggregate_usage` | Saved memory uses `tool_usage`, not legacy `steps`; usage is aggregated from serialized agent stages. | Parse only `memory.tool_usage`; never add `agent_usage` to stage usage. |
| [`tool_usage_iteration.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/data_structure/tool_usage_iteration.py) | Serializes an `action_decisions` list, `retrieval_subtask`, and `retrieval_result`. | Use latest decision to describe action; list all decisions for observed usage. |
| [`action_decision.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/data_structure/action_decision.py) | Serializes `next_action`, `anchor`, `retrieval_task`, requested search modes, time, and API usage. | Preserve requested anchor/modes, with no claim they were effective. |
| [`retrieval_result.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/data_structure/retrieval_result.py) | Serializes selected components as `[[fn,cid],score]`, evaluator `updated_subtasks`, candidate/selected modes and nested usage. | Compare stable pairs. Require explicit `answerability` false to flag a failed predecessor; never infer quality from novelty. |
| [`output.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/model/mllm/data_structure/output.py) and [`time_usage.py`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/data_structure/time_usage.py) | API usage has model, tokens, cached tokens, estimated USD; time has embedding, vector search, LLM reasoning. | Preserve zero vs missing and annotate partial sums. No fabricated prices. |

The original `retry` path derives anchor documents from the previous result, even if its serialized decision has a null anchor. `search` uses its decision anchor as a zero-based step index via `_get_anchor_docnames`. Do not equate null retry anchor with no backtracking. The original `RetrievalResult.evaluation_status` can return “not answerable” for an empty evaluator list; this tool deliberately treats that as unknown to avoid claiming a known failed retrieval without an explicit recorded false value.

## Existing analysis versus this diagnostic

| Existing public tool | What it already provides | Narrow extra signal here |
| --- | --- | --- |
| [`EfficiencyEvaluatorV2`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/evaluator/evaluator/efficiency.py) and [efficiency visualizer](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/evaluator/visualizer/efficiency.py) | Run/question aggregate time, calls, tokens, cost. | Align evidence overlap and usage to each saved recovery step. |
| [retrieval accuracy evaluator](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/evaluator/evaluator/retrieval_accuracy.py) | Accuracy against benchmark relevance labels. | Local ID-set transitions; no competing accuracy metric. |
| Repetition, noisy-graph and budget [experiment scripts](https://github.com/joohyung00/failure_is_feedback/tree/990c068358126ed39ec9a345ac5932bc37cace5f/scripts/experiment/fif) | Repeated runs, perturbations, cost constraints. | Inspect a particular trace's transition after evaluator failure. |
| [Algorithm visualization](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/failure_is_feedback/visualization.html) | Static process explanation. | Structured per-step CSV/JSON and review locations. |

**Usefulness judgment:** A synthetic pair with the same step count and same serialized usage but 0 versus 1 new selected ID in its retry proves the report contains a distinction aggregate usage alone cannot show. It does **not** prove real-world frequency, a FiF defect, wasted costs, better retrieval, or scientific novelty. The practical benefit is plausible for post-run diagnosis, conditional on validation with a real trace and a researcher finding this distinction relevant.

## Data provenance and reproducible checks

No actual `details/*.json` files appeared in the pinned public repository tree, GitHub code search, or public releases; the official README describes how a local run would generate them. Public project pages searched did not provide a trace download. We did **not** run FiF's dataset/indexer/LLM pipeline. Thus real-run compatibility is **unverified**; all reported counts below are from source-shaped synthetic fixtures.

```bash
python -m unittest discover -s tests -v
python -m examples.demo
python -m compileall -q fif_recovery_auditor.py examples tests

git clone https://github.com/joohyung00/failure_is_feedback.git ../failure_is_feedback
git -C ../failure_is_feedback checkout 990c068358126ed39ec9a345ac5932bc37cace5f
python -m tests.upstream_contract ../failure_is_feedback
```

Local results (2026-11-04): **21 synthetic tests passed**, synthetic demo assertions passed, `compileall` passed, and **six original `to_dict` source contracts** passed the optional AST check. The AST check validates field presence without importing FiF or executing a real retrieval; it cannot establish runtime compatibility.

Adversarial tests cover false versus unknown evaluator status, repeated and new IDs, deliberate reuse after an answerable step, replan/stop/rerank exclusion, malformed records/components, zero versus missing cost, multiple decisions and queries, empty history, numeric versus string IDs, CLI/CSV/JSON round trip, anchor and mode changes.

## Limits and next validation gate

The tool sees selected IDs, not content relevance or unselected candidates. A changed subquery can make repeated IDs useful. Step usage is a sum of available serialized fields, not a bill or causal attribution of value. `observed_llm_calls` counts nondefault usage entries and may differ from upstream aggregate counting or provider records; missing usage is flagged. Source formats may change after the pinned commit. Reports can contain private question text/IDs in JSON.

**Before research outreach:** obtain a genuine FiF-produced `details/*.json`, run this CLI on it, compare reconstruction against the original run's own evaluation/usage outputs, and review at least one transition with task context. Until then, present this as an independent engineering prototype with demonstrated synthetic information gain only.
