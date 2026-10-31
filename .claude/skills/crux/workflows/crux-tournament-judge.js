export const meta = {
  name: 'crux-tournament-judge',
  description: 'Judge final tournament ranking for one hypothesis batch',
}

const ALLOWED_EFFORT = ['low', 'medium', 'high', 'xhigh', 'max']

let input = args
if (typeof input === 'string') {
  try {
    input = JSON.parse(input)
  } catch (error) {
    throw new Error(`crux-tournament-judge args are not JSON: ${error.message}`)
  }
}
if (!input || typeof input !== 'object') {
  throw new Error(
    'crux-tournament-judge requires research_goal, and batch_path (+ hypothesis_ids) or hypotheses[]; optional user_notes',
  )
}

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

const researchGoal =
  typeof input.research_goal === 'string' && input.research_goal.trim().length > 0
    ? input.research_goal.trim()
    : null
if (!researchGoal) {
  throw new Error('research_goal must be a non-empty string')
}

const promptPath =
  typeof input.judge_prompt_path === 'string' && input.judge_prompt_path.length > 0
    ? input.judge_prompt_path
    : '.claude/skills/crux/prompts/judge.md'

const batchPath =
  typeof input.batch_path === 'string' && input.batch_path.trim()
    ? input.batch_path.trim()
    : null

let hypothesisIds = Array.isArray(input.hypothesis_ids)
  ? input.hypothesis_ids.filter(id => typeof id === 'string' && id)
  : []
let hypotheses = Array.isArray(input.hypotheses) ? input.hypotheses : null

if (batchPath) {
  if (hypothesisIds.length === 0) {
    throw new Error('with batch_path, pass hypothesis_ids[] (from select_batch)')
  }
} else {
  if (!Array.isArray(hypotheses) || hypotheses.length < 2) {
    throw new Error('inline mode needs hypotheses[] with >= 2 items')
  }
  hypothesisIds = hypotheses
    .map(h => (h && typeof h.id === 'string' ? h.id : null))
    .filter(Boolean)
  if (hypothesisIds.length !== hypotheses.length) {
    throw new Error('every hypothesis needs id')
  }
}

if (hypothesisIds.length < 2 || hypothesisIds.length > 9) {
  throw new Error('hypothesis_ids must have 2–9 unique ids')
}
if (new Set(hypothesisIds).size !== hypothesisIds.length) {
  throw new Error('hypothesis_ids must be unique')
}

const userNotes =
  typeof input.user_notes === 'string' && input.user_notes.trim()
    ? input.user_notes.trim()
    : null

const resultSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['ranked_ids', 'scores', 'rationale'],
  properties: {
    ranked_ids: {
      type: 'array',
      minItems: 2,
      maxItems: 9,
      items: { type: 'string' },
    },
    scores: {
      type: 'object',
      additionalProperties: { type: 'number' },
    },
    rationale: { type: 'string' },
  },
}

function normalizeJudge(raw) {
  if (!raw || typeof raw !== 'object') return null
  const ranked = Array.isArray(raw.ranked_ids)
    ? raw.ranked_ids.filter(id => typeof id === 'string')
    : []
  if (ranked.length !== hypothesisIds.length) return null
  if (new Set(ranked).size !== ranked.length) return null
  for (const id of hypothesisIds) {
    if (!ranked.includes(id)) return null
  }
  const scores = raw.scores && typeof raw.scores === 'object' ? raw.scores : {}
  return {
    ranked_ids: ranked,
    scores,
    rationale: typeof raw.rationale === 'string' ? raw.rationale : '',
  }
}

const bodySection = batchPath
  ? `
4. Load the batch JSON at:
   ${batchPath}
   Use only hypotheses / hypothesis_ids. Rank every id in hypothesis_ids.
`
  : `
4. Batch hypotheses JSON (science fields only — no Elo):
${JSON.stringify(hypotheses, null, 2)}
5. Rank exactly these ids (permutation):
${JSON.stringify(hypothesisIds)}
`

const prompt = `
1. Read the judge instructions at: ${promptPath}
2. Research goal:
${researchGoal}
3. Batch hypothesis ids (rank every one):
${JSON.stringify(hypothesisIds)}
${bodySection}
6. Optional notes from main (soft preference only; judge criteria still win):
${userNotes || '(none)'}
7. Return structured output matching the schema.
`

const raw = await agent(prompt, {
  label: 'tournament-judge',
  ...routing,
  schema: resultSchema,
})
const result = normalizeJudge(raw)
if (!result) {
  throw new Error('judge returned invalid ranking')
}

return {
  research_goal: researchGoal,
  hypothesis_ids: hypothesisIds,
  ...result,
}
