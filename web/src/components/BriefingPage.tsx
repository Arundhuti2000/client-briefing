// One briefing: title row, conflict banner, the main cards and the right-hand column.
import { useMemo, useState } from 'react'
import type { Briefing } from '../api'
import { numberSources } from '../cite'
import type { Cite } from '../cite'
import { shortDate } from '../format'
import { SourceCard, TalkingPointsCard, TraceCard, UnificationCard } from './AsideCards'
import { AsksCard, ChangesCard, GlanceCard, MetricsCard, NewsCard, OpportunitiesCard, UncertainCard } from './MainCards'

type Props = {
  briefing: Briefing
  userId: string
  meetingDate: string
  loading: boolean
  onRegenerate: () => void
}

function downloadMarkdown(b: Briefing) {
  const url = URL.createObjectURL(new Blob([b.markdown], { type: 'text/markdown' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `briefing-${b.client_id}-${b.meeting_date}-${b.user_id}.md`
  link.click()
  URL.revokeObjectURL(url)
}

export function BriefingPage({ briefing: b, userId, meetingDate, loading, onRegenerate }: Props) {
  const [selected, setSelected] = useState<string | null>(null)
  const numbers = useMemo(() => numberSources(b), [b])
  const cite: Cite = { number: (id) => numbers.get(id) ?? 0, total: numbers.size, selected, select: setSelected }

  const conflicts = b.flags.filter((f) => f.flag_type === 'conflict').length
  const unverified = b.sections.some((s) => !s.check.passed || s.status === 'fallback')
  const status = conflicts
    ? { label: `Needs review: ${conflicts} conflicts`, tone: 'pill-warn' }
    : unverified
      ? { label: 'Partly unverified', tone: 'pill-warn' }
      : { label: 'All checks passed', tone: 'pill-ok' }

  return (
    <>
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <span>Briefings</span>
        <span aria-hidden="true">/</span>
        <span className="strong">{b.client_name}</span>
      </nav>

      <div className="title-row">
        <div className="title-block">
          <div className="title-line">
            <h1>{b.client_name}</h1>
            <span className={`pill ${status.tone}`}>{status.label}</span>
          </div>
          <p className="muted">
            Meeting {shortDate(b.meeting_date)} · Last interaction {shortDate(b.last_interaction)} · Prepared for{' '}
            {b.prepared_for}
          </p>
          <div className="people">
            <span className="strong">Key contacts</span>
            {b.contacts.map((c) => (
              <span key={c} className="person">
                {c}
              </span>
            ))}
          </div>
        </div>
        <div className="title-actions">
          <button type="button" className="btn btn-ghost" disabled={loading} onClick={onRegenerate}>
            {loading ? 'Regenerating…' : 'Regenerate'}
          </button>
          <button type="button" className="btn" onClick={() => downloadMarkdown(b)}>
            Download as Markdown
          </button>
        </div>
      </div>

      {conflicts > 0 && (
        <div role="status" className="banner">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#B45309" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l9.5 17h-19z" />
            <path d="M12 10v4M12 17.5v.01" />
          </svg>
          <span>
            <strong>{conflicts} conflicting statements</strong> were found in the source data. The briefing uses the
            newer source and shows both.
          </span>
          <a href="#uncertain">Review now</a>
        </div>
      )}

      <div className="columns">
        <div className="main-col">
          <GlanceCard briefing={b} cite={cite} />
          <ChangesCard briefing={b} cite={cite} />
          <AsksCard briefing={b} cite={cite} userId={userId} meetingDate={meetingDate} />
          <MetricsCard briefing={b} cite={cite} />
          <OpportunitiesCard briefing={b} cite={cite} />
          <NewsCard briefing={b} cite={cite} />
          <UncertainCard briefing={b} cite={cite} />
        </div>
        <aside aria-label="Evidence and provenance" className="side-col">
          <SourceCard key={selected ?? 'none'} briefing={b} cite={cite} userId={userId} />
          <TalkingPointsCard briefing={b} cite={cite} />
          <UnificationCard briefing={b} cite={cite} />
          <TraceCard briefing={b} />
        </aside>
      </div>
    </>
  )
}
