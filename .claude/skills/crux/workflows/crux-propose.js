export const meta = {
  name: 'crux-propose',
  description: 'Draft proposals from seed packs (not final hypotheses)',
}

const STRATEGIES = ['literature', 'debate', 'assumptions']
const ALLOWED_EFFORT = ['low', 'medium', 'high', 'xhigh', 'max']
const CLAIM_KINDS = [
  'finding',
  'mechanism',
  'method',
  'limitation',
  'assumption',
  'problem',
  'other',
]

let input = args
if (typeof input === 'string') {
  try {
    input = JSON.parse(input)
  } catch (error) {
    throw new Error(`crux-propose args are not JSON: ${error.message}`)
  }
}

if (!input || typeof input !== 'object') {
  throw new Error(
    'crux-propose requires { seeds_path + slot_ids } OR { seeds|slots }, plus research_goal; optional shards_dir?, strategies?, model?, effort?, propose_prompt_path?, use_pack_agents?',
  )
}

const shardsDir =
  typeof input.shards_dir === 'string' && input.shards_dir.trim()
    ? input.shards_dir.trim().replace(/[\\/]+$/, '')
    : null
const writeShardPath =
  typeof input.write_shard_path === 'string' && input.write_shard_path.trim()
    ? input.write_shard_path.trim()
    : '.claude/skills/crux/scripts/write_shard.py'
// Per-slot agent types from write_pack_agents.py carry the pack as system prompt.
const usePackAgents = input.use_pack_agents === true

function sanitizeShardPart(value) {
  return String(value).replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^_+|_+$/g, '') || 'id'
}

const researchGoal =
  typeof input.research_goal === 'string' && input.research_goal.trim().length > 0
    ? input.research_goal.trim()
    : null
if (!researchGoal) {
  throw new Error('research_goal must be a non-empty string')
}
const userNotes =
  typeof input.user_notes === 'string' && input.user_notes.trim()
    ? input.user_notes.trim()
    : null

function resolveAgentRouting(src) {
  const routing = {}
  if (typeof src.model === 'string' && src.model.trim()) {
    routing.model = src.model.trim()
  }
  if (typeof src.effort === 'string' && src.effort.trim()) {
    const value = src.effort.trim()
    if (!ALLOWED_EFFORT.includes(value)) {
      throw new Error(`effort must be one of ${ALLOWED_EFFORT.join(', ')}`)
    }
    routing.effort = value
  }
  return routing
}
const routing = resolveAgentRouting(input)

const promptPath =
  typeof input.propose_prompt_path === 'string' && input.propose_prompt_path.length > 0
    ? input.propose_prompt_path
    : '.claude/skills/crux/prompts/propose.md'

let strategies = STRATEGIES
if (input.strategies != null) {
  if (!Array.isArray(input.strategies) || input.strategies.length === 0) {
    throw new Error('strategies must be a non-empty array, or omitted')
  }
  for (const strategy of input.strategies) {
    if (!STRATEGIES.includes(strategy)) {
      throw new Error(`unknown strategy "${strategy}"; expected one of ${STRATEGIES.join(', ')}`)
    }
  }
  strategies = [...new Set(input.strategies)]
}

function normalizeClaim(claim) {
  if (!claim || typeof claim !== 'object') return null
  const id = claim.id
  if (typeof id !== 'string' || !id) return null
  return claim
}

function normalizeSlot(slot) {
  if (!slot || typeof slot !== 'object' || typeof slot.slot_id !== 'string') {
    throw new Error('every seed slot needs slot_id')
  }
  const claimIds = Array.isArray(slot.claim_ids)
    ? slot.claim_ids.filter(id => typeof id === 'string' && id)
    : []
  const claimsRaw = Array.isArray(slot.claims) ? slot.claims : []
  const claims = claimsRaw.map(normalizeClaim).filter(Boolean)
  if (claims.length === 0 && claimIds.length === 0) {
    throw new Error(`slot ${slot.slot_id}: no claims`)
  }
  const knownIds = claims.length > 0 ? claims.map(c => c.id) : claimIds
  const papers = (Array.isArray(slot.papers) ? slot.papers : [])
    .filter(row => row && typeof row.paper_id === 'string' && row.paper_id)
    .map(row => ({
      paper_id: row.paper_id,
      text_path: typeof row.text_path === 'string' && row.text_path ? row.text_path : null,
    }))
  return {
    slot_id: slot.slot_id,
    paper_ids: Array.isArray(slot.paper_ids)
      ? slot.paper_ids.filter(id => typeof id === 'string' && id)
      : papers.map(p => p.paper_id),
    papers,
    claim_ids: knownIds,
    claims:
      claims.length > 0
        ? claims
        : claimIds.map(id => ({
            id,
            statement: '',
            kind: null,
            source_quality: null,
            quotes: [],
          })),
  }
}

const seedsPath =
  typeof input.seeds_path === 'string' && input.seeds_path.trim()
    ? input.seeds_path.trim()
    : null

const jobs = []

if (seedsPath) {
  // Path mode: main passes slot_ids (tiny). No loader agent.
  if (!Array.isArray(input.slot_ids) || input.slot_ids.length === 0) {
    throw new Error(
      'seeds_path requires slot_ids: string[] (main lists them; workers load each slot from the path)',
    )
  }
  const slotIds = [...new Set(input.slot_ids.filter(id => typeof id === 'string' && id))]
  for (const slotId of slotIds) {
    for (const strategy of strategies) {
      jobs.push({ mode: 'path', seeds_path: seedsPath, slot_id: slotId, strategy })
    }
  }
} else {
  const seedsObj =
    input.seeds && typeof input.seeds === 'object' && !Array.isArray(input.seeds)
      ? input.seeds
      : null
  const slotsRaw = Array.isArray(input.slots)
    ? input.slots
    : seedsObj && Array.isArray(seedsObj.slots)
      ? seedsObj.slots
      : null
  if (!slotsRaw || slotsRaw.length === 0) {
    throw new Error('provide seeds_path+slot_ids, or inline seeds.slots / slots')
  }
  let slotFilter = null
  if (input.slot_ids != null) {
    if (!Array.isArray(input.slot_ids) || input.slot_ids.length === 0) {
      throw new Error('slot_ids must be a non-empty array when provided')
    }
    slotFilter = new Set(input.slot_ids)
  }
  const slots = slotsRaw
    .map(normalizeSlot)
    .filter(slot => (slotFilter == null ? true : slotFilter.has(slot.slot_id)))
  if (slots.length === 0) {
    throw new Error('no seed slots left after slot_ids filter')
  }
  for (const slot of slots) {
    for (const strategy of strategies) {
      jobs.push({
        mode: 'inline',
        slot_id: slot.slot_id,
        strategy,
        claim_ids: slot.claim_ids,
        claims: slot.claims,
        papers: slot.papers,
      })
    }
  }
}

const chainItem = {
  type: 'object',
  additionalProperties: false,
  required: ['note'],
  properties: {
    kind: { type: 'string', enum: ['extracted', 'well_known', 'conjecture'] },
    claim_id: { type: ['string', 'null'] },
    statement: { type: 'string' },
    check: { type: 'string' },
    note: { type: 'string' },
    // conjecture only: the two real claims the leap runs between, and the
    // experiment that would kill it. Premises real, arrow free.
    from_claim_id: { type: ['string', 'null'] },
    to_claim_id: { type: ['string', 'null'] },
    kill_experiment: { type: 'string' },
  },
}

const gapItem = {
  type: 'object',
  additionalProperties: false,
  required: ['query', 'why'],
  properties: {
    query: { type: 'string' },
    why: { type: 'string' },
    related_claim_ids: { type: 'array', items: { type: 'string' } },
    suggested_kinds: {
      type: 'array',
      items: { type: 'string', enum: CLAIM_KINDS },
    },
  },
}

const hypothesisObject = {
  type: 'object',
  additionalProperties: false,
  required: [
    'statement',
    'mechanism',
    'experimental_plan',
    'dependency_claim_ids',
    'claim_chain',
    'references',
  ],
  properties: {
    statement: { type: 'string' },
    mechanism: { type: 'string' },
    experimental_plan: { type: 'string' },
    dependency_claim_ids: {
      type: 'array',
      minItems: 1,
      items: { type: 'string' },
    },
    claim_chain: {
      type: 'array',
      minItems: 1,
      items: chainItem,
    },
    references: { type: 'array', items: { type: 'string' } },
    debate_transcript: { type: ['string', 'null'] },
    intermediate_assumptions: {
      type: ['array', 'null'],
      items: { type: 'string' },
    },
  },
}

const resultSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['slot_id', 'strategy', 'status', 'gap_requests'],
  properties: {
    slot_id: { type: 'string' },
    strategy: { type: 'string', enum: STRATEGIES },
    status: { type: 'string', enum: ['ok', 'needs_claims'] },
    hypothesis: { anyOf: [hypothesisObject, { type: 'null' }] },
    gap_requests: { type: 'array', maxItems: 3, items: gapItem },
  },
}

const ackSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['ok', 'shard', 'slot_id', 'strategy', 'status'],
  properties: {
    ok: { type: 'boolean' },
    shard: { type: 'string' },
    slot_id: { type: 'string' },
    strategy: { type: 'string', enum: STRATEGIES },
    status: { type: 'string', enum: ['ok', 'needs_claims'] },
  },
}

function normalizeProposeResult(raw, job) {
  if (!raw || typeof raw !== 'object') return null

  const status = raw.status === 'needs_claims' ? 'needs_claims' : 'ok'
  let gapRequests = Array.isArray(raw.gap_requests) ? raw.gap_requests.slice(0, 3) : []
  let hypothesis = raw.hypothesis && typeof raw.hypothesis === 'object' ? raw.hypothesis : null

  if (status === 'ok') {
    if (!hypothesis) {
      return {
        slot_id: job.slot_id,
        strategy: job.strategy,
        status: 'needs_claims',
        hypothesis: null,
        gap_requests: gapRequests.length
          ? gapRequests
          : [
              {
                query: 'missing grounded evidence for proposal',
                why: 'agent returned ok without a hypothesis object',
                related_claim_ids: [],
                suggested_kinds: [],
              },
            ],
        _pipeline_note: 'coerced_ok_without_hypothesis',
      }
    }
    if (job.strategy !== 'debate') {
      hypothesis = { ...hypothesis, debate_transcript: null }
    }
    if (job.strategy !== 'assumptions') {
      hypothesis = { ...hypothesis, intermediate_assumptions: null }
    }
  } else if (gapRequests.length === 0) {
    gapRequests = [
      {
        query: 'additional supporting claim for seed gap',
        why: 'agent marked needs_claims but emitted no gap_requests',
        related_claim_ids: [],
        suggested_kinds: [],
      },
    ]
  }

  return {
    slot_id: job.slot_id,
    strategy: job.strategy,
    status,
    hypothesis,
    gap_requests: gapRequests,
  }
}

async function proposeWork(job) {
  const dumpPaper = `Dump every page of each paper (pages[].text):
     python -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf-8-sig')); print('paper_id', p.get('paper_id'), 'title', p.get('title'), 'n_pages', len(p.get('pages') or [])); [print(chr(10)+'----- page %s -----'%pg.get('page')+chr(10)+(pg.get('text') or '')) for pg in (p.get('pages') or [])]"`
  const packAgent = usePackAgents ? `crux-pack-${job.slot_id}` : null
  const seedSection = packAgent
    ? `
5. The papers and seed claims for slot "${job.slot_id}" are in your system prompt. Use them directly; do not re-read or dump them.
`
    : job.mode === 'path'
      ? `
5. Load ONLY seed slot "${job.slot_id}" from:
   ${job.seeds_path}
   Prefer Bash + python (not Read) so the file is not truncated. First print paper_ids + papers[].text_path + claim_ids.
6. ${dumpPaper} <each papers[].text_path>
`
      : `
5. Papers in this slot:
${JSON.stringify(job.papers || [], null, 2)}
   ${dumpPaper} <text_path>
6. Seed claim ids:
${job.claim_ids.join(', ')}
7. Seed claims JSON:
${JSON.stringify(job.claims, null, 2)}
`

  const prompt = `
1. Read the proposer instructions at: ${promptPath}
2. Research goal:
${researchGoal}
3. Optional notes from main (soft preference only; hard rules still win):
${userNotes || '(none)'}
4. Set slot_id exactly to "${job.slot_id}" and strategy exactly to "${job.strategy}".
${seedSection}
Return structured output matching the schema.
`

  const raw = await agent(prompt, {
    label: `propose:${job.slot_id}:${job.strategy}`,
    ...routing,
    ...(packAgent ? { agentType: packAgent } : {}),
    schema: resultSchema,
  })
  return normalizeProposeResult(raw, job)
}

async function proposeWriteShard(normalized, job) {
  if (!normalized) return null
  const shardPath = `${shardsDir}/${sanitizeShardPart(job.slot_id)}.${sanitizeShardPart(job.strategy)}.json`
  // Keep scratch outside the stage dir — merge_generation globs *.json there.
  const scratchDir = `${shardsDir}/../.scratch`
  const tmpPath = `${scratchDir}/tmp-${sanitizeShardPart(job.slot_id)}.${sanitizeShardPart(job.strategy)}.json`
  const payload = JSON.stringify(normalized)
  const prompt = `
Persist one propose shard. Do not rethink the science.

1. Write this exact JSON to temporary file path:
${tmpPath}

PAYLOAD:
${payload}

2. Run:
python ${writeShardPath} --out ${JSON.stringify(shardPath)} --stage propose --file ${JSON.stringify(tmpPath)}

3. Delete the temporary file ${tmpPath} after write_shard.py succeeds.

4. Return structured ack only. Set ok true only if write_shard.py succeeded.
slot_id="${job.slot_id}" strategy="${job.strategy}" status="${normalized.status}" shard=${JSON.stringify(shardPath)}
`

  const ack = await agent(prompt, {
    label: `shard-propose:${job.slot_id}:${job.strategy}`,
    ...routing,
    schema: ackSchema,
  })
  if (!ack || ack.ok !== true) return null
  return {
    slot_id: job.slot_id,
    strategy: job.strategy,
    status: normalized.status,
    shard: typeof ack.shard === 'string' ? ack.shard : shardPath,
  }
}

const results = shardsDir
  ? await pipeline(jobs, proposeWork, proposeWriteShard)
  : await pipeline(jobs, proposeWork)

const ok = []
const needsClaims = []
const failed = []

for (let index = 0; index < results.length; index++) {
  const result = results[index]
  const job = jobs[index]
  if (!result) {
    failed.push({ slot_id: job.slot_id, strategy: job.strategy })
    continue
  }
  if (result.status === 'ok') ok.push(result)
  else needsClaims.push(result)
}

return {
  model: routing.model ?? null,
  effort: routing.effort ?? null,
  research_goal: researchGoal,
  seeds_path: seedsPath,
  shards_dir: shardsDir,
  strategies,
  job_count: jobs.length,
  results: results.filter(Boolean),
  ok_count: ok.length,
  needs_claims_count: needsClaims.length,
  failed,
  // Full gap bodies live in shards when shards_dir is set; acks are status-only.
  gap_requests: shardsDir
    ? []
    : needsClaims.flatMap(r =>
        (r.gap_requests || []).map(g => ({
          slot_id: r.slot_id,
          strategy: r.strategy,
          stage: 'propose',
          ...g,
        })),
      ),
}
