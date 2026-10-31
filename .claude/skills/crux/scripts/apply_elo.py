#!/usr/bin/env python3
"""Update private Elo from a final ranking (agents never see this file).

Base Elo 1000. Treat the ordered list as a round-robin: each higher-ranked
hypothesis beats each lower-ranked one. K shrinks as Elo rises so climbs get
harder.

  K = max(K_MIN, K_BASE * (BASE / max(elo, BASE)))

Writes/updates elo.jsonl rows: {hypothesis_id, elo, matches, updated_at}.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS / 'lib'
for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from jsonl_io import load_jsonl, write_jsonl  # noqa: E402

BASE = 1000.0
K_BASE = 32.0
K_MIN = 8.0
SCALE = 400.0


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected object')
    return data


def k_for(elo: float) -> float:
    return max(K_MIN, K_BASE * (BASE / max(elo, BASE)))


def expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (b - a) / SCALE))


def apply_ranking(elo: dict[str, dict], ranked_ids: list[str]) -> dict[str, dict]:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Working copy of ratings for simultaneous update within the cycle.
    current = {
        hid: float(elo.get(hid, {}).get('elo') or BASE) for hid in ranked_ids
    }
    matches = {
        hid: int(elo.get(hid, {}).get('matches') or 0) for hid in ranked_ids
    }
    delta = {hid: 0.0 for hid in ranked_ids}

    for i, winner in enumerate(ranked_ids):
        for loser in ranked_ids[i + 1 :]:
            ea = expected(current[winner], current[loser])
            eb = 1.0 - ea
            ka = k_for(current[winner])
            kb = k_for(current[loser])
            delta[winner] += ka * (1.0 - ea)
            delta[loser] += kb * (0.0 - eb)

    out = dict(elo)
    for hid in ranked_ids:
        new_elo = current[hid] + delta[hid]
        out[hid] = {
            'hypothesis_id': hid,
            'elo': round(new_elo, 3),
            'matches': matches[hid] + (len(ranked_ids) - 1),
            'updated_at': now,
            'last_delta': round(delta[hid], 3),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--ranking',
        required=True,
        type=Path,
        help='judge JSON with ranked_ids[]',
    )
    parser.add_argument('--elo', required=True, type=Path, help='elo.jsonl (read+write)')
    parser.add_argument(
        '--history',
        type=Path,
        default=None,
        help='append-only cycle log (default: <elo-dir>/cycles.jsonl)',
    )
    args = parser.parse_args()

    payload = load_json(args.ranking)
    ranked = payload.get('ranked_ids')
    if not isinstance(ranked, list) or len(ranked) < 2:
        raise SystemExit('ranked_ids must be a list of >= 2 ids')
    if not all(isinstance(x, str) and x for x in ranked):
        raise SystemExit('ranked_ids must be non-empty strings')
    if len(set(ranked)) != len(ranked):
        raise SystemExit('ranked_ids must be unique')

    existing_rows = load_jsonl(args.elo) if args.elo.exists() else []
    by_id = {
        r['hypothesis_id']: r
        for r in existing_rows
        if isinstance(r, dict) and isinstance(r.get('hypothesis_id'), str)
    }
    updated = apply_ranking(by_id, ranked)
    # Preserve ids not in this batch; overwrite batch ids.
    merged = {**by_id, **{hid: updated[hid] for hid in ranked}}
    rows = sorted(merged.values(), key=lambda r: (-float(r.get('elo') or BASE), r['hypothesis_id']))
    write_jsonl(args.elo, rows)

    history_path = args.history or (args.elo.parent / 'cycles.jsonl')
    history_path.parent.mkdir(parents=True, exist_ok=True)
    cycle = {
        'ranked_ids': ranked,
        'weights': payload.get('weights'),
        'scores': payload.get('scores'),
        'applied_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'elo_after': {hid: updated[hid]['elo'] for hid in ranked},
        'delta': {hid: updated[hid]['last_delta'] for hid in ranked},
    }
    with history_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(cycle, ensure_ascii=False) + '\n')

    print(
        json.dumps(
            {
                'elo_path': str(args.elo),
                'history_path': str(history_path),
                'ranked_ids': ranked,
                'elo_after': cycle['elo_after'],
                'delta': cycle['delta'],
            },
            indent=2,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
