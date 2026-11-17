// The briefing workspace: header, the four steps (Gather, Check, Read, Share), and the
// step on screen. The briefing itself comes from POST /briefings; this file only adds
// the banker's workflow on top (decisions, approval, follow-up tasks).
import { useState } from 'react'
import { createTask } from '../api'
import type { Briefing, ClientSummary, Task } from '../api'
import { count, countdown, errorMessage, initials, shortDate, weekdayDate } from '../format'
import type { Progress } from '../progress'
import { suggestedFollowUps } from '../workflow'
import { CheckStep } from './CheckStep'
import { GatherStep } from './GatherStep'
import { ReadStep } from './ReadStep'
import { ShareStep } from './ShareStep'
import { ArrowRight, Check, ChevronLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'

export type Step = 'gather' | 'check' | 'read' | 'share'
const STEPS: Step[] = ['gather', 'check', 'read', 'share']

type Props = {
  userId: string
  summary?: ClientSummary
  briefing: Briefing | null
  loading: boolean
  error: string | null
  step: Step
  progress: Progress
  onStep: (step: Step) => void
  onProgress: (change: Partial<Progress>) => void
  backLabel: string // where the back link goes: "All meetings", "All clients"…
  onBack: () => void
  onRetry: () => void
}

function readingMinutes(b: Briefing): number {
  const text = [...b.sections.flatMap((s) => s.bullets.map((x) => x.text)), ...b.what_changed.map((c) => c.text)].join(' ')
  return Math.max(1, Math.round(text.split(/\s+/).length / 200))
}

export function BriefingPage(props: Props) {
  const { userId, summary, briefing: b, loading, error, step, progress, onStep, onProgress } = props
  const [ticks, setTicks] = useState<Record<string, boolean>>({}) // follow-ups the banker (un)ticked
  const [created, setCreated] = useState<Task[]>([])
  const [shareError, setShareError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const conflicts = b?.flags.filter((f) => f.flag_type === 'conflict') ?? []
  const open = conflicts.filter((f) => !progress.decisions[f.evidence_id]).length
  const followUps = b ? suggestedFollowUps(b, progress) : []
  const isTicked = (key: string, defaultOn: boolean) => ticks[key] ?? defaultOn

  async function approve() {
    if (!b) return
    setBusy(true)
    setShareError(null)
    try {
      const made: Task[] = []
      for (const f of followUps.filter((x) => isTicked(x.key, x.defaultOn))) {
        // one at a time: task IDs are numbered in order by the API
        made.push(await createTask(userId, { client_id: b.client_id, description: f.description, due_date: b.meeting_date, source_id: f.sourceId }))
      }
      setCreated(made)
      onProgress({ approved: true })
    } catch (e) {
      setShareError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const name = b?.client_name ?? summary?.client_name ?? 'Loading…'
  const meeting = b?.meeting_date ?? summary?.meeting_date
  const sources = b ? Object.values(b.evidence).filter((e) => e.kind !== 'flag').length : 0
  const defs: Record<Step, { n: number; title: string; sub: string; done: boolean; heading: string; guide: string }> = {
    gather: {
      n: 1, title: 'Gather', sub: b ? `${count(sources, 'source')} · automatic` : 'Automatic', done: !!b,
      heading: 'We gathered everything',
      guide: 'Here is what was read and tidied up, using only what you can access. Nothing to do; take a look and continue.',
    },
    check: {
      n: 2, title: 'Check',
      sub: open ? `${count(open, 'decision')} for you` : conflicts.length ? 'All decided' : 'Nothing to decide',
      done: !!b && open === 0,
      heading: open ? (open === 1 ? 'One quick decision' : `${open} quick decisions`) : conflicts.length ? 'All decided' : 'Nothing to decide',
      guide: open
        ? 'Two sources disagree. Pick the one you trust; your choice goes into “Watch out for” and the follow-ups.'
        : conflicts.length
          ? 'Thanks. Your choices are noted in the briefing and the follow-ups.'
          : 'No two sources disagree for this client.',
    },
    read: {
      n: 3, title: 'Read', sub: b ? `About ${readingMinutes(b)} min read` : 'Your briefing', done: progress.read,
      heading: 'Your briefing',
      guide: 'Short sections. Click any small number to see where a sentence came from.',
    },
    share: {
      n: 4, title: 'Share', sub: progress.approved ? 'Approved' : 'Approve and export', done: progress.approved,
      heading: progress.approved ? 'All done' : 'Approve and export',
      guide: progress.approved
        ? 'The briefing is approved and the follow-ups are created. Download it to take it with you.'
        : 'Confirm the checks, choose the follow-ups, and approve.',
    },
  }
  const idx = STEPS.indexOf(step)
  let nextLabel = 'Continue to check'
  let next = () => onStep('check')
  let nextDisabled = !b
  if (step === 'check') {
    nextLabel = open ? `${open} left to decide` : 'Read the briefing'
    next = () => onStep('read')
    nextDisabled ||= open > 0
  } else if (step === 'read') {
    nextLabel = 'Approve and export'
    next = () => onStep('share')
  } else if (step === 'share') {
    nextLabel = progress.approved ? 'Approved' : open ? 'Decide conflicts first' : busy ? 'Approving…' : 'Approve'
    next = approve
    nextDisabled ||= progress.approved || open > 0 || busy
  }

  return (
    <div className="container">
      <div className="ws-head">
        <button type="button" className="link-back" onClick={props.onBack}>
          <ChevronLeft size={14} aria-hidden="true" />
          {props.backLabel}
        </button>
        <div className="ws-title">
          <span className="initials initials-lg" aria-hidden="true">
            {initials(name)}
          </span>
          <div>
            <h1>{name}</h1>
            {b && (
              <p className="note">
                {b.segment} · {b.region} · Last interaction {b.last_interaction ? shortDate(b.last_interaction) : 'none on file'}
                <br />
                Prepared for {b.prepared_for} · Coverage: {b.coverage.join(', ')}
              </p>
            )}
          </div>
          {meeting && (
            <span className="pill-when">
              <span className="dot" aria-hidden="true" />
              {countdown(meeting)} · {weekdayDate(meeting)}
            </span>
          )}
        </div>
      </div>

      <ol className="stepper panel" aria-label="Briefing steps">
        {STEPS.map((id) => {
          const d = defs[id]
          const current = id === step
          const done = d.done && !current
          const warn = id === 'check' && open > 0 && !current
          return (
            <li key={id}>
              <button type="button" className="step" aria-current={current ? 'step' : undefined} onClick={() => onStep(id)} disabled={!b}>
                <span className={`step-dot ${current ? 'is-current' : done ? 'is-done' : warn ? 'is-warn' : ''}`}>
                  {done ? <Check size={13} strokeWidth={3.2} aria-hidden="true" /> : d.n}
                </span>
                <span className="step-text">
                  <span className="step-title">{d.title}</span>
                  <span className={`step-sub ${warn ? 'is-warn' : ''}`}>{d.sub}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <div className="step-head">
        <div>
          <h2>{defs[step].heading}</h2>
          <p className="lead">{defs[step].guide}</p>
        </div>
        <div className="step-buttons">
          {idx > 0 && (
            <Button variant="outline" size="lg" onClick={() => onStep(STEPS[idx - 1])}>
              Back
            </Button>
          )}
          <Button size="lg" onClick={next} disabled={nextDisabled}>
            {nextLabel}
            <ArrowRight aria-hidden="true" />
          </Button>
        </div>
      </div>

      {loading && (
        <div className="panel loading-panel note">
          Gathering the briefing: the tools run first, then one AI call writes the narrative, and every section is checked
          before you see it…
        </div>
      )}
      {error && (
        <div className="panel loading-panel">
          <p className="note note-error">{error}</p>
          <Button variant="outline" size="sm" onClick={props.onRetry} className="mt-3">
            Try again
          </Button>
        </div>
      )}
      {b && step === 'gather' && <GatherStep briefing={b} />}
      {b && step === 'check' && (
        <CheckStep briefing={b} progress={progress} onDecide={(flagId, sourceId) => onProgress({ decisions: { ...progress.decisions, [flagId]: sourceId } })} />
      )}
      {b && step === 'read' && <ReadStep briefing={b} userId={userId} progress={progress} />}
      {b && step === 'share' && (
        <ShareStep
          briefing={b}
          progress={progress}
          open={open}
          followUps={followUps}
          isTicked={isTicked}
          onTick={(key, on) => setTicks((t) => ({ ...t, [key]: on }))}
          created={created}
          error={shareError}
        />
      )}
    </div>
  )
}
