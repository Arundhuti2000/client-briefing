import { useEffect, useState } from 'react'
import { getAudit } from '../api'
import type { AuditRow } from '../api'
import { errorMessage } from '../format'
import { Button } from '@/components/ui/button'

type Props = { userId: string; userName: string; onClose: () => void }

// The caller's own recent tool calls: who asked what, and which evidence IDs came back.
export function AuditDrawer({ userId, userName, onClose }: Props) {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getAudit(userId, 100)
      .then((r) => !cancelled && setRows(r))
      .catch((e) => !cancelled && setError(errorMessage(e)))
    return () => {
      cancelled = true
    }
  }, [userId])

  return (
    <aside className="drawer" aria-label="Audit log">
      <div className="drawer-head">
        <h2 className="h2">Audit log · {userName}</h2>
        <Button variant="outline" size="sm" onClick={onClose} className="ml-auto">
          Close
        </Button>
      </div>
      <p className="note">Every tool call you made: arguments, and the evidence IDs that came back.</p>
      {error && <p className="note note-error">{error}</p>}
      {rows && rows.length === 0 && <p className="muted">No tool calls yet.</p>}
      {rows && rows.length > 0 && (
        <div className="table-scroll">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Time (UTC)</th>
                <th>Tool</th>
                <th>Arguments</th>
                <th>Returned</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="mono small">{r.ts.slice(11, 19)}</td>
                  <td>{r.tool}</td>
                  <td className="mono small">{JSON.stringify(r.args)}</td>
                  <td>{r.error ? <span className="note-error">{r.error}</span> : `${r.result_ids.length} items`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </aside>
  )
}
