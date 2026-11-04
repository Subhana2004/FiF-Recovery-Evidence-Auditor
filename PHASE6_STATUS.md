# Phase 6: publication and real-run feasibility

**Audit date:** 2026-11-04. **Pinned upstream source:** [`joohyung00/failure_is_feedback` at `990c068358126ed39ec9a345ac5932bc37cace5f`](https://github.com/joohyung00/failure_is_feedback/tree/990c068358126ed39ec9a345ac5932bc37cace5f). This independent repository does not modify upstream.

## Publication gate

The Phase 5 paired-output checker, synthetic fixture, regression tests, and sample report were reviewed and integrated on a feature branch. The original kit had a false unconditional `memory.tool_usage` presence check. That check now inspects the field, and malformed history or final IDs fail the consistency verdict. The example report is illustrative: its relative file paths are normalized for display, while an actual CLI report contains checkout-specific absolute paths; its SHA-256 hashes refer to the committed synthetic files.

Local checks on Python **3.12.14**: **30/30** synthetic unit/regression tests passed; the synthetic recovery demo passed; the synthetic pair checker exited 0 and reported internal consistency with `authentic_fif_execution_verified: false`; `compileall` passed; six upstream `to_dict` key contracts passed a source-only AST check; `git diff --check` passed. These are local checks, not a claim that GitHub CI has passed. PR and CI status must be verified on GitHub before merge.

## Genuine execution prerequisites and evidence

| Prerequisite | Source evidence | Status in this workspace / decision |
| --- | --- | --- |
| Benchmark corpus and query split | Upstream [`download_datasets.sh`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/scripts/lcg_construction/download_datasets.sh) names public [`multimodalqa_doc`](https://huggingface.co/datasets/JoohyungYun/multimodalqa_doc) and [`mmcoqa_doc`](https://huggingface.co/datasets/JoohyungYun/mmcoqa_doc); the public [`webqa_doc`](https://huggingface.co/datasets/JoohyungYun/webqa_doc) also exists. | Public source corpora exist, but none has been fetched or prepared locally. The script's comment saying WebQA is not on Hugging Face is stale relative to the public listing. A raw/preparsed corpus alone is not a finished FiF index. |
| Layered graph and seven matching embedding pairs | Upstream [README](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/README.md) and [`IndexerServer._init_indexers`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/data_structure/indexer/server.py) require `document_title`, `text`, `table`, `image`, `sentence`, `table_segment`, `subimage` `.pt`/`.json` pairs. The server can rebuild `graph.pickle` from prepared graph files. | The pinned repository checkout and this workspace contain no graph cache or embedding shards. We found no confirmed downloadable set of ready-to-run index artifacts. Building them would require the full preprocessing and embedding pipeline, outside the budget of a minimal trace run. |
| Indexer | The upstream server loads all seven embedding pairs before serving retrieval. [`NodeIndexer.create_index`](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/algorithm/fif/data_structure/indexer/node_indexer/local.py) and edge/tree indexers have CPU fallback; the published example uses CUDA. | CPU fallback means GPU is not an absolute code-level prerequisite. It does not remove the artifact, memory, and compute requirements. No indexer was launched because it cannot initialize without the embeddings. |
| Embedding and reasoning models | Default [FiF config](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/config/algorithm/fif/retriever_agentic_naive.yaml) selects `mmembed` and `chatgpt5`; [model registry](https://github.com/joohyung00/failure_is_feedback/blob/990c068358126ed39ec9a345ac5932bc37cace5f/src/model/mllm/registry.py) also lists local Qwen variants. | The default reasoning path uses an API client and would violate the ₹0/no-paid-API constraint. An alternative local backbone changes the run configuration and still needs model assets and sufficient hardware. No inference was invoked and no charges occurred. |

**Execution verdict: blocked before query execution.** There was no defensible 1–3-query FiF run in this environment. No genuine `details/*.json` or companion `.jsonl` was produced, so real-trace parser compatibility, paired-output parity on authentic runs, and actual recovery utility remain **unverified**. A synthetic consistency pass must never be described as a real FiF outcome. No paid API, GPU job, or model training was used.

## Reproduce the checks

From this repository root, with Python 3.10 or 3.12:

```bash
python -m unittest discover -s tests -v
python -m examples.demo
python validate_trace_pair.py examples/SYNTHETIC_details_1.json examples/SYNTHETIC_run.jsonl
python -m compileall -q fif_recovery_auditor.py validate_trace_pair.py examples tests
python -m tests.upstream_contract /path/to/pinned/failure_is_feedback
```

The last check requires a local upstream checkout at the pinned commit and validates six serialization keys statically. The fixture checker should report `internal_consistency_passed: true` and `authentic_fif_execution_verified: false`. It reports two final IDs and one serialized retrieval attempt for the **synthetic example only**. Paths in its output are absolute and environment dependent. No benchmark number or scientific finding is inferred from these checks.

## Contribution and next validation step

The tool adds a narrow per-transition signal: after an explicitly failed evaluator decision, it distinguishes newly selected IDs from previously selected IDs while showing recorded action and usage. Existing FiF aggregate efficiency and accuracy evaluations do not directly report that transition (see [VALIDATION.md](VALIDATION.md)). This is a plausible debugging aid, not demonstrated real-run utility or novelty. A researcher could reject its usefulness after examining authentic traces.

The smallest decisive next input is an authorized, unmodified FiF `details/<index>.json` and companion run JSONL with matching `qid`, plus provenance (upstream commit and run settings). Run both tools, compare the original aggregate fields and manually inspect a failed-to-next-attempt transition. If no such files are available, a free real run first requires prepared graph/embedding artifacts and an independently feasible no-cost inference setup. Do not substitute fabricated outputs for those inputs.
