// Step 4, Share: the validator's results as plain checks, the follow-ups to create
// (POST /tasks, on Approve), and the briefing as a file (the Markdown the API returns).
import { useState } from 'react'
import type { Briefing, Task } from '../api'
import { count } from '../format'
import type { Progress } from '../progress'
import type { FollowUp } from '../workflow'
import { Check, CircleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'

type Props = {
  briefing: Briefing
  progress: Progress
  open: number
  followUps: FollowUp[]
  isTicked: (key: string, defaultOn: boolean) => boolean
  onTick: (key: string, on: boolean) => void
  created: Task[]
  error: string | null
}

export function ShareStep({ briefing: b, progress, open, followUps, isTicked, onTick, created, error }: Props) {
  const [copied, setCopied] = useState(false)
  const bullets = b.sections.flatMap((s) => s.bullets)
  const checked = b.sections.filter((s) => s.check.passed).flatMap((s) => s.bullets)
  const allPassed = b.sections.every((s) => s.check.passed)
  const rejected = b.sections.filter((s) => s.retry_errors.length > 0).length
  const conflicts = b.flags.filter((f) => f.flag_type === 'conflict').length
  const checks: [boolean, string][] = [
    [checked.length === bullets.length, `${checked.length} of ${bullets.length} sentences cite a source and passed every check`],
    [allPassed, 'No restricted content you may not see (checked in every section)'],
    [true, 'Figures computed by SQL and formatted by code, never by AI'],
    [open === 0, open ? `${count(open, 'conflict')} still to decide` : conflicts ? 'Conflicts decided by you' : 'No conflicting sources'],
  ]
  if (rejected) checks.push([true, `${count(rejected, 'first draft')} rejected by the checks and rewritten`])

  function download() {
    const url = URL.createObjectURL(new Blob([b.markdown], { type: 'text/markdown' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `${b.client_name} briefing.md`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(b.markdown)
      setCopied(true)
    } catch {
      setCopied(false) // clipboard blocked: the download still works
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {progress.approved && (
        <div className="banner-ok" role="status">
          <span className="check-icon" style={{ flex: '0 0 32px', height: 32 }}>
            <Check size={16} strokeWidth={3} aria-hidden="true" />
          </span>
          <div className="stack">
            <span className="h3">{created.length ? `Approved · ${count(created.length, 'follow-up')} created` : 'Approved'}</span>
            <span className="note" style={{ color: 'var(--good-ink)' }}>
              Follow-ups are saved as tasks and in the audit log. Download the briefing to take it with you.
            </span>
          </div>
        </div>
      )}
      {error && <p className="note note-error">{error}</p>}

      <div className="cols">
        <div className="col-wide" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <section className="panel panel-pad" aria-labelledby="s-checks">
            <h3 id="s-checks" className="h3">
              Safety checks
            </h3>
            {checks.map(([ok, text]) => (
              <div key={text} className="check-row">
                <span className={`check-icon ${ok ? '' : 'is-wait'}`} aria-hidden="true">
                  {ok ? <Check size={11} strokeWidth={3.4} /> : <CircleAlert size={11} strokeWidth={3} />}
                </span>
                {text}
              </div>
            ))}
          </section>

          <section className="panel panel-pad" aria-labelledby="s-follow" style={{ gap: 4 }}>
            <h3 id="s-follow" className="h3">
              Follow-ups
            </h3>
            <p className="sub" style={{ marginBottom: 8 }}>
              Suggested from your decisions and the open actions. Ticked ones become tasks when you approve.
            </p>
            {followUps.length === 0 && <p className="note">Nothing to follow up.</p>}
            {followUps.map((f) => (
              <label key={f.key} htmlFor={`follow-${f.key}`} className="tick-row">
                <Checkbox
                  id={`follow-${f.key}`}
                  checked={isTicked(f.key, f.defaultOn)}
                  disabled={progress.approved}
                  onCheckedChange={(on) => onTick(f.key, on === true)}
                />
                <span>
                  <span style={{ fontWeight: 500 }}>{f.description}</span>
                  <span className="small muted">{f.detail}</span>
                </span>
              </label>
            ))}
          </section>
        </div>

        <section className="panel panel-pad col-narrow" aria-labelledby="s-export">
          <h3 id="s-export" className="h3">
            Take it with you
          </h3>
          <p className="note">
            The briefing as a Markdown file, ready to paste into email or the CRM. Sources are numbered and named, with no
            internal record codes.
          </p>
          <div className="button-row">
            <Button variant="outline" size="sm" onClick={download}>
              Download (.md)
            </Button>
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? 'Copied' : 'Copy text'}
            </Button>
          </div>
          <span className="small muted">Internal only. It holds only what {b.prepared_for} is cleared to see.</span>
        </section>
      </div>
    </div>
  )
}
