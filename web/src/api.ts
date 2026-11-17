// Typed calls to the FastAPI endpoints (SPEC.md section 6). Each type mirrors a
// Pydantic model in api/main.py or app/; the names and fields are the same.

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

// --- shapes ------------------------------------------------------------------

export type UserInfo = { user_id: string; name: string; role: string; entitlements: string[] }

export type ClientInfo = { client_id: string; legal_name: string; segment: string }

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
  written_by: string // code, mock, a model name, or "evidence (fallback)"
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
  detail: string
  source_ids: string[]
  evidence_id: string
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

export type LLMRun = { provider: string; model: string; cached: boolean; notes: string[] }

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

export const resolveClient = (userId: string, query: string) =>
  request<ResolveResponse>(`/clients/resolve?q=${encodeURIComponent(query)}`, userId)

export const createBriefing = (userId: string, clientId: string, meetingDate: string) =>
  request<Briefing>('/briefings', userId, {
    method: 'POST',
    body: JSON.stringify({ client_id: clientId, meeting_date: meetingDate }),
  })

export const getSource = (userId: string, evidenceId: string) =>
  request<Source>(`/sources/${encodeURIComponent(evidenceId)}`, userId)

export const createTask = (userId: string, task: NewTask) =>
  request<Task>('/tasks', userId, { method: 'POST', body: JSON.stringify(task) })

export const getAudit = (userId: string, limit = 50) => request<AuditRow[]>(`/audit?limit=${limit}`, userId)
