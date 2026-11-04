"""Schema-faithful synthetic fixtures; these are not FiF experimental traces."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from fif_recovery_auditor import analyze_detail, component_ids, inspect_path, main, observed_usage, write_csv


def usage(calls=0, cost=0.0):
    return {"time": {"embedding": 0.1, "vector_searching": 0.2, "llm_reasoning": 0.3},
            "api_usage": {"model": "fixture-model" if calls else "", "rate_info": None,
                          "input_tokens": 10 if calls else 0, "output_tokens": 5 if calls else 0,
                          "cached_input_tokens": 0, "estimated_cost_usd": cost}}


def step(action=None, ids=(), status=False, subquery="q", anchor=None,
         mode="vector search", candidate_mode="vector search", cost=0.0):
    decision = {"action": action, "next_action": action, "retrieval_task": subquery,
                "anchor": anchor, "document_search_mode": candidate_mode,
                "component_search_mode": mode, **usage(1, cost)} if action else None
    return {
        "action_decisions": [decision] if decision else [],
        "retrieval_subtask": {"predicted_subtasks": [subquery], **usage()},
        "retrieval_result": {
            "subquery_task": subquery, "final_status": "not answerable",
            "candidate_result": {"mode": candidate_mode, "candidate_documents": [], **usage()},
            "component_result": {"mode": mode,
                                 "selected_components": [[[fn, cid], float(i)] for i, (fn, cid) in enumerate(ids)],
                                 **usage()},
            "evaluator_result": {"updated_subtasks":
                [] if status is None else [{"retrieval_subtask": subquery, "answerability": status,
                                            "answer": None}],
                "next_parameters": None, **usage()},
        },
    }


def detail(steps, qid="synthetic"):
    return {"qid": qid, "question": "synthetic", "retrieval_tasks": [], "retrieved_nids": [],
            "memory": {"subtasks": {"subtasks": []}, "subtask_plans": [], "tool_usage": steps},
            "agent_usage": {}}


class AuditorTests(unittest.TestCase):
    def test_failure_then_new_evidence(self):
        r = analyze_detail(detail([step(ids=[("d", "a")]), step("retry", [("d", "b")])]))
        self.assertTrue(r["steps"][1]["after_evaluator_failure"])
        self.assertEqual((r["steps"][1]["new_count"], r["steps"][1]["reused_count"]), (1, 0))
        self.assertFalse(r["flags"])

    def test_failure_then_repeated_evidence(self):
        r = analyze_detail(detail([step(ids=[("d", "a")]), step("retry", [("d", "a")])]))
        self.assertEqual(r["flags"][0]["code"], "repeated_evidence_after_failed_evaluation")
        self.assertEqual(r["steps"][1]["previous_overlap_count"], 1)

    def test_reuse_after_success_is_not_flagged(self):
        r = analyze_detail(detail([step(ids=[("d", "a")], status=True),
                                   step("search", [("d", "a")], subquery="different")]))
        self.assertEqual(r["steps"][1]["reused_count"], 1)
        self.assertFalse(r["flags"])
        self.assertFalse(r["steps"][1]["same_subquery"])

    def test_new_and_reused_after_failure_not_flagged(self):
        r = analyze_detail(detail([step(ids=[("d", "a")]),
                                   step("retry", [("d", "a"), ("d", "b")])]))
        self.assertEqual((r["steps"][1]["new_count"], r["steps"][1]["reused_count"]), (1, 1))
        self.assertFalse(r["flags"])

    def test_backtracking_anchor_and_mode_change(self):
        r = analyze_detail(detail([step(ids=[("d", 1)]),
                                   step("search", [("e", 2)], anchor=0, mode="llm reasoning")]))
        self.assertEqual(r["steps"][1]["anchor"], 0)
        self.assertTrue(r["steps"][1]["mode_changed"])

    def test_replan_is_not_retrieval_but_intervening_is_recorded(self):
        r = analyze_detail(detail([step(ids=[("d", 1)]), step("replan"),
                                   step("search", [("d", 1)])]))
        self.assertEqual(r["retrieval_attempts"], 2)
        self.assertEqual(r["steps"][1]["kind"], "replan")
        self.assertEqual(r["steps"][2]["intervening_nonretrieval_steps"], 1)

    def test_stop_is_not_retrieval(self):
        r = analyze_detail(detail([step(ids=[("d", 1)]), step("stop")]))
        self.assertEqual(r["retrieval_attempts"], 1)
        self.assertEqual(r["steps"][1]["kind"], "stop")

    def test_rerank_excluded_and_usage_preserved(self):
        r = analyze_detail(detail([step(ids=[("d", 1)]),
                                   step(ids=[("d", 1)], mode="rerank")]))
        self.assertEqual((r["retrieval_attempts"], r["excluded_rerank"]), (1, 1))
        self.assertIsNotNone(r["steps"][1]["usage"])

    def test_unknown_evaluation_not_failure(self):
        r = analyze_detail(detail([step(ids=[("d", 1)], status=None),
                                   step("retry", [("d", 1)])]))
        self.assertEqual(r["steps"][0]["evaluator_status"], "unknown")
        self.assertFalse(r["steps"][1]["after_evaluator_failure"])
        self.assertFalse(r["flags"])

    def test_multiple_queries_and_retries(self):
        reports = [analyze_detail(detail([step(ids=[("a", 1)]), step("retry", [("a", 1)])], "q1")),
                   analyze_detail(detail([step(ids=[("b", 2)]), step("search", [("b", 3)])], "q2"))]
        self.assertEqual([len(r["flags"]) for r in reports], [1, 0])
        self.assertEqual([r["retrieval_attempts"] for r in reports], [2, 2])

    def test_empty_trajectory(self):
        r = analyze_detail(detail([]))
        self.assertEqual((r["retrieval_attempts"], r["steps"], r["flags"]), (0, [], []))

    def test_identifier_formats_preserve_types(self):
        ids, errors = component_ids([[[1, 2], 0.2], [["1", "2"], 0.3]])
        self.assertEqual(len(ids), 2)
        self.assertFalse(errors)

    def test_malformed_component_does_not_trigger_repeat_flag(self):
        bad = step("retry", [("d", 1)])
        bad["retrieval_result"]["component_result"]["selected_components"].append(["broken"])
        r = analyze_detail(detail([step(ids=[("d", 1)]), bad]))
        self.assertEqual(r["steps"][1]["reused_count"], 1)
        self.assertEqual(r["flags"][0]["code"], "incomplete_trace")

    def test_invalid_root_and_legacy_steps_rejected(self):
        for bad in ([], {"memory": {"steps": []}}, {"memory": {"tool_usage": {}}}):
            with self.assertRaises(ValueError):
                analyze_detail(bad)

    def test_malformed_step_recorded(self):
        r = analyze_detail(detail([None, step(ids=[("d", 1)])]))
        self.assertEqual(r["malformed_steps"], 1)
        self.assertEqual(r["flags"][0]["code"], "invalid_step")

    def test_zero_cost_is_known_not_missing(self):
        s = step("search", [("d", 1)], cost=0)
        result = observed_usage(s)
        self.assertTrue(result["complete"])
        self.assertEqual(result["observed"]["estimated_cost_usd"], 0)
        self.assertEqual(result["observed_llm_calls"], 1)

    def test_unknown_cost_remains_unknown(self):
        s = step("search", [("d", 1)])
        del s["action_decisions"][0]["api_usage"]["estimated_cost_usd"]
        result = observed_usage(s)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["observed"]["estimated_cost_usd"])
        self.assertIn("action_decisions[0].api_usage.estimated_cost_usd",
                      result["missing_usage_fields"])

    def test_multiple_decisions_counted_and_latest_action_used(self):
        s = step("retry", [("d", 1)])
        s["action_decisions"].insert(0, {"next_action": "search", **usage(1)})
        r = analyze_detail(detail([step(ids=[("d", 1)]), s]))
        self.assertEqual(r["steps"][1]["action"], "retry")
        self.assertEqual(r["steps"][1]["decision_count"], 2)
        self.assertEqual(r["steps"][1]["usage"]["observed_llm_calls"], 2)

    def test_file_and_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "details"
            directory.mkdir()
            (directory / "0.json").write_text(json.dumps(detail([step(ids=[("a", 1)])])))
            r = inspect_path(directory)
            self.assertEqual(r[0]["retrieval_attempts"], 1)
            csv_path = Path(tmp) / "report.csv"
            write_csv(r, csv_path)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["new_count"], "1")
            self.assertEqual(main([str(directory), "--json-out", str(Path(tmp) / "report.json")]), 0)

    def test_bad_json_isolated_and_nonzero_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("{")
            self.assertIn("error", inspect_path(p)[0])
            self.assertEqual(main([str(p)]), 2)

    def test_report_cannot_overwrite_or_pollute_input_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "details"
            directory.mkdir()
            source = directory / "0.json"
            original = json.dumps(detail([step(ids=[("a", 1)])]))
            source.write_text(original)
            with self.assertRaises(SystemExit):
                main([str(directory), "--json-out", str(source)])
            with self.assertRaises(SystemExit):
                main([str(directory), "--csv-out", str(directory / "steps.csv")])
            self.assertEqual(source.read_text(), original)


if __name__ == "__main__":
    unittest.main()
