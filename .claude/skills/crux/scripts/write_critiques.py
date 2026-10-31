#!/usr/bin/env python3
"""Write critiques.jsonl (+ gap_requests) from /crux-critique output.

Assigns critique ids (agents do not mint these).

Ids: cri_<proposal_id>_<nnnn>  (proposal_id sanitized)
Use --append to add into an existing critiques.jsonl without wiping prior rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS / 'lib'
for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from jsonl_io import (  # noqa: E402
    load_json,
    load_jsonl,
    next_prefixed_index,
    sanitize_id,
    write_jsonl,
)


def build_rows(
    workflow: dict,
    *,
    existing: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    results = workflow.get('results')
    if not isinstance(results, list):
        raise ValueError('workflow result missing results[]')

    research_goal = workflow.get('research_goal')
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    cri_rows: list[dict] = []
    gap_rows: list[dict] = []
    warnings: list[str] = []
    working = list(existing)

    for item in results:
        if not isinstance(item, dict):
            continue
        slot_id = item.get('slot_id')
        proposal_id = item.get('proposal_id')
        status = item.get('status')
        if not isinstance(slot_id, str) or not isinstance(proposal_id, str):
            continue
        if status not in ('pass', 'needs_claims'):
            warnings.append(f'{proposal_id}: unknown status {status!r}')
            continue

        gaps = item.get('gap_requests') if isinstance(item.get('gap_requests'), list) else []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            query = gap.get('query')
            why = gap.get('why')
            if not isinstance(query, str) or not isinstance(why, str):
                continue
            gap_rows.append(
                {
                    'slot_id': slot_id,
                    'proposal_id': proposal_id,
                    'stage': 'critique',
                    'query': query,
                    'why': why,
                    'related_claim_ids': gap.get('related_claim_ids')
                    if isinstance(gap.get('related_claim_ids'), list)
                    else [],
                    'suggested_kinds': gap.get('suggested_kinds')
                    if isinstance(gap.get('suggested_kinds'), list)
                    else [],
                    'status': status,
                }
            )

        verdict = item.get('verdict')
        if not isinstance(verdict, str) or not verdict.strip():
            warnings.append(f'{proposal_id}: missing verdict')
            verdict = ''

        prefix = f'cri_{sanitize_id(proposal_id, max_len=64, fallback="proposal")}_'
        index = next_prefixed_index(working + cri_rows, prefix)
        cri_id = f'{prefix}{index:04d}'
        cri_rows.append(
            {
                'id': cri_id,
                'slot_id': slot_id,
                'proposal_id': proposal_id,
                'status': status,
                'source': {
                    'type': 'critique',
                    'slot_id': slot_id,
                    'proposal_id': proposal_id,
                    'workflow': 'critique',
                },
                'research_goal': research_goal,
                'created_at': created,
                'verdict': verdict,
                'issues': item.get('issues') if isinstance(item.get('issues'), list) else [],
                'unsupported_hops': item.get('unsupported_hops')
                if isinstance(item.get('unsupported_hops'), list)
                else [],
                'gap_requests': gaps if isinstance(gaps, list) else [],
            }
        )

    return cri_rows, gap_rows, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow_result', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='critiques.jsonl')
    parser.add_argument(
        '--gaps_out',
        type=Path,
        default=None,
        help='gap_requests.jsonl (default: <out-dir>/gap_requests.jsonl)',
    )
    parser.add_argument(
        '--append',
        action='store_true',
        help='Append critiques (and this stage’s gaps) instead of replacing them',
    )
    args = parser.parse_args()

    workflow = load_json(args.workflow_result)
    existing = load_jsonl(args.out) if args.append else []

    cri_rows, gap_rows, warnings = build_rows(workflow, existing=existing)
    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)

    final = existing + cri_rows if args.append else cri_rows
    write_jsonl(args.out, final)

    # Shared gap_requests.jsonl across propose/critique/revise. Without --append,
    # replace only this stage’s rows; keep other stages. With --append, concatenate.
    gaps_path = args.gaps_out or (args.out.parent / 'gap_requests.jsonl')
    if gaps_path.exists():
        prior_gaps = load_jsonl(gaps_path)
        if args.append:
            gap_rows = prior_gaps + gap_rows
        else:
            gap_rows = [g for g in prior_gaps if g.get('stage') != 'critique'] + gap_rows
    write_jsonl(gaps_path, gap_rows)

    print(
        json.dumps(
            {
                'critiques_path': str(args.out),
                'gap_requests_path': str(gaps_path),
                'critique_count': len(final),
                'new_critiques': len(cri_rows) if args.append else len(final),
                'gap_request_count': len(gap_rows),
                'warning_count': len(warnings),
                'pass_count': workflow.get('pass_count'),
                'needs_claims_count': workflow.get('needs_claims_count'),
                'failed': workflow.get('failed'),
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
