# FiF Recovery Evidence Auditor

An independent, offline diagnostic for saved `details/*.json` trajectories from [Failure is Feedback (FiF)](https://github.com/joohyung00/failure_is_feedback). It aligns **an explicit evaluator failure** with the next retrieval attempt and reports newly selected vs previously selected component IDs, actions, requested anchor, observed modes, and available step usage. It does not score relevance, infer whether reuse was useful, or change FiF.

**Validation status:** source contract and synthetic tests pass; no genuine FiF-generated detail file was publicly available to validate real-run compatibility. Treat this as a cautious engineering prototype, not a research result or an official FiF analysis tool.

## Run

Python 3.10+ standard library; no installation, API key, GPU, or model training.

```bash
python fif_recovery_auditor.py /path/to/run/details
python fif_recovery_auditor.py /path/to/run --json-out report.json --csv-out steps.csv
python fif_recovery_auditor.py /path/to/run/details/0.json
python validate_trace_pair.py /path/to/run/details/0.json /path/to/run/run_name.jsonl --report pair_report.json

python -m unittest discover -s tests -v
python -m examples.demo
```

`path` can be a detail JSON, its `details/` folder, or the run parent containing `details/`. Reports must be saved outside the input details directory and never modify input traces. JSON includes query strings and component IDs from inputs; keep reports private if those fields are sensitive. CSV has one row per serialized step. The CLI returns 2 if any supplied file fails to parse, and 0 otherwise. A review flag by itself is **not** a failing scientific verdict.

`validate_trace_pair.py` is an optional read-only check for one detail JSON and its companion run JSONL. It compares the unique `qid`, ordered final IDs, and copied `agent_usage`, and records SHA-256 hashes. Exit status is 0 for internal consistency, 1 for a mismatch, and 2 for malformed input. A pass cannot authenticate the files or prove FiF retrieval quality. Its `--report` path must differ from both input paths.

## Synthetic demonstration

`python -m examples.demo` creates two source-shaped temporary details with identical usage fields. Both begin with selected IDs `A/p1, B/p2` and an explicit false `answerability`. The next retry selects:

| Synthetic case | Newly selected | Previously selected | Diagnostic |
| --- | ---: | ---: | --- |
| repeat | 0 | 2 | Candidate repeated-evidence episode for manual review |
| changed | 1 | 1 | No repeated-only flag |

The demo asserts these differences and equal recorded usage. **These are synthetic fixture values, not FiF experiment outcomes.**

The paired-output fixture is also explicitly synthetic:

```bash
python validate_trace_pair.py examples/SYNTHETIC_details_1.json examples/SYNTHETIC_run.jsonl
```

An illustrative report is in `examples/SYNTHETIC_consistency_report.json`; the actual CLI prints absolute paths in your checkout. See [PHASE6_STATUS.md](PHASE6_STATUS.md) for the real-run feasibility gate and [VALIDATION.md](VALIDATION.md) for source parity.

## Interpretation

- An attempt is a saved retrieval result with an `initial`, `search`, or `retry` action. `replan` and `stop` records do not count as retrievals. `component_result.mode == "rerank"` is excluded from attempt and novelty counts, but its usage remains visible.
- Component identity is the pair `(document_name, component_id)` from `[[doc,id],score]`; scores and display text do not define novelty. `new` means **new among selected IDs in this saved query's earlier retrieval steps**. It does not include unseen candidates or prove relevance.
- A failed predecessor requires an explicit false `answerability` in `evaluator_result.updated_subtasks` and no true entry. Missing status is unknown. `final_status` is shown for context but is not sufficient proof for our flag.
- A repeated-only episode is flagged for review only after such a failed predecessor and a subsequent `search` or `retry` with valid nonempty selected IDs. Reusing good evidence can be correct. Query, anchor, modes, and task semantics require manual inspection.
- Usage fields are observed sums of serialized leaves in each step (subtask prediction, every decision, candidate generator, component searcher, evaluator). Missing fields are listed and the estimate is marked incomplete. A zero serialized cost is a real observed zero; a missing cost is unknown. Observed nondefault API-usage entries are a call proxy, not a verified billing total. FiF's own `agent_usage` aggregate is not added again.
- `search`'s `anchor` is a requested index into earlier saved steps. `retry` obtains prior document anchors implicitly in upstream code, so `anchor: null` in a retry does not mean no backtracking occurred. Recorded modes distinguish requested and actual candidate/component modes.

## Scope and credit

The code was checked against original [FiF commit `990c068`](https://github.com/joohyung00/failure_is_feedback/tree/990c068358126ed39ec9a345ac5932bc37cace5f). See [VALIDATION.md](VALIDATION.md) for source mapping, existing-tool comparison, exact tests, and gaps. Original research: Joohyung Yun, Doyup Lee, and Wook-Shin Han, *Failure is Feedback: History-Aware Backtracking for Agentic Traversal in Multimodal Graphs* (ICML 2026). This independent project is not affiliated with or endorsed by the authors.
