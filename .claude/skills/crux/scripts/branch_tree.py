#!/usr/bin/env python3
"""Carry a refining loop's dead ends forward, and generate its next frontier.

The deepen loop keeps a hypothesis across rounds but has no memory of what
has been *ruled out*, so later rounds re-propose branches earlier rounds
already killed. This holds that memory as an explicit tree and derives the
open frontier from it mechanically.

  python branch_tree.py init   --tree tree.json --premise "<root premise>"
  python branch_tree.py close  --tree tree.json --node N05a \\
      --why "..." --evidence proved --scope "..." --spawn N08:"<premise>"
  python branch_tree.py open   --tree tree.json --node N08 --parent N01 \\
      --premise "..." [--cost small] [--value "..."]
  python branch_tree.py check  --tree tree.json [--ledger closed.json]
  python branch_tree.py frontier --tree tree.json [--json]

The load-bearing rule is **scope discipline**. A closure is a wall only
inside the scope it states, so every closed node must carry three fields:

  WHY             the proof or computation that closed it
  EVIDENCE CLASS  proved | machine-verified | structural | empirical
  SCOPE BOUNDARY  exactly what the closure does NOT exclude

and must then either name the sibling nodes its boundary implies
(`--spawn`) or be marked `--exhausted "<reason>"`. `check` fails on any
closure missing a field or leaving its boundary unmined; that is the whole
point, because an over-scoped negative silently deletes live branches.

`frontier` is what the next round consumes: open nodes, plus any closure
whose boundary has not been turned into nodes yet, cheapest first.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = ('proved', 'machine-verified', 'structural', 'empirical')
COST_ORDER = {'small': 0, 'medium': 1, 'large': 2, '': 3}
OPEN_STATES = ('open', 'open-root', 'open-unexpanded', 'expanded')


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or 'nodes' not in data:
        raise ValueError(f'{path}: not a branch tree (no "nodes")')
    return data


def save(path: Path, tree: dict) -> None:
    tree['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    path.write_text(json.dumps(tree, indent=1) + '\n', encoding='utf-8')


def find(tree: dict, node_id: str) -> dict | None:
    for n in tree['nodes']:
        if n['id'] == node_id:
            return n
    return None


def next_id(tree: dict) -> str:
    used = {n['id'] for n in tree['nodes']}
    i = 1
    while f'N{i:02d}' in used:
        i += 1
    return f'N{i:02d}'


def cmd_init(a: argparse.Namespace) -> int:
    if a.tree.exists() and not a.force:
        print(f'{a.tree} exists (use --force to overwrite)', file=sys.stderr)
        return 2
    tree = {
        'run': a.run or a.tree.parent.name,
        'updated': '',
        'value_function': a.value_function,
        'nodes': [{'id': 'N01', 'parent': None, 'premise': a.premise,
                   'status': 'open-root'}],
    }
    save(a.tree, tree)
    print(f'wrote {a.tree}: root N01')
    return 0


def cmd_open(a: argparse.Namespace) -> int:
    tree = load(a.tree)
    node_id = a.node or next_id(tree)
    if find(tree, node_id):
        print(f'{node_id} already exists', file=sys.stderr)
        return 2
    if a.parent and not find(tree, a.parent):
        print(f'parent {a.parent} not found', file=sys.stderr)
        return 2
    node = {'id': node_id, 'parent': a.parent, 'premise': a.premise,
            'status': 'open-unexpanded'}
    if a.cost:
        node['cost'] = a.cost
    if a.value:
        node['value_note'] = a.value
    if a.source:
        node['source'] = a.source
    tree['nodes'].append(node)
    save(a.tree, tree)
    print(f'opened {node_id} under {a.parent}')
    return 0


def cmd_close(a: argparse.Namespace) -> int:
    tree = load(a.tree)
    node = find(tree, a.node)
    if node is None:
        print(f'{a.node} not found', file=sys.stderr)
        return 2
    if a.evidence not in EVIDENCE:
        print(f'--evidence must be one of {", ".join(EVIDENCE)}',
              file=sys.stderr)
        return 2
    if not a.spawn and not a.exhausted:
        print('a closure must either --spawn the siblings its boundary '
              'implies, or be --exhausted "<reason>". Scope boundaries that '
              'are never mined are how live branches get deleted.',
              file=sys.stderr)
        return 2

    spawned = []
    for spec in a.spawn:
        sid, _, premise = spec.partition(':')
        sid, premise = sid.strip(), premise.strip()
        if not premise:
            print(f'--spawn {spec!r}: expected ID:"premise"', file=sys.stderr)
            return 2
        if not sid:
            sid = next_id(tree)
        if find(tree, sid) is None:
            tree['nodes'].append({
                'id': sid, 'parent': node.get('parent') or node['id'],
                'premise': premise, 'status': 'open-unexpanded',
                'source': f'scope line of {node["id"]}'})
        spawned.append(sid)

    node['status'] = 'closed'
    node['why'] = a.why
    node['evidence_class'] = a.evidence
    node['scope_boundary'] = a.scope
    if a.closed_by:
        node['closed_by'] = a.closed_by
    if spawned:
        node['spawned'] = spawned
    if a.exhausted:
        node['boundary_exhausted'] = a.exhausted
    save(a.tree, tree)
    print(f'closed {a.node} ({a.evidence})'
          + (f'; spawned {", ".join(spawned)}' if spawned else '')
          + ('; boundary exhausted' if a.exhausted else ''))
    return 0


def problems(tree: dict) -> list[str]:
    out = []
    ids = {n['id'] for n in tree['nodes']}
    for n in tree['nodes']:
        if n.get('parent') and n['parent'] not in ids:
            out.append(f'{n["id"]}: parent {n["parent"]} missing')
        if n.get('status') != 'closed':
            continue
        for field, label in (('why', 'WHY'),
                             ('evidence_class', 'EVIDENCE CLASS'),
                             ('scope_boundary', 'SCOPE BOUNDARY')):
            if not n.get(field):
                out.append(f'{n["id"]}: closed without {label}')
        if n.get('evidence_class') and n['evidence_class'] not in EVIDENCE:
            out.append(f'{n["id"]}: evidence_class '
                       f'{n["evidence_class"]!r} not in {EVIDENCE}')
        if not n.get('spawned') and not n.get('boundary_exhausted'):
            out.append(f'{n["id"]}: scope boundary never mined '
                       f'(no spawned siblings, not marked exhausted)')
        for sid in n.get('spawned', []):
            if sid not in ids:
                out.append(f'{n["id"]}: spawned {sid} which does not exist')
    return out


def cmd_check(a: argparse.Namespace) -> int:
    tree = load(a.tree)
    errs = problems(tree)
    if a.ledger:
        errs += ledger_problems(a.ledger)
    for e in errs:
        print(f'  FAIL {e}')
    n_closed = sum(1 for n in tree['nodes'] if n.get('status') == 'closed')
    print(f'{len(tree["nodes"])} nodes, {n_closed} closed, '
          f'{len(errs)} problem(s)')
    return 1 if errs else 0


def ledger_problems(path: Path) -> list[str]:
    """Closed-branch ledger pages must carry the same three fields.

    EVIDENCE and SCOPE BOUNDARY are labelled markers. The why is the prose
    body that precedes them, so it is checked by length rather than by a
    literal 'WHY:' token -- demanding the token flags well-formed pages.
    """
    out = []
    try:
        doc = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return [f'{path}: unreadable ({exc})']
    for page in doc.get('pages', []):
        raw = page.get('text') or ''
        upper = raw.upper()
        if 'CLOSED' not in upper:
            continue
        where = page.get('page')
        for marker in ('EVIDENCE', 'SCOPE BOUNDARY'):
            if marker not in upper:
                out.append(f'{path.name} page {where}: '
                           f'closure without {marker}')
        head = raw[:upper.index('EVIDENCE')] if 'EVIDENCE' in upper else raw
        if len(head.split()) < 12:
            out.append(f'{path.name} page {where}: closure states no WHY '
                       f'(only {len(head.split())} words before EVIDENCE)')
    return out


def frontier(tree: dict) -> list[dict]:
    rows = []
    for n in tree['nodes']:
        status = n.get('status', '')
        if status in OPEN_STATES and status != 'expanded':
            rows.append({'id': n['id'], 'why_listed': status,
                         'premise': n.get('premise', ''),
                         'cost': n.get('cost', ''),
                         'value_note': n.get('value_note', '')})
        elif status == 'closed' and not n.get('spawned') \
                and not n.get('boundary_exhausted'):
            rows.append({'id': n['id'], 'why_listed': 'unmined-closure',
                         'premise': n.get('scope_boundary', ''),
                         'cost': n.get('cost', ''),
                         'value_note': 'boundary not turned into nodes'})
    rows.sort(key=lambda r: (COST_ORDER.get(r['cost'], 3), r['id']))
    return rows


def cmd_frontier(a: argparse.Namespace) -> int:
    tree = load(a.tree)
    rows = frontier(tree)
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    if not rows:
        print('frontier empty: every branch closed and every boundary mined')
        return 0
    print(f'{len(rows)} node(s) on the frontier, cheapest first:\n')
    for r in rows:
        print(f'  {r["id"]}  [{r["why_listed"]}]'
              + (f'  cost={r["cost"]}' if r['cost'] else ''))
        print(f'      {r["premise"]}')
        if r['value_note']:
            print(f'      value: {r["value_note"]}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('init', help='create a tree with a root premise')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--premise', required=True)
    p.add_argument('--run', default='')
    p.add_argument('--value_function', default='main (rounds of the deepen loop)')
    p.add_argument('--force', action='store_true')
    p.set_defaults(func=cmd_init)

    p = sub.add_parser('open', help='add an open node')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--node', default='', help='id (default: next free)')
    p.add_argument('--parent', required=True)
    p.add_argument('--premise', required=True)
    p.add_argument('--cost', default='', choices=['', 'small', 'medium', 'large'])
    p.add_argument('--value', default='')
    p.add_argument('--source', default='')
    p.set_defaults(func=cmd_open)

    p = sub.add_parser('close', help='close a node with scope discipline')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--node', required=True)
    p.add_argument('--why', required=True, help='the proof or computation')
    p.add_argument('--evidence', required=True, choices=list(EVIDENCE))
    p.add_argument('--scope', required=True,
                   help='exactly what this closure does NOT exclude')
    p.add_argument('--closed_by', default='', help='claim id, if banked')
    p.add_argument('--spawn', action='append', default=[],
                   metavar='ID:"premise"',
                   help='sibling implied by the boundary (repeatable)')
    p.add_argument('--exhausted', default='',
                   help='use only when the boundary implies no sibling; give the reason')
    p.set_defaults(func=cmd_close)

    p = sub.add_parser('check', help='fail on over-scoped or unmined closures')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--ledger', type=Path, help='closed-branches ledger json')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('frontier', help='what the next round should expand')
    p.add_argument('--tree', required=True, type=Path)
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_frontier)

    a = parser.parse_args()
    return a.func(a)


if __name__ == '__main__':
    raise SystemExit(main())
