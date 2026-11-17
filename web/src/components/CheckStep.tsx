// Step 2, Check: for each conflict flag, the banker picks the source they trust. The choice
// is the banker's note (saved through POST /briefings/{id}/decisions and turned into a follow-up); the briefing
// text itself always follows the records, as the validator checked it.
import type { Briefing, FlagRow } from '../api'
import { dateTime, shortDate } from '../format'
import type { Progress } from '../progress'
import { conflictOptions, isRecord, statement } from '../workflow'
import { SourceIcon, StatusText, Tag } from './common'
import type { Tone } from './common'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

type Props = {
  briefing: Briefing
  progress: Progress
  saved: Record<string, string> // flag -> when the API saved the decision
  error: string | null
  onDecide: (flagId: string, sourceId: string) => void
}

// The side the briefing uses: the newer one, as unify decided (older reports: the record)
const usedSource = (f: FlagRow) => f.uses ?? f.source_ids.find(isRecord)

function optionNote(evidenceId: string, asOf: string, used: boolean): string {
  if (isRecord(evidenceId)) {
    return used
      ? `Updated ${shortDate(asOf)}. The briefing uses this one.`
      : `Updated ${shortDate(asOf)}. Older than the document, so the briefing uses the document.`
  }
  return used ? 'Newer than the record, so the briefing uses this one.' : 'The briefing marks this statement as contradicted.'
}

const GOOD_TO_KNOW: Record<string, [string, Tone]> = {
  stale_statement: ['Out of date', 'warn'],
  overdue: ['Overdue', 'bad'],
}

export function CheckStep({ briefing: b, progress, saved, error, onDecide }: Props) {
  const conflicts = b.flags.filter((f) => f.flag_type === 'conflict')
  const others = b.flags.filter((f) => f.flag_type !== 'conflict' && !f.housekeeping)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {error && <p className="note note-error">{error}</p>}
      {conflicts.length === 0 && (
        <div className="panel panel-pad">
          <p className="note">Nothing to decide: no two sources disagree for this client.</p>
        </div>
      )}
      {conflicts.map((f, i) => {
        const chosen = progress.decisions[f.evidence_id]
        return (
          <fieldset key={f.flag_id} className="panel conflict">
            <legend className="sr-only">{f.title}</legend>
            <div className="conflict-head">
              <span className="mono small muted">
                {i + 1}/{conflicts.length}
              </span>
              <span className="conflict-q">{f.title}</span>
              {chosen ? (
                <StatusText tone="good">
                  {saved[f.evidence_id] ? `Decided · saved ${dateTime(saved[f.evidence_id])}` : 'Decided'}
                </StatusText>
              ) : (
                <StatusText tone="warn">Needs you</StatusText>
              )}
            </div>
            <p className="lead" style={{ marginTop: -8, fontSize: 14 }}>
              {f.detail}
            </p>
            <RadioGroup
              className="options"
              value={chosen ?? ''}
              onValueChange={(sourceId) => onDecide(f.evidence_id, sourceId)}
              aria-label={f.title}
            >
              {conflictOptions(b, f).map((e) => {
                const on = chosen === e.evidence_id
                const id = `${f.flag_id}-${e.evidence_id}`
                const used = e.evidence_id === usedSource(f)
                return (
                  <label key={e.evidence_id} htmlFor={id} className={`option ${on ? 'is-on' : ''}`}>
                    <span className="option-top">
                      <RadioGroupItem value={e.evidence_id} id={id} />
                      <SourceIcon source={e.source} evidenceId={e.evidence_id} size={14} />
                      {isRecord(e.evidence_id) ? 'Bank record' : 'Document'}
                      {used && <span className="suggested">Suggested</span>}
                    </span>
                    <span className="option-value">{e.label}</span>
                    <span className="option-meta">{optionNote(e.evidence_id, e.as_of, used)}</span>
                    <span className="quote">{statement(b, e)}</span>
                  </label>
                )
              })}
            </RadioGroup>
          </fieldset>
        )
      })}

      <section className="panel panel-pad" aria-labelledby="c-good" style={{ gap: 4 }}>
        <h3 id="c-good" className="h3" style={{ marginBottom: 6 }}>
          Good to know <span style={{ fontWeight: 400, color: 'var(--text-3)' }}>· already in the briefing</span>
        </h3>
        {others.length === 0 && <p className="note">Nothing else was flagged.</p>}
        {others.map((f) => {
          const [tag, tone] = GOOD_TO_KNOW[f.flag_type] ?? [f.title, 'muted']
          return (
            <div key={f.flag_id} className="gap-row">
              <Tag tone={tone}>{tag}</Tag>
              <span>{f.detail}</span>
            </div>
          )
        })}
      </section>
    </div>
  )
}
