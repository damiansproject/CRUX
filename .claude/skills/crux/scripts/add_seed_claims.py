#!/usr/bin/env python3
"""Add papers into an *existing* seed slot after a gap is fulfilled.

Not for creating seeds — use create_seeds.py for that.

Gap fulfill: **search the claim pool**, then drag that hit's **paper**.

  python add_seed_claims.py --seeds seeds.json --slot seed-0001 \\
    --from_claims clm_x,clm_y --claims claims.jsonl --out seeds.json \\
    --cleaned_jsons cleaned_jsons

`--from_claims` expands each id to its paper_id and adds *all* claims of
those papers plus text_path. `--add_papers` if you already know the paper.
Does not mint ids.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected JSON object')
    return data


def load_claims(path: Path) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    with path.open(encoding='utf-8-sig') as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            claim = json.loads(line)
            cid = claim.get('id') if isinstance(claim, dict) else None
            if not isinstance(cid, str) or not cid:
                raise ValueError(f'{path}:{line_no}: claim missing id')
            by_id[cid] = claim
    return by_id


def parse_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace('\n', ',').split(',')]
    return [p for p in parts if p]


def paper_pack_key(paper_ids: list) -> str:
    ids = [pid for pid in paper_ids if isinstance(pid, str) and pid]
    return ','.join(sorted(set(ids)))


def append_attempt(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def paper_ids_for_claims(
    by_id: dict[str, dict], claim_ids: list[str]
) -> tuple[list[str], list[str], list[str]]:
    missing: list[str] = []
    no_paper: list[str] = []
    papers: list[str] = []
    seen: set[str] = set()
    for cid in claim_ids:
        claim = by_id.get(cid)
        if claim is None:
            missing.append(cid)
            continue
        pid = claim.get('paper_id')
        if not isinstance(pid, str) or not pid:
            no_paper.append(cid)
            continue
        if pid not in seen:
            seen.add(pid)
            papers.append(pid)
    return papers, missing, no_paper


def claim_ids_for_papers(by_id: dict[str, dict], paper_ids: list[str]) -> tuple[list[str], list[str]]:
    wanted = set(paper_ids)
    found: set[str] = set()
    ids: list[str] = []
    for cid, claim in by_id.items():
        pid = claim.get('paper_id')
        if pid in wanted:
            found.add(pid)
            ids.append(cid)
    missing = [pid for pid in paper_ids if pid not in found]
    return ids, missing


def refresh_papers(target: dict, *, cleaned_jsons: Path) -> None:
    claims = list(target.get('claims') or [])
    paper_ids: list[str] = []
    seen: set[str] = set()
    path_map = {
        row['paper_id']: row.get('text_path')
        for row in (target.get('papers') or [])
        if isinstance(row, dict) and isinstance(row.get('paper_id'), str)
    }
    for claim in claims:
        pid = claim.get('paper_id')
        if isinstance(pid, str) and pid and pid not in seen:
            seen.add(pid)
            paper_ids.append(pid)
    target['paper_ids'] = paper_ids
    index = cleaned_jsons / 'index.json'
    if index.exists():
        data = json.loads(index.read_text(encoding='utf-8-sig'))
        papers = data.get('papers') if isinstance(data, dict) else None
        if isinstance(papers, list):
            for row in papers:
                if not isinstance(row, dict):
                    continue
                pid = row.get('paper_id')
                text_path = row.get('text_path')
                if isinstance(pid, str) and pid and isinstance(text_path, str) and text_path:
                    if not path_map.get(pid):
                        path_map[pid] = text_path
    for pid in paper_ids:
        if path_map.get(pid):
            continue
        candidate = cleaned_jsons / f'{pid}.json'
        if candidate.exists():
            path_map[pid] = str(candidate.resolve())
    target['papers'] = [
        {'paper_id': pid, 'text_path': path_map.get(pid)} for pid in paper_ids
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', required=True, type=Path)
    parser.add_argument('--slot', required=True, help='existing slot_id to append into')
    parser.add_argument(
        '--from_claims',
        default=None,
        help='gap fulfill: claim ids whose papers are dragged in full (all claims + text_path)',
    )
    parser.add_argument(
        '--add_papers',
        default=None,
        help='comma-separated paper ids; adds ALL claims of those papers',
    )
    parser.add_argument('--claims', required=True, type=Path, help='claims.jsonl pool')
    parser.add_argument(
        '--cleaned_jsons',
        type=Path,
        required=True,
        help='cleaned_jsons/ to fill papers[].text_path for newly added papers',
    )
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()

    seeds = load_json(args.seeds)
    slots = seeds.get('slots')
    if not isinstance(slots, list):
        raise SystemExit('seeds.json missing slots[]')
    target = None
    for slot in slots:
        if isinstance(slot, dict) and slot.get('slot_id') == args.slot:
            target = slot
            break
    if target is None:
        raise SystemExit(f'slot not found: {args.slot}')

    add_paper_ids = parse_ids(args.add_papers)
    from_claim_ids = parse_ids(args.from_claims)
    if not add_paper_ids and not from_claim_ids:
        raise SystemExit('pass --from_claims (preferred for gaps) and/or --add_papers')

    by_id = load_claims(args.claims)
    dragged, missing_from, no_paper = paper_ids_for_claims(by_id, from_claim_ids)
    if missing_from:
        raise SystemExit(f'unknown claim id(s): {", ".join(missing_from[:8])}')
    if no_paper:
        raise SystemExit(
            'from_claims missing paper_id: ' + ', '.join(no_paper[:8])
        )
    for pid in dragged:
        if pid not in add_paper_ids:
            add_paper_ids.append(pid)
    paper_claim_ids, missing_papers = claim_ids_for_papers(by_id, add_paper_ids)
    if missing_papers:
        raise SystemExit(
            'no claims for paper_id(s): '
            + ', '.join(missing_papers[:8])
            + '; extract that paper first'
        )

    claim_ids = list(target.get('claim_ids') or [])
    claims = list(target.get('claims') or [])
    have = set(claim_ids)
    added_claims: list[str] = []
    for cid in paper_claim_ids:
        if cid in have:
            continue
        claim_ids.append(cid)
        claims.append(by_id[cid])
        have.add(cid)
        added_claims.append(cid)

    target['claim_ids'] = claim_ids
    target['claims'] = claims
    refresh_papers(target, cleaned_jsons=args.cleaned_jsons)
    missing_paths = [
        row.get('paper_id')
        for row in (target.get('papers') or [])
        if isinstance(row, dict)
        and row.get('paper_id')
        and not (isinstance(row.get('text_path'), str) and row.get('text_path'))
    ]
    if missing_paths:
        raise SystemExit(
            'no cleaned JSON found for paper_id(s): '
            + ', '.join(str(p) for p in missing_paths[:8])
            + '; convert/extract that paper first'
        )
    added_papers: list[str] = []
    seen_added_papers: set[str] = set()
    for cid in added_claims:
        pid = by_id[cid].get('paper_id')
        if isinstance(pid, str) and pid and pid not in seen_added_papers:
            seen_added_papers.add(pid)
            added_papers.append(pid)
    if 'enrichments' not in target or not isinstance(target.get('enrichments'), list):
        target['enrichments'] = []
    target['enrichments'].append(
        {
            'from_claim_ids': from_claim_ids,
            'added_paper_ids': added_papers,
            'added_claim_ids': added_claims,
        }
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seeds, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    attempts_path = args.out.parent / 'seed_attempts.jsonl'
    paper_ids = [p for p in (target.get('paper_ids') or []) if isinstance(p, str)]
    key = paper_pack_key(paper_ids)
    if key:
        append_attempt(
            attempts_path,
            {
                'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'kind': 'enrich',
                'slot_id': args.slot,
                'pack_key': key,
                'paper_ids': paper_ids,
                'from_claim_ids': from_claim_ids,
                'added_paper_ids': added_papers,
                'seeds_path': str(args.out),
            },
        )
    print(
        json.dumps(
            {
                'slot_id': args.slot,
                'from_claim_ids': from_claim_ids,
                'added_paper_ids': added_papers,
                'added': added_claims,
                'claim_count': len(claim_ids),
                'paper_count': len(target.get('paper_ids') or []),
                'out': str(args.out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.exit(0)
