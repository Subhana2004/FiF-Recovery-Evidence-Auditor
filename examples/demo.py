"""Synthetic, source-shaped comparison with equal usage and different evidence."""
import json
import tempfile
from pathlib import Path

from fif_recovery_auditor import format_text, inspect_path


def usage():
    return {"time": {"embedding": 0.0, "vector_searching": 0.0, "llm_reasoning": 0.0},
            "api_usage": {"model": "synthetic", "rate_info": None, "input_tokens": 10,
                          "output_tokens": 5, "cached_input_tokens": 0, "estimated_cost_usd": 0.0}}


def step(action, ids, answerability):
    return {
        "action_decisions": [] if action is None else [{
            "next_action": action, "retrieval_task": "Find corroborating component",
            "anchor": 0 if action else None, "document_search_mode": "vector search",
            "component_search_mode": "vector search", **usage()}],
        "retrieval_subtask": {"predicted_subtasks": ["Find corroborating component"], **usage()},
        "retrieval_result": {
            "subquery_task": "Find corroborating component", "final_status": "not answerable",
            "candidate_result": {"mode": "vector search", "candidate_documents": [], **usage()},
            "component_result": {"mode": "vector search",
                                 "selected_components": [[[doc, cid], 0.5] for doc, cid in ids], **usage()},
            "evaluator_result": {"updated_subtasks": [{
                "retrieval_subtask": "Find corroborating component",
                "answerability": answerability, "answer": None}], "next_parameters": None, **usage()},
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fif-synthetic-") as tmp:
        directory = Path(tmp) / "details"
        directory.mkdir()
        initial = step(None, [("A", "p1"), ("B", "p2")], False)
        for name, ids in (("repeat", [("A", "p1"), ("B", "p2")]),
                          ("changed", [("A", "p1"), ("C", "p3")])):
            record = {"qid": name, "question": "synthetic question", "retrieval_tasks": [],
                      "retrieved_nids": [], "memory": {
                          "subtasks": {"subtasks": []}, "subtask_plans": [],
                          "tool_usage": [initial, step("retry", ids, False)]},
                      "agent_usage": {}}
            (directory / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")
        reports = inspect_path(directory)
        by_qid = {r["qid"]: r for r in reports}
        assert by_qid["repeat"]["steps"][1]["new_count"] == 0
        assert by_qid["changed"]["steps"][1]["new_count"] == 1
        assert by_qid["repeat"]["steps"][1]["usage"] == by_qid["changed"]["steps"][1]["usage"]
        print("SYNTHETIC DEMONSTRATION — NOT A FiF EXPERIMENT OR REAL TRACE")
        print(format_text(reports))


if __name__ == "__main__":
    main()
