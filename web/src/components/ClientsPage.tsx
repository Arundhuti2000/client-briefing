// Clients, laid out like the design: summary cards, a searchable list (any name or alias finds
// the client) and the selected client's detail: metric trends, the names the matching rules
// linked, and data health. Everything comes from GET /clients; numbers are formatted by the API.
import { useState } from 'react'
import { ArrowRight, CalendarDays, Search } from 'lucide-react'
import type { ClientSummary, MetricSeries } from '../api'
import { count, initials, weekdayDate } from '../format'
import type { Step } from './BriefingPage'
import type { Tone } from './common'

type Props = { clients: ClientSummary[] | null; onOpen: (clientId: string, step: Step) => void }
type Filter = 'all' | 'attention' | 'clear'

const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['attention', 'Needs you'],
  ['clear', 'Clear'],
]
// Plain names for the clean-up flags, for the "data fixes" card
const FIX_NAMES: Record<string, string> = {
  duplicate_client: 'duplicates',
  duplicate_contact: 'duplicates',
  stale: 'old values',
  excluded_source: 'unapproved sources',
  unresolved_reference: 'unmatched names',
}

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const needsYou = (c: ClientSummary) => c.conflicts.length + c.heads_up.length > 0
const fixes = (c: ClientSummary) => c.flags.filter((f) => f.housekeeping)
const revenue = (c: ClientSummary) => c.metrics.find((m) => m.label === 'Revenue')

// The alias a search matched, when it wasn't the client's own name
function matchedAlias(c: ClientSummary, query: string) {
  if (!query || c.client_name.toLowerCase().includes(query)) return null
  return c.aliases.find((a) => a.toLowerCase().includes(query)) ?? null
}

function attentionText(c: ClientSummary) {
  if (c.conflicts.length) return `${count(c.conflicts.length, 'conflict')} to decide`
  if (c.heads_up.length) return `${c.heads_up.length} to watch`
  return null
}

// Is the latest move good news? Lower is better only for rates of things going wrong
function trendTone(m: MetricSeries): Tone {
  if (m.stale || m.points.length < 2) return 'muted'
  const [before, latest] = m.points.slice(-2).map((p) => p.value)
  if (latest === before) return 'muted'
  const lowerIsBetter = /exception|error|fail/i.test(m.label)
  return latest > before !== lowerIsBetter ? 'good' : 'bad'
}

// SVG polyline points for a trend line in a w x h box
function linePoints(values: number[], w: number, h: number, pad = 3) {
  const low = Math.min(...values)
  const range = Math.max(...values) - low || 1
  const step = (w - 2 * pad) / Math.max(values.length - 1, 1)
  return values.map((v, i) => `${(pad + i * step).toFixed(1)},${(h - pad - ((v - low) / range) * (h - 2 * pad)).toFixed(1)}`).join(' ')
}

function Sparkline({ m, width, height, area = false }: { m?: MetricSeries; width: number; height: number; area?: boolean }) {
  if (!m || m.points.length < 2) return area ? null : <span aria-hidden="true" style={{ width, height, flex: 'none' }} />
  const line = linePoints(m.points.map((p) => p.value), width, height)
  const tone = trendTone(m)
  return (
    <svg className={`spark is-${tone}`} aria-hidden="true" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      {area && <polygon points={`3,${height} ${line} ${width - 3},${height}`} />}
      <polyline points={line} />
    </svg>
  )
}

// ---- the summary cards --------------------------------------------------------------------

function Summary({ clients }: { clients: ClientSummary[] }) {
  const dates = [...new Set(clients.map((c) => c.meeting_date))].sort()
  const ready = clients.filter((c) => !needsYou(c)).length
  const names = clients.reduce((n, c) => n + c.aliases.length + 1, 0)
  const allFixes = clients.flatMap(fixes)
  const fixKinds = [...new Set(allFixes.map((f) => FIX_NAMES[f.flag_type]).filter(Boolean))]
  return (
    <div className="stat-cards">
      <div className="panel stat-card">
        <span className="small">Clients on your desk</span>
        <span className="stat-num">{clients.length}</span>
        <span className="small muted">
          {dates.length === 1 ? `All meeting ${weekdayDate(dates[0])}` : dates[0] && `Next meeting ${weekdayDate(dates[0])}`}
        </span>
      </div>
      <div className="panel stat-card">
        <span className="small">Ready to brief</span>
        <span className="stat-num tone-good">
          {ready}
          <small>/{clients.length}</small>
        </span>
        <div className="ready-bar" aria-hidden="true">
          {clients.map((c) => (
            <span key={c.client_id} className={needsYou(c) ? 'seg seg-warn' : 'seg seg-done'} />
          ))}
        </div>
      </div>
      <div className="panel stat-card">
        <span className="small">Names linked</span>
        <span className="stat-num">
          {names} <small>into {clients.length}</small>
        </span>
        <span className="small muted">By the matching rules, no AI</span>
      </div>
      <div className="panel stat-card">
        <span className="small">Data fixes made for you</span>
        <span className="stat-num">{allFixes.length}</span>
        <span className="small muted">{fixKinds.length ? capitalize(fixKinds.join(', ')) : 'Nothing to fix'}</span>
      </div>
    </div>
  )
}

// ---- the selected client ---------------------------------------------------------------------

function MetricCard({ m }: { m: MetricSeries }) {
  const latest = m.points[m.points.length - 1]
  const tone = trendTone(m)
  return (
    <div className="panel metric-card">
      <div className="metric-card-head">
        <span className="small">{m.label}</span>
        {m.stale && <span className="stale-tag">Out of date</span>}
      </div>
      <span className="stat-num">{latest.text}</span>
      <span className={`small strong tone-${tone}`}>
        {m.change ? `${m.change} since ${m.points[m.points.length - 2].period}` : `As of ${latest.period}`}
      </span>
      <Sparkline m={m} width={200} height={40} area />
    </div>
  )
}

function RevenueBars({ m }: { m: MetricSeries }) {
  const top = Math.max(...m.points.map((p) => p.value)) || 1
  return (
    <div className="panel panel-pad revenue-chart">
      <div className="panel-head">
        <h3 className="h3">Revenue by quarter</h3>
        <span className="sub">From the finance system, latest quarter in dark</span>
      </div>
      <div className="bars" style={{ gridTemplateColumns: `repeat(${m.points.length}, minmax(0, 1fr))` }}>
        {m.points.map((p, i) => (
          <div key={p.evidence_id} className="bar-col">
            <span className="mono small">{p.text}</span>
            <div className={i === m.points.length - 1 ? 'bar-fill is-latest' : 'bar-fill'} style={{ height: `${Math.round((p.value / top) * 110)}px` }} />
            <span className="small muted">{p.period}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Detail({ c, query, onOpen }: { c: ClientSummary; query: string; onOpen: Props['onOpen'] }) {
  const attention = attentionText(c)
  const tidied = fixes(c).length
  const rev = revenue(c)
  return (
    <section className="client-detail" aria-labelledby="client-detail-title">
      <div className="panel panel-pad">
        <div className="detail-head">
          <span className="initials initials-lg" aria-hidden="true">
            {initials(c.client_name)}
          </span>
          <div className="detail-title">
            <h2 id="client-detail-title" className="detail-name">
              {c.client_name}
            </h2>
            <span className="sub">
              {c.segment} · {c.region}
              {c.primary_banker && ` · Coverage lead ${c.primary_banker}`}
            </span>
          </div>
          <button type="button" className="primary-btn" onClick={() => onOpen(c.client_id, 'gather')}>
            Open briefing <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
        <div className="chips">
          <span className="pill">
            <CalendarDays size={14} aria-hidden="true" /> Next meeting {weekdayDate(c.meeting_date)}
          </span>
          <span className={`pill pill-${attention ? 'warn' : 'good'}`}>
            <span className="dot" aria-hidden="true" />
            {attention ?? 'No issues found'}
          </span>
        </div>
      </div>

      {c.metrics.length > 0 && (
        <div className="metric-cards">
          {c.metrics.map((m) => (
            <MetricCard key={m.label} m={m} />
          ))}
        </div>
      )}

      <div className="detail-row">
        {rev && rev.points.length > 1 && <RevenueBars m={rev} />}
        <div className="panel panel-pad names-card">
          <h3 className="h3">Names we matched</h3>
          <div className="names-link">
            <div className="names-list">
              {c.aliases.length === 0 && <span className="note">No other names on file.</span>}
              {c.aliases.map((a) => (
                <span key={a} className={query && a.toLowerCase().includes(query) ? 'alias is-hit' : 'alias'}>
                  {a}
                </span>
              ))}
            </div>
            <span className="names-bracket" aria-hidden="true" />
            <span className="names-target">{initials(c.client_name)}</span>
          </div>
          <span className="small muted">
            {c.aliases.length
              ? `${count(c.aliases.length, 'other name')} in the source data, linked to this client by the matching rules`
              : 'The source data uses only this name'}
          </span>
        </div>
      </div>

      <div className="panel panel-pad">
        <h3 className="h3">Data health</h3>
        <ul className="health-list">
          {c.conflicts.length > 0 && (
            <li>
              <span className="dot is-warn" aria-hidden="true" />
              <span>{count(c.conflicts.length, 'conflicting statement')} to decide: {c.conflicts.join(' · ')}</span>
              <span className="health-tag tone-warn">Decide</span>
            </li>
          )}
          {c.heads_up.map((h) => (
            <li key={h}>
              <span className="dot is-indigo" aria-hidden="true" />
              <span>{h}</span>
              <span className="health-tag tone-indigo">Watch</span>
            </li>
          ))}
          <li>
            <span className="dot is-good" aria-hidden="true" />
            <span>{tidied ? `${count(tidied, 'data fix')} made automatically` : 'Nothing needed fixing'}</span>
            <span className="health-tag tone-good">Done</span>
          </li>
        </ul>
      </div>
    </section>
  )
}

// ---- the page ------------------------------------------------------------------------------

export function ClientsPage({ clients, onOpen }: Props) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const q = query.trim().toLowerCase()
  const shown = (clients ?? []).filter(
    (c) =>
      (!q || c.client_name.toLowerCase().includes(q) || c.aliases.some((a) => a.toLowerCase().includes(q))) &&
      (filter === 'all' || needsYou(c) === (filter === 'attention')),
  )
  const selected = shown.find((c) => c.client_id === selectedId) ?? shown[0]

  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1 className="page-title">Clients</h1>
          <p className="lead">Each client goes by several names across systems. Search any of them: “NWC” finds Northwind.</p>
        </div>
        <label className="search client-search">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search clients or aliases</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or alias, e.g. NWC" />
        </label>
      </div>

      {!clients && <p className="note">Loading clients…</p>}
      {clients && <Summary clients={clients} />}

      {clients && (
        <div className="clients-split">
          <section className="panel client-list" aria-labelledby="client-list-title">
            <div className="client-list-head">
              <h2 id="client-list-title" className="h3">
                Your clients
              </h2>
              <div role="radiogroup" aria-label="Filter clients" className="segmented">
                {FILTERS.map(([id, label]) => (
                  <button key={id} type="button" role="radio" aria-checked={filter === id} onClick={() => setFilter(id)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {shown.map((c) => {
              const on = c.client_id === selected?.client_id
              const alias = matchedAlias(c, q)
              const attention = attentionText(c)
              return (
                <button
                  key={c.client_id}
                  type="button"
                  className={on ? 'client-row is-on' : 'client-row'}
                  aria-current={on}
                  onClick={() => setSelectedId(c.client_id)}
                >
                  <span className={attention ? 'initials has-ring' : 'initials'} aria-hidden="true">
                    {initials(c.client_name)}
                  </span>
                  <span className="client-row-text">
                    <span className="client-row-name">{c.client_name}</span>
                    <span className={alias ? 'small strong tone-indigo' : attention ? 'small strong tone-warn' : 'small muted'}>
                      {alias ? `Matched “${alias}”` : (attention ?? [c.segment, c.primary_banker].filter(Boolean).join(' · '))}
                    </span>
                  </span>
                  <Sparkline m={revenue(c)} width={64} height={26} />
                </button>
              )
            })}
            {shown.length === 0 && <p className="note client-empty">No client or alias matches “{query.trim()}”.</p>}
          </section>
          {selected && <Detail c={selected} query={q} onOpen={onOpen} />}
        </div>
      )}
    </div>
  )
}
