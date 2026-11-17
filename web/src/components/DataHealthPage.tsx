// Data health: every data-quality flag the unify step wrote, per client, and how it was
// handled. Only flags this user is cleared to see (they come from the same tool as the briefing).
import type { ClientSummary, FlagSummary } from '../api'
import { count, initials } from '../format'
import type { Step } from './BriefingPage'
import { Tag } from './common'
import type { Tone } from './common'
import { Button } from '@/components/ui/button'

type Props = { clients: ClientSummary[] | null; onOpen: (clientId: string, step: Step) => void }

// What each kind of flag means for the banker, as a short tag
const LOOK: Record<string, [string, Tone]> = {
  conflict: ['Conflict', 'warn'],
  stale_statement: ['Out of date', 'warn'],
  overdue: ['Overdue', 'bad'],
  duplicate_client: ['Merged', 'good'],
  duplicate_contact: ['Merged', 'good'],
  stale: ['Superseded', 'good'],
  excluded_source: ['Left out', 'muted'],
  unresolved_reference: ['Unmatched', 'muted'],
}

function FlagRow({ flag: f }: { flag: FlagSummary }) {
  const [tag, tone] = LOOK[f.flag_type] ?? ['Flagged', 'muted']
  return (
    <div className="gap-row">
      <Tag tone={tone} className="shrink-0">
        {tag}
      </Tag>
      <span>
        <strong>{f.title.endsWith('?') ? f.title : `${f.title}.`}</strong> {f.detail}
      </span>
    </div>
  )
}

export function DataHealthPage({ clients, onOpen }: Props) {
  const flags = (clients ?? []).flatMap((c) => c.flags)
  const tiles: [string, number, string][] = [
    ['Flags', flags.length, 'Found while unifying the data'],
    ['Conflicts', flags.filter((f) => f.flag_type === 'conflict').length, 'Two sources disagree'],
    ['To watch', flags.filter((f) => !f.housekeeping && f.flag_type !== 'conflict').length, 'Out of date or overdue'],
    ['Fixed or left out', flags.filter((f) => f.housekeeping).length, 'Housekeeping, done by rules'],
  ]
  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1 className="page-title">Data health</h1>
          <p className="lead">
            What the unify step found in the source data, and how each problem was handled. You see only the flags you
            are cleared for.
          </p>
        </div>
      </div>
      {!clients && <p className="note">Loading…</p>}
      {clients && (
        <div className="tiles">
          {tiles.map(([label, n, meaning]) => (
            <div key={label} className="tile" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
              <span style={{ fontSize: 13, color: 'var(--text-2)' }}>{label}</span>
              <span className="tile-value">{n}</span>
              <span className="small muted">{meaning}</span>
            </div>
          ))}
        </div>
      )}
      {(clients ?? []).map((c) => (
        <section key={c.client_id} className="panel panel-pad" aria-labelledby={`health-${c.client_id}`}>
          <div className="panel-head" style={{ alignItems: 'center' }}>
            <span className="initials" aria-hidden="true">
              {initials(c.client_name)}
            </span>
            <h2 id={`health-${c.client_id}`} className="h2">
              {c.client_name}
            </h2>
            <span className="sub">{count(c.flags.length, 'flag')}</span>
            <Button variant="outline" size="sm" className="ml-auto" onClick={() => onOpen(c.client_id, 'check')}>
              Open briefing
            </Button>
          </div>
          {c.flags.length === 0 && <p className="note">Nothing flagged.</p>}
          <div>
            {c.flags.map((f, i) => (
              <FlagRow key={i} flag={f} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
