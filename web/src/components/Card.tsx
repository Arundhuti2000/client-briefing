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

// Who wrote the section, and what the validator said about it
export function SectionBadge({ section, codeLabel }: { section?: Section; codeLabel?: string }) {
  if (!section) return null
  const errors = [...section.check.errors, ...section.retry_errors].join('\n')
  if (section.status === 'unavailable') return <span className="tag tag-bad">Unavailable</span>
  if (!section.check.passed) return <span className="tag tag-bad" title={errors}>Checks failed</span>
  if (section.status === 'fallback')
    return <span className="tag tag-warn" title={errors}>Evidence shown · draft failed checks</span>
  if (section.written_by === 'code') return <span className="tag tag-code">{codeLabel ?? 'Computed by code · no LLM'}</span>
  return (
    <span className="tag tag-ai" title={`Written by ${section.written_by}; every citation and number checked by code`}>
      AI written · checks passed
    </span>
  )
}

// "Unavailable", "nothing on file", and why a first draft was rejected
export function SectionNotes({ section }: { section?: Section }) {
  if (!section) return null
  return (
    <>
      {section.note && <p className={`note note-${section.status}`}>{section.note}</p>}
      {section.retry_errors.length > 0 && (
        <p className="note note-retry">
          The validator rejected the model's first draft ({section.retry_errors.join('; ')});{' '}
          {section.status === 'fallback' ? 'the retry failed too.' : `the retry by ${section.written_by} passed.`}
        </p>
      )}
    </>
  )
}

export function Bullets({ section, cite }: { section?: Section; cite: Cite }) {
  if (!section || section.bullets.length === 0) return null
  return (
    <ul className="bullets">
      {section.bullets.map((b, i) => (
        <li key={i}>
          <span>{b.text}</span> <Chips ids={b.citations} cite={cite} />
        </li>
      ))}
    </ul>
  )
}
