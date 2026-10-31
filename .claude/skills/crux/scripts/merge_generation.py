#!/usr/bin/env python3
"""Merge propose/critique/revise shards into banked jsonl via write_*.py.

  python merge_generation.py --stage propose --shards "$RUN/shards/propose" \\
    --run "$RUN" --research_goal "..." --seeds "$RUN/seeds.json"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS / 'lib'
for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from jsonl_io import load_json  # noqa: E402

STAGES = ('propose', 'critique', 'revise')

STAGE_RESULT_NAME = {
    'propose': 'propose_result.json',
    'critique': 'critique_result.json',
    'revise': 'revise_result.json',
}

STAGE_WRITER = {
    'propose': _SCRIPTS / 'write_proposals.py',
    'critique': _SCRIPTS / 'write_critiques.py',
    'revise': _SCRIPTS / 'write_hypotheses.py',
}

STAGE_OUT_NAME = {
    'propose': 'proposals.jsonl',
    'critique': 'critiques.jsonl',
    'revise': 'hypotheses.jsonl',
}

REQUIRED_KEYS = {
    'propose': ('slot_id', 'strategy', 'status', 'gap_requests'),
    'critique': ('slot_id', 'proposal_id', 'status', 'gap_requests'),
    'revise': ('slot_id', 'proposal_id', 'status', 'gap_requests'),
}


def unwrap_shard(path: Path, stage: str) -> dict:
    data = load_json(path)
    if 'result' in data and isinstance(data['result'], dict):
        declared = data.get('stage')
        if isinstance(declared, str) and declared and declared != stage:
            raise ValueError(f'{path}: envelope stage {declared!r} != {stage!r}')
        item = dict(data['result'])
    else:
        item = dict(data)
    if not isinstance(item, dict):
        raise ValueError(f'{path}: shard result must be an object')
    for key in REQUIRED_KEYS[stage]:
        if key not in item:
            raise ValueError(f'{path}: missing required key {key!r}')
    return item


def load_shards(shards_dir: Path, stage: str) -> list[dict]:
    if not shards_dir.is_dir():
        raise ValueError(f'shards dir not found: {shards_dir}')
    paths = sorted(
        p
        for p in shards_dir.glob('*.json')
        if p.is_file() and not p.name.startswith('.')
    )
    if not paths:
        raise ValueError(f'no *.json shards in {shards_dir}')
    return [unwrap_shard(p, stage) for p in paths]


def count_status(results: list[dict], *, ok_values: set[str], needs_key: str) -> tuple[int, int]:
    ok = sum(1 for r in results if r.get('status') in ok_values)
    needs = sum(1 for r in results if r.get('status') == needs_key)
    return ok, needs


def build_workflow(
    *,
    stage: str,
    results: list[dict],
    research_goal: str,
    model: str | None,
    effort: str | None,
) -> dict:
    workflow: dict = {
        'model': model,
        'effort': effort,
        'results': results,
        'merged_from_shards': True,
        'shard_count': len(results),
        'research_goal': research_goal,
        'failed': [],
    }
    if stage == 'propose':
        ok_count, needs_count = count_status(results, ok_values={'ok'}, needs_key='needs_claims')
        workflow['ok_count'] = ok_count
        workflow['needs_claims_count'] = needs_count
        workflow['strategies'] = sorted(
            {r['strategy'] for r in results if isinstance(r.get('strategy'), str)}
        )
        return workflow
    if stage == 'critique':
        ok_count, needs_count = count_status(results, ok_values={'pass'}, needs_key='needs_claims')
        workflow['pass_count'] = ok_count
        workflow['needs_claims_count'] = needs_count
        return workflow
    ok_count, needs_count = count_status(results, ok_values={'ok'}, needs_key='needs_claims')
    workflow['ok_count'] = ok_count
    workflow['needs_claims_count'] = needs_count
    return workflow


def run_writer(
    *,
    stage: str,
    workflow_result: Path,
    out: Path,
    seeds: Path | None,
    gaps_out: Path | None,
    append: bool,
    source_type: str | None,
) -> int:
    cmd = [
        sys.executable,
        str(STAGE_WRITER[stage]),
        '--workflow_result',
        str(workflow_result),
        '--out',
        str(out),
    ]
    if append:
        cmd.append('--append')
    if gaps_out is not None:
        cmd.extend(['--gaps_out', str(gaps_out)])
    if stage in ('propose', 'revise') and seeds is not None:
        cmd.extend(['--seeds', str(seeds)])
    if stage == 'revise' and source_type is not None:
        cmd.extend(['--source_type', source_type])
    return int(subprocess.run(cmd, check=False).returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, choices=STAGES)
    parser.add_argument('--shards', required=True, type=Path)
    parser.add_argument('--run', type=Path, default=None)
    parser.add_argument('--workflow_result_out', type=Path, default=None)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--research_goal', type=str, default=None)
    parser.add_argument('--model', type=str, default=None)
    parser.add_argument('--effort', type=str, default=None)
    parser.add_argument('--seeds', type=Path, default=None)
    parser.add_argument('--gaps_out', type=Path, default=None)
    parser.add_argument('--append', action='store_true')
    parser.add_argument(
        '--source_type',
        default=None,
        choices=['generate', 'feedback', 'manual', 'evolution'],
    )
    parser.add_argument('--aggregate_only', action='store_true')
    args = parser.parse_args(argv)

    if args.research_goal is None or not str(args.research_goal).strip():
        print('error: --research_goal is required', file=sys.stderr)
        return 1

    try:
        results = load_shards(args.shards, args.stage)
        workflow = build_workflow(
            stage=args.stage,
            results=results,
            research_goal=args.research_goal.strip(),
            model=args.model,
            effort=args.effort,
        )
    except Exception as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1

    if args.workflow_result_out is not None:
        result_path = args.workflow_result_out
    elif args.run is not None:
        result_path = args.run / STAGE_RESULT_NAME[args.stage]
    else:
        print('error: provide --run or --workflow_result_out', file=sys.stderr)
        return 1

    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    print(
        json.dumps(
            {
                'stage': args.stage,
                'shard_count': len(results),
                'workflow_result': str(result_path),
                'aggregate_only': bool(args.aggregate_only),
            },
            indent=2,
        )
    )
    if args.aggregate_only:
        return 0

    if args.out is not None:
        out = args.out
    elif args.run is not None:
        out = args.run / STAGE_OUT_NAME[args.stage]
    else:
        print('error: provide --run or --out to bank', file=sys.stderr)
        return 1

    return run_writer(
        stage=args.stage,
        workflow_result=result_path,
        out=out,
        seeds=args.seeds,
        gaps_out=args.gaps_out,
        append=bool(args.append),
        source_type=args.source_type,
    )


if __name__ == '__main__':
    raise SystemExit(main())
