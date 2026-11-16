import type { ClientInfo, ResolveResponse } from '../api'

type Props = {
  query: string
  onQueryChange: (query: string) => void
  onFind: () => void
  resolved: ResolveResponse | null
  onPickCandidate: (client: ClientInfo) => void
  meetingDate: string
  onMeetingDateChange: (date: string) => void
  onGenerate: () => void
  loading: boolean
}

const MATCHED_BY: Record<string, string> = {
  id: 'matched by client ID',
  exact: 'exact name or alias match',
  fuzzy: 'fuzzy name match',
  picked: 'chosen by you',
}

// Find a client (showing how the name was resolved), pick the meeting date, generate.
export function Toolbar(props: Props) {
  const r = props.resolved
  return (
    <div className="toolbar">
      <form
        className="toolbar-search"
        onSubmit={(e) => {
          e.preventDefault()
          props.onFind()
        }}
      >
        <label className="search-box">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#64748B" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <span className="visually-hidden">Client ID, name or alias</span>
          <input
            type="search"
            value={props.query}
            onChange={(e) => props.onQueryChange(e.target.value)}
            placeholder="Client ID, name or alias (try NWC)"
          />
        </label>
        <button type="submit" className="btn" disabled={!props.query.trim()}>
          Find
        </button>
      </form>

      <div className="toolbar-result" aria-live="polite">
        {r?.client && (
          <span>
            “{r.query}” → <strong>{r.client.legal_name}</strong> ({r.client.client_id}) ·{' '}
            <span className="muted">{MATCHED_BY[r.matched_by ?? ''] ?? r.matched_by}</span>
          </span>
        )}
        {r && !r.client && (
          <span>
            No confident match for “{r.query}”.{' '}
            {r.candidates.map((c) => (
              <button key={c.client_id} type="button" className="link" onClick={() => props.onPickCandidate(c)}>
                Did you mean {c.legal_name}?
              </button>
            ))}
          </span>
        )}
      </div>

      <label className="toolbar-date">
        <span>Meeting</span>
        <input type="date" value={props.meetingDate} onChange={(e) => props.onMeetingDateChange(e.target.value)} />
      </label>
      <button type="button" className="btn btn-primary" disabled={!r?.client || props.loading} onClick={props.onGenerate}>
        {props.loading ? 'Generating…' : 'Generate briefing'}
      </button>
    </div>
  )
}
