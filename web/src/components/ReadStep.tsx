// Step 3, Read: the briefing itself. Every value comes from POST /briefings; sentences
// written by the AI or the template are shown as they passed the validator.
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { judgeBriefing } from '../api'
import type { ActionRow, Answer, Briefing, Evidence, JudgeReport } from '../api'
import { numberSources, sectionOf } from '../cite'
import type { Cite } from '../cite'
import { count, dayMonth, daysBetween, shortDate } from '../format'
import type { Progress } from '../progress'
import { conflictOptions } from '../workflow'
import { AskPanel } from './AskPanel'
import { SourcePanel } from './SourcePanel'
import { AuthorTag, BulletList, BulletText, CiteChips, JudgeBadge, SectionNotes, SourceIcon, StatusText, Tag } from './common'
import type { Judged } from './common'
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { Tone } from './common'

type Props = { briefing: Briefing; userId: string; progress: Progress }

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
  const [current, setCurrent] = useState(0) // the section on screen
  const [agendaEdits, setAgendaEdits] = useState<Record<string, boolean>>({}) // opportunity -> on/off agenda
  // The AI judge: asked on demand (one request, none when cached); labels only, counted by the API
  const [judge, setJudge] = useState<JudgeReport | null>(null)
  const [judging, setJudging] = useState(false)
  const [judgeError, setJudgeError] = useState<string | null>(null)
  const askJudge = async () => {
    setJudging(true)
    setJudgeError(null)
    try {
      setJudge(await judgeBriefing(userId, b.client_id))
    } catch (e) {
      setJudgeError(e instanceof Error ? e.message : 'The judge could not be reached.')
    } finally {
      setJudging(false)
    }
  }
  const judged: Judged = (section, bullet) => judge?.bullets.find((x) => x.section === section && x.bullet === bullet)?.verdict
  const judgedText = (section: string, text: string) => {
    const i = sectionOf(b, section)?.bullets.findIndex((x) => x.text === text) ?? -1
    return i >= 0 ? judged(section, i) : undefined
  }
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

  // The sections, one shown at a time: title in the list, a count beside it, and the body
  type Part = { id: string; nav: string; title: ReactNode; meta: string; tone?: Tone; tag?: ReactNode; body: ReactNode }
  const overdue = b.actions.filter((a) => a.overdue).length
  const picked = live.filter((o) => onAgenda(o.evidence_id)).length
  const parts: Part[] = [
    {
      id: 'who', nav: 'Who they are', title: 'Who they are', tag: <AuthorTag section={s('client_overview')} />,
      meta: count(s('client_overview')?.bullets.length ?? 0, 'fact'),
      body: (
        <>
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
          <BulletList section={s('client_overview')} cite={cite} compact judged={judged} />
        </>
      ),
    },
    {
      id: 'changed', nav: 'What changed', meta: String(b.what_changed.length),
      title: b.last_interaction ? `What changed since ${dayMonth(b.last_interaction)}` : 'What changed',
      tag: <Tag className="author-tag">Computed by code · no AI</Tag>,
      body:
        b.what_changed.length === 0 ? (
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
        ),
    },
    {
      id: 'asks', nav: 'Asks and promises', title: 'What they asked, what we promised',
      meta: overdue ? `${overdue} late` : String(b.actions.length), tone: overdue ? 'bad' : undefined,
      tag: <AuthorTag section={s('client_said')} />,
      body: (
        <>
          <SectionNotes section={s('client_said')} />
          <span className="list-label">They said</span>
          <BulletList section={s('client_said')} cite={cite} judged={judged} />
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
                    <JudgeBadge verdict={judgedText('open_items', x.text)} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ),
    },
    {
      id: 'numbers', nav: 'Numbers', title: 'Numbers that matter', meta: String(b.metrics.length),
      tag: (
        <>
          {latestAsOf && <span className="sub">As of {shortDate(latestAsOf)}</span>}
          <AuthorTag section={s('metrics')} />
        </>
      ),
      body: (
        <>
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
        </>
      ),
    },
    {
      id: 'opps', nav: 'What to bring up', title: 'What to bring up', meta: picked ? `${picked} picked` : '',
      tone: 'indigo', tag: <AuthorTag section={s('opportunities')} />,
      body: (
        <>
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
                {why ? (
                  <p className="opp-pitch">
                    <BulletText text={why.text} />
                    <CiteChips ids={why.citations} cite={cite} />
                    <JudgeBadge verdict={judgedText('opportunities', why.text)} />
                  </p>
                ) : (
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
        </>
      ),
    },
    {
      id: 'news', nav: 'In the news', title: 'In the news', meta: String(s('news')?.bullets.length ?? 0),
      tag: <AuthorTag section={s('news')} />,
      body: (
        <>
          <SectionNotes section={s('news')} />
          {(s('news')?.bullets ?? []).length === 0 && <p className="note">No recent approved news.</p>}
          {(s('news')?.bullets ?? []).map((x, i) => {
            const source = b.evidence[x.citations[0]]
            return (
              <div key={i} className="news-row">
                <span className="news-date">{source ? dayMonth(source.as_of) : ''}</span>
                <span className="news-text">
                  {x.text}
                  <CiteChips ids={x.citations} cite={cite} />
                  <JudgeBadge verdict={judged('news', i)} />
                </span>
              </div>
            )
          })}
        </>
      ),
    },
    {
      id: 'watch', nav: 'Watch out for', title: 'Watch out for', meta: String(attention.length),
      tone: attention.length ? 'warn' : undefined, tag: <AuthorTag section={s('uncertain')} />,
      body: (
        <div className="watch">
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
        </div>
      ),
    },
    {
      id: 'ask', nav: 'Ask a follow-up', title: 'Ask a follow-up', meta: answers.length ? `${answers.length} asked` : '',
      body: <AskPanel briefing={b} userId={userId} answers={answers} onAnswer={(a) => setAnswers((all) => [a, ...all])} cite={cite} />,
    },
  ]
  const part = parts[current]
  const prev = parts[current - 1]
  const next = parts[current + 1]

  return (
    <div className="read">
      <nav className="section-nav" aria-label="Briefing sections">
        <span className="section-nav-label">Sections</span>
        {parts.map((p, i) => (
          <button key={p.id} type="button" className="nav-sec" aria-current={i === current} onClick={() => setCurrent(i)}>
            <span className="nav-num">{i + 1}</span>
            <span className="nav-title">{p.nav}</span>
            {p.meta && <span className={`nav-meta ${p.tone ? `tone-${p.tone}` : ''}`}>{p.meta}</span>}
          </button>
        ))}
        <span className="nav-hint">One section at a time, so the source panel stays in view.</span>
      </nav>

      <div className="read-main">
        <section className="panel summary-card" aria-labelledby="h-summary">
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

        <section className="panel panel-pad" aria-labelledby="h-judge">
          <div className="panel-head">
            <h3 id="h-judge" className="h3">
              Second opinion: AI judge
            </h3>
            <Button variant="outline" size="sm" className="ml-auto" disabled={judging} onClick={askJudge}>
              {judging ? 'Judging…' : judge ? 'Ask again' : 'Ask the AI judge'}
            </Button>
          </div>
          {!judge && !judgeError && (
            <p className="small muted">
              Another AI model checks each AI-written sentence against the sources it cites. It only picks a label; the
              validator's checks stay the gate.
            </p>
          )}
          {judgeError && <p className="small" style={{ color: 'var(--bad)' }}>{judgeError}</p>}
          {judge?.note && <p className="small muted">{judge.note}</p>}
          {judge?.judge && (
            <p className="small">
              Judged by <strong>{judge.judge}</strong>
              {judge.cached && ' (cached)'}: {judge.verdicts.supported ?? 0} of {count(judge.claims, 'claim')} supported
              {(judge.verdicts.unsupported ?? 0) > 0 && `, ${judge.verdicts.unsupported} not in their sources`}
              {(judge.verdicts.contradicted ?? 0) > 0 && `, ${judge.verdicts.contradicted} contradicted`}
              {(judge.verdicts.no_verdict ?? 0) > 0 && `, ${judge.verdicts.no_verdict} without an answer`}. Labels appear beside each
              sentence.
              {judge.self_judged && ' The judge is the same model as the writer, which tends to favour its own wording.'}
            </p>
          )}
        </section>

        <article className="panel read-card" aria-labelledby="h-part">
          <div className="read-progress">
            <span className="mono small muted">
              {current + 1} of {parts.length}
            </span>
            <span className="progress-segs" aria-hidden="true">
              {parts.map((p, i) => (
                <span key={p.id} className={i <= current ? 'on' : ''} />
              ))}
            </span>
          </div>
          <div className="sec-head">
            <h3 id="h-part">{part.title}</h3>
            {part.tag}
          </div>
          {part.body}
          <div className="read-pager">
            {prev && (
              <Button variant="ghost" size="sm" onClick={() => setCurrent(current - 1)}>
                <ChevronLeft aria-hidden="true" />
                {prev.nav}
              </Button>
            )}
            {next && (
              <Button variant="outline" size="sm" className="ml-auto" onClick={() => setCurrent(current + 1)}>
                Next: {next.nav}
                <ChevronRight aria-hidden="true" />
              </Button>
            )}
          </div>
        </article>
      </div>

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
                  <JudgeBadge verdict={judgedText('talking_points', item.text)} />
                </span>
              </li>
            ))}
          </ol>
          <span className="small muted">Add or remove topics in “What to bring up”.</span>
        </section>
      </aside>
    </div>
  )
}
