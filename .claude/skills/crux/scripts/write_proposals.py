#!/usr/bin/env python3
"""Write proposals.jsonl (+ gap_requests) from /crux-propose output.

Assigns proposal ids (agents do not mint these). Validates claim refs against
the seed pack when --seeds is provided.

Ids: prp_<slot_id>_<strategy>_<nnnn>  (slot_id sanitized)
Use --append to add into an existing proposals.jsonl without wiping prior rows.
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
    claim_ids_from_hypothesis,
    load_json,
    load_jsonl,
    next_prefixed_index,
    sanitize_id,
    seed_claim_ids,
    write_jsonl,
)

STRATEGIES = {'literature', 'debate', 'assumptions'}


def validate_claim_refs(
    *,
    slot_id: str,
    strategy: str,
    hypothesis: dict,
    allowed: set[str] | None,
) -> list[str]:
    warnings: list[str] = []
    chain = hypothesis.get('claim_chain')
    well_known = 0
    if isinstance(chain, list):
        for hop in chain:
            if not isinstance(hop, dict):
                continue
            kind = hop.get('kind')
            if kind == 'well_known' or (
                kind is None
                and not hop.get('claim_id')
                and hop.get('statement')
            ):
                well_known += 1
                statement = hop.get('statement')
                check = hop.get('check')
                if not isinstance(statement, str) or not statement.strip():
                    warnings.append(f'{slot_id}/{strategy}: well_known hop missing statement')
                if not isinstance(check, str) or not check.strip():
                    warnings.append(f'{slot_id}/{strategy}: well_known hop missing check')
        if well_known > 2:
            warnings.append(f'{slot_id}/{strategy}: {well_known} well_known hops (max 2)')
    if allowed is None:
        return warnings
    unknown = sorted(cid for cid in claim_ids_from_hypothesis(hypothesis) if cid not in allowed)
    if unknown:
        preview = ', '.join(unknown[:5])
        more = '' if len(unknown) <= 5 else f' (+{len(unknown) - 5} more)'
        warnings.append(
            f'{slot_id}/{strategy}: unknown claim id(s) not in seed: {preview}{more}'
        )
    return warnings


def build_rows(
    workflow: dict,
    *,
    existing: list[dict],
    seeds: dict | None,
) -> tuple[list[dict], list[dict], list[str]]:
    results = workflow.get('results')
    if not isinstance(results, list):
        raise ValueError('workflow result missing results[]')

    research_goal = workflow.get('research_goal')
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    prop_rows: list[dict] = []
    gap_rows: list[dict] = []
    warnings: list[str] = []
    working = list(existing)

    for item in results:
        if not isinstance(item, dict):
            continue
        slot_id = item.get('slot_id')
        strategy = item.get('strategy')
        status = item.get('status')
        if not isinstance(slot_id, str) or strategy not in STRATEGIES:
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
                    'strategy': strategy,
                    'stage': 'propose',
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

        if status != 'ok':
            continue

        hypothesis = item.get('hypothesis')
        if not isinstance(hypothesis, dict):
            warnings.append(f'{slot_id}/{strategy}: status ok but missing hypothesis')
            continue

        allowed = seed_claim_ids(seeds, slot_id)
        warnings.extend(
            validate_claim_refs(
                slot_id=slot_id,
                strategy=strategy,
                hypothesis=hypothesis,
                allowed=allowed,
            )
        )

        prefix = f'prp_{sanitize_id(slot_id)}_{strategy}_'
        index = next_prefixed_index(working + prop_rows, prefix)
        prop_id = f'{prefix}{index:04d}'
        prop_rows.append(
            {
                'id': prop_id,
                'slot_id': slot_id,
                'strategy': strategy,
                'source': {
                    'type': 'propose',
                    'slot_id': slot_id,
                    'strategy': strategy,
                    'workflow': 'propose',
                },
                'research_goal': research_goal,
                'created_at': created,
                'statement': hypothesis.get('statement'),
                'mechanism': hypothesis.get('mechanism'),
                'experimental_plan': hypothesis.get('experimental_plan'),
                'dependency_claim_ids': hypothesis.get('dependency_claim_ids') or [],
                'claim_chain': hypothesis.get('claim_chain') or [],
                'references': hypothesis.get('references') or [],
                'debate_transcript': hypothesis.get('debate_transcript'),
                'intermediate_assumptions': hypothesis.get('intermediate_assumptions'),
            }
        )

    return prop_rows, gap_rows, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow_result', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='proposals.jsonl')
    parser.add_argument(
        '--gaps_out',
        type=Path,
        default=None,
        help='gap_requests.jsonl (default: <out-dir>/gap_requests.jsonl)',
    )
    parser.add_argument('--seeds', type=Path, default=None)
    parser.add_argument(
        '--append',
        action='store_true',
        help='Append proposals (and this stage’s gaps) instead of replacing them',
    )
    args = parser.parse_args()

    workflow = load_json(args.workflow_result)
    seeds = load_json(args.seeds) if args.seeds else None
    existing = load_jsonl(args.out) if args.append else []

    prop_rows, gap_rows, warnings = build_rows(
        workflow, existing=existing, seeds=seeds
    )
    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)

    final = existing + prop_rows if args.append else prop_rows
    write_jsonl(args.out, final)

    # Shared gap_requests.jsonl across propose/critique/revise. Without --append,
    # replace only this stage’s rows; keep other stages. With --append, concatenate.
    gaps_path = args.gaps_out or (args.out.parent / 'gap_requests.jsonl')
    if gaps_path.exists():
        prior_gaps = load_jsonl(gaps_path)
        if args.append:
            gap_rows = prior_gaps + gap_rows
        else:
            gap_rows = [g for g in prior_gaps if g.get('stage') != 'propose'] + gap_rows
    write_jsonl(gaps_path, gap_rows)

    print(
        json.dumps(
            {
                'proposals_path': str(args.out),
                'gap_requests_path': str(gaps_path),
                'proposal_count': len(final),
                'new_proposals': len(prop_rows) if args.append else len(final),
                'gap_request_count': len(gap_rows),
                'warning_count': len(warnings),
                'ok_count': workflow.get('ok_count'),
                'needs_claims_count': workflow.get('needs_claims_count'),
                'failed': workflow.get('failed'),
                'strategies': workflow.get('strategies'),
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
