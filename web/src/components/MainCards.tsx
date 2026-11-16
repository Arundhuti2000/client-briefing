// The main column: one card per briefing question, in the design's order.
// Numbers and structure come from the API (SQL and rules); prose comes from the
// validated sections.
import { useState } from 'react'
import { createTask } from '../api'
import type { Briefing, Section, Task } from '../api'
import type { Cite } from '../cite'
import { errorMessage, shortDate } from '../format'
import { Bullets, Card, Chips, SectionBadge, SectionNotes } from './Card'

type Props = { briefing: Briefing; cite: Cite }

const sectionOf = (b: Briefing, id: string): Section | undefined => b.sections.find((s) => s.id === id)

export function GlanceCard({ briefing: b, cite }: Props) {
  const s = sectionOf(b, 'client_overview')
  return (
    <Card title="At a glance" badges={<SectionBadge section={s} />}>
      <SectionNotes section={s} />
      <Bullets section={s} cite={cite} />
      <dl className="facts">
        <div>
          <dt>Segment</dt>
          <dd>{b.segment}</dd>
        </div>
        <div>
          <dt>Region</dt>
          <dd>{b.region}</dd>
        </div>
        <div>
          <dt>Coverage lead</dt>
          <dd>{b.coverage[0] ?? 'Not on file'}</dd>
        </div>
        <div>
          <dt>Last interaction</dt>
          <dd>{shortDate(b.last_interaction)}</dd>
        </div>
      </dl>
    </Card>
  )
}

export function ChangesCard({ briefing: b, cite }: Props) {
  return (
    <Card
      title={`What changed since ${shortDate(b.last_interaction)}`}
      badges={<span className="tag tag-code">Computed by code · no LLM</span>}
    >
      {b.what_changed.length === 0 && <p className="muted">No earlier meeting note or briefing on file.</p>}
      <ul className="dots">
        {b.what_changed.map((c) => (
          <li key={c.text}>
            <span>{c.text}</span> <Chips ids={c.evidence_ids} cite={cite} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

type AsksProps = Props & { userId: string; meetingDate: string }

export function AsksCard({ briefing: b, cite, userId, meetingDate }: AsksProps) {
  const said = sectionOf(b, 'client_said')
  const open = sectionOf(b, 'open_items')
  const [selected, setSelected] = useState<string[]>([])
  const [created, setCreated] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)

  const toggle = (id: string) => setSelected((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]))

  async function createTasks() {
    setError(null)
    try {
      const chosen = b.actions.filter((a) => selected.includes(a.action_id))
      const tasks = await Promise.all(
        chosen.map((a) =>
          createTask(userId, {
            client_id: b.client_id,
            description: `Follow up: ${a.description}`,
            due_date: meetingDate,
            source_id: a.evidence_id,
          }),
        ),
      )
      setCreated((existing) => [...existing, ...tasks])
      setSelected([])
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Card
      title="Asks, commitments and open items"
      badges={
        <>
          <SectionBadge section={said} />
        </>
      }
    >
      <h3 className="subhead">What the client asked, said or committed</h3>
      <SectionNotes section={said} />
      <Bullets section={said} cite={cite} />

      <h3 className="subhead">Open actions</h3>
      <div className="table-scroll">
        <table className="grid-table">
          <thead>
            <tr>
              <th aria-label="Select" />
              <th>Item</th>
              <th>Owner</th>
              <th>Due</th>
              <th>Status</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {b.actions.map((a) => (
              <tr key={a.action_id} className={a.status === 'Done' ? 'row-done' : ''}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${a.description}`}
                    disabled={a.status !== 'Open'}
                    checked={selected.includes(a.action_id)}
                    onChange={() => toggle(a.action_id)}
                  />
                </td>
                <td className="strong">{a.description}</td>
                <td>{a.owner}</td>
                <td className={a.overdue ? 'text-bad' : ''}>{shortDate(a.due_date)}</td>
                <td>
                  {a.overdue ? (
                    <span className="pill pill-bad">Overdue</span>
                  ) : a.status === 'Done' ? (
                    <span className="pill pill-ok">Done</span>
                  ) : (
                    <span className="pill pill-info">Open</span>
                  )}
                </td>
                <td>
                  <Chips ids={[a.evidence_id]} cite={cite} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-actions">
        <button type="button" className="btn" disabled={selected.length === 0} onClick={createTasks}>
          Create follow-up task{selected.length > 1 ? 's' : ''}
        </button>
        <span className="muted small">Tick open actions to create tasks for them. This is the only thing you can write.</span>
      </div>
      {error && <p className="note note-unavailable">{error}</p>}
      {created.length > 0 && (
        <p className="note note-ok">Created {created.map((t) => `${t.task_id} (${t.description})`).join(', ')}.</p>
      )}

      <h3 className="subhead">
        Summary of open items <SectionBadge section={open} />
      </h3>
      <SectionNotes section={open} />
      <Bullets section={open} cite={cite} />
    </Card>
  )
}

export function MetricsCard({ briefing: b, cite }: Props) {
  const s = sectionOf(b, 'metrics')
  return (
    <Card title="Material metrics" badges={<SectionBadge section={s} codeLabel="Computed via SQL · no LLM" />}>
      <SectionNotes section={s} />
      <div className="tiles">
        {b.metrics.map((m) => (
          <div key={m.label} className="tile">
            <div className="tile-head">
              <span>{m.label}</span>
              <Chips ids={[m.evidence_id]} cite={cite} />
            </div>
            <span className="tile-value">{m.value}</span>
            <span className={`tile-delta ${m.change?.startsWith('-') ? 'text-bad' : m.change ? 'text-ok' : ''}`}>
              {m.change ? `${m.change} since last interaction` : 'No earlier value'}
            </span>
            <span className="muted small">
              as of {shortDate(m.as_of)}
              {m.period ? ` (${m.period})` : ''}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function OpportunitiesCard({ briefing: b, cite }: Props) {
  const s = sectionOf(b, 'opportunities')
  const live = b.opportunities.filter((o) => o.live)
  const notLive = b.opportunities.filter((o) => !o.live)
  const liveIds = new Set(live.map((o) => o.evidence_id))
  const bullets = s?.bullets ?? []
  const other = bullets.filter((bullet) => !bullet.citations.some((c) => liveIds.has(c)))
  return (
    <Card title="Opportunities to discuss" badges={<SectionBadge section={s} />}>
      <SectionNotes section={s} />
      <p className="muted small">Ranked by code: expected value (estimate × stage probability), then recency.</p>
      {live.map((o) => {
        const why = bullets.filter((bullet) => bullet.citations.includes(o.evidence_id))
        return (
          <div key={o.opp_id} className="opp">
            <div className="opp-head">
              <span className="rank">#{o.rank}</span>
              <span className="opp-title">{o.product}</span>
              <span className="pill pill-info">{o.stage}</span>
              <span className="mono">{o.value}</span>
              <span className="muted">· {o.owner}</span>
              <Chips ids={[o.evidence_id]} cite={cite} />
            </div>
            <p className="opp-next">Next step: {o.next_step}</p>
            {why.length > 0 && (
              <div className="evidence-box">
                <span className="eyebrow">Why now</span>
                {why.map((bullet, i) => (
                  <div key={i} className="evidence-line">
                    <span>{bullet.text}</span> <Chips ids={bullet.citations} cite={cite} />
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
      {live.length === 0 && <p className="muted">No live opportunities.</p>}
      {(notLive.length > 0 || other.length > 0) && (
        <div className="evidence-box">
          <span className="eyebrow">Not live</span>
          {notLive.map((o) => (
            <div key={o.opp_id} className="evidence-line">
              <span>
                {o.product}: {o.stage} ({o.next_step})
              </span>{' '}
              <Chips ids={[o.evidence_id]} cite={cite} />
            </div>
          ))}
          {other.map((bullet, i) => (
            <div key={i} className="evidence-line">
              <span>{bullet.text}</span> <Chips ids={bullet.citations} cite={cite} />
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export function NewsCard({ briefing: b, cite }: Props) {
  const s = sectionOf(b, 'news')
  return (
    <Card
      title="News to shape the conversation"
      badges={
        <>
          <span className="tag tag-code">Approved sources only</span>
          <SectionBadge section={s} />
        </>
      }
    >
      <SectionNotes section={s} />
      {(s?.bullets ?? []).map((bullet, i) => {
        const doc = b.evidence[bullet.citations.find((c) => c.startsWith('DOC:')) ?? '']
        return (
          <div key={i} className="news">
            <span className="news-date">{doc ? shortDate(doc.as_of) : ''}</span>
            <div className="news-body">
              <div className="news-head">
                <span className="strong">{doc ? doc.text.split('\n')[0] : 'News item'}</span>
                {doc?.source && <span className="muted small">{doc.source}</span>}
                <Chips ids={bullet.citations} cite={cite} />
              </div>
              <span className="muted">{bullet.text}</span>
            </div>
          </div>
        )
      })}
    </Card>
  )
}

const FLAG_LABELS: Record<string, string> = {
  stale_statement: 'Stale figure',
  stale: 'Superseded values',
  overdue: 'Overdue',
  excluded_source: 'Excluded source',
  duplicate_client: 'Merged duplicate',
  duplicate_contact: 'Duplicate contact',
  unresolved_reference: 'Unmatched reference',
}

export function UncertainCard({ briefing: b, cite }: Props) {
  const s = sectionOf(b, 'uncertain')
  const conflicts = b.flags.filter((f) => f.flag_type === 'conflict')
  const others = b.flags.filter((f) => f.flag_type !== 'conflict')
  return (
    <Card
      id="uncertain"
      tone="warn"
      title="Uncertain, conflicting or unavailable"
      badges={
        <>
          {conflicts.length > 0 && <span className="tag tag-warn">{conflicts.length} conflicts</span>}
          <SectionBadge section={s} codeLabel="Rules · no LLM" />
        </>
      }
    >
      <SectionNotes section={s} />
      {b.flags.length === 0 && <p className="muted">No data-quality issues found.</p>}
      {conflicts.map((f) => (
        <div key={f.flag_id} className="conflict">
          <div className="conflict-head">
            <span className="tag tag-conflict">Conflict</span>
            <Chips ids={[f.evidence_id, ...f.source_ids]} cite={cite} />
          </div>
          <p>{f.detail}</p>
        </div>
      ))}
      <div className="gaps">
        {others.map((f) => (
          <div key={f.flag_id} className="gap">
            <span className={`pill severity-${f.severity}`}>{FLAG_LABELS[f.flag_type] ?? f.flag_type}</span>
            <span>
              {f.detail} <Chips ids={[f.evidence_id, ...f.source_ids]} cite={cite} />
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}
