"""Offline diagnostic for saved FiF details/*.json trajectories.

Counts observed component IDs, never inferred relevance or retrieval quality.
No FiF imports, model inference, network requests, or input modification.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

UPSTREAM_COMMIT = "990c068358126ed39ec9a345ac5932bc37cace5f"
USAGE_PARTS = ("retrieval_subtask", "candidate_result", "component_result", "evaluator_result")
TIME_FIELDS = ("embedding", "vector_searching", "llm_reasoning")
API_FIELDS = ("input_tokens", "output_tokens", "cached_input_tokens", "estimated_cost_usd")


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def component_ids(raw: Any) -> tuple[set[tuple[str | int, str | int]], list[str]]:
    ids: set[tuple[str | int, str | int]] = set()
    errors: list[str] = []
    if not isinstance(raw, list):
        return ids, ["selected_components is not a list"]
    for index, entry in enumerate(raw):
        if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                or not isinstance(entry[0], (list, tuple)) or len(entry[0]) != 2):
            errors.append(f"selected_components[{index}] has no [[doc,id],score] shape")
            continue
        fn, cid = entry[0]
        if (type(fn) not in (str, int) or type(cid) not in (str, int)
                or not isinstance(entry[1], (int, float)) or isinstance(entry[1], bool)):
            errors.append(f"selected_components[{index}] has invalid identifier or score")
            continue
        ids.add((fn, cid))
    return ids, errors


def status_from_evaluator(result: dict[str, Any]) -> str:
    updates = obj(result.get("evaluator_result")).get("updated_subtasks")
    if not isinstance(updates, list):
        return "unknown"
    values = [x.get("answerability") for x in updates if isinstance(x, dict)]
    if any(v is True for v in values):
        return "answerable"
    if any(v is False for v in values):
        return "not_answerable"
    return "unknown"


def observed_usage(step: dict[str, Any]) -> dict[str, Any]:
    """Sum direct serialized usage leaves only; never sum agent_usage a second time."""
    rr = obj(step.get("retrieval_result"))
    leaves: list[tuple[str, Any]] = [("retrieval_subtask", step.get("retrieval_subtask"))]
    decisions = step.get("action_decisions")
    if isinstance(decisions, list):
        leaves.extend((f"action_decisions[{i}]", x) for i, x in enumerate(decisions))
    for key in USAGE_PARTS[1:]:
        leaves.append((key, rr.get(key)))
    known: dict[str, float] = {x: 0 for x in (*TIME_FIELDS, *API_FIELDS)}
    seen: dict[str, int] = {x: 0 for x in known}
    missing_metrics: set[str] = set()
    missing: list[str] = []
    observed_calls = 0
    for label, value in leaves:
        if value is None:  # legacy/incomplete trace; avoid treating absence as a zero
            missing.append(label)
            missing_metrics.update(known)
            continue
        if not isinstance(value, dict):
            missing.append(label)
            missing_metrics.update(known)
            continue
        time, api = value.get("time"), value.get("api_usage")
        if not isinstance(time, dict):
            missing.append(f"{label}.time")
            missing_metrics.update(TIME_FIELDS)
        else:
            for field in TIME_FIELDS:
                v = time.get(field)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    known[field] += v
                    seen[field] += 1
                else:
                    missing.append(f"{label}.time.{field}")
                    missing_metrics.add(field)
        if not isinstance(api, dict):
            missing.append(f"{label}.api_usage")
            missing_metrics.update(API_FIELDS)
        else:
            for field in API_FIELDS:
                v = api.get(field)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    known[field] += v
                    seen[field] += 1
                else:
                    missing.append(f"{label}.api_usage.{field}")
                    missing_metrics.add(field)
            if ((isinstance(api.get("model"), str) and api["model"].strip())
                    or bool(api.get("rate_info"))
                    or any(isinstance(api.get(k), (int, float)) and api[k] > 0
                           for k in API_FIELDS)):
                observed_calls += 1
    # These are sums of available fields, not guaranteed complete totals.
    return {
        "observed_llm_calls": observed_calls,
        "observed": {k: known[k] if seen[k] and k not in missing_metrics else None for k in known},
        "missing_usage_fields": missing,
        "complete": not missing,
        "unit": "time fields as serialized (seconds in upstream TimeUsage)",
    }


def analyze_detail(data: Any, source: str = "<memory>") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("detail root is not an object")
    memory = data.get("memory")
    if not isinstance(memory, dict) or not isinstance(memory.get("tool_usage"), list):
        raise ValueError("expected memory.tool_usage list (no legacy memory.steps fallback)")
    steps = memory["tool_usage"]
    result: dict[str, Any] = {
        "source": source, "qid": data.get("qid"), "steps": [], "flags": [],
        "retrieval_attempts": 0, "excluded_rerank": 0, "malformed_steps": 0,
        "provenance": "saved detail; observational diagnostics",
    }
    seen: set[tuple[str | int, str | int]] = set()
    prev_ids: set[tuple[str | int, str | int]] | None = None
    prev_step: dict[str, Any] | None = None
    intervening = 0
    for ix, raw in enumerate(steps):
        number = ix + 1
        if not isinstance(raw, dict):
            result["malformed_steps"] += 1
            result["flags"].append({"step": number, "code": "invalid_step", "confidence": "high",
                                    "evidence": "tool_usage entry is not an object",
                                    "review": "Inspect the serialized step."})
            intervening += 1
            continue
        rr = obj(raw.get("retrieval_result"))
        cr = obj(rr.get("component_result"))
        candidate = obj(rr.get("candidate_result"))
        decisions = raw.get("action_decisions")
        errors: list[str] = []
        if not isinstance(decisions, list):
            errors.append("action_decisions is not a list")
            decisions = []
        if any(not isinstance(d, dict) for d in decisions):
            errors.append("action_decisions includes non-object")
        decision = next((d for d in reversed(decisions) if isinstance(d, dict)), {})
        action = decision.get("next_action") if decision else ("initial" if ix == 0 else "unknown")
        if action not in ("initial", "search", "retry", "replan", "stop"):
            errors.append("unknown action")
            action = "unknown"
        mode = cr.get("mode")
        usage = observed_usage(raw)
        if mode == "rerank":
            kind = "rerank"
            result["excluded_rerank"] += 1
        elif action in ("replan", "stop"):
            kind = action
        elif action in ("initial", "search", "retry") and isinstance(rr.get("component_result"), dict):
            kind = "retrieval"
        else:
            kind = "unknown"
            errors.append("retrieval result or component_result missing")
        step: dict[str, Any] = {
            "step": number, "kind": kind, "action": action,
            "decision_count": len(decisions), "anchor": decision.get("anchor"),
            "requested_document_mode": decision.get("document_search_mode"),
            "requested_component_mode": decision.get("component_search_mode"),
            "candidate_mode": candidate.get("mode"), "component_mode": mode,
            "subquery": rr.get("subquery_task") or decision.get("retrieval_task") or "",
            "evaluator_status": status_from_evaluator(rr) if kind == "retrieval" else "not_applicable",
            "serialized_final_status": rr.get("final_status"),
            "usage": usage, "parse_warnings": errors,
        }
        if kind != "retrieval":
            result["steps"].append(step)
            intervening += 1
            continue
        ids, id_errors = component_ids(cr.get("selected_components"))
        errors.extend(id_errors)
        # Malformed identifiers make novelty counts lower bounds, not complete sets.
        new = ids - seen
        reused = ids & seen
        consecutive_overlap = ids & prev_ids if prev_ids is not None else set()
        step.update({
            "selected_count": len(ids), "new_count": len(new), "reused_count": len(reused),
            "previous_overlap_count": len(consecutive_overlap),
            "selected_ids": [list(x) for x in sorted(ids, key=repr)],
            "new_ids": [list(x) for x in sorted(new, key=repr)],
            "reused_ids": [list(x) for x in sorted(reused, key=repr)],
            "prior_retrieval_step": prev_step["step"] if prev_step else None,
            "intervening_nonretrieval_steps": intervening,
            "after_evaluator_failure": bool(prev_step and prev_step["evaluator_status"] == "not_answerable"),
            "same_subquery": step["subquery"] == prev_step["subquery"] if prev_step else None,
            "mode_changed": (step["candidate_mode"], mode) !=
                            (prev_step["candidate_mode"], prev_step["component_mode"]) if prev_step else None,
        })
        if step["after_evaluator_failure"] and action in ("search", "retry") and not errors:
            if ids and not new:
                result["flags"].append({
                    "step": number, "code": "repeated_evidence_after_failed_evaluation",
                    "confidence": "high for ID overlap; unknown for usefulness",
                    "evidence": f"{len(ids)} selected IDs, 0 new; previous retrieval step "
                                f"{prev_step['step']} had an explicit false answerability",
                    "review": "Inspect query, anchor, modes and evidence utility; reuse may be intentional.",
                })
            elif not ids:
                result["flags"].append({
                    "step": number, "code": "empty_selection_after_failed_evaluation",
                    "confidence": "high for empty selected set; unknown for cause",
                    "evidence": f"0 selected IDs after failed retrieval step {prev_step['step']}",
                    "review": "Inspect candidate documents and upstream retrieval logs.",
                })
        if errors:
            result["flags"].append({"step": number, "code": "incomplete_trace",
                                    "confidence": "high for parse issue; low for novelty count",
                                    "evidence": "; ".join(errors),
                                    "review": "Inspect malformed fields before interpreting counts."})
        seen.update(ids)
        prev_ids = ids
        prev_step = step
        intervening = 0
        result["retrieval_attempts"] += 1
        result["steps"].append(step)
    return result


def inspect_path(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        directory = path / "details" if (path / "details").is_dir() else path
        files = sorted(directory.glob("*.json"))
        if not files:
            raise ValueError(f"no *.json detail files in {directory}")
    elif path.is_file():
        files = [path]
    else:
        raise ValueError(f"not a file or directory: {path}")
    reports = []
    for file in files:
        try:
            reports.append(analyze_detail(json.loads(file.read_text(encoding="utf-8")), str(file)))
        except (ValueError, UnicodeError, OSError) as exc:
            reports.append({"source": str(file), "error": f"{type(exc).__name__}: {exc}",
                            "flags": [], "steps": [], "retrieval_attempts": 0})
    return reports


def format_text(reports: list[dict[str, Any]]) -> str:
    lines = [f"FiF Recovery Evidence Auditor | files={len(reports)} | synthetic/real provenance depends on input"]
    for report in reports:
        lines.append(f"\n{report['source']} | qid={report.get('qid')} | "
                     f"retrieval_attempts={report['retrieval_attempts']}")
        if "error" in report:
            lines.append(f"  ERROR: {report['error']}")
            continue
        for step in report["steps"]:
            if step["kind"] == "retrieval":
                usage = step["usage"]
                observed = usage["observed"]
                lines.append(f"  step {step['step']} {step['action']} status={step['evaluator_status']} "
                             f"selected={step['selected_count']} new={step['new_count']} "
                             f"reused={step['reused_count']} anchor={step['anchor']} "
                             f"mode={step['component_mode']} observed_calls={usage['observed_llm_calls']} "
                             f"input_tokens={observed['input_tokens']} "
                             f"cost_usd={observed['estimated_cost_usd']} "
                             f"usage_complete={usage['complete']}")
            else:
                lines.append(f"  step {step['step']} {step['kind']} (not a retrieval attempt)")
        for flag in report["flags"]:
            lines.append(f"  REVIEW step {flag['step']} [{flag['code']}]: {flag['evidence']}; "
                         f"{flag['review']} Confidence: {flag['confidence']}")
    return "\n".join(lines)


CSV_FIELDS = ("source", "qid", "step", "kind", "action", "evaluator_status", "selected_count",
              "new_count", "reused_count", "previous_overlap_count", "after_evaluator_failure",
              "same_subquery", "anchor", "candidate_mode", "component_mode",
              "observed_llm_calls", "observed_input_tokens", "observed_output_tokens",
              "observed_estimated_cost_usd", "observed_time_seconds", "usage_complete")


def write_csv(reports: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for report in reports:
            for step in report["steps"]:
                usage = step["usage"]
                observed = usage["observed"]
                writer.writerow({
                    **{k: step.get(k) for k in CSV_FIELDS},
                    "source": report["source"], "qid": report.get("qid"),
                    "observed_llm_calls": usage["observed_llm_calls"],
                    "observed_input_tokens": observed["input_tokens"],
                    "observed_output_tokens": observed["output_tokens"],
                    "observed_estimated_cost_usd": observed["estimated_cost_usd"],
                    "observed_time_seconds": sum(observed[k] for k in TIME_FIELDS)
                                             if all(observed[k] is not None for k in TIME_FIELDS) else None,
                    "usage_complete": usage["complete"],
                })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="FiF details/ directory, its parent run, or one detail JSON")
    parser.add_argument("--json-out", type=Path, help="write full structured report")
    parser.add_argument("--csv-out", type=Path, help="write one row per serialized step")
    args = parser.parse_args(argv)
    input_dir = (args.path / "details" if args.path.is_dir() and (args.path / "details").is_dir()
                 else args.path if args.path.is_dir() else args.path.parent).resolve()
    for output in (args.json_out, args.csv_out):
        if output is not None and output.resolve().is_relative_to(input_dir):
            parser.error(f"report output must be outside the input details directory: {output}")
    if args.json_out and args.csv_out and args.json_out.resolve() == args.csv_out.resolve():
        parser.error("JSON and CSV report paths must differ")
    try:
        reports = inspect_path(args.path)
    except ValueError as exc:
        parser.error(str(exc))
    print(format_text(reports))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps({"upstream_commit": UPSTREAM_COMMIT, "reports": reports},
                                            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        write_csv(reports, args.csv_out)
    return 2 if any("error" in r for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
