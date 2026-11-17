// Step 3, Read: the briefing itself. Every value comes from POST /briefings; sentences
// written by the AI or the template are shown as they passed the validator.
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { ActionRow, Answer, Briefing, Evidence } from '../api'
import { numberSources, sectionOf } from '../cite'
import type { Cite } from '../cite'
import { count, dayMonth, daysBetween, shortDate } from '../format'
import type { Progress } from '../progress'
import { conflictOptions } from '../workflow'
import { AskPanel } from './AskPanel'
import { SourcePanel } from './SourcePanel'
import { AuthorTag, BulletList, BulletText, CiteChips, SectionNotes, SourceIcon, StatusText, Tag } from './common'
import { Button } from '@/components/ui/button'
import type { Tone } from './common'

type Props = { briefing: Briefing; userId: string; progress: Progress }

const TOC: [string, string][] = [
  ['r-summary', 'In 30 seconds'],
  ['r-who', 'Who they are'],
  ['r-changed', 'What changed'],
  ['r-asks', 'Asks and promises'],
  ['r-numbers', 'Numbers'],
  ['r-opps', 'What to bring up'],
  ['r-news', 'In the news'],
  ['r-watch', 'Watch out for'],
]

const STAGE_TONE: Record<string, Tone> = { Negotiation: 'indigo', Proposal: 'good' }

function actionStatus(a: ActionRow, meetingDate: string): [Tone, string] {
  if (a.status === 'Done') return ['good', 'Done']
  if (a.overdue) return ['bad', `${count(daysBetween(a.due_date, meetingDate), 'day')} late`]
  return ['indigo', `Due ${dayMonth(a.due_date)}`]
}

// "In 30 seconds": the headline facts, composed by code from values the API already formatted
function summary(b: Briefing): ReactNode[] {
  const lines: ReactNode[] = []
  const revenue = b.metrics.find((m) => m.label === 'Revenue')
  if (revenue)
    lines.push(
      <>
        Revenue is <strong>{revenue.value}</strong>
        {revenue.change && ` (${revenue.change} since the last meeting)`}.
      </>,
    )
  const conflicts = b.flags.filter((f) => f.flag_type === 'conflict')
  if (conflicts.length)
    lines.push(
      <>
        <strong>{count(conflicts.length, 'thing')} to confirm:</strong> {conflicts.map((f) => f.title).join(' ')}
      </>,
    )
  const overdue = b.actions.filter((a) => a.overdue)
  if (overdue.length)
    lines.push(
      <>
        <strong>{overdue.length} overdue</strong> on our side: {overdue.map((a) => a.description).join('; ')}.
      </>,
    )
  const top = b.opportunities.find((o) => o.rank === 1)
  if (top)
    lines.push(
      <>
        Top opportunity: <strong>{top.product}</strong> ({top.stage}, {top.value}).
      </>,
    )
  return lines
}

export function ReadStep({ briefing: b, userId, progress }: Props) {
  const [answers, setAnswers] = useState<Answer[]>([]) // follow-up answers, newest first
  // Chips number the briefing's sources first, then any new ones the answers cite
  const numbers = useMemo(() => {
    const map = numberSources(b)
    for (const id of answers.flatMap((a) => a.bullets.flatMap((x) => x.citations))) if (!map.has(id)) map.set(id, map.size + 1)
    return map
  }, [b, answers])
  const evidence: Record<string, Evidence> = useMemo(
    () => Object.assign({}, ...answers.map((a) => a.evidence), b.evidence),
    [b, answers],
  )
  const [selected, setSelected] = useState<string | null>(null)
  const [agendaEdits, setAgendaEdits] = useState<Record<string, boolean>>({}) // opportunity -> on/off agenda
  const cite: Cite = {
    number: (id) => numbers.get(id) ?? 0,
    describe: (id) => ({ label: evidence[id]?.label ?? 'Source', source: evidence[id]?.source ?? null }),
    selected,
    select: setSelected,
  }

  const s = (id: string) => sectionOf(b, id)
  const actionIds = new Set(b.actions.map((a) => a.evidence_id))
  const serviceIssues = (s('open_items')?.bullets ?? []).filter((x) => !x.citations.some((c) => actionIds.has(c)))
  const live = b.opportunities.filter((o) => o.live)
  const notLive = b.opportunities.filter((o) => !o.live)
  const attention = b.flags.filter((f) => !f.housekeeping)
  const cfo = b.contacts.find((c) => c.endsWith(', CFO'))
  const latestAsOf = b.metrics.map((m) => m.as_of).sort().at(-1)

  // The agenda: the talking points, plus or minus the opportunities the banker toggled
  const points = s('talking_points')?.bullets ?? []
  const pointCites = (oppId: string) => points.some((p) => p.citations.includes(oppId))
  const onAgenda = (oppId: string) => agendaEdits[oppId] ?? pointCites(oppId)
  const agenda = [
    ...points
      .filter((p) => !p.citations.some((c) => agendaEdits[c] === false))
      .map((p) => ({ text: p.text, citations: p.citations })),
    ...live
      .filter((o) => agendaEdits[o.evidence_id] && !pointCites(o.evidence_id))
      .map((o) => ({ text: `Discuss ${o.product} (${o.stage}, estimated ${o.value}).`, citations: [o.evidence_id] })),
  ]

  return (
    <>
    <AskPanel
      briefing={b}
      userId={userId}
      answers={answers}
      onAnswer={(a) => setAnswers((all) => [a, ...all])}
      cite={cite}
    />
    <div className="read">
      <nav className="toc" aria-label="Briefing contents">
        <span className="small muted" style={{ padding: '0 10px 8px' }}>
          On this page
        </span>
        {TOC.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </nav>

      <article className="panel article">
        <section id="r-summary" aria-labelledby="h-summary">
          <h3 id="h-summary" className="kicker">
            In 30 seconds
          </h3>
          <ul className="summary">
            {summary(b).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          <div className="hints">
            <span>
              <span className="cite" style={{ marginLeft: 0 }} aria-hidden="true">
                <SourceIcon source="email" size={10} />2
              </span>
              Click a number to see the source
            </span>
            <span>
              <span className="mono" style={{ fontWeight: 600, color: 'var(--text)' }} aria-hidden="true">
                $
              </span>
              Figures come from SQL, formatted by code, never by AI
            </span>
          </div>
        </section>

        <section id="r-who" aria-labelledby="h-who">
          <div className="sec-head">
            <h3 id="h-who">Who they are</h3>
            <AuthorTag section={s('client_overview')} />
          </div>
          <dl className="facts">
            <div>
              <dt>Segment</dt>
              <dd>{b.segment}</dd>
            </div>
            <div>
              <dt>Region</dt>
              <dd>{b.region}</dd>
            </div>
            {b.coverage[0] && (
              <div>
                <dt>Coverage lead</dt>
                <dd>{b.coverage[0].replace(/ \(.*\)$/, '')}</dd>
              </div>
            )}
            {cfo && (
              <div>
                <dt>CFO</dt>
                <dd>{cfo.replace(', CFO', '')}</dd>
              </div>
            )}
          </dl>
          <SectionNotes section={s('client_overview')} />
          <BulletList section={s('client_overview')} cite={cite} compact />
        </section>

        <section id="r-changed" aria-labelledby="h-changed">
          <div className="sec-head">
            <h3 id="h-changed">{b.last_interaction ? `What changed since ${dayMonth(b.last_interaction)}` : 'What changed'}</h3>
            <Tag className="ml-auto">Computed by code · no AI</Tag>
          </div>
          {b.what_changed.length === 0 ? (
            <p className="note">{b.last_interaction ? 'Nothing new since the last interaction.' : 'No earlier interaction on file.'}</p>
          ) : (
            <ul className="bullets">
              {b.what_changed.map((c, i) => (
                <li key={i}>
                  {c.text}
                  <CiteChips ids={c.evidence_ids} cite={cite} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <section id="r-asks" aria-labelledby="h-asks">
          <div className="sec-head">
            <h3 id="h-asks">What they asked, what we promised</h3>
            <AuthorTag section={s('client_said')} />
          </div>
          <SectionNotes section={s('client_said')} />
          <span className="list-label">They said</span>
          <BulletList section={s('client_said')} cite={cite} />
          {b.actions.length > 0 && <span className="list-label">We promised</span>}
          <div>
            {b.actions.map((a) => {
              const [tone, text] = actionStatus(a, b.meeting_date)
              return (
                <div key={a.action_id} className="ask-row">
                  <StatusText tone={tone}>{text}</StatusText>
                  <div>
                    <span className="ask-item">
                      {a.description}
                      <CiteChips ids={[a.evidence_id]} cite={cite} />
                    </span>
                    <span className="sub">
                      Owner {a.owner} · due {shortDate(a.due_date)}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
          {serviceIssues.length > 0 && (
            <>
              <span className="list-label">Service issues</span>
              <ul className="bullets">
                {serviceIssues.map((x, i) => (
                  <li key={i}>
                    <BulletText text={x.text} />
                    <CiteChips ids={x.citations} cite={cite} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section id="r-numbers" aria-labelledby="h-numbers">
          <div className="sec-head">
            <h3 id="h-numbers">Numbers that matter</h3>
            {latestAsOf && <span className="sub">As of {shortDate(latestAsOf)}</span>}
            <AuthorTag section={s('metrics')} />
          </div>
          {b.metrics.length === 0 && <p className="note">No figures on file.</p>}
          <div className="tiles">
            {b.metrics.map((m) => (
              <div key={m.label} className="tile">
                <span style={{ fontSize: 13, color: 'var(--text-2)' }}>
                  {m.label}
                  <CiteChips ids={[m.evidence_id]} cite={cite} />
                </span>
                <span className="tile-value">{m.value}</span>
                {m.change && (
                  <span className={`delta ${m.change.startsWith('+') ? 'delta-up' : m.change.startsWith('-') ? 'delta-down' : ''}`}>
                    {m.change} since the last meeting
                  </span>
                )}
                <span className="small muted">
                  {m.period ? `${m.period} · ` : ''}as of {dayMonth(m.as_of)}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section id="r-opps" aria-labelledby="h-opps">
          <div className="sec-head">
            <h3 id="h-opps">What to bring up</h3>
            <AuthorTag section={s('opportunities')} />
          </div>
          <SectionNotes section={s('opportunities')} />
          {live.length === 0 && <p className="note">No live opportunities.</p>}
          {live.map((o) => {
            const on = onAgenda(o.evidence_id)
            const why = s('opportunities')?.bullets.find((x) => x.citations.includes(o.evidence_id))
            return (
              <div key={o.opp_id} className={`opp ${on ? 'is-on' : ''}`}>
                <div className="opp-head">
                  <span className="opp-title">{o.product}</span>
                  <Tag tone={STAGE_TONE[o.stage] ?? 'muted'}>{o.stage}</Tag>
                  <span className="mono" style={{ fontWeight: 600 }}>
                    {o.value}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className={on ? 'ml-auto border-(--indigo) bg-(--indigo) text-white hover:bg-(--indigo-strong) hover:text-white' : 'ml-auto'}
                    aria-pressed={on}
                    onClick={() => setAgendaEdits((e) => ({ ...e, [o.evidence_id]: !on }))}
                  >
                    {on ? 'On agenda' : 'Add to agenda'}
                  </Button>
                </div>
                {why && (
                  <p className="opp-pitch">
                    <BulletText text={why.text} />
                    <CiteChips ids={why.citations} cite={cite} />
                  </p>
                )}
                {!why && (
                  <span className="sub">
                    Owner {o.owner}
                    {o.next_step && ` · Next step: ${o.next_step}`}
                    <CiteChips ids={[o.evidence_id]} cite={cite} />
                  </span>
                )}
              </div>
            )
          })}
          {notLive.length > 0 && <span className="list-label">Not live</span>}
          {notLive.map((o) => (
            <p key={o.opp_id} className="note">
              <strong>{o.product}</strong>: {o.stage} on {dayMonth(o.updated)}
              {o.next_step && `: ${o.next_step}`}.
              <CiteChips ids={[o.evidence_id]} cite={cite} />
            </p>
          ))}
        </section>

        <section id="r-news" aria-labelledby="h-news">
          <div className="sec-head">
            <h3 id="h-news">In the news</h3>
            <AuthorTag section={s('news')} />
          </div>
          <SectionNotes section={s('news')} />
          {(s('news')?.bullets ?? []).map((x, i) => {
            const source = b.evidence[x.citations[0]]
            return (
              <div key={i} className="news-row">
                <span className="news-date">{source ? dayMonth(source.as_of) : ''}</span>
                <span className="news-text">
                  {x.text}
                  <CiteChips ids={x.citations} cite={cite} />
                </span>
              </div>
            )
          })}
        </section>

        <section id="r-watch" aria-labelledby="h-watch" className="watch">
          <div className="sec-head">
            <h3 id="h-watch">Watch out for</h3>
            <AuthorTag section={s('uncertain')} />
          </div>
          {attention.length === 0 && <p className="note">Nothing to watch out for.</p>}
          <ul>
            {attention.map((f) => {
              const chosen = progress.decisions[f.evidence_id]
              const pick = chosen ? conflictOptions(b, f).find((e) => e.evidence_id === chosen) : undefined
              return (
                <li key={f.flag_id}>
                  <strong>{f.title}</strong> {f.detail}
                  {pick && <em> Your call: you trust {pick.label}.</em>}
                  <CiteChips ids={[f.evidence_id]} cite={cite} />
                </li>
              )
            })}
            {b.sections
              .filter((x) => x.status === 'fallback' || x.status === 'unavailable')
              .map((x) => (
                <li key={x.id}>
                  {x.status === 'fallback'
                    ? `“${x.title}”: the draft failed its checks, so the source facts are shown instead.`
                    : `“${x.title}”: the data could not be loaded.`}
                </li>
              ))}
          </ul>
        </section>
      </article>

      <aside className="read-aside" aria-label="Source and agenda">
        <SourcePanel key={selected ?? 'none'} briefing={{ ...b, evidence }} userId={userId} evidenceId={selected} number={selected ? cite.number(selected) : 0} />
        <section className="panel panel-pad" aria-labelledby="h-agenda">
          <div className="panel-head">
            <h3 id="h-agenda" className="h3">
              Your agenda
            </h3>
            <span className="end mono small muted">{count(agenda.length, 'topic')}</span>
          </div>
          <AuthorTag section={s('talking_points')} />
          <ol className="agenda">
            {agenda.map((item, i) => (
              <li key={i}>
                <span className="mono">{String(i + 1).padStart(2, '0')}</span>
                <span style={{ flex: '1 1 auto', fontWeight: 500 }}>
                  <BulletText text={item.text} />
                  <CiteChips ids={item.citations} cite={cite} />
                </span>
              </li>
            ))}
          </ol>
          <span className="small muted">Add or remove topics in “What to bring up”.</span>
        </section>
      </aside>
    </div>
    </>
  )
}
