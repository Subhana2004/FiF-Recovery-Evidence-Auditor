"""Check source-level serialization keys against a pinned original FiF checkout.

No FiF runtime imports or paid APIs. This checks structure, not genuine trace
compatibility. Usage: python -m tests.upstream_contract /path/to/failure_is_feedback
"""
import ast
import sys
from pathlib import Path


ROOT = "src/algorithm/fif/failure_is_feedback/data_structure"
CONTRACTS = {
    ("memory.py", "RetrievalMemory"): {"subtasks", "subtask_plans", "tool_usage"},
    ("tool_usage_iteration.py", "ToolUsageIteration"): {
        "action_decisions", "retrieval_subtask", "retrieval_result"},
    ("action_decision.py", "ActionDecision"): {
        "next_action", "anchor", "retrieval_task", "document_search_mode",
        "component_search_mode", "time", "api_usage"},
    ("retrieval_result.py", "RetrievalResult"): {
        "subquery_task", "final_status", "candidate_result", "component_result", "evaluator_result"},
    ("retrieval_result.py", "ComponentSearcherResult"): {
        "mode", "selected_components", "time", "api_usage"},
    ("retrieval_result.py", "EvaluatorResult"): {"updated_subtasks", "next_parameters", "time", "api_usage"},
}


def returned_keys(path: Path, class_name: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == class_name)
    fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "to_dict")
    returns = [x.value for x in ast.walk(fn) if isinstance(x, ast.Return)]
    literals = [x for x in returns if isinstance(x, ast.Dict)]
    if len(literals) != 1:
        raise AssertionError(f"{path}:{class_name} to_dict return changed")
    return {x.value for x in literals[0].keys if isinstance(x, ast.Constant) and isinstance(x.value, str)}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m tests.upstream_contract /path/to/failure_is_feedback")
    upstream = Path(sys.argv[1]).resolve()
    for (filename, class_name), required in CONTRACTS.items():
        actual = returned_keys(upstream / ROOT / filename, class_name)
        missing = required - actual
        if missing:
            raise AssertionError(f"{class_name}: missing {sorted(missing)}")
    print(f"PASS: {len(CONTRACTS)} upstream to_dict key contracts present (source only)")


if __name__ == "__main__":
    main()
