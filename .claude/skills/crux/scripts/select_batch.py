#!/usr/bin/env python3
"""Pick ≤9 hypotheses for a tournament cycle (Elo stays private).

Reads hypotheses.jsonl + optional elo.jsonl. Writes a batch JSON for the judge
workflow with science fields only — never Elo.

Selection is **match-band first**: take only from the lowest Elo `matches`
count (finish that layer before the next). Shuffle within the band. If the
band has fewer than 2 hyps, spill into the next band(s) so a valid batch still
runs. Pass --ids to force a set.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS / 'lib'
for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from jsonl_io import load_jsonl  # noqa: E402

BATCH_FIELDS = (
    'id',
    'slot_id',
    'statement',
    'mechanism',
    'experimental_plan',
    'dependency_claim_ids',
    'claim_chain',
    'references',
    'research_goal',
)


def load_elo(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    by_id: dict[str, dict] = {}
    for row in load_jsonl(path):
        hid = row.get('hypothesis_id')
        if isinstance(hid, str) and hid:
            by_id[hid] = row
    return by_id


def match_count(elo: dict[str, dict], hid: str) -> int:
    return int(elo.get(hid, {}).get('matches') or 0)


def public_hyp(row: dict) -> dict:
    out = {k: row.get(k) for k in BATCH_FIELDS if k in row}
    out['id'] = row.get('id')
    return out


def select_band_first(
    pool: list[str],
    elo: dict[str, dict],
    size: int,
    rng: random.Random,
) -> tuple[list[str], int]:
    """Fill a batch from the lowest match band, then spill only if needed."""
    if len(pool) < 2:
        raise SystemExit('need at least 2 hypotheses to form a batch')

    by_matches: dict[int, list[str]] = {}
    for hid in pool:
        by_matches.setdefault(match_count(elo, hid), []).append(hid)
    bands = sorted(by_matches.keys())
    min_band = bands[0]

    chosen: list[str] = []
    for band in bands:
        layer = list(by_matches[band])
        rng.shuffle(layer)
        if not chosen:
            # Primary layer: take up to size; do not pad from higher bands
            # unless this layer alone cannot make a legal batch (>=2).
            if len(layer) >= 2:
                take = min(size, len(layer))
                chosen.extend(layer[:take])
                break
            chosen.extend(layer)
            continue
        # Spill only to reach a legal batch of >=2 (never to pad to full size).
        need = max(0, 2 - len(chosen))
        if need <= 0:
            break
        chosen.extend(layer[:need])
        if len(chosen) >= 2:
            break

    if len(chosen) < 2:
        raise SystemExit('could not form a batch of >= 2 hypotheses')
    return chosen[:size], min_band


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hypotheses', required=True, type=Path)
    parser.add_argument('--elo', type=Path, default=None, help='private elo.jsonl')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--size', type=int, default=9)
    parser.add_argument('--ids', default=None, help='comma-separated hypothesis ids')
    parser.add_argument('--rng_seed', type=int, default=1)
    parser.add_argument('--research_goal', default=None)
    args = parser.parse_args()

    if args.size < 2:
        raise SystemExit('--size must be >= 2')

    rows = load_jsonl(args.hypotheses)
    by_id = {r['id']: r for r in rows if isinstance(r.get('id'), str)}
    if not by_id:
        raise SystemExit('no hypotheses')

    elo = load_elo(args.elo)
    rng = random.Random(args.rng_seed)

    match_hist: dict[int, int] = {}
    for hid in by_id:
        m = match_count(elo, hid)
        match_hist[m] = match_hist.get(m, 0) + 1
    min_matches_pool = min(match_hist) if match_hist else 0
    at_min = match_hist.get(min_matches_pool, 0)

    if args.ids:
        ids = [p.strip() for p in args.ids.split(',') if p.strip()]
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise SystemExit(f'unknown ids: {", ".join(missing[:8])}')
        if len(ids) < 2:
            raise SystemExit('--ids needs at least 2 hypotheses')
        if len(ids) > args.size:
            raise SystemExit(f'--ids has {len(ids)} entries; --size is {args.size}')
        band_used = min(match_count(elo, i) for i in ids)
    else:
        ids, band_used = select_band_first(list(by_id.keys()), elo, args.size, rng)

    batch = [public_hyp(by_id[i]) for i in ids]
    payload = {
        'schema_version': '1.0',
        'research_goal': args.research_goal,
        'hypothesis_ids': ids,
        'hypotheses': batch,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(
        json.dumps(
            {
                'out': str(args.out),
                'count': len(ids),
                'ids': ids,
                'pool_size': len(by_id),
                'match_band': band_used,
                'min_matches_in_pool': min_matches_pool,
                'pool_at_min_matches': at_min,
                'match_histogram': {str(k): v for k, v in sorted(match_hist.items())},
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
