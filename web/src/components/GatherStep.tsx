// Step 1, Gather: what was read (grouped from the briefing's evidence), what was tidied
// up (aliases and the data-housekeeping flags), and how the briefing was made.
import { useState } from 'react'
import type { Briefing, Evidence } from '../api'
import { count, dayMonth } from '../format'
import { CircleAlert, Check } from 'lucide-react'
import { SourceIcon } from './common'
import { Button } from '@/components/ui/button'

type Group = { kind: string; name: string; what: string; sources: string[]; undated?: boolean }

// Which system each evidence source comes from. Documents from any other source are news.
const GROUPS: Group[] = [
  { kind: 'clients', name: 'CRM', what: 'Client record, coverage team and contacts', sources: ['clients', 'coverage', 'contacts'] },
  { kind: 'revenue_metrics', name: 'Revenue and balances', what: 'Computed by SQL, never by AI', sources: ['revenue_metrics', 'holdings', 'performance'] },
  { kind: 'opportunities', name: 'Pipeline', what: 'Opportunities you are cleared to see', sources: ['opportunities'] },
  { kind: 'open_actions', name: 'Actions and service desk', what: 'Open actions and service issues', sources: ['open_actions', 'service_issues'], undated: true },
  { kind: 'email', name: 'Email', what: 'Threads with the client', sources: ['email'] },
  { kind: 'crm_notes', name: 'Notes and past briefings', what: 'Meeting notes, prior briefings and research', sources: ['crm_notes', 'briefing_archive', 'internal_research'] },
  { kind: 'news', name: 'News', what: 'Approved sources only', sources: [] },
]

function groupOf(e: Evidence): Group | undefined {
  const known = GROUPS.find((g) => g.sources.includes(e.source ?? ''))
  if (known) return known
  return e.kind === 'document' ? GROUPS[GROUPS.length - 1] : undefined
}

const WARN_FLAGS = new Set(['unresolved_reference', 'excluded_source'])

export function GatherStep({ briefing: b }: { briefing: Briefing }) {
  const [showHow, setShowHow] = useState(true)
  const evidence = Object.values(b.evidence).filter((e) => e.kind !== 'flag')
  const systems = GROUPS.map((g) => {
    const items = evidence.filter((e) => groupOf(e) === g)
    const latest = g.undated ? undefined : items.map((e) => e.as_of).sort().at(-1) // actions are dated by when they're due
    return { ...g, count: items.length, latest }
  }).filter((g) => g.count > 0)

  const cleanup = [
    ...(b.aliases.length
      ? [{ key: 'aliases', title: `${b.aliases.length + 1} names, 1 client`, detail: `${b.aliases.join(', ')} and ${b.client_name} are linked.`, warn: false }]
      : []),
    ...b.flags
      .filter((f) => f.housekeeping)
      .map((f) => ({ key: f.flag_id, title: f.title, detail: f.detail, warn: WARN_FLAGS.has(f.flag_type) })),
  ]

  const ai = b.sections.some((s) => s.author === 'ai')
  const models = [...new Set(b.llm_runs.filter((r) => r.provider !== 'mock').map((r) => r.model + (r.cached ? ' (cached)' : '')))]
  const passed = b.sections.filter((s) => s.check.passed).length
  const rejected = b.sections.filter((s) => s.retry_errors.length > 0).length
  const notes = [...new Set(b.llm_runs.flatMap((r) => r.notes))]
  const trace: [string, string, string][] = [
    ['Check access', 'Every query filters by what you can see.', 'Rules'],
    ['Match the client', 'Aliases, duplicates and stale data, by rules.', 'Rules'],
    ['Compute numbers', 'Typed SQL, formatted by code.', 'SQL'],
    ['Find documents', 'Keyword and meaning search.', 'Search'],
    ['Write the narrative', ai ? `One call to ${models.join(', ')}.` : 'Template (no AI), built from the evidence.', ai ? 'AI' : 'Template'],
    ['Check every line', `${passed} of ${b.sections.length} sections passed; ${count(rejected, 'first draft')} rejected.`, 'Rules'],
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="cols">
        <section className="panel col-wide" aria-labelledby="g-sources">
          <div className="panel-head" style={{ padding: '18px 22px 10px' }}>
            <h3 id="g-sources" className="h3">
              Sources read
            </h3>
            <span className="sub">For {b.prepared_for} · only what you can access</span>
          </div>
          {systems.map((s) => (
            <div key={s.kind} className="source-row">
              <SourceIcon source={s.kind} tile />
              <div className="stack" style={{ flex: '1 1 auto' }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
                <span className="sub">{s.what}</span>
              </div>
              {s.latest && <span className="small muted">Latest {dayMonth(s.latest)}</span>}
              <span className="source-count">{s.count}</span>
            </div>
          ))}
        </section>

        <section className="panel panel-pad col-narrow" aria-labelledby="g-clean">
          <h3 id="g-clean" className="h3">
            Cleaned up for you
          </h3>
          {cleanup.length === 0 && <p className="note">Nothing needed tidying.</p>}
          {cleanup.map((c) => (
            <div key={c.key} className="clean-item">
              <span className={`clean-icon ${c.warn ? 'is-warn' : ''}`} aria-hidden="true">
                {c.warn ? <CircleAlert size={12} strokeWidth={3} /> : <Check size={12} strokeWidth={3} />}
              </span>
              <div className="stack">
                <span style={{ fontWeight: 600 }}>{c.title}</span>
                <span className="note">{c.detail}</span>
              </div>
            </div>
          ))}
        </section>
      </div>

      <section className="panel panel-pad" aria-labelledby="g-how">
        <div className="panel-head" style={{ alignItems: 'center' }}>
          <h3 id="g-how" className="h3">
            How the briefing is made
          </h3>
          <span className="legend">
            <span className="dot" aria-hidden="true" />
            Rules, SQL and search
          </span>
          <span className="legend is-ai">
            <span className="dot" aria-hidden="true" />
            AI
          </span>
          <Button variant="outline" size="sm" className="ml-auto" aria-expanded={showHow} onClick={() => setShowHow((s) => !s)}>
            {showHow ? 'Hide' : 'Show steps'}
          </Button>
        </div>
        {showHow && (
          <>
            <ol className="trace">
              {trace.map(([step, detail, tag], i) => (
                <li key={step} className={tag === 'AI' ? 'is-ai' : ''}>
                  <span className="trace-tag">
                    {String(i + 1).padStart(2, '0')} · {tag}
                  </span>
                  <span style={{ fontWeight: 600, lineHeight: 1.3 }}>{step}</span>
                  <span className="small" style={{ color: 'var(--text-2)', lineHeight: 1.45 }}>
                    {detail}
                  </span>
                </li>
              ))}
            </ol>
            <p className="small muted">
              Built in {(b.generated_ms / 1000).toFixed(1)} s.{notes.length > 0 && ` Fallback: ${notes.join('; ')}.`}
            </p>
          </>
        )}
      </section>
    </div>
  )
}
