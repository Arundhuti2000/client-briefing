// Typed calls to the FastAPI endpoints (docs/API.md#endpoints). Each type mirrors a
// Pydantic model in api/main.py or app/; the names and fields are the same.

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// --- shapes ------------------------------------------------------------------

export type UserInfo = { user_id: string; name: string; role: string; entitlements: string[] }

export type ClientInfo = { client_id: string; legal_name: string; segment: string }

export type FlagSummary = {
  title: string
  detail: string
  flag_type: string
  severity: 'low' | 'medium' | 'high'
  housekeeping: boolean // data clean-up, not something to raise at the meeting
}

// One row of the meetings list (GET /clients): no LLM call, entitlement-filtered like the briefing
export type ClientSummary = {
  client_id: string
  client_name: string
  segment: string
  region: string
  primary_banker: string | null
  aliases: string[]
  meeting_date: string
  conflicts: string[] // titles of conflict flags: the banker decides these in Check
  heads_up: string[] // other flags that need attention (housekeeping left out)
  flags: FlagSummary[] // every flag this user may see, attention first (the Data health page)
  metrics: MetricSeries[] // every metric over time, revenue first (the Clients page trend lines)
}

// One metric over time. Every number comes from SQL; `text` and `change` are formatted by the API
export type MetricPoint = { period: string; value: number; text: string; as_of: string; evidence_id: string }
export type MetricSeries = {
  label: string // "Revenue", "Wallet share", "Operating deposits"
  unit: 'usd' | 'pct'
  points: MetricPoint[] // oldest first
  change: string | null // latest vs the one before: "+$270K", "+0.7 pts"
  stale: boolean // the latest value is older than the stale threshold
}

// The last `make eval` scorecard (GET /evaluations): counts and statuses, never failure text
export type EvalCheck = { name: string; measures: string; result: string; target: string; passed: boolean; zero_tolerance: boolean }
export type EvalTrap = { trap_id: string; what: string; checks: string[]; status: 'PASS' | 'FAIL' | 'not checked' }
export type EvalRun = {
  provider: string
  dataset?: 'dev' | 'dev2' | 'holdout'
  cases: number
  models: string
  checks: EvalCheck[]
  latency: string
  cost?: { requests: number; tokens_in: number; tokens_out: number; cache_hits: number }
  traps: EvalTrap[]
}
export type RetrievalScores = { 'precision@5': number; 'recall@5': number; mrr: number; 'ndcg@5': number }
export type RetrievalReport = { questions: number; scored: number; methods: Record<string, RetrievalScores>; restricted_retrieved: number }
export type DetectorReport = {
  cases: number; precision: number; recall: number; f1: number; false_positives: string[]; false_negatives: string[]
}
export type QualityReport = {
  retrieval: Record<string, RetrievalReport> // dev, dev2, holdout
  detectors: Record<string, { cases: number; detectors: Record<string, DetectorReport> }>
  router: { questions: number; accuracy: number; routes: string[]; confusion: number[][]; misroutes: string[] }
  faithfulness: Record<string, { claims: number; supported: number; faithfulness: number | null; llm_sections: number;
    first_drafts_rejected: number; rejection_rate: number | null }> // unsupported claim texts stay in the terminal
  note: EvalNote | string[] // string[]: reports written before the note had titles
}
export type EvalNote = { proves: string[]; not_proves: { title: string; detail: string }[] }
export type JudgeHistory = {
  ran_at: string; judges: string[]; writers: string[]; self_judged: boolean; briefings: number; claims: number
  verdicts: Record<string, number>; agreement_with_overlap: number | null
  judge_only_unsupported: number; overlap_only_unsupported: number
}
export type EvalReport = { ran_at: string; runs: EvalRun[]; holdout_runs?: EvalRun[]; quality?: QualityReport; judge?: JudgeHistory }

export type ResolveResponse = {
  query: string
  client: ClientInfo | null // set when the name resolved
  matched_by: string | null // id, exact, fuzzy
  error: string | null // client_not_found or ambiguous_client
  candidates: ClientInfo[] // "did you mean" suggestions
}

export type Bullet = { text: string; citations: string[] }

export type Check = { passed: boolean; errors: string[]; reasons: string[] }

export type Section = {
  id: string
  title: string
  question: string
  bullets: Bullet[]
  written_by: string // code, mock, the model that answered, or "evidence (fallback)"
  provider: string | null // gemini, openrouter, ollama, mock; null when code wrote it
  author: 'ai' | 'template' | 'code' | 'evidence' // what the label says: AI only when a real model wrote it
  status: 'ok' | 'empty' | 'unavailable' | 'fallback'
  check: Check
  retry_note: string | null // plain: "First draft rejected: a date wasn't in its source. Regenerated and verified."
  retry_errors: string[] // technical detail of that rejection, for the Details box
  note: string | null
}

export type Change = { text: string; evidence_ids: string[] }

export type MetricRow = {
  label: string
  value: string
  change: string | null
  period: string | null
  as_of: string
  evidence_id: string
}

export type OpportunityRow = {
  opp_id: string
  product: string
  stage: string
  value: string
  owner: string
  next_step: string
  updated: string
  live: boolean
  rank: number | null // 1 = discuss first; null for Lost or Won
  evidence_id: string
}

export type ActionRow = {
  action_id: string
  description: string
  owner: string
  due_date: string
  status: string
  overdue: boolean
  evidence_id: string
}

export type FlagRow = {
  flag_id: string
  flag_type: string
  title: string // e.g. "Who is the CFO?"
  severity: 'low' | 'medium' | 'high'
  housekeeping: boolean // data clean-up (duplicates, superseded values...): shown collapsed
  detail: string
  source_ids: string[]
  evidence_id: string
  uses: string | null // conflicts: the source the briefing uses (shown as "Suggested")
}

export type Evidence = {
  evidence_id: string
  kind: 'fact' | 'document' | 'flag'
  label: string
  text: string
  as_of: string
  source: string | null // e.g. Reuters, crm_notes, revenue_metrics
  suggestion: string | null // how this reads as a talking point
  caveat: string | null // why a flag says this document is contradicted
  caveat_id: string | null
}

export type LLMRun = { provider: string; model: string; cached: boolean; notes: string[]; seconds: number }

export type Briefing = {
  client_id: string
  client_name: string
  segment: string
  region: string
  user_id: string
  prepared_for: string // "Sam Rivera (Analyst)"
  meeting_date: string
  last_interaction: string | null
  coverage: string[]
  contacts: string[] // key contacts, e.g. "Raj Patel, CFO"
  aliases: string[] // names the data uses for this client
  what_changed: Change[]
  sections: Section[]
  metrics: MetricRow[]
  opportunities: OpportunityRow[]
  actions: ActionRow[]
  flags: FlagRow[]
  evidence: Record<string, Evidence>
  llm_runs: LLMRun[]
  generated_ms: number
  markdown: string
}

// A follow-up question's answer (POST /briefings/{client_id}/ask, the Answer model in app/ask.py)
export type Answer = {
  question: string
  client_id: string
  route: string // metrics, people, pipeline, actions, data_quality, documents, news, out_of_scope
  method: 'rule' | 'meaning' | 'llm' | 'default' // how the route was chosen
  reason: string
  status: 'answered' | 'couldnt_summarize' | 'refused'
  answered_by: 'code' | 'ai' | 'evidence' | 'nobody'
  provider: string | null
  model: string | null
  tools_called: string[]
  llm_steps: number
  bullets: Bullet[]
  note: string | null
  evidence: Record<string, Evidence>
  check: Check
}

// What a citation chip opens (the Fact model in app/tools.py)
export type Source = {
  evidence_id: string
  label: string
  value: number | string
  as_of: string
  source: string
  details: Record<string, unknown>
}

export type Task = {
  task_id: string
  user_id: string
  client_id: string
  description: string
  due_date: string | null
  source_id: string | null
  status: string
  created_at: string
}

export type NewTask = Pick<Task, 'client_id' | 'description' | 'due_date' | 'source_id'>

export type AuditRow = {
  ts: string
  user_id: string
  tool: string
  args: Record<string, unknown>
  result_ids: string[]
  error: string | null
}

// --- calls --------------------------------------------------------------------

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// FastAPI sends either a message, or (for invalid input, 422) a list of {loc, msg} problems
function describeDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const problems = detail.map((d) => `${(d?.loc ?? []).slice(1).join('.') || 'input'}: ${d?.msg ?? 'invalid'}`)
    return `Invalid request (${problems.join('; ')})`
  }
  return null
}

async function request<T>(path: string, userId: string | null, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (userId) headers['X-User-Id'] = userId // who is asking; entitlements are looked up server-side
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, describeDetail(body?.detail) ?? response.statusText)
  }
  return (await response.json()) as T
}

export const getUsers = () => request<UserInfo[]>('/users', null)

export const getClients = (userId: string) => request<ClientSummary[]>('/clients', userId)

export const resolveClient = (userId: string, query: string) =>
  request<ResolveResponse>(`/clients/resolve?q=${encodeURIComponent(query)}`, userId)

// meetingDate null: the API uses its meeting date (18 Nov 2026 in the demo data)
export const createBriefing = (userId: string, clientId: string, meetingDate: string | null = null) =>
  request<Briefing>('/briefings', userId, {
    method: 'POST',
    body: JSON.stringify({ client_id: clientId, meeting_date: meetingDate }),
  })

// The AI judge (app/judge.py): a label per AI-written bullet, counted by code
export type Verdict = 'supported' | 'unsupported' | 'contradicted' | 'no_verdict'
export type JudgeReport = {
  client_id: string; judge: string | null; writers: string[]; self_judged: boolean; claims: number
  verdicts: Record<string, number>; bullets: { section: string; bullet: number; verdict: Verdict }[]
  cached: boolean; note: string | null
}
export const judgeBriefing = (userId: string, clientId: string) =>
  request<JudgeReport>(`/briefings/${encodeURIComponent(clientId)}/judge`, userId, { method: 'POST' })

export const askFollowUp = (userId: string, clientId: string, question: string) =>
  request<Answer>(`/briefings/${encodeURIComponent(clientId)}/ask`, userId, {
    method: 'POST',
    body: JSON.stringify({ question }),
  })

// Conflict decisions and sharing (app/workflow.py)
export type Decision = { flag_id: string; source_id: string; decided_at: string }
export type ShareRecord = {
  share_id: string
  client_id: string
  approver: string
  approver_name: string
  recipients: string[]
  shared_at: string
  task_ids: string[]
  tasks: Task[]
}
export type WorkflowState = { decisions: Decision[]; open_conflicts: number; share: ShareRecord | null }
export type ShareBody = { recipients: string[]; follow_ups: { description: string; source_id: string | null }[] }

export const getWorkflow = (userId: string, clientId: string) =>
  request<WorkflowState>(`/briefings/${encodeURIComponent(clientId)}/workflow`, userId)

export const saveDecision = (userId: string, clientId: string, flagId: string, sourceId: string) =>
  request<Decision>(`/briefings/${encodeURIComponent(clientId)}/decisions`, userId, {
    method: 'POST',
    body: JSON.stringify({ flag_id: flagId, source_id: sourceId }),
  })

export const shareBriefing = (userId: string, clientId: string, body: ShareBody) =>
  request<ShareRecord>(`/briefings/${encodeURIComponent(clientId)}/share`, userId, {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const getSource = (userId: string, evidenceId: string) =>
  request<Source>(`/sources/${encodeURIComponent(evidenceId)}`, userId)

export const createTask = (userId: string, task: NewTask) =>
  request<Task>('/tasks', userId, { method: 'POST', body: JSON.stringify(task) })

export const getEvaluations = (userId: string) => request<EvalReport>('/evaluations', userId)

export const getAudit = (userId: string, limit = 50) => request<AuditRow[]>(`/audit?limit=${limit}`, userId)
