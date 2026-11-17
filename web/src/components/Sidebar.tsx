// Left sidebar: brand, navigation, and who is signed in. The user card is a dropdown
// (shadcn Select) so the demo can switch users and show entitlement filtering live.
import { AlignLeft, Building2, CalendarDays, Database, ScrollText, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { UserInfo } from '../api'
import { initials } from '../format'
import { Tag } from './common'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export type Page = 'meetings' | 'clients' | 'health' | 'evals'

type Props = {
  users: UserInfo[]
  userId: string
  onUserChange: (userId: string) => void
  meetingCount: number | null
  page: Page // the page that is open (a briefing counts as Meetings)
  onNavigate: (page: Page) => void
  onAudit: () => void
}

const PAGES: [Page, string, LucideIcon][] = [
  ['meetings', 'Meetings', CalendarDays],
  ['clients', 'Clients', Building2],
  ['health', 'Data health', Database],
  ['evals', 'Evaluations', ShieldCheck],
]

const ACCESS_NAMES: Record<string, string> = { standard: 'Standard', restricted_deals: 'Restricted deals' }

function Person({ user }: { user: UserInfo }) {
  return (
    <span className="user-row">
      <span className="avatar" aria-hidden="true">
        {initials(user.name)}
      </span>
      <span className="stack text-left">
        <span className="user-name">{user.name}</span>
        <span className="small muted">{user.role}</span>
      </span>
    </span>
  )
}

export function Sidebar({ users, userId, onUserChange, meetingCount, page, onNavigate, onAudit }: Props) {
  const me = users.find((u) => u.user_id === userId)
  return (
    <aside className="sidebar" aria-label="Sidebar">
      <div className="brand">
        <span className="brand-mark">
          <AlignLeft size={16} strokeWidth={2.4} aria-hidden="true" />
        </span>
        Briefing Desk
      </div>
      <nav className="nav" aria-label="Primary">
        {PAGES.map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            className={`nav-item ${page === id ? 'is-active' : ''}`}
            aria-current={page === id ? 'page' : undefined}
            onClick={() => onNavigate(id)}
          >
            <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
            {label}
            {id === 'meetings' && meetingCount !== null && <span className="nav-count">{meetingCount}</span>}
          </button>
        ))}
        <button type="button" className="nav-item" onClick={onAudit}>
          <ScrollText size={18} strokeWidth={1.8} aria-hidden="true" />
          Audit log
        </button>
      </nav>
      {me && (
        <div className="user-card">
          <span className="small muted">Viewing as (demo)</span>
          <Select value={userId} onValueChange={onUserChange}>
            <SelectTrigger className="h-auto w-full py-2 pl-2" aria-label="Switch user">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper" align="start">
              {users.map((u) => (
                <SelectItem key={u.user_id} value={u.user_id} className="py-2">
                  <Person user={u} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="access" aria-label="Your access">
            {me.entitlements.map((e) => (
              <Tag key={e} tone={e === 'standard' ? 'muted' : 'indigo'}>
                {ACCESS_NAMES[e] ?? e}
              </Tag>
            ))}
          </div>
        </div>
      )}
    </aside>
  )
}
