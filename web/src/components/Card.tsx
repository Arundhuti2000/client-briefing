// Building blocks shared by every card: the frame, the validator badge, notes,
// bullets and numbered citation chips.
import type { ReactNode } from 'react'
import type { Section } from '../api'
import type { Cite } from '../cite'

type CardProps = { id?: string; title: string; badges?: ReactNode; tone?: 'warn' | 'source'; children: ReactNode }

export function Card({ id, title, badges, tone, children }: CardProps) {
  const headingId = `h-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`
  return (
    <section id={id} aria-labelledby={headingId} className={`card ${tone ? `card-${tone}` : ''}`}>
      <div className="card-head">
        <h2 id={headingId}>{title}</h2>
        <span className="card-badges">{badges}</span>
      </div>
      {children}
    </section>
  )
}

export function Chips({ ids, cite }: { ids: string[]; cite: Cite }) {
  return (
    <span className="chips">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className={`chip ${cite.selected === id ? 'chip-on' : ''}`}
          title={id}
          aria-label={`Show source ${cite.number(id)}: ${id}`}
          onClick={() => cite.select(id)}
        >
          {cite.number(id)}
        </button>
      ))}
    </span>
  )
}

// Who wrote the section, and what the validator said about it. "AI written" only when a
// real model wrote it; mock mode is labelled as a template.
export function SectionBadge({ section, codeLabel }: { section?: Section; codeLabel?: string }) {
  if (!section) return null
  if (section.status === 'unavailable') return <span className="tag tag-bad">Unavailable</span>
  if (!section.check.passed) return <span className="tag tag-bad">Checks failed</span>
  switch (section.author) {
    case 'code':
      return <span className="tag tag-code">{codeLabel ?? 'Computed by code · no LLM'}</span>
    case 'template':
      return <span className="tag tag-plain" title="Bullets built by code from the evidence; no AI">Template (no AI)</span>
    case 'evidence':
      return <span className="tag tag-warn">Source facts shown</span>
    default:
      return (
        <span className="tag tag-ai" title={`Written by ${section.written_by}; every citation, number and date checked by code`}>
          AI written · checks passed
        </span>
      )
  }
}

// "Unavailable", "nothing on file", and why a first draft was rejected (detail on request)
export function SectionNotes({ section }: { section?: Section }) {
  if (!section) return null
  return (
    <>
      {section.note && <p className={`note note-${section.status}`}>{section.note}</p>}
      {section.retry_note && (
        <div className="note note-retry">
          {section.retry_note}
          {section.retry_errors.length > 0 && (
            <details>
              <summary>Details</summary>
              <ul className="small">
                {section.retry_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </>
  )
}

// A bullet's text, with "⚠ Contradicted: ..." set apart so it can't be missed
export function BulletText({ text }: { text: string }) {
  const [statement, contradiction] = text.split('⚠ Contradicted:')
  return (
    <span>
      {statement}
      {contradiction !== undefined && <span className="contradicted">⚠ Contradicted:{contradiction}</span>}
    </span>
  )
}

export function Bullets({ section, cite }: { section?: Section; cite: Cite }) {
  if (!section || section.bullets.length === 0) return null
  return (
    <ul className="bullets">
      {section.bullets.map((b, i) => (
        <li key={i}>
          <BulletText text={b.text} /> <Chips ids={b.citations} cite={cite} />
        </li>
      ))}
    </ul>
  )
}
