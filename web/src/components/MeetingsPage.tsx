// The meeting queue: every client meeting, where its briefing is, and what needs the banker.
// Rows come from GET /clients (no LLM call); progress comes from this browser.
import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { resolveClient } from '../api'
import type { ClientSummary, ResolveResponse } from '../api'
import { count, countdown, errorMessage, greeting, initials, todayLine, weekdayDate } from '../format'
import { openDecisions, statusOf } from '../progress'
import type { Progress, Status } from '../progress'
import type { Step } from './BriefingPage'
import { StatusText } from './common'
import type { Tone } from './common'
import { CircleAlert, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

type Props = {
  clients: ClientSummary[] | null
  firstName: string
  userId: string
  progressOf: (clientId: string) => Progress
  onOpen: (clientId: string, step: Step) => void
}

type Filter = 'all' | Status
type Row = { client: ClientSummary; status: Status; open: number }

// How each status shows: progress bar segments (Gather, Check, Read, Share), text, button
const LOOK: Record<Status, { segs: string[]; tone: Tone; action: string; step: Step }> = {
  'needs-you': { segs: ['done', 'warn', '', ''], tone: 'warn', action: 'Review', step: 'check' },
  ready: { segs: ['done', 'done', 'indigo', ''], tone: 'indigo', action: 'Open', step: 'read' },
  read: { segs: ['done', 'done', 'done', 'indigo'], tone: 'indigo', action: 'Open', step: 'share' },
  approved: { segs: ['done', 'done', 'done', 'done'], tone: 'good', action: 'Open', step: 'read' },
}

function statusText(row: Row): string {
  switch (row.status) {
    case 'needs-you':
      return `Waiting on you: ${count(row.open, 'decision')}`
    case 'ready':
      return 'Ready to read'
    case 'read':
      return 'Read, not approved yet'
    default:
      return 'Approved'
  }
}

function headsUp(c: ClientSummary): string {
  if (c.conflicts.length) return `${count(c.conflicts.length, 'conflict')}: ${c.conflicts.join(' ')}`
  return c.heads_up.length ? c.heads_up.join(' · ') : 'No issues found'
}

export function MeetingsPage({ clients, firstName, userId, progressOf, onOpen }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [resolved, setResolved] = useState<ResolveResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const rows: Row[] = (clients ?? []).map((c) => {
    const progress = progressOf(c.client_id)
    return { client: c, status: statusOf(c.conflicts.length, progress), open: openDecisions(c.conflicts.length, progress) }
  })
  const needYou = rows.filter((r) => r.status === 'needs-you')
  const q = query.trim().toLowerCase()
  const matches = (c: ClientSummary) => !q || [c.client_name, ...c.aliases].some((n) => n.toLowerCase().includes(q))
  const shown = rows.filter((r) => (filter === 'all' || r.status === filter) && matches(r.client))
  const tabs: [Filter, string][] = [
    ['all', 'All'],
    ['needs-you', `Needs you · ${needYou.length}`],
    ['ready', `Ready · ${rows.filter((r) => r.status === 'ready').length}`],
    ['approved', `Approved · ${rows.filter((r) => r.status === 'approved').length}`],
  ]

  // Enter: open the one match; otherwise ask the API, which resolves aliases and typos
  async function search(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key !== 'Enter' || !q) return
    setError(null)
    setResolved(null)
    const local = rows.filter((r) => matches(r.client))
    if (local.length === 1) return onOpen(local[0].client.client_id, LOOK[local[0].status].step)
    try {
      const r = await resolveClient(userId, query.trim())
      if (r.client) onOpen(r.client.client_id, 'gather')
      else setResolved(r)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const next = needYou[0]
  return (
    <div className="container">
      <div className="page-head">
        <div>
          <span className="sub">{todayLine()}</span>
          <h1 className="page-title">
            {greeting()}, {firstName}
          </h1>
          {clients && (
            <p className="lead">
              You have {count(rows.length, 'client meeting')} coming up.{' '}
              {needYou.length > 0 ? (
                <strong style={{ color: 'var(--text)' }}>{needYou.length} need you</strong>
              ) : (
                'Every briefing is ready to read'
              )}
              {needYou.length > 0 ? ' before they are ready.' : '.'}
            </p>
          )}
        </div>
      </div>

      {next && (
        <button type="button" className="up-next" onClick={() => onOpen(next.client.client_id, 'check')}>
          <span className="up-next-icon" style={{ color: 'var(--warn)' }}>
            <CircleAlert size={20} aria-hidden="true" />
          </span>
          <span className="up-next-text">
            <span className="eyebrow">Up next for you</span>
            <span className="up-next-title">
              {next.client.client_name} needs {count(next.open, 'quick decision')}
            </span>
            <span className="note">
              {countdown(next.client.meeting_date)} · {next.client.conflicts.join(' ')}
            </span>
          </span>
          <span className="fake-btn">Start review</span>
        </button>
      )}

      <section className="panel" aria-labelledby="meetings-title">
        <div className="queue-head">
          <h2 id="meetings-title" className="h2">
            Upcoming meetings
          </h2>
          <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)} aria-label="Filter meetings">
            <TabsList>
              {tabs.map(([id, label]) => (
                <TabsTrigger key={id} value={id} className="px-3">
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <label className="search">
            <Search size={15} className="text-muted-foreground" aria-hidden="true" />
            <span className="sr-only">Search clients by name or alias</span>
            <input
              type="search"
              placeholder="Search a client or alias"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setResolved(null)
              }}
              onKeyDown={search}
            />
          </label>
        </div>
        {(resolved || error) && (
          <div className="resolve-note note">
            {error && <span className="note-error">{error}</span>}
            {resolved && resolved.candidates.length > 0 && (
              <>
                <span>“{resolved.query}” is not a confident match. Did you mean</span>
                {resolved.candidates.map((c) => (
                  <Button key={c.client_id} variant="outline" size="sm" onClick={() => onOpen(c.client_id, 'gather')}>
                    {c.legal_name}
                  </Button>
                ))}
              </>
            )}
            {resolved && resolved.candidates.length === 0 && <span>No client matches “{resolved.query}”.</span>}
          </div>
        )}
        <div className="table-scroll">
          <div className="queue">
            <div className="queue-row queue-labels">
              <span>Client</span>
              <span>When</span>
              <span>Briefing progress</span>
              <span>Heads up</span>
              <span />
            </div>
            {!clients && <div className="empty">Loading meetings…</div>}
            {shown.map((row) => {
              const c = row.client
              const look = LOOK[row.status]
              return (
                <div key={c.client_id} className="queue-row">
                  <div className="client-cell">
                    <span className="initials" aria-hidden="true">
                      {initials(c.client_name)}
                    </span>
                    <div>
                      <button type="button" className="client-link" onClick={() => onOpen(c.client_id, look.step)}>
                        {c.client_name}
                      </button>
                      <span className="sub">
                        {c.segment}
                        {c.primary_banker ? ` · ${c.primary_banker}` : ''}
                      </span>
                    </div>
                  </div>
                  <div className="stack">
                    <span style={{ fontWeight: 500 }}>{weekdayDate(c.meeting_date)}</span>
                    <span className="sub">{c.region}</span>
                  </div>
                  <div className="stack" style={{ gap: 7 }}>
                    <div className="segments" aria-hidden="true">
                      {look.segs.map((s, i) => (
                        <span key={i} className={`seg ${s ? `seg-${s}` : ''}`} />
                      ))}
                    </div>
                    <StatusText tone={look.tone}>{statusText(row)}</StatusText>
                  </div>
                  <span className="heads-up">{headsUp(c)}</span>
                  <div className="row-end">
                    <Button
                      variant={row.status === 'needs-you' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => onOpen(c.client_id, look.step)}
                    >
                      {look.action}
                    </Button>
                  </div>
                </div>
              )
            })}
            {clients && shown.length === 0 && <div className="empty">Nothing here. You are all caught up.</div>}
          </div>
        </div>
      </section>

      <section aria-labelledby="how-title" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <h2 id="how-title" className="h2">
          How every briefing works
        </h2>
        <ol className="how">
          {HOW.map(([title, who, text], i) => (
            <li key={title}>
              <div className="how-top">
                <span className="num-badge">{i + 1}</span>
                {title}
                <span className="muted">{who}</span>
              </div>
              <span className="note">{text}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}

const HOW = [
  ['Gather', 'Automatic', 'We read CRM, finance, pipeline, email, notes and approved news, match the client’s names, and skip anything you are not cleared to see.'],
  ['Check', 'You', 'If two sources disagree, you pick the one you trust. Nothing is approved with an open question.'],
  ['Read', 'You', 'Short sections. Numbers come from SQL, never from AI, and every sentence links to its source.'],
  ['Share', 'You', 'Approve, create the follow-ups, and take the briefing with you as a file.'],
]
