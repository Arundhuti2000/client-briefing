// Every client on the desk: who they are, the other names the source data uses for them
// (linked to one client by the unify rules), and what needs attention. From GET /clients.
import type { ClientSummary } from '../api'
import { count, initials, weekdayDate } from '../format'
import type { Step } from './BriefingPage'
import { StatusText, Tag } from './common'
import { Button } from '@/components/ui/button'

type Props = { clients: ClientSummary[] | null; onOpen: (clientId: string, step: Step) => void }

function Attention({ client: c }: { client: ClientSummary }) {
  const tidied = c.flags.filter((f) => f.housekeeping).length
  return (
    <div className="stack" style={{ gap: 6 }}>
      {c.conflicts.length > 0 && <StatusText tone="warn">{count(c.conflicts.length, 'conflict')} to decide</StatusText>}
      {c.heads_up.length > 0 && (
        <>
          <StatusText tone="indigo">{c.heads_up.length} to watch</StatusText>
          <span className="note" style={{ paddingLeft: 14 }}>
            {c.heads_up.join(' · ')}
          </span>
        </>
      )}
      {c.conflicts.length + c.heads_up.length === 0 && <StatusText tone="good">No issues found</StatusText>}
      {tidied > 0 && <StatusText tone="muted">{count(tidied, 'data fix')} made automatically</StatusText>}
    </div>
  )
}

export function ClientsPage({ clients, onOpen }: Props) {
  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1 className="page-title">Clients</h1>
          {clients && (
            <p className="lead">
              {count(clients.length, 'client')} on your desk. The source systems call each client by several names; the
              matching rules link them, so searching “NWC” finds Northwind.
            </p>
          )}
        </div>
      </div>
      {!clients && <p className="note">Loading clients…</p>}
      <div className="client-grid">
        {(clients ?? []).map((c) => (
          <section key={c.client_id} className="panel panel-pad" aria-labelledby={`client-${c.client_id}`}>
            <div className="client-cell">
              <span className="initials" aria-hidden="true">
                {initials(c.client_name)}
              </span>
              <div>
                <h2 id={`client-${c.client_id}`} className="h2">
                  {c.client_name}
                </h2>
                <span className="sub">
                  {c.segment} · {c.region}
                </span>
              </div>
            </div>
            <dl className="facts">
              {c.primary_banker && (
                <div>
                  <dt>Coverage lead</dt>
                  <dd>{c.primary_banker}</dd>
                </div>
              )}
              <div>
                <dt>Next meeting</dt>
                <dd>{weekdayDate(c.meeting_date)}</dd>
              </div>
            </dl>
            <div className="stack" style={{ gap: 6 }}>
              <span className="small muted">Also known as</span>
              <div className="access">
                {c.aliases.length === 0 && <span className="note">No other names on file.</span>}
                {c.aliases.map((a) => (
                  <Tag key={a}>{a}</Tag>
                ))}
              </div>
            </div>
            <Attention client={c} />
            <div>
              <Button variant="outline" size="sm" onClick={() => onOpen(c.client_id, 'gather')}>
                Open briefing
              </Button>
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
