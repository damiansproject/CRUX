#!/usr/bin/env python3
"""Atomically write one worker shard JSON (stdin or --file).

Used by slash-workflow / Cowork workers so main never ferries full payloads.

  python write_shard.py --out shards/propose/seed-0001.literature.json --stage propose < result.json

With --stage, wraps as { "stage", "result" }. Without, writes the object as-is.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def load_payload(path: Path | None) -> dict:
    raw = path.read_text(encoding='utf-8-sig') if path else sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('shard payload must be a JSON object')
    return data


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            if not text.endswith('\n'):
                handle.write('\n')
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--file', type=Path, default=None, help='Payload JSON file (default: stdin)')
    parser.add_argument(
        '--stage',
        type=str,
        default=None,
        help='If set, wrap payload as {stage, result}',
    )
    args = parser.parse_args(argv)

    try:
        payload = load_payload(args.file)
        if args.stage:
            body = {'stage': args.stage, 'result': payload}
        else:
            body = payload
        atomic_write(args.out, json.dumps(body, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1

    print(json.dumps({'ok': True, 'shard': str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
