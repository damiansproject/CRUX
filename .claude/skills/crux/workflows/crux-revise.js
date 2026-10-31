export const meta = {
  name: 'crux-revise',
  description: 'Revise drafts into final hypotheses',
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
    throw new Error(`crux-revise args are not JSON: ${error.message}`)
  }
}

if (!input || typeof input !== 'object') {
  throw new Error(
    'crux-revise requires { seeds_path + proposals_path + critiques_path + critique_refs } OR inline seeds+proposals+critiques, plus research_goal; optional shards_dir?, use_pack_agents?',
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
  typeof input.revise_prompt_path === 'string' && input.revise_prompt_path.length > 0
    ? input.revise_prompt_path
    : '.claude/skills/crux/prompts/revise.md'

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

function asList(value, key) {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object' && Array.isArray(value[key])) return value[key]
  return null
}

const seedsPath =
  typeof input.seeds_path === 'string' && input.seeds_path.trim()
    ? input.seeds_path.trim()
    : null
const proposalsPath =
  typeof input.proposals_path === 'string' && input.proposals_path.trim()
    ? input.proposals_path.trim()
    : null
const critiquesPath =
  typeof input.critiques_path === 'string' && input.critiques_path.trim()
    ? input.critiques_path.trim()
    : null

const jobs = []

if (seedsPath && proposalsPath && critiquesPath) {
  const refs = input.critique_refs
  if (!Array.isArray(refs) || refs.length === 0) {
    throw new Error(
      'path mode requires critique_refs: [{id, proposal_id, slot_id}, ...] (main lists them; workers load each row)',
    )
  }
  for (const ref of refs) {
    if (
      !ref ||
      typeof ref.id !== 'string' ||
      typeof ref.proposal_id !== 'string' ||
      typeof ref.slot_id !== 'string'
    ) {
      throw new Error('each critique_ref needs id, proposal_id, and slot_id strings')
    }
    jobs.push({
      mode: 'path',
      seeds_path: seedsPath,
      proposals_path: proposalsPath,
      critiques_path: critiquesPath,
      critique_id: ref.id,
      proposal_id: ref.proposal_id,
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
    throw new Error('provide path args + critique_refs, or inline seeds+proposals+critiques')
  }
  const slotsById = new Map()
  for (const slot of slotsRaw.map(normalizeSlot)) {
    slotsById.set(slot.slot_id, slot)
  }
  const proposalsRaw = asList(input.proposals, 'proposals')
  const critiquesRaw = asList(input.critiques, 'critiques')
  if (!proposalsRaw || !critiquesRaw) {
    throw new Error('inline mode needs proposals and critiques arrays')
  }
  const proposalsById = new Map()
  for (const row of proposalsRaw) {
    if (row && typeof row.id === 'string') proposalsById.set(row.id, row)
  }
  const critiqueByProposal = new Map()
  for (const row of critiquesRaw) {
    if (row && typeof row.proposal_id === 'string') critiqueByProposal.set(row.proposal_id, row)
  }
  let proposalFilter = null
  if (input.proposal_ids != null) {
    proposalFilter = new Set(input.proposal_ids)
  }
  for (const [proposalId, critique] of critiqueByProposal.entries()) {
    if (proposalFilter && !proposalFilter.has(proposalId)) continue
    const proposal = proposalsById.get(proposalId)
    if (!proposal) throw new Error(`critique for ${proposalId}: proposal not found`)
    const slotId = proposal.slot_id || critique.slot_id
    const slot = slotsById.get(slotId)
    if (!slot) throw new Error(`proposal ${proposalId}: slot ${slotId} not in seeds`)
    const hypothesis =
      proposal.hypothesis && typeof proposal.hypothesis === 'object'
        ? proposal.hypothesis
        : {
            statement: proposal.statement,
            mechanism: proposal.mechanism,
            experimental_plan: proposal.experimental_plan,
            dependency_claim_ids: proposal.dependency_claim_ids,
            claim_chain: proposal.claim_chain,
            references: proposal.references,
          }
    jobs.push({
      mode: 'inline',
      proposal_id: proposalId,
      critique_id: typeof critique.id === 'string' ? critique.id : null,
      slot_id: slotId,
      hypothesis,
      critique: {
        id: critique.id,
        status: critique.status,
        verdict: critique.verdict,
        issues: critique.issues || [],
        unsupported_hops: critique.unsupported_hops || [],
        gap_requests: critique.gap_requests || [],
      },
      claim_ids: slot.claim_ids,
      claims: slot.claims,
      papers: slot.papers,
    })
  }
}

if (jobs.length === 0) {
  throw new Error('no revise jobs')
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
  },
}

const resultSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['slot_id', 'proposal_id', 'status', 'gap_requests'],
  properties: {
    slot_id: { type: 'string' },
    proposal_id: { type: 'string' },
    critique_id: { type: ['string', 'null'] },
    status: { type: 'string', enum: ['ok', 'needs_claims'] },
    hypothesis: { anyOf: [hypothesisObject, { type: 'null' }] },
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
    status: { type: 'string', enum: ['ok', 'needs_claims'] },
  },
}

function normalizeReviseResult(raw, job) {
  if (!raw || typeof raw !== 'object') return null

  const status = raw.status === 'needs_claims' ? 'needs_claims' : 'ok'
  let gapRequests = Array.isArray(raw.gap_requests) ? raw.gap_requests.slice(0, 3) : []
  let hypothesis = raw.hypothesis && typeof raw.hypothesis === 'object' ? raw.hypothesis : null

  if (status === 'ok') {
    if (!hypothesis) {
      return {
        slot_id: job.slot_id,
        proposal_id: job.proposal_id,
        critique_id: job.critique_id,
        status: 'needs_claims',
        hypothesis: null,
        gap_requests: gapRequests.length
          ? gapRequests
          : [
              {
                query: 'missing grounded evidence after revise',
                why: 'agent returned ok without a hypothesis object',
                related_claim_ids: [],
                suggested_kinds: [],
              },
            ],
        _pipeline_note: 'coerced_ok_without_hypothesis',
      }
    }
  } else if (gapRequests.length === 0) {
    gapRequests = [
      {
        query: 'additional supporting claim after revise',
        why: 'reviser marked needs_claims but emitted no gap_requests',
        related_claim_ids: [],
        suggested_kinds: [],
      },
    ]
  }

  return {
    slot_id: job.slot_id,
    proposal_id: job.proposal_id,
    critique_id: job.critique_id,
    status,
    hypothesis,
    gap_requests: gapRequests,
  }
}

async function reviseWork(job) {
  const dumpPaper = `Dump every page of each paper (pages[].text):
     python -c "import json,sys; p=json.load(open(sys.argv[1], encoding='utf-8-sig')); print('paper_id', p.get('paper_id'), 'title', p.get('title'), 'n_pages', len(p.get('pages') or [])); [print(chr(10)+'----- page %s -----'%pg.get('page')+chr(10)+(pg.get('text') or '')) for pg in (p.get('pages') or [])]"`
  // Exact row loader — workers otherwise improvise several failed one-liners.
  const loadRow = `python -c "import json,sys; rows=(json.loads(l) for l in open(sys.argv[1],encoding='utf-8-sig') if l.strip()); r=next((x for x in rows if x.get('id')==sys.argv[2]),None); print(json.dumps(r,ensure_ascii=False,indent=2) if r else 'ROW NOT FOUND')"`
  const packAgent = usePackAgents ? `crux-pack-${job.slot_id}` : null
  const seedPart = packAgent
    ? `The papers and seed claims for slot "${job.slot_id}" (including any added after gaps) are in your system prompt. Use them directly; do not re-read or dump them.`
    : null
  const bodySection =
    job.mode === 'path'
      ? `
5. Load the draft proposal — run exactly this, do not improvise another loader:
   ${loadRow} ${JSON.stringify(job.proposals_path)} ${JSON.stringify(job.proposal_id)}
6. Load the critique the same way:
   ${loadRow} ${JSON.stringify(job.critiques_path)} ${JSON.stringify(job.critique_id)}
7. ${seedPart || `Load seed slot "${job.slot_id}" from:
   ${job.seeds_path}
   Prefer Bash + python for each (full objects; do not slim quotes).
8. ${dumpPaper} <each papers[].text_path>`}
`
      : `
5. Draft hypothesis JSON:
${JSON.stringify(job.hypothesis, null, 2)}
6. Critique JSON:
${JSON.stringify(job.critique, null, 2)}
7. ${seedPart || `Papers in this slot (including any added after gaps):
${JSON.stringify(job.papers || [], null, 2)}
   ${dumpPaper} <text_path>
8. Seed claims JSON:
${JSON.stringify(job.claims, null, 2)}`}
`

  const prompt = `
1. Read the reviser instructions at: ${promptPath}
2. Research goal:
${researchGoal}
3. Optional notes from main (soft preference only; hard rules still win):
${userNotes || '(none)'}
4. Set slot_id exactly to "${job.slot_id}", proposal_id exactly to "${job.proposal_id}", and critique_id to ${
    job.critique_id ? `"${job.critique_id}"` : 'null'
  }.
${bodySection}
Return structured output matching the schema.
`

  const raw = await agent(prompt, {
    label: `revise:${job.proposal_id}`,
    ...routing,
    ...(packAgent ? { agentType: packAgent } : {}),
    schema: resultSchema,
  })
  return normalizeReviseResult(raw, job)
}

async function reviseWriteShard(normalized, job) {
  if (!normalized) return null
  const key = job.critique_id || job.proposal_id
  const shardPath = `${shardsDir}/${sanitizeShardPart(key)}.json`
  // Keep scratch outside the stage dir — merge_generation globs *.json there.
  const scratchDir = `${shardsDir}/../.scratch`
  const tmpPath = `${scratchDir}/tmp-${sanitizeShardPart(key)}.json`
  const payload = JSON.stringify(normalized)
  const prompt = `
Persist one revise shard. Do not rethink the science.

1. Write this exact JSON to temporary file path:
${tmpPath}

PAYLOAD:
${payload}

2. Run:
python ${writeShardPath} --out ${JSON.stringify(shardPath)} --stage revise --file ${JSON.stringify(tmpPath)}

3. Delete the temporary file ${tmpPath} after write_shard.py succeeds.

4. Return structured ack only. Set ok true only if write_shard.py succeeded.
slot_id="${job.slot_id}" proposal_id="${job.proposal_id}" status="${normalized.status}" shard=${JSON.stringify(shardPath)}
`

  const ack = await agent(prompt, {
    label: `shard-revise:${job.proposal_id}`,
    ...routing,
    schema: ackSchema,
  })
  if (!ack || ack.ok !== true) return null
  return {
    slot_id: job.slot_id,
    proposal_id: job.proposal_id,
    critique_id: job.critique_id,
    status: normalized.status,
    shard: typeof ack.shard === 'string' ? ack.shard : shardPath,
  }
}

const results = shardsDir
  ? await pipeline(jobs, reviseWork, reviseWriteShard)
  : await pipeline(jobs, reviseWork)

const ok = []
const needsClaims = []
const failed = []

for (let index = 0; index < results.length; index++) {
  const result = results[index]
  const job = jobs[index]
  if (!result) {
    failed.push({ slot_id: job.slot_id, proposal_id: job.proposal_id })
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
  proposals_path: proposalsPath,
  critiques_path: critiquesPath,
  shards_dir: shardsDir,
  job_count: jobs.length,
  results: results.filter(Boolean),
  ok_count: ok.length,
  needs_claims_count: needsClaims.length,
  failed,
  gap_requests: shardsDir
    ? []
    : needsClaims.flatMap(r =>
        (r.gap_requests || []).map(g => ({
          slot_id: r.slot_id,
          proposal_id: r.proposal_id,
          critique_id: r.critique_id,
          stage: 'revise',
          ...g,
        })),
      ),
}
