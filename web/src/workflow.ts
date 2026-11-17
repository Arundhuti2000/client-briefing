// The banker's workflow on top of a briefing: the two sides of a conflict, what each one
// says, and the follow-ups to suggest. Pure functions over the API's data.
import type { Briefing, Evidence, FlagRow } from './api'
import { shortDate } from './format'
import type { Progress } from './progress'

// Records are the bank's system of record, so the briefing uses them; documents carry the caveat
export const isRecord = (evidenceId: string) => evidenceId.startsWith('SQL:')

// The sources a conflict flag points at, as evidence the briefing holds
export function conflictOptions(b: Briefing, f: FlagRow): Evidence[] {
  return f.source_ids.map((id) => b.evidence[id]).filter((e): e is Evidence => !!e)
}

// What a source says, in one line: a record's sentence, or the briefing's own bullet about a document
export function statement(b: Briefing, e: Evidence): string {
  if (e.kind !== 'document') return e.text
  const bullet = b.sections.flatMap((s) => s.bullets).find((x) => x.citations[0] === e.evidence_id)
  if (bullet) return bullet.text.split('⚠ Contradicted:')[0].trim()
  const text = e.text.split('\n').slice(1).join(' ').replace(/\s+/g, ' ').trim()
  return text.length > 220 ? `${text.slice(0, 220).replace(/\s\S*$/, '')}…` : text
}

export type FollowUp = { key: string; description: string; detail: string; sourceId: string; defaultOn: boolean }

// Suggested from the banker's decisions in Check, and from the open actions
export function suggestedFollowUps(b: Briefing, p: Progress): FollowUp[] {
  const decided = b.flags
    .filter((f) => f.flag_type === 'conflict' && p.decisions[f.evidence_id])
    .map((f) => ({
      key: f.evidence_id,
      description: `Confirm with the client: ${f.title} (you trust ${b.evidence[p.decisions[f.evidence_id]]?.label ?? 'your choice'})`,
      detail: 'From your decision in Check',
      sourceId: f.evidence_id,
      defaultOn: true,
    }))
  const actions = b.actions
    .filter((a) => a.status === 'Open')
    .map((a) => ({
      key: a.evidence_id,
      description: `${a.overdue ? 'Overdue' : 'Follow up'}: ${a.description}`,
      detail: `Owner ${a.owner} · due ${shortDate(a.due_date)}`,
      sourceId: a.evidence_id,
      defaultOn: a.overdue,
    }))
  return [...decided, ...actions]
}
