// What a numbered chip opens: fetched from GET /sources (entitlement-checked and audited).
// "Report a mistake" creates a follow-up task on that source (POST /tasks).
import { useEffect, useState } from 'react'
import { createTask, getSource } from '../api'
import type { Briefing, Source, Task } from '../api'
import { dayMonth, errorMessage } from '../format'
import { sourceKind } from '../sources'
import { SourceIcon } from './common'
import { Button } from '@/components/ui/button'

type Props = { briefing: Briefing; userId: string; evidenceId: string | null; number: number }

export function SourcePanel({ briefing: b, userId, evidenceId, number }: Props) {
  const [source, setSource] = useState<Source | null>(null)
  const [failed, setFailed] = useState(false)
  const [task, setTask] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!evidenceId) return
    let cancelled = false
    getSource(userId, evidenceId)
      .then((s) => !cancelled && setSource(s))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [evidenceId, userId])

  if (!evidenceId) {
    return (
      <section className="panel panel-pad" aria-label="Source">
        <p className="note">Click a small number in the briefing to see its source here.</p>
      </section>
    )
  }
  const evidence = b.evidence[evidenceId]
  const label = evidence?.label ?? 'Source'

  async function report() {
    setError(null)
    try {
      setTask(await createTask(userId, { client_id: b.client_id, description: `Check this source: ${label}`, due_date: b.meeting_date, source_id: evidenceId }))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const isDocument = evidenceId.startsWith('DOC:') || evidenceId.startsWith('FLAG:')
  return (
    <section className="panel panel-pad" aria-labelledby="src-title" style={{ gap: 10 }}>
      <div className="src-head">
        <SourceIcon source={evidence?.source ?? source?.source} evidenceId={evidenceId} tile size={15} />
        <span className="src-kind">{sourceKind(evidence?.source ?? source?.source, evidenceId).name}</span>
        <span className="src-n" aria-label={`Source ${number}`}>
          {number}
        </span>
        {source && <span className="muted">{dayMonth(source.as_of)}</span>}
      </div>
      <span id="src-title" className="src-title">
        {label}
      </span>
      {!source && !failed && <p className="note">Loading…</p>}
      {failed && <p className="note">This source can't be opened. Sources left out of the briefing, such as unapproved news, can't be opened.</p>}
      {source && <p className="excerpt">{isDocument ? String(source.value) : (evidence?.text ?? String(source.value))}</p>}
      {source && (
        <div className="button-row">
          {task ? (
            <span className="note note-ok">Thanks. A follow-up task was created to check it.</span>
          ) : (
            <Button variant="ghost" size="sm" onClick={report} className="ml-auto text-(--text-2)">
              Report a mistake
            </Button>
          )}
          {error && <span className="note note-error">{error}</span>}
        </div>
      )}
    </section>
  )
}
