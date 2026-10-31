export const meta = {
  name: 'crux-critique',
  description: 'Critique draft proposals (separate critic)',
}

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
    throw new Error(`crux-critique args are not JSON: ${error.message}`)
  }
}

if (!input || typeof input !== 'object') {
  throw new Error(
    'crux-critique requires { seeds_path + proposals_path + proposal_refs } OR inline seeds+proposals, plus research_goal; optional shards_dir?, use_pack_agents?',
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
  typeof input.critique_prompt_path === 'string' && input.critique_prompt_path.length > 0
    ? input.critique_prompt_path
    : '.claude/skills/crux/prompts/critique.md'

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
const proposalsPath =
  typeof input.proposals_path === 'string' && input.proposals_path.trim()
    ? input.proposals_path.trim()
    : null

const jobs = []

if (seedsPath && proposalsPath) {
  // Path mode: main passes tiny proposal_refs [{id, slot_id}]. No loader agent.
  const refs = input.proposal_refs
  if (!Array.isArray(refs) || refs.length === 0) {
    throw new Error(
      'seeds_path+proposals_path require proposal_refs: [{id, slot_id}, ...] (main lists them; workers load each row)',
    )
  }
  for (const ref of refs) {
    if (!ref || typeof ref.id !== 'string' || typeof ref.slot_id !== 'string') {
      throw new Error('each proposal_ref needs id and slot_id strings')
    }
    jobs.push({
      mode: 'path',
      seeds_path: seedsPath,
      proposals_path: proposalsPath,
      proposal_id: ref.id,
      slot_id: ref.slot_id,
    })
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
    throw new Error('provide seeds_path+proposals_path+proposal_refs, or inline seeds+proposals')
  }
  const slotsById = new Map()
  for (const slot of slotsRaw.map(normalizeSlot)) {
    slotsById.set(slot.slot_id, slot)
  }
  let proposalsRaw = input.proposals
  if (proposalsRaw && typeof proposalsRaw === 'object' && !Array.isArray(proposalsRaw)) {
    proposalsRaw = Array.isArray(proposalsRaw.proposals) ? proposalsRaw.proposals : null
  }
  if (!Array.isArray(proposalsRaw) || proposalsRaw.length === 0) {
    throw new Error('proposals must be a non-empty array in inline mode')
  }
  let proposalFilter = null
  if (input.proposal_ids != null) {
    proposalFilter = new Set(input.proposal_ids)
  }
  for (const row of proposalsRaw) {
    if (!row || typeof row !== 'object') continue
    const proposalId = row.id
    const slotId = row.slot_id
    if (typeof proposalId !== 'string' || typeof slotId !== 'string') continue
    if (proposalFilter && !proposalFilter.has(proposalId)) continue
    const slot = slotsById.get(slotId)
    if (!slot) throw new Error(`proposal ${proposalId}: slot ${slotId} not in seeds`)
    const hypothesis =
      row.hypothesis && typeof row.hypothesis === 'object'
        ? row.hypothesis
        : {
            statement: row.statement,
            mechanism: row.mechanism,
            experimental_plan: row.experimental_plan,
            dependency_claim_ids: row.dependency_claim_ids,
            claim_chain: row.claim_chain,
            references: row.references,
          }
    jobs.push({
      mode: 'inline',
      proposal_id: proposalId,
      slot_id: slotId,
      hypothesis,
      claim_ids: slot.claim_ids,
      claims: slot.claims,
      papers: slot.papers,
    })
  }
}

if (jobs.length === 0) {
  throw new Error('no critique jobs')
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

const issueItem = {
  type: 'object',
  additionalProperties: false,
  required: ['severity', 'note'],
  properties: {
    severity: { type: 'string', enum: ['soft', 'blocking'] },
    note: { type: 'string' },
  },
}

const hopItem = {
  type: 'object',
  additionalProperties: false,
  required: ['note'],
  properties: {
    claim_id: { type: ['string', 'null'] },
    note: { type: 'string' },
  },
}

const resultSchema = {
  type: 'object',
  additionalProperties: false,
  required: [
    'slot_id',
    'proposal_id',
    'status',
    'verdict',
    'issues',
    'unsupported_hops',
    'gap_requests',
  ],
  properties: {
    slot_id: { type: 'string' },
    proposal_id: { type: 'string' },
    status: { type: 'string', enum: ['pass', 'needs_claims'] },
    verdict: { type: 'string' },
    issues: { type: 'array', items: issueItem },
    unsupported_hops: { type: 'array', items: hopItem },
    gap_requests: { type: 'array', maxItems: 3, items: gapItem },
  },
}

const ackSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['ok', 'shard', 'slot_id', 'proposal_id', 'status'],
  properties: {
    ok: { type: 'boolean' },
    shard: { type: 'string' },
    slot_id: { type: 'string' },
    proposal_id: { type: 'string' },
    status: { type: 'string', enum: ['pass', 'needs_claims'] },
  },
}

function normalizeCritiqueResult(raw, job) {
  if (!raw || typeof raw !== 'object') return null

  const status = raw.status === 'needs_claims' ? 'needs_claims' : 'pass'
  let gapRequests = Array.isArray(raw.gap_requests) ? raw.gap_requests.slice(0, 3) : []
  const issues = Array.isArray(raw.issues) ? raw.issues : []
  const unsupportedHops = Array.isArray(raw.unsupported_hops) ? raw.unsupported_hops : []
  const verdict = typeof raw.verdict === 'string' ? raw.verdict : ''

  if (status === 'needs_claims' && gapRequests.length === 0) {
    gapRequests = [
      {
        query: 'additional supporting claim for unsupported hop',
        why: 'critic marked needs_claims but emitted no gap_requests',
        related_claim_ids: [],
        suggested_kinds: [],
      },
    ]
  }

  return {
    slot_id: job.slot_id,
    proposal_id: job.proposal_id,
    status,
    verdict,
    issues,
    unsupported_hops: unsupportedHops,
    gap_requests: gapRequests,
  }
}

async function critiqueWork(job) {
  const dumpPaper = `Dump every page of each paper (pages[].text):
     python -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf-8-sig')); print('paper_id', p.get('paper_id'), 'title', p.get('title'), 'n_pages', len(p.get('pages') or [])); [print(chr(10)+'----- page %s -----'%pg.get('page')+chr(10)+(pg.get('text') or '')) for pg in (p.get('pages') or [])]"`
  // Exact row loader — workers otherwise improvise several failed one-liners.
  const loadRow = `python -c "import json,sys; rows=(json.loads(l) for l in open(sys.argv[1],encoding='utf-8-sig') if l.strip()); r=next((x for x in rows if x.get('id')==sys.argv[2]),None); print(json.dumps(r,ensure_ascii=False,indent=2) if r else 'ROW NOT FOUND')"`
  const packAgent = usePackAgents ? `crux-pack-${job.slot_id}` : null
  const seedPart = packAgent
    ? `The papers and seed claims for slot "${job.slot_id}" are in your system prompt. Use them directly; do not re-read or dump them.`
    : null
  const bodySection =
    job.mode === 'path'
      ? `
5. Load the draft proposal — run exactly this, do not improvise another loader:
   ${loadRow} ${JSON.stringify(job.proposals_path)} ${JSON.stringify(job.proposal_id)}
6. ${seedPart || `Load seed slot "${job.slot_id}" from:
   ${job.seeds_path}
   Prefer Bash + python for paper_ids + papers[].text_path + claims.
7. ${dumpPaper} <each papers[].text_path>`}
`
      : `
5. Draft hypothesis JSON:
${JSON.stringify(job.hypothesis, null, 2)}
6. ${seedPart || `Papers in this slot:
${JSON.stringify(job.papers || [], null, 2)}
   ${dumpPaper} <text_path>
7. Seed claims JSON:
${JSON.stringify(job.claims, null, 2)}`}
`

  const prompt = `
1. Read the critic instructions at: ${promptPath}
2. Research goal:
${researchGoal}
3. Optional notes from main (soft preference only; hard rules still win):
${userNotes || '(none)'}
4. Set slot_id exactly to "${job.slot_id}" and proposal_id exactly to "${job.proposal_id}".
${bodySection}
Return structured output matching the schema.
`

  const raw = await agent(prompt, {
    label: `critique:${job.proposal_id}`,
    ...routing,
    ...(packAgent ? { agentType: packAgent } : {}),
    schema: resultSchema,
  })
  return normalizeCritiqueResult(raw, job)
}

async function critiqueWriteShard(normalized, job) {
  if (!normalized) return null
  const shardPath = `${shardsDir}/${sanitizeShardPart(job.proposal_id)}.json`
  // Keep scratch outside the stage dir — merge_generation globs *.json there.
  const scratchDir = `${shardsDir}/../.scratch`
  const tmpPath = `${scratchDir}/tmp-${sanitizeShardPart(job.proposal_id)}.json`
  const payload = JSON.stringify(normalized)
  const prompt = `
Persist one critique shard. Do not rethink the science.

1. Write this exact JSON to temporary file path:
${tmpPath}

PAYLOAD:
${payload}

2. Run:
python ${writeShardPath} --out ${JSON.stringify(shardPath)} --stage critique --file ${JSON.stringify(tmpPath)}

3. Delete the temporary file ${tmpPath} after write_shard.py succeeds.

4. Return structured ack only. Set ok true only if write_shard.py succeeded.
slot_id="${job.slot_id}" proposal_id="${job.proposal_id}" status="${normalized.status}" shard=${JSON.stringify(shardPath)}
`

  const ack = await agent(prompt, {
    label: `shard-critique:${job.proposal_id}`,
    ...routing,
    schema: ackSchema,
  })
  if (!ack || ack.ok !== true) return null
  return {
    slot_id: job.slot_id,
    proposal_id: job.proposal_id,
    status: normalized.status,
    shard: typeof ack.shard === 'string' ? ack.shard : shardPath,
  }
}

const results = shardsDir
  ? await pipeline(jobs, critiqueWork, critiqueWriteShard)
  : await pipeline(jobs, critiqueWork)

const passed = []
const needsClaims = []
const failed = []

for (let index = 0; index < results.length; index++) {
  const result = results[index]
  const job = jobs[index]
  if (!result) {
    failed.push({ slot_id: job.slot_id, proposal_id: job.proposal_id })
    continue
  }
  if (result.status === 'pass') passed.push(result)
  else needsClaims.push(result)
}

return {
  model: routing.model ?? null,
  effort: routing.effort ?? null,
  research_goal: researchGoal,
  seeds_path: seedsPath,
  proposals_path: proposalsPath,
  shards_dir: shardsDir,
  job_count: jobs.length,
  results: results.filter(Boolean),
  pass_count: passed.length,
  needs_claims_count: needsClaims.length,
  failed,
  gap_requests: shardsDir
    ? []
    : needsClaims.flatMap(r =>
        (r.gap_requests || []).map(g => ({
          slot_id: r.slot_id,
          proposal_id: r.proposal_id,
          stage: 'critique',
          ...g,
        })),
      ),
}
