// The right-hand column: the selected source, talking points, how the data was
// unified, and how the briefing was built. Every number here comes from the API.
import { useEffect, useState } from 'react'
import { getSource } from '../api'
import type { Briefing, Source } from '../api'
import type { Cite } from '../cite'
import { shortDate } from '../format'
import { Bullets, Card, SectionBadge, SectionNotes } from './Card'

type Props = { briefing: Briefing; cite: Cite }

// What a numbered chip opens, fetched from the entitlement-checked /sources endpoint.
// BriefingPage gives it a new `key` per chip, so it starts empty each time.
export function SourceCard({ briefing: b, cite, userId }: Props & { userId: string }) {
  const id = cite.selected
  const [source, setSource] = useState<Source | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    getSource(userId, id)
      .then((s) => !cancelled && setSource(s))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [id, userId])

  const evidence = id ? b.evidence[id] : undefined
  const isText = id?.startsWith('DOC:') || id?.startsWith('FLAG:')
  return (
    <Card
      tone="source"
      title={id ? `Source ${cite.number(id)} of ${cite.total}` : 'Sources'}
      badges={source && <span className="tag tag-plain">{source.source}</span>}
    >
      {!id && <p className="muted">Select any numbered chip in the briefing to see its source.</p>}
      {id && <p className="mono small">{id}</p>}
      {id && !source && !failed && <p className="muted">Loading…</p>}
      {failed && (
        <p className="note note-unavailable">
          This source is not available. Sources excluded from the briefing, such as unapproved news, can't be opened.
        </p>
      )}
      {source && (
        <>
          <span className="strong">{evidence?.label ?? source.label}</span>
          <span className="muted small">as of {shortDate(source.as_of)}</span>
          <blockquote className="excerpt">{isText ? String(source.value) : (evidence?.text ?? String(source.value))}</blockquote>
          <details>
            <summary className="small">Record fields</summary>
            <table className="fields">
              <tbody>
                {Object.entries(source.details).map(([key, value]) => (
                  <tr key={key}>
                    <th>{key}</th>
                    <td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </Card>
  )
}

export function TalkingPointsCard({ briefing: b, cite }: Props) {
  const s = b.sections.find((x) => x.id === 'talking_points')
  return (
    <Card title="Talking points" badges={<SectionBadge section={s} />}>
      <SectionNotes section={s} />
      <Bullets section={s} cite={cite} />
    </Card>
  )
}

export function UnificationCard({ briefing: b, cite }: Props) {
  const count = (type: string) => b.flags.filter((f) => f.flag_type === type).length
  const merged = count('duplicate_client')
  const dedupedContacts = count('duplicate_contact')
  const cited = new Set(b.sections.flatMap((s) => s.bullets.flatMap((bullet) => bullet.citations)))
  return (
    <Card title="Data unification">
      <dl className="kv">
        <div>
          <dt>Resolved entity</dt>
          <dd className="mono strong">{b.client_id}</dd>
        </div>
        <div>
          <dt>Aliases linked</dt>
          <dd>{b.aliases.join(', ') || 'None'}</dd>
        </div>
        <div>
          <dt>Duplicates merged</dt>
          <dd>
            {merged} client record{merged === 1 ? '' : 's'}, {dedupedContacts} contact{dedupedContacts === 1 ? '' : 's'}
          </dd>
        </div>
        <div>
          <dt>Unmatched references</dt>
          <dd>{count('unresolved_reference')} not attached to any client</dd>
        </div>
        <div>
          <dt>Excluded sources</dt>
          <dd>{count('excluded_source')} unapproved news item(s)</dd>
        </div>
      </dl>
      <div className="stats">
        <div>
          <span className="stat">{cited.size}</span>
          <span className="muted small">sources cited</span>
        </div>
        <div>
          <span className="stat">{cite.total}</span>
          <span className="muted small">sources linked</span>
        </div>
        <div>
          <span className="stat">{b.flags.length}</span>
          <span className="muted small">data-quality flags</span>
        </div>
      </div>
    </Card>
  )
}

export function TraceCard({ briefing: b }: { briefing: Briefing }) {
  const models = [...new Set(b.llm_runs.map((r) => `${r.model}${r.cached ? ' (cached)' : ''}`))]
  const notes = [...new Set(b.llm_runs.flatMap((r) => r.notes))]
  const passed = b.sections.filter((s) => s.check.passed).length
  const rejected = b.sections.filter((s) => s.retry_errors.length > 0).length
  const steps = [
    ['Check entitlements', 'Every query and search filters by your entitlements first.', false],
    ['Resolve and unify', 'Aliases, duplicates, stale and conflicting data handled by rules.', false],
    ['Compute metrics', 'Typed SQL tools; numbers formatted by code.', false],
    ['Retrieve documents', 'Hybrid search (keywords + meaning) over sources you may see.', false],
    ['Write the narrative', `One call to ${models.join(', ') || 'no model'}.`, true],
    ['Validate every section', 'Citations, numbers, restricted text and injected instructions checked by code.', false],
  ] as const
  return (
    <Card title="How this briefing was built">
      <ol className="trace">
        {steps.map(([step, detail, llm], i) => (
          <li key={step}>
            <span className="trace-n">{i + 1}</span>
            <div>
              <span className="strong">{step}</span>
              <span className="muted small">{detail}</span>
            </div>
            <span className={`tag ${llm ? 'tag-ai' : 'tag-code'}`}>{llm ? 'LLM' : 'No LLM'}</span>
          </li>
        ))}
      </ol>
      <div className="stats stats-2">
        <div className="stat-ok">
          <span className="stat">
            {passed} / {b.sections.length}
          </span>
          <span className="small">sections passed every check</span>
        </div>
        <div>
          <span className="stat">{rejected}</span>
          <span className="muted small">first drafts rejected and retried</span>
        </div>
      </div>
      {notes.length > 0 && <p className="muted small">Fallback: {notes.join('; ')}</p>}
      <p className="muted small">Generated in {(b.generated_ms / 1000).toFixed(1)} s.</p>
    </Card>
  )
}
