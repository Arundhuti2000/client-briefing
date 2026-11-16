import type { UserInfo } from '../api'

type Props = {
  users: UserInfo[]
  userId: string
  onUserChange: (userId: string) => void
  onToggleAudit: () => void
}

// Navy app bar: product name, who you are (and what you may see), audit log.
export function AppBar({ users, userId, onUserChange, onToggleAudit }: Props) {
  const user = users.find((u) => u.user_id === userId)
  return (
    <header className="appbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 5h16M4 12h10M4 19h7" />
          </svg>
        </span>
        <span>Briefing Desk</span>
      </div>
      <div className="appbar-right">
        {user && (
          <span className="appbar-pills" title="Entitlements come from the users table, not the browser">
            {user.entitlements.map((e) => (
              <span key={e} className={`appbar-pill ${e === 'restricted_deals' ? 'appbar-pill-restricted' : ''}`}>
                {e}
              </span>
            ))}
          </span>
        )}
        <label className="appbar-user">
          <span className="visually-hidden">Signed in as</span>
          <select value={userId} onChange={(e) => onUserChange(e.target.value)}>
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.name} · {u.role}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="appbar-link" onClick={onToggleAudit}>
          Audit log
        </button>
      </div>
    </header>
  )
}
