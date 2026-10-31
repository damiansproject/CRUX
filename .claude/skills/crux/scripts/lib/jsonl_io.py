#!/usr/bin/env python3
"""Shared JSON / JSONL helpers for CRUX write scripts."""

from __future__ import annotations

import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected JSON object')
    return data


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding='utf-8-sig') as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f'{path}:{line_no}: expected object')
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def sanitize_id(value: str, *, max_len: int = 48, fallback: str = 'id') -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '_', value).strip('_').lower()
    return cleaned[:max_len] or fallback


def next_prefixed_index(existing: list[dict], prefix: str) -> int:
    highest = 0
    for row in existing:
        rid = row.get('id')
        if isinstance(rid, str) and rid.startswith(prefix):
            suffix = rid[len(prefix) :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return highest + 1


def seed_claim_ids(seeds: dict | None, slot_id: str) -> set[str] | None:
    """Claim ids for slot, or None if seeds/slot missing (skip validation)."""
    if seeds is None:
        return None
    slots = seeds.get('slots')
    if not isinstance(slots, list):
        return None
    for slot in slots:
        if not isinstance(slot, dict) or slot.get('slot_id') != slot_id:
            continue
        ids = slot.get('claim_ids')
        if isinstance(ids, list) and ids:
            return {cid for cid in ids if isinstance(cid, str)}
        claims = slot.get('claims')
        if isinstance(claims, list):
            return {
                c['id']
                for c in claims
                if isinstance(c, dict) and isinstance(c.get('id'), str)
            }
        return set()
    return None


def claim_ids_from_hypothesis(hypothesis: dict) -> set[str]:
    found: set[str] = set()
    deps = hypothesis.get('dependency_claim_ids')
    if isinstance(deps, list):
        found.update(cid for cid in deps if isinstance(cid, str) and cid)
    chain = hypothesis.get('claim_chain')
    if isinstance(chain, list):
        for hop in chain:
            if isinstance(hop, dict):
                cid = hop.get('claim_id')
                if isinstance(cid, str) and cid:
                    found.add(cid)
    return found
