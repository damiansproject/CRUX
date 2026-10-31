#!/usr/bin/env python3
"""Write final hypotheses.jsonl (+ gap_requests) from /crux-revise output.

Assigns hyp ids and stamps provenance `source` (agents do not mint these).
Does not mint claim ids. Validates dependency / chain ids against the seed pack
when --seeds is provided.

Ids: hyp_<slot_id>_<nnnn>  (slot_id sanitized)
Use --append to add into an existing hypotheses.jsonl without wiping prior rows.

source.type:
  generate   — from /crux-revise (default; pipeline-produced final)
  feedback   — fed back from tournament / review / external
  manual     — main-authored or pasted
  evolution  — derived from a parent hypothesis
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

SOURCE_TYPES = {'generate', 'feedback', 'manual', 'evolution'}


def validate_claim_refs(
    *,
    slot_id: str,
    hypothesis: dict,
    allowed: set[str] | None,
) -> list[str]:
    warnings: list[str] = []
    if allowed is None:
        return warnings
    unknown = sorted(cid for cid in claim_ids_from_hypothesis(hypothesis) if cid not in allowed)
    if unknown:
        preview = ', '.join(unknown[:5])
        more = '' if len(unknown) <= 5 else f' (+{len(unknown) - 5} more)'
        warnings.append(f'{slot_id}: unknown claim id(s) not in seed: {preview}{more}')
    return warnings


def stamp_source(
    *,
    slot_id: str,
    proposal_id: str | None,
    critique_id: str | None,
    default_type: str,
    item: dict,
    hypothesis: dict,
) -> dict:
    """Provenance for the stored hyp. Prefer explicit source on the result item."""
    raw = item.get('source')
    if not isinstance(raw, dict):
        raw = hypothesis.get('source') if isinstance(hypothesis.get('source'), dict) else {}

    source_type = raw.get('type') if isinstance(raw.get('type'), str) else default_type
    if source_type not in SOURCE_TYPES:
        source_type = default_type

    source: dict = {
        'type': source_type,
        'slot_id': slot_id,
    }
    if isinstance(proposal_id, str) and proposal_id:
        source['proposal_id'] = proposal_id
    if isinstance(critique_id, str) and critique_id:
        source['critique_id'] = critique_id
    if source_type == 'generate':
        source['workflow'] = 'revise'

    parent = raw.get('parent_hypothesis_id')
    if isinstance(parent, str) and parent:
        source['parent_hypothesis_id'] = parent

    note = raw.get('note')
    if isinstance(note, str) and note.strip():
        source['note'] = note.strip()

    origin = raw.get('origin')
    if isinstance(origin, str) and origin.strip():
        source['origin'] = origin.strip()

    return source


def build_rows(
    workflow: dict,
    *,
    existing: list[dict],
    existing_blocked: list[dict],
    seeds: dict | None,
    default_source_type: str,
) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    results = workflow.get('results')
    if not isinstance(results, list):
        raise ValueError('workflow result missing results[]')

    research_goal = workflow.get('research_goal')
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    hyp_rows: list[dict] = []
    blocked_rows: list[dict] = []
    gap_rows: list[dict] = []
    warnings: list[str] = []
    working = list(existing)

    for item in results:
        if not isinstance(item, dict):
            continue
        slot_id = item.get('slot_id')
        status = item.get('status')
        proposal_id = item.get('proposal_id') if isinstance(item.get('proposal_id'), str) else None
        critique_id = item.get('critique_id') if isinstance(item.get('critique_id'), str) else None
        if not isinstance(slot_id, str):
            continue

        gaps = item.get('gap_requests') if isinstance(item.get('gap_requests'), list) else []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            query = gap.get('query')
            why = gap.get('why')
            if not isinstance(query, str) or not isinstance(why, str):
                continue
            gap_row = {
                'slot_id': slot_id,
                'stage': 'revise',
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
            if proposal_id:
                gap_row['proposal_id'] = proposal_id
            if critique_id:
                gap_row['critique_id'] = critique_id
            gap_rows.append(gap_row)

        hypothesis = item.get('hypothesis')

        if status != 'ok':
            # Keep the blocked idea. A blocking hop must be repairable by finding
            # evidence, never by deleting the hypothesis — so bank it out of the
            # tournament instead of dropping it on the floor.
            if isinstance(hypothesis, dict):
                prefix = f'blk_{sanitize_id(slot_id)}_'
                index = next_prefixed_index(list(existing_blocked) + blocked_rows, prefix)
                blocked_rows.append(
                    {
                        'id': f'{prefix}{index:04d}',
                        'slot_id': slot_id,
                        'proposal_id': proposal_id,
                        'critique_id': critique_id,
                        'status': status,
                        'research_goal': research_goal,
                        'created_at': created,
                        'statement': hypothesis.get('statement'),
                        'mechanism': hypothesis.get('mechanism'),
                        'experimental_plan': hypothesis.get('experimental_plan'),
                        'dependency_claim_ids': hypothesis.get('dependency_claim_ids') or [],
                        'claim_chain': hypothesis.get('claim_chain') or [],
                        'references': hypothesis.get('references') or [],
                        'blocking_gaps': [
                            g.get('query')
                            for g in gaps
                            if isinstance(g, dict) and isinstance(g.get('query'), str)
                        ],
                    }
                )
            else:
                warnings.append(
                    f'{slot_id}: {status} with no hypothesis; the idea is lost - '
                    'revise must keep the statement and emit gaps'
                )
            continue

        if not isinstance(hypothesis, dict):
            warnings.append(f'{slot_id}: status ok but missing hypothesis')
            continue

        allowed = seed_claim_ids(seeds, slot_id)
        warnings.extend(
            validate_claim_refs(slot_id=slot_id, hypothesis=hypothesis, allowed=allowed)
        )

        prefix = f'hyp_{sanitize_id(slot_id)}_'
        index = next_prefixed_index(working + hyp_rows, prefix)
        hyp_id = f'{prefix}{index:04d}'
        hyp_rows.append(
            {
                'id': hyp_id,
                'slot_id': slot_id,
                'proposal_id': proposal_id,
                'critique_id': critique_id,
                'source': stamp_source(
                    slot_id=slot_id,
                    proposal_id=proposal_id,
                    critique_id=critique_id,
                    default_type=default_source_type,
                    item=item,
                    hypothesis=hypothesis,
                ),
                'research_goal': research_goal,
                'created_at': created,
                'statement': hypothesis.get('statement'),
                'mechanism': hypothesis.get('mechanism'),
                'experimental_plan': hypothesis.get('experimental_plan'),
                'dependency_claim_ids': hypothesis.get('dependency_claim_ids') or [],
                'claim_chain': hypothesis.get('claim_chain') or [],
                'references': hypothesis.get('references') or [],
            }
        )

    return hyp_rows, blocked_rows, gap_rows, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow_result', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='hypotheses.jsonl')
    parser.add_argument(
        '--gaps_out',
        type=Path,
        default=None,
        help='gap_requests.jsonl (default: <out-dir>/gap_requests.jsonl)',
    )
    parser.add_argument(
        '--blocked_out',
        type=Path,
        default=None,
        help='blocked_hypotheses.jsonl — needs_claims finals kept out of the tournament '
        '(default: <out-dir>/blocked_hypotheses.jsonl)',
    )
    parser.add_argument('--seeds', type=Path, default=None, help='optional seeds.json for id checks')
    parser.add_argument(
        '--append',
        action='store_true',
        help='Append hypotheses (and this stage’s gaps) instead of replacing them',
    )
    parser.add_argument(
        '--source_type',
        default='generate',
        choices=sorted(SOURCE_TYPES),
        help='default source.type when the workflow row does not set source (default: generate)',
    )
    args = parser.parse_args()

    workflow = load_json(args.workflow_result)
    seeds = load_json(args.seeds) if args.seeds else None
    existing = load_jsonl(args.out) if args.append else []
    blocked_path = args.blocked_out or (args.out.parent / 'blocked_hypotheses.jsonl')
    existing_blocked = load_jsonl(blocked_path) if args.append and blocked_path.exists() else []

    hyp_rows, blocked_rows, gap_rows, warnings = build_rows(
        workflow,
        existing=existing,
        existing_blocked=existing_blocked,
        seeds=seeds,
        default_source_type=args.source_type,
    )
    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)

    final_hyps = existing + hyp_rows if args.append else hyp_rows
    write_jsonl(args.out, final_hyps)

    # Separate file so a blocked idea is recoverable but never ranked:
    # select_batch.py reads hypotheses.jsonl only.
    final_blocked = existing_blocked + blocked_rows if args.append else blocked_rows
    if final_blocked:
        write_jsonl(blocked_path, final_blocked)

    # Shared gap_requests.jsonl across propose/critique/revise. Without --append,
    # replace only this stage’s rows; keep other stages. With --append, concatenate.
    gaps_path = args.gaps_out or (args.out.parent / 'gap_requests.jsonl')
    if gaps_path.exists():
        prior_gaps = load_jsonl(gaps_path)
        if args.append:
            gap_rows = prior_gaps + gap_rows
        else:
            gap_rows = [g for g in prior_gaps if g.get('stage') != 'revise'] + gap_rows
    write_jsonl(gaps_path, gap_rows)

    print(
        json.dumps(
            {
                'hypotheses_path': str(args.out),
                'gap_requests_path': str(gaps_path),
                'blocked_hypotheses_path': str(blocked_path) if final_blocked else None,
                'blocked_count': len(final_blocked),
                'hypothesis_count': len(final_hyps),
                'new_hypotheses': len(hyp_rows) if args.append else len(final_hyps),
                'gap_request_count': len(gap_rows),
                'warning_count': len(warnings),
                'ok_count': workflow.get('ok_count'),
                'needs_claims_count': workflow.get('needs_claims_count'),
                'failed': workflow.get('failed'),
                'default_source_type': args.source_type,
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
