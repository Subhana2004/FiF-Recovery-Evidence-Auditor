"""Cross-validate one FiF per-query detail file against its companion retrieval JSONL.

Designed for a *genuine* FiF run, but cannot establish provenance by itself.
Never claims a fixture is an experiment, and never changes input files.

Usage:
    python validate_trace_pair.py /path/to/details/0.json /path/to/run/run.jsonl
    python validate_trace_pair.py /path/to/details/0.json /path/to/run/run.jsonl --report phase5.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from fif_recovery_auditor import analyze_detail


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _normalize_pair(value: Any) -> tuple[Any, Any] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if type(value[0]) not in (str, int) or type(value[1]) not in (str, int):
        return None
    return tuple(value)


def _detail_ids(data: dict[str, Any]) -> tuple[list[tuple[Any, Any]], list[str]]:
    issues: list[str] = []
    raw = data.get('retrieved_nids')
    if not isinstance(raw, list):
        return [], ['details.retrieved_nids is not a list']
    ids: list[tuple[Any, Any]] = []
    for i, row in enumerate(raw):
        pair = _normalize_pair(row[0]) if isinstance(row, list) and len(row) == 2 else None
        if pair is None:
            issues.append(f'details.retrieved_nids[{i}] invalid')
        else:
            ids.append(pair)
    return ids, issues


def _result_ids(data: dict[str, Any]) -> tuple[list[tuple[Any, Any]], list[str]]:
    raw = data.get('retrieved_units')
    if not isinstance(raw, list):
        return [], ['result.retrieved_units is not a list']
    ids: list[tuple[Any, Any]] = []
    issues: list[str] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict) or not isinstance(row.get('nodes'), list):
            issues.append(f'result.retrieved_units[{i}].nodes invalid')
            continue
        for j, node in enumerate(row['nodes']):
            pair = _normalize_pair(node)
            if pair is None:
                issues.append(f'result.retrieved_units[{i}].nodes[{j}] invalid')
            else:
                ids.append(pair)
    return ids, issues


def verify_pair(detail_path: Path, result_path: Path) -> dict[str, Any]:
    """Return an evidence report; no claim of authenticity or relevance."""
    detail_path = detail_path.resolve()
    result_path = result_path.resolve()
    report: dict[str, Any] = {
        'verification_type': 'FiF saved-output cross-check; not an authenticity certificate',
        'detail_file': str(detail_path),
        'result_file': str(result_path),
        'checks': {},
        'warnings': [],
        'authentic_fif_execution_verified': False,
    }
    for path, name in ((detail_path, 'detail_sha256'), (result_path, 'result_sha256')):
        report[name] = _hash(path)

    detail = json.loads(detail_path.read_text(encoding='utf-8'))
    if not isinstance(detail, dict):
        raise ValueError('detail file is not a JSON object')
    report['qid'] = detail.get('qid')
    tool_usage = detail.get('memory', {}).get('tool_usage') if isinstance(detail.get('memory'), dict) else None
    report['checks']['memory_tool_usage_present'] = isinstance(tool_usage, list)
    if not report['checks']['memory_tool_usage_present']:
        report['warnings'].append('details.memory.tool_usage is missing or not a list; retrieval history cannot be checked.')
        report['retrieval_attempts'] = None
        report['review_flags'] = []
    else:
        audit = analyze_detail(detail, str(detail_path))
        report['retrieval_attempts'] = audit['retrieval_attempts']
        report['review_flags'] = audit['flags']

    same_qid: list[dict[str, Any]] = []
    invalid_lines = []
    with result_path.open('r', encoding='utf-8') as source:
        for number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                invalid_lines.append(number)
                continue
            if isinstance(row, dict) and row.get('qid') == detail.get('qid'):
                same_qid.append(row)
    report['matching_jsonl_records'] = len(same_qid)
    report['invalid_jsonl_lines'] = invalid_lines
    report['checks']['unique_matching_qid'] = (len(same_qid) == 1 and report['qid'] is not None)
    if invalid_lines:
        report['warnings'].append(f'Invalid JSONL lines: {invalid_lines[:20]}')
    if len(same_qid) != 1:
        report['warnings'].append('Expected exactly one JSONL record matching a nonnull detail qid.')
        report['checks']['same_final_component_sequence'] = None
        report['checks']['same_final_component_set'] = None
        report['checks']['same_agent_usage'] = None
    else:
        result = same_qid[0]
        dids, derrors = _detail_ids(detail)
        rids, rerrors = _result_ids(result)
        if derrors or rerrors:
            report['warnings'].extend(derrors + rerrors)
            report['checks']['same_final_component_sequence'] = False
            report['checks']['same_final_component_set'] = False
        else:
            report['checks']['same_final_component_sequence'] = (dids == rids)
            report['checks']['same_final_component_set'] = (set(dids) == set(rids))
        report['detail_final_component_count'] = len(dids)
        report['jsonl_final_component_count'] = len(rids)
        da, ra = detail.get('agent_usage'), result.get('agent_usage')
        report['checks']['same_agent_usage'] = (da == ra) if da is not None and ra is not None else None
        if da is None or ra is None:
            report['warnings'].append('Cannot compare agent_usage; one side is missing.')
        report['upstream_jsonl_llm_calls'] = result.get('llm_calls')
        report['upstream_jsonl_api_usage'] = result.get('api_usage')
    required_checks = ('memory_tool_usage_present', 'unique_matching_qid',
                       'same_final_component_sequence', 'same_agent_usage')
    report['internal_consistency_passed'] = all(report['checks'].get(k) is True for k in required_checks)
    if not report['internal_consistency_passed']:
        report['warnings'].append('At least one consistency check failed or could not be performed.')
    report['limitations'] = [
        'This compares stored outputs and does not prove either came from an actual FiF execution.',
        'The two files may have been modified; record paths and SHA-256 hashes for provenance.',
        'Passing checks does not validate retrieval relevance, scientific results, or algorithm correctness.',
        'Upstream results may be appended/re-run and contain duplicate qids; resolve duplicates manually.'
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('detail', type=Path, help='One saved FiF details/*.json file')
    parser.add_argument('results', type=Path, help='Companion FiF run JSONL')
    parser.add_argument('--report', type=Path, help='Write a JSON report outside the input paths')
    args = parser.parse_args(argv)
    try:
        for p in (args.detail, args.results):
            if not p.is_file():
                parser.error(f'input is not a file: {p}')
        if args.report and (args.report.resolve() in {args.detail.resolve(), args.results.resolve()}):
            parser.error('--report cannot overwrite an input file')
        outcome = verify_pair(args.detail, args.results)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f'Validation failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    output = json.dumps(outcome, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + '\n', encoding='utf-8')
    else:
        print(output)
    return 0 if outcome['internal_consistency_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
