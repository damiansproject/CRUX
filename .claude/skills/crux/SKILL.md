---
name: crux
description: >-
  CRUX loop: from banked claims, build seed packs and run propose → critique →
  revise, then a required tournament ranking. Use when forming or ranking
  hypotheses from an existing claims.jsonl. At start ask goal, presentation,
  run mode, and model/effort if missing from chat or run.json.
---

# CRUX

Main orchestrates seeds → propose → critique → revise → tournament. Pace
follows **run mode**. After each core substage (and after enrichment), invoke
`crux-report`. If `claims.jsonl` is missing, invoke `claim-extractor` first
(from CRUX-CLAIMS; that skill still runs its own kickoff). Hard blockers always
pause. Ask before any web tool (gap web-ingest).

Human how-to: [../../../README.md](../../../README.md). Schemas:
[prompts/schemas.md](prompts/schemas.md).

## Kickoff (always, this skill)

At the **start** of this skill — before seeds / propose / tournament — collect
what is still missing. Skip any item the user already gave in chat **or** that
is already set in `<run>/run.json`. Re-ask only if the user changes it.

Write `<run>/run.json` when missing (create if needed). Omit keys that are not
set yet. Do not write empty strings as “unknown.”

```json
{
  "research_goal": "…",
  "presentation": "professional|general",
  "run_mode": "autonomous|manual",
  "model_effort": "eco|intensive|inherit|custom",
  "seeder": "default|isc",
  "tournament_rounds": 1
}
```

1. **Research goal**, if missing (**required** before `create_seeds`).
2. **Presentation mode**, if missing — professional vs general. Affects this
   skill’s chat and reports via `crux-report`. Workers stay technically precise.
   Propose/revise prose still argues for the next experiment.
3. **Run mode**, if missing. **Autonomous** *(default if unsure)* — main
   chooses sensible defaults (which papers share a seed slot, strategy mix,
   when to enrich, when to stop a cycle) and **keeps advancing** after each
   substage. Honor mid-run steering. **Manual** — after each substage
   (seeds, propose, critique, enrich, revise, tournament cycle, …), summarize
   + point at the report, then **wait for an explicit go-ahead**. Still ask
   before any web work.
4. **Model/effort**, if missing — applies to propose / critique / revise /
   judge. If unsure, default to **Eco**.
5. **Seeder**, only when the `crux-isc` skill (from CRUX-ISC) is available —
   **default** claim packs (`create_seeds.py`: every extracted claim of the
   grouped papers) or **isc** graph packs (typed-graph chains ranked for
   novelty, plus Swanson gap candidates). If crux-isc is not installed, skip
   the question and use default. If unsure, default.
6. **Tournament rounds:** default **1** — do **not** ask. Honor a volunteered
   higher count. If the user **skips** ranking, do **not** start the
   tournament; write the hypotheses report and stop. Lens weights stay all-1
   unless the user volunteers a focus.

## Runtime

`<skill_root>` = `${CLAUDE_PLUGIN_ROOT}/.claude/skills/crux` (plugin/Cowork) or
`.claude/skills/crux` (this repo). Run Python from the **repo / plugin root**.

If `Skill(crux)` resolved to `~/.claude/skills/crux` (or any path outside this
working tree / plugin root), **stop using that body**. Read and follow
`.claude/skills/crux/SKILL.md` in this repo instead. A same-named user skill
shadows the project copy; `/claim-extractor` and `/crux-report` are unaffected
because they have no global twin.

Workflows: `/crux-propose` · `/crux-critique` · `/crux-revise` ·
`/crux-tournament-judge`. Plugin runs: pass `*_prompt_path` under
`<skill_root>/prompts/` (defaults are repo-relative).

**No Workflow tool** (Cowork, Codex, Cursor): one fresh subagent per slot×strategy /
proposal / revision; only that row + matching `prompts/` file; write a
**shard** under `<run>/shards/<stage>/` (use `write_shard.py`); return a tiny
ack to main; main runs `merge_generation.py` then invokes `crux-report`. Keep
propose / critique / revise separate. No subagents + folders → say full run
needs Cowork; do not collapse roles.

## Who does what

| Role | Responsibility |
| --- | --- |
| **Main (you)** | This skill’s kickoff; invoke `claim-extractor` if claims missing; scripts; workflows / Cowork with `shards_dir`; `merge_generation.py`; gap fulfill (pool-first); **required** tournament unless skipped; invoke `crux-report` after core substages. **Autonomous:** advance between substages. **Manual:** stop for go-ahead after each substage. Ask before any web tool |
| **Provided scripts** | Mint ids; write/merge jsonl/seeds; tournament select/Elo — **no LLM** |
| **Workflows / workers** | Propose, critique, revise, tournament judge using `prompts/*.md`; with `shards_dir`, persist each result as a shard and return tiny acks |

Do **not** invent proposal/critique/hypothesis ids or `source` objects —
only `write_*.py` (via `merge_generation.py`) mint those.

## Scripts

All under `<skill_root>/scripts/`. Prefer these over throwaways.

| Script | You run it to… |
| --- | --- |
| `select_cross_packs.py` | **Cross-discipline packing.** `--claims claims.jsonl --slots N --papers_per_slot M` → packs of papers that are far apart in the literature but share at least one entity. `--emit_args` prints `--manual_papers` lines to pipe into `create_seeds.py` (strip CR on Windows: `tr -d '\r'`). `--verify_pair a,b` reports where a known bridge ranks. Use this, not gist packing, when the goal spans fields |
| `create_seeds.py` | **New** pack from gists: `--manual_papers` (any number of papers per slot). Records `seed_attempts.jsonl`. Random fallback: `--slots N`. Exact claim lists: `--manual` |
| `add_seed_claims.py` | Gap fulfill: search claims, then `--from_claims clm_…` (drags that claim's **whole paper**). `--add_papers` if you already have the paper id. Never re-`create_seeds` |
| `branch_tree.py` | **Deepen loop memory.** `close` a dead end with its why, evidence class and scope boundary; `check` refuses a closure that states no scope or leaves its boundary unmined; `frontier` prints the next round's agenda. See [prompts/accumulate.md](prompts/accumulate.md) |
| `write_pack_agents.py` | **Claude Code only.** `--seeds seeds.json` → one `.claude/agents/crux-pack-<slot>.md` per slot. Re-run after `add_seed_claims` (`--slot <id>`). `--max_tokens` default 150k. Then pass `use_pack_agents: true` to `/crux-propose` `/crux-critique` `/crux-revise` |
| `write_proposals.py` | Bank propose (legacy single result JSON) → `proposals.jsonl` |
| `write_critiques.py` | Bank critique (legacy) → `critiques.jsonl` (+ gaps) |
| `write_hypotheses.py` | Bank revise (legacy) → `hypotheses.jsonl` + `blocked_hypotheses.jsonl` |
| `select_batch.py` | Pick ≤9 hyps from the lowest Elo-`matches` band → batch JSON |
| `apply_elo.py` | Update `<run>/tournament/elo.jsonl` from judge `ranked_ids` |
| `write_shard.py` | Worker helper: atomically write one shard JSON |
| `merge_generation.py` | `--stage propose\|critique\|revise --shards <dir> --run <run> …` → aggregate + bank via `write_*.py` |

`scripts/lib/` is shared code (`kinds`, `jsonl_io`) — import only.

If a gap needs a **new paper** extracted, invoke `claim-extractor` for that
paper (ask before web ingest). Prefer searching existing `claims.jsonl` first.

## Workflows, shards, and path mode

In Claude Code the `crux` plugin registers each workflow under its own namespace: pass `crux:<name>` as the Workflow tool's `name` (for example `crux:crux-propose`); the bare name is not found. Launch the shipped workflow by that name, never by `scriptPath`.

Ids: `seed-` · `prp_<slot>_<strategy>_` · `cri_<proposal_id>_` · `hyp_`.
Status: propose/revise `ok`|`needs_claims`; critique `pass`|`needs_claims`.

**Default bank path (slash + Cowork):** pass `shards_dir` =
`<run>/shards/<stage>` on every `/crux-*` workflow (or have each Cowork worker
write there). Then main:

```
python .claude/skills/crux/scripts/merge_generation.py \
  --stage propose --shards "$RUN/shards/propose" --run "$RUN" \
  --research_goal "..." --seeds "$RUN/seeds.json"
```

Omit `shards_dir` only for tiny debug runs (legacy: full `results[]` returned,
then `write_*.py --workflow_result`).

Shard layout:

| Stage | Path |
| --- | --- |
| propose | `shards/propose/<slot_id>.<strategy>.json` |
| critique | `shards/critique/<proposal_id>.json` |
| revise | `shards/revise/<critique_id_or_proposal_id>.json` |

Workers load rows via Bash+python (workflows have no `fs`). Do not inline large
packs. Prefer path mode:

| Workflow | Tiny refs |
| --- | --- |
| `/crux-propose` | `seeds_path` + `slot_ids` (+ `shards_dir`) |
| `/crux-critique` | `seeds_path` + `proposals_path` + `proposal_refs` (+ `shards_dir`) |
| `/crux-revise` | paths + `critique_refs` (+ `shards_dir`) |

**Resume** (Workflow tool): full original args + `resumeFromRunId` — never bare
`scriptPath`. No Workflow tool: relaunch only the units with no shard yet.

**Fan-out:** one worker per slot×strategy / proposal / critique. Launch the
full set in **one** workflow call. Split only if the user asks or a run
fails/truncates.

Prompts: `prompts/{propose,critique,revise,judge}.md`. Loop guidance (not a
worker prompt): `prompts/accumulate.md`.

Optional `user_notes` (short soft preference from main/user) on propose,
critique, revise, and judge. Hard schema/rules still win.

## Model and effort

After kickoff, before first **core** workflow, use the recorded `model_effort`.
If the user is unsure, default to **Eco**.

1. **Eco** *(default)* — every worker `sonnet` / `medium`
2. **Intensive** — table below
3. **Inherit main** — omit `model` / `effort`
4. **Custom** — user specifies

Model names are Claude Code's. On Codex or Cursor use the host's own models:
`sonnet` → its standard model, `opus` → its most capable. Keep the named
effort, or the nearest one the host offers.

| Stage | Model | Effort |
| --- | --- | --- |
| `/crux-propose` · `/crux-critique` · `/crux-revise` | `opus` | `xhigh` |
| `/crux-tournament-judge` | inherit or `opus` / `xhigh` | |

Scripts ignore model/effort.

## Run dir

Use the existing `.crux_run/<name>/` (or Cowork output folder). Do not nest
another run. If `claims.jsonl` is missing, invoke `claim-extractor` first.

## Generation

```
create_seeds → /crux-propose (shards) → merge_generation propose   # may emit gaps
            → /crux-critique (shards) → merge_generation critique # may emit gaps
            → search claims → --from_claims (drags paper) → add_seed_claims
            → /crux-revise (shards) → merge_generation revise     # fills those gaps
```

**Propose and critique both emit gaps** (`needs_claims` + `gap_requests`).
After main enriches the seed, **revise** turns drafts into finals. Do not
re-run propose just to close gaps on drafts that already returned `ok`.

1. Seeds: research goal must already be set (kickoff). **If `seeder` is
   `isc`:** follow the crux-isc SKILL from graph extract through
   `compose_chains.py` with `--papers_manifest` and `--claims` (skip
   `create_seeds.py`), then continue at step 2 in **path mode** with
   `propose_prompt_path` = crux-isc's `prompts/propose-isc.md` — inline slots
   would drop the ISC pack's `chains[]`/`gaps[]`.
   **Otherwise (default seeder):** Read `gists.json` (and
   claims). Compose packs of however many papers the goal needs. Read
   `seed_attempts.jsonl` and **do not repeat** a `pack_key` unless the user
   asks to retry. For a cross-field goal, get the pack list from
   `select_cross_packs.py --claims … --emit_args` first — gist/topic packing
   selects for coherence, and coherence files each literature separately
   (measured: 2 of 12 slots held both target molecules under gist packing,
   10 of 12 under cross-discipline packing). Then
   `create_seeds.py --manual_papers id,id,id … --cleaned_jsons …`. On Claude
   Code, then run `write_pack_agents.py --seeds <run>/seeds.json` before
   launching (new agent types take ~a minute to register); pass
   `use_pack_agents: true` to propose / critique / revise.
   Do **not** pass `--slots` / `--rng_seed` unless the user asks for a random
   draw or you cannot pair (then say so). Particular claims → `--manual`.
   Missing hop → gap fulfill (step 4); never re-seed.
   - **Autonomous:** pack from gists; skip keys already in `seed_attempts.jsonl`;
     say why each slot.
   - **Manual:** propose the paper groupings after claims exist; wait for
     go-ahead before `create_seeds`.
2. Path-mode `/crux-propose` + `shards_dir` → `merge_generation.py --stage propose`
   → invoke `crux-report` for `03_proposals.pdf`. Manual: wait for go-ahead.
3. Path-mode `/crux-critique` + `shards_dir` → `merge_generation.py --stage critique`
   → invoke `crux-report` for `04_critiques.pdf`. Manual: wait for go-ahead.
4. Gaps: **search `claims.jsonl`** for a hop matching the gap `query` /
   `why`. Then `add_seed_claims.py --from_claims clm_… --cleaned_jsons`
   — that hit **drags its whole paper**. If nothing in the pool, invoke
   `claim-extractor` for a candidate paper (ask first before web). Never
   re-`create_seeds`. (ISC packs: fulfill through crux-isc's gap refill, not
   `add_seed_claims.py`. A pool hit from another slot is
   `compose_chains.py --from_seeds … --add_papers <slot_id>=<paper_id>` with the
   same adapter flags; a new paper is `write_graph.py --append` first.) If pack agents are in use, re-run
   `write_pack_agents.py --seeds … --slot <slot_id>`. Invoke `crux-report`
   for `04b_seed_enrichment.pdf` when enrichment runs. Manual: wait for
   go-ahead after enrichment.
5. If propose returned `needs_claims` with **no draft** for some slot×strategy,
   after enrichment re-propose **only those** unfinished combinations, then
   critique them. Do not re-propose successful `ok` drafts.
6. Path-mode `/crux-revise` + `shards_dir` → `merge_generation.py --stage revise`
   → invoke `crux-report` for `05_hypotheses.pdf`. Still-blocked finals land
   in `blocked_hypotheses.jsonl` — the idea is kept, not dropped, and the
   tournament never sees it. Say how many were blocked; to recover one,
   fulfill its gap (step 4) and re-run revise for that slot.
7. **Deepen (optional, per hypothesis).** Looping is for ideas worth the spend.
   The user may name hypotheses to deepen; autonomous may pick blocked ones or
   ones the tournament ranked well. For each chosen slot, repeat: gap fulfill
   (step 4) → re-run `/crux-revise` for that slot only.
   **When a round rules something out**, accumulate that too. Between rounds:
   execute what the draft asserted, control the verdict in both directions,
   then bank the outcome — verified results as `origin: computation-ledger`
   claims, dead ends as a closed-branches page whose **scope boundary** states
   what the closure does *not* exclude. Track it with
   `branch_tree.py close|check|frontier`. Full loop:
   [prompts/accumulate.md](prompts/accumulate.md).
   **Stop** when any of these is true, and say which:
   - the critic returns `pass`;
   - a round adds **no new paper** — carry those gaps forward as already-sought;
   - the next pack would exceed `write_pack_agents.py --max_tokens`;
   - a round cap the user set (default 3) is reached;
   - `branch_tree.py frontier` is empty.
   Each round: re-run `write_pack_agents.py --slot <slot_id>` if pack agents
   are in use. A newly written agent type can take tens of minutes to
   register; do not block on it — run path mode instead.
   Then **tournament (required)** per run mode unless the user skipped ranking.

## Tournament (required unless skipped)

**Required** after banked hypotheses unless the user skipped ranking at
kickoff or mid-run. Handles **any** `N` (skip if `N < 2`). If skipped: stop
after the hypotheses report.

Batches of up to **9**. Selection is **match-band first** via `select_batch.py`:
finish every hypothesis at the current lowest Elo `matches` count before
touching a higher band; shuffle within the band. Last partial band may be
2–9. Only spill into the next band when fewer than 2 remain in the current one.

Kickoff `tournament_rounds` defaults to **1** (do not ask; honor a higher
count if the user volunteers it). For each round `1..R`:

1. Note `min_matches` across the pool (from `elo.jsonl`; missing row = 0).
2. Repeat cycles until that layer is done:
   1. `select_batch.py --hypotheses …/hypotheses.jsonl --elo …/tournament/elo.jsonl --out …/tournament/batch.json --size 9 --research_goal "…"`
   2. **`/crux-tournament-judge`** — one judge ranks the batch holistically
      (prompt: `prompts/judge.md`). Pass `batch_path` + `hypothesis_ids` (or
      inline `hypotheses[]`) + `research_goal`; optional `user_notes`. Web
      search allowed when helpful.
   3. `apply_elo.py --ranking <judge JSON> --elo …/tournament/elo.jsonl`
   4. Invoke `crux-report` for `06_tournament.pdf`.
3. After `R` rounds, stop. Further rounds only if the user asks.

**Autonomous:** advance batch-to-batch and round-to-round without re-asking.
**Manual:** go-ahead after each batch (and optionally each round).

### Cowork

One judge subagent per batch (web ok). Main still owns the multi-batch /
multi-round loop.

## Invariants

- Invoke `claim-extractor` first if `claims.jsonl` is missing.
- Ids + `source` only from write scripts. Finals `source.type`: `generate` |
  `feedback` | `manual` | `evolution` (`generate` = from `/crux-revise`).
- Kinds: `scripts/lib/kinds.py` (keep propose/critique/revise workflow enums
  in sync).
- Tournament is **required unless the user skips ranking**. Invoke
  `crux-report` after core substages.
- Prefer higher `source_quality` when seeding.
- Path mode for non-trivial packs; no loader agent that re-emits full JSON.
- **Resume** (Workflow tool): full original args + `resumeFromRunId` — never
  bare `scriptPath`. No Workflow tool: relaunch only the units with no shard yet.
- Propose/critique/revise stay separate. Always pause on hard errors or
  before any web tool.
