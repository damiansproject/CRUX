# Artifact schemas (CRUX loop)

Ids for seeds / proposals / critiques / hypotheses are minted only by write
scripts — never by workflow agents.

| Prefix | Writer | Shape |
| --- | --- | --- |
| `seed-` | `create_seeds.py` | `seed-0001`, … |
| `prp_` | `write_proposals.py` | `prp_<slot>_<strategy>_<nnnn>` |
| `cri_` | `write_critiques.py` | `cri_<proposal_id>_<nnnn>` |
| `hyp_` | `write_hypotheses.py` | `hyp_<slot>_<nnnn>` |
| `blk_` | `write_hypotheses.py` | `blk_<slot>_<nnnn>` (blocked finals) |

Claims (`clm_…`) come from claim-extractor and are cited, not minted here.

## Pre-bank / shard envelopes (before write scripts)

Workers emit these; slash workflows also enforce them via `schema`.
`merge_generation.py` → `write_*.py` stamp ids / `source`.

**Propose:** `{ slot_id, strategy, status: "ok"|"needs_claims", hypothesis: {…}|null, gap_requests: [] }`  
Hypothesis fields when `ok`: `statement`, `mechanism`, `experimental_plan`,
`dependency_claim_ids`, `claim_chain`, `references`, plus strategy-only
`debate_transcript` / `intermediate_assumptions`.  
`claim_chain` hops: `{ kind: "extracted", claim_id, note }` from the seed, or
`{ kind: "well_known", claim_id: null, statement, check, note }` (≤2).

**Critique:** `{ slot_id, proposal_id, status: "pass"|"needs_claims", verdict, issues, unsupported_hops, gap_requests: [] }`

**Revise:** `{ slot_id, proposal_id, critique_id, status: "ok"|"needs_claims", hypothesis: {…}|null, gap_requests: [] }`  
(Revise hypothesis omits debate/assumptions fields.)

## Seed pack (`seeds.json`)

```json
{
  "schema_version": "1.0",
  "claims_path": "…/claims.jsonl",
  "created_at": "2026-08-05T00:00:00Z",
  "slot_count": 5,
  "slots": [
    {
      "slot_id": "seed-0001",
      "mode": "paper|manual",
      "claim_ids": ["clm_…"],
      "claims": ["/* full claim objects, including quotes */"],
      "paper_ids": ["paper_a", "paper_b"],
      "papers": [{ "paper_id": "paper_a", "text_path": "…/cleaned_jsons/paper_a.json" }],
      "rng_seed": null,
      "sample": "directed",
      "enrichments": [{ "from_claim_ids": ["clm_…"], "added_paper_ids": ["paper_c"], "added_claim_ids": ["clm_…"] }]
    }
  ]
}
```

`enrichments` appears only after `add_seed_claims.py`. Gap fulfill **searches
claims** then `--from_claims` (that hit drags its whole paper: all claims +
`text_path` so revise reads the paper, not the matching card). `--add_papers`
if the paper id is already known. Main chooses initial slots with
`--manual_papers` takes as many paper ids as the composition needs (no cap of
2). `create_seeds.py` / `add_seed_claims.py` append `<run>/seed_attempts.jsonl`
(`pack_key` = sorted unique paper ids) so main does not retry the same set
unless asked. Prefer path mode:
`seeds_path` + `slot_ids` (and `proposals_path` / `critiques_path` with
`proposal_refs` / `critique_refs`). Inline full packs only when tiny.

## Proposal (`proposals.jsonl` row)

Stamped by `write_proposals.py` after `/crux-propose`.
One row per **slot × strategy** (`literature` | `debate` | `assumptions`).

```json
{
  "id": "prp_seed_0001_literature_0001",
  "slot_id": "seed-0001",
  "strategy": "literature|debate|assumptions",
  "source": {
    "type": "propose",
    "slot_id": "seed-0001",
    "strategy": "literature",
    "workflow": "propose"
  },
  "research_goal": "…",
  "created_at": "2026-08-05T00:00:00Z",
  "statement": "…",
  "mechanism": "…",
  "experimental_plan": "…",
  "dependency_claim_ids": ["clm_…"],
  "claim_chain": [
    { "kind": "extracted", "claim_id": "clm_…", "note": "…" },
    { "kind": "well_known", "claim_id": null, "statement": "…", "check": "…", "note": "…" }
  ],
  "references": ["claim:clm_…"],
  "debate_transcript": null,
  "intermediate_assumptions": null
}
```

Propose may return `needs_claims` (no proposal row) when the seed cannot
ground a load-bearing hop; those gaps land in `gap_requests.jsonl` for main.

## Critique (`critiques.jsonl` row)

Stamped by `write_critiques.py` after `/crux-critique`.

```json
{
  "id": "cri_prp_seed_0001_literature_0001_0001",
  "slot_id": "seed-0001",
  "proposal_id": "prp_seed_0001_literature_0001",
  "status": "pass|needs_claims",
  "source": {
    "type": "critique",
    "slot_id": "seed-0001",
    "proposal_id": "prp_seed_0001_literature_0001",
    "workflow": "critique"
  },
  "research_goal": "…",
  "created_at": "2026-08-05T00:00:00Z",
  "verdict": "…",
  "issues": [{ "severity": "soft|blocking", "note": "…" }],
  "unsupported_hops": [{ "claim_id": "clm_…|null", "note": "…" }],
  "gap_requests": []
}
```

## Hypothesis (`hypotheses.jsonl` row)

Stamped by `write_hypotheses.py` after `/crux-revise` (finals, not drafts).

```json
{
  "id": "hyp_seed_0001_0001",
  "slot_id": "seed-0001",
  "proposal_id": "prp_seed_0001_literature_0001",
  "critique_id": "cri_prp_seed_0001_literature_0001_0001",
  "source": {
    "type": "generate|feedback|manual|evolution",
    "slot_id": "seed-0001",
    "proposal_id": "prp_seed_0001_literature_0001",
    "critique_id": "cri_…",
    "workflow": "revise"
  },
  "research_goal": "…",
  "created_at": "2026-08-05T00:00:00Z",
  "statement": "…",
  "mechanism": "…",
  "experimental_plan": "…",
  "dependency_claim_ids": ["clm_…"],
  "claim_chain": [
    { "kind": "extracted", "claim_id": "clm_…", "note": "…" },
    { "kind": "well_known", "claim_id": null, "statement": "…", "check": "…", "note": "…" }
  ],
  "references": ["claim:clm_…"]
}
```

`source.type: "generate"` means minted from `/crux-revise` (pipeline-produced
final).

## Blocked hypothesis (`blocked_hypotheses.jsonl` row)

Written by `write_hypotheses.py` when revise returns `needs_claims` **with** a
hypothesis. Same fields as a hypothesis row (minus `source`) plus `status` and
`blocking_gaps` (the gap queries that blocked it).

A blocking hop means evidence is missing, not that the prediction was too
ambitious — so the idea is kept here rather than discarded. The tournament
never sees this file (`select_batch.py` reads `hypotheses.jsonl` only). Fill the
gap with `add_seed_claims.py`, re-run revise for that slot, and it can return as
a normal `hyp_` row.

## Gap request (`gap_requests.jsonl` row)

Appended by `write_proposals` / `write_critiques` / `write_hypotheses`.
Propose and critique can both emit gaps; revise fills them after main enriches
the seed (and may escalate if still blocked). After enrich, re-propose only
unfinished slot×strategies that never got a draft — not successful `ok` drafts.

```json
{
  "slot_id": "seed-0001",
  "proposal_id": "prp_…",
  "strategy": "literature",
  "stage": "propose|critique|revise",
  "query": "paper or result that would ground the missing hop",
  "why": "which hop needs that paper",
  "related_claim_ids": ["clm_…"],
  "suggested_kinds": ["finding"],
  "status": "needs_claims|pass|ok"
}
```

`status` mirrors the emitting stage: propose/revise use `ok`|`needs_claims`;
critique uses `pass`|`needs_claims`.

## Tournament

Private ranking state: `<run>/tournament/elo.jsonl` (scripts only). Batch JSON
holds science fields only. Stage 3 runs sequential ≤9 batches in **match-band
order** (lowest Elo `matches` layer first), for `tournament_rounds` (default 1;
do not ask — honor a higher count if volunteered).

### Batch (`select_batch.py` out)

```json
{
  "schema_version": "1.0",
  "research_goal": "…",
  "hypothesis_ids": ["hyp_…", "hyp_…"],
  "hypotheses": [
    {
      "id": "hyp_…",
      "statement": "…",
      "mechanism": "…",
      "experimental_plan": "…",
      "dependency_claim_ids": [],
      "claim_chain": [],
      "references": []
    }
  ]
}
```

### Judge (`/crux-tournament-judge`)

```json
{
  "ranked_ids": ["hyp_best", "…"],
  "scores": { "hyp_…": 42.0 },
  "rationale": "short"
}
```

`ranked_ids` is a permutation of the batch (best → worst). `scores` are the
judge’s numeric scores (higher = better).

### Elo row (`apply_elo.py`, private)

```json
{
  "hypothesis_id": "hyp_…",
  "elo": 1000.0,
  "matches": 0,
  "updated_at": "…",
  "last_delta": 0.0
}
```

Base 1000. Higher place beats lower in the batch; K shrinks as Elo rises.
