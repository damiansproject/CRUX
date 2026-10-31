#!/usr/bin/env python3
"""Create initial seed packs from claims.jsonl (new seeds.json).

This is the *first* seed step. To add a paper later after a gap, use
add_seed_claims.py --from_claims.

Preferred: --manual_papers (main names which papers share a slot).
Each slot is those papers plus *all* of their extracted claims. Propose
reads the papers and composes them.

Fallbacks: --slots (random paper packs, for diversity experiments),
--manual (exact claim ids).

Each slot embeds full claim objects (statements + all verbatim quotes) —
intentional; quality over cost. Do not slim seeds before /crux-propose.
Reports mean source_quality per slot and overall (measurement only).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path


def paper_pack_key(paper_ids: list) -> str:
    ids = [
        pid
        for pid in paper_ids
        if isinstance(pid, str) and pid
    ]
    return ','.join(sorted(set(ids)))


def load_attempt_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    with path.open(encoding='utf-8-sig') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and isinstance(row.get('pack_key'), str) and row['pack_key']:
                keys.add(row['pack_key'])
    return keys


def append_attempts(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def load_claims(path: Path) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    with path.open(encoding='utf-8-sig') as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                claim = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{line_no}: invalid JSON: {exc}') from exc
            claim_id = claim.get('id')
            if not isinstance(claim_id, str) or not claim_id:
                raise ValueError(f'{path}:{line_no}: claim missing id')
            if claim_id in by_id:
                raise ValueError(f'duplicate claim id: {claim_id}')
            pid = claim.get('paper_id')
            if not isinstance(pid, str) or not pid:
                raise ValueError(f'{path}:{line_no}: claim {claim_id} has no paper_id; re-run write_claims')
            by_id[claim_id] = claim
    if not by_id:
        raise ValueError(f'no claims in {path}')
    return by_id


def resolve_ids(by_id: dict[str, dict], claim_ids: list[str]) -> list[dict]:
    missing = [cid for cid in claim_ids if cid not in by_id]
    if missing:
        preview = ', '.join(missing[:5])
        more = '' if len(missing) <= 5 else f' (+{len(missing) - 5} more)'
        raise ValueError(f'unknown claim id(s): {preview}{more}')
    return [by_id[cid] for cid in claim_ids]


def parse_id_list(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.replace('\n', ',').split(',')]
    return [p for p in parts if p]


def paper_ids_of_claims(claims: list[dict]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        pid = claim.get('paper_id')
        if isinstance(pid, str) and pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    return ids


def load_paper_paths(cleaned_jsons: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
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
                    paths[pid] = text_path
    return paths


def attach_papers(
    slot: dict,
    *,
    path_map: dict[str, str],
    cleaned_jsons: Path,
) -> None:
    paper_ids = paper_ids_of_claims(slot.get('claims') or [])
    slot['paper_ids'] = paper_ids
    rows = []
    for pid in paper_ids:
        text_path = path_map.get(pid)
        if text_path is None:
            candidate = cleaned_jsons / f'{pid}.json'
            if candidate.exists():
                text_path = str(candidate.resolve())
        rows.append({'paper_id': pid, 'text_path': text_path})
    slot['papers'] = rows


def build_manual_slots(
    by_id: dict[str, dict],
    manual_lists: list[str],
) -> list[dict]:
    slots = []
    for index, raw in enumerate(manual_lists, start=1):
        claim_ids = parse_id_list(raw)
        if not claim_ids:
            raise ValueError(f'manual slot {index} is empty')
        claims = resolve_ids(by_id, claim_ids)
        slots.append(
            {
                'slot_id': f'seed-{index:04d}',
                'mode': 'manual',
                'rng_seed': None,
                'claim_ids': claim_ids,
                'claims': claims,
            }
        )
    return slots


def mean_source_quality(claims: list[dict]) -> float | None:
    vals = [
        float(c['source_quality'])
        for c in claims
        if isinstance(c.get('source_quality'), (int, float)) and not isinstance(c.get('source_quality'), bool)
    ]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def claims_by_paper(by_id: dict[str, dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for cid, claim in by_id.items():
        grouped.setdefault(claim['paper_id'], []).append(cid)
    return grouped


def build_directed_paper_slots(
    by_id: dict[str, dict],
    paper_lists: list[str],
    *,
    start_index: int,
) -> list[dict]:
    grouped = claims_by_paper(by_id)
    slots = []
    for offset, raw in enumerate(paper_lists):
        paper_ids = parse_id_list(raw)
        if not paper_ids:
            raise ValueError(f'--manual_papers slot {offset + 1} is empty')
        seen: set[str] = set()
        ordered: list[str] = []
        for pid in paper_ids:
            if pid not in seen:
                seen.add(pid)
                ordered.append(pid)
        missing = [pid for pid in ordered if pid not in grouped]
        if missing:
            raise ValueError(
                'unknown paper_id(s) (extract first): ' + ', '.join(missing[:8])
            )
        claim_ids: list[str] = []
        for pid in ordered:
            claim_ids.extend(grouped[pid])
        claims = [by_id[cid] for cid in claim_ids]
        index = start_index + offset
        slots.append(
            {
                'slot_id': f'seed-{index:04d}',
                'mode': 'paper',
                'rng_seed': None,
                'sample': 'directed',
                'mean_source_quality': mean_source_quality(claims),
                'claim_ids': claim_ids,
                'claims': claims,
            }
        )
    return slots


def build_paper_slots(
    by_id: dict[str, dict],
    *,
    slot_count: int,
    papers_per_slot: int,
    rng_seed: int,
    start_index: int,
) -> list[dict]:
    grouped = claims_by_paper(by_id)
    paper_ids = list(grouped)
    if slot_count < 1:
        raise ValueError('--slots must be >= 1')
    if not paper_ids:
        raise ValueError('no papers on claims (need paper_id)')
    k = min(max(papers_per_slot, 1), len(paper_ids))

    rng = random.Random(rng_seed)
    remaining = list(paper_ids)
    rng.shuffle(remaining)
    slots = []
    for offset in range(slot_count):
        index = start_index + offset
        if len(remaining) < k:
            remaining = list(paper_ids)
            rng.shuffle(remaining)
        chosen = remaining[:k]
        remaining = remaining[k:]
        claim_ids: list[str] = []
        for pid in chosen:
            claim_ids.extend(grouped[pid])
        claims = [by_id[cid] for cid in claim_ids]
        slots.append(
            {
                'slot_id': f'seed-{index:04d}',
                'mode': 'paper',
                'rng_seed': rng_seed,
                'sample': 'paper',
                'mean_source_quality': mean_source_quality(claims),
                'claim_ids': claim_ids,
                'claims': claims,
            }
        )
    return slots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claims', required=True, type=Path, help='claims.jsonl from write_claims')
    parser.add_argument('--out', required=True, type=Path, help='Output seeds.json path')
    parser.add_argument(
        '--manual_papers',
        action='append',
        default=[],
        metavar='PAPER,PAPER,...',
        help='Main-chosen paper pack (all claims of those papers). Repeatable. Prefer this over --slots.',
    )
    parser.add_argument(
        '--manual',
        action='append',
        default=[],
        metavar='ID,ID,...',
        help='Manual seed pack (claim ids). Repeatable.',
    )
    parser.add_argument(
        '--manual_file',
        type=Path,
        default=None,
        help='Optional file: one manual pack per line (comma-separated claim ids)',
    )
    parser.add_argument(
        '--slots',
        type=int,
        default=0,
        help='Random paper packs to add (fallback; default 0). Prefer --manual_papers.',
    )
    parser.add_argument(
        '--papers_per_slot',
        type=int,
        default=2,
        help='Papers per random --slots pack (not a cap on --manual_papers)',
    )
    parser.add_argument(
        '--cleaned_jsons',
        type=Path,
        required=True,
        help='cleaned_jsons/ so each slot records papers[].text_path',
    )
    parser.add_argument(
        '--rng_seed',
        type=int,
        default=1,
        help='RNG seed for random paper packs (default 1)',
    )
    parser.add_argument(
        '--total_slots',
        type=int,
        default=None,
        help='If set, fill with random packs until this many total slots '
        '(after --manual_papers/--manual). Overrides --slots when those are present.',
    )
    args = parser.parse_args(argv)

    try:
        by_id = load_claims(args.claims)
        manuals = list(args.manual)
        if args.manual_file is not None:
            text = args.manual_file.read_text(encoding='utf-8')
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    manuals.append(line)

        slots = build_manual_slots(by_id, manuals)
        slots.extend(
            build_directed_paper_slots(
                by_id, list(args.manual_papers), start_index=len(slots) + 1
            )
        )

        random_count = args.slots
        if args.total_slots is not None:
            if args.total_slots < len(slots):
                raise ValueError(
                    f'--total_slots {args.total_slots} < existing directed/manual slots {len(slots)}'
                )
            random_count = args.total_slots - len(slots)

        if random_count > 0:
            slots.extend(
                build_paper_slots(
                    by_id,
                    slot_count=random_count,
                    papers_per_slot=args.papers_per_slot,
                    rng_seed=args.rng_seed,
                    start_index=len(slots) + 1,
                )
            )

        if not slots:
            raise ValueError(
                'nothing to write: pass --manual_papers (preferred) and/or --manual / --slots'
            )

        path_map = load_paper_paths(args.cleaned_jsons)
        for slot in slots:
            if 'mean_source_quality' not in slot:
                slot['mean_source_quality'] = mean_source_quality(slot['claims'])
            attach_papers(slot, path_map=path_map, cleaned_jsons=args.cleaned_jsons)
        missing_paths = [
            f"{slot['slot_id']}/{row.get('paper_id')}"
            for slot in slots
            for row in (slot.get('papers') or [])
            if isinstance(row, dict)
            and row.get('paper_id')
            and not (isinstance(row.get('text_path'), str) and row.get('text_path'))
        ]
        if missing_paths:
            raise ValueError(
                'no cleaned JSON found for: '
                + ', '.join(missing_paths[:8])
                + '; convert/extract that paper first'
            )

        means = [s['mean_source_quality'] for s in slots if s.get('mean_source_quality') is not None]
        overall_mean = round(sum(means) / len(means), 4) if means else None
        directed_slots = sum(1 for s in slots if s.get('sample') == 'directed')
        random_slots = sum(1 for s in slots if s.get('sample') == 'paper')

        payload = {
            'schema_version': '1.0',
            'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'claims_path': str(args.claims.resolve()),
            'slot_count': len(slots),
            'manual_slots': sum(1 for s in slots if s['mode'] == 'manual'),
            'directed_slots': directed_slots,
            'random_slots': random_slots,
            'rng_seed': args.rng_seed if random_count > 0 else None,
            'sample': 'paper' if random_count > 0 else None,
            'papers_per_slot': args.papers_per_slot if random_count > 0 else None,
            'mean_source_quality': overall_mean,
            'slots': slots,
        }

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        attempts_path = args.out.parent / 'seed_attempts.jsonl'
        prior_keys = load_attempt_keys(attempts_path)
        created = payload['created_at']
        attempt_rows = []
        repeats = []
        for slot in slots:
            paper_ids = slot['paper_ids']
            key = paper_pack_key(paper_ids)
            if key in prior_keys:
                repeats.append(f"{slot['slot_id']}:{key}")
            attempt_rows.append(
                {
                    'created_at': created,
                    'kind': 'seed',
                    'slot_id': slot['slot_id'],
                    'pack_key': key,
                    'paper_ids': paper_ids,
                    'sample': slot.get('sample'),
                    'seeds_path': str(args.out),
                }
            )
            prior_keys.add(key)
        if attempt_rows:
            append_attempts(attempts_path, attempt_rows)
        for item in repeats:
            print(f'warning: repeated paper pack (see seed_attempts.jsonl): {item}', file=sys.stderr)
        print(
            f'wrote {args.out} '
            f'({payload["slot_count"]} slots: '
            f'{payload["manual_slots"]} manual, {directed_slots} directed, '
            f'{random_slots} random-paper'
            + (f'; mean_source_quality={overall_mean}' if overall_mean is not None else '')
            + ')'
        )
        print(f'wrote {attempts_path} ({len(attempt_rows)} attempts)')
        return 0
    except Exception as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
