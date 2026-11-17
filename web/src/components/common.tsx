// Small building blocks shared by every screen: source icons, citation chips, tags,
// who-wrote-it labels, retry notes, bullets and status dots. Built on shadcn/ui.
import type { ReactNode } from 'react'
import type { Section } from '../api'
import type { Cite } from '../cite'
import { sourceKind } from '../sources'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export type Tone = 'indigo' | 'warn' | 'good' | 'bad' | 'muted'

// The kind of source as an icon; `tile` puts it on a coloured square (lists, the source panel)
export function SourceIcon({ source, evidenceId, tile, size = 16 }: { source?: string | null; evidenceId?: string; tile?: boolean; size?: number }) {
  const kind = sourceKind(source, evidenceId)
  const Icon = kind.icon
  if (!tile) return <Icon aria-hidden="true" size={size} />
  return (
    <span className={`src-tile is-${kind.tone}`} title={kind.name}>
      <Icon aria-hidden="true" size={size} />
    </span>
  )
}

// A citation: the source's icon and its number. Hover shows what it is; click opens it.
export function CiteChips({ ids, cite }: { ids: string[]; cite: Cite }) {
  return (
    <>
      {ids.map((id) => {
        const { label, source } = cite.describe(id)
        return (
          <Tooltip key={id}>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={cn('cite', cite.selected === id && 'is-on')}
                aria-label={`Show source ${cite.number(id)}: ${label}`}
                onClick={() => cite.select(id)}
              >
                <SourceIcon source={source} evidenceId={id} size={10} />
                {cite.number(id)}
              </button>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
          </Tooltip>
        )
      })}
    </>
  )
}

// shadcn's Badge in the design's soft colours
const TONES: Record<Tone, string> = {
  indigo: 'bg-(--indigo-soft) text-(--indigo-strong)',
  warn: 'bg-(--warn-soft) text-(--warn-ink)',
  good: 'bg-(--good-soft) text-(--good-ink)',
  bad: 'bg-(--bad-soft) text-(--bad-ink)',
  muted: 'bg-secondary text-(--text-strong)',
}

export function Tag({ tone = 'muted', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return <Badge className={cn('px-2.5 font-semibold', TONES[tone], className)}>{children}</Badge>
}

// A bullet's text, with "⚠ Contradicted: ..." set apart so it can't be missed
export function BulletText({ text }: { text: string }) {
  const [statement, contradiction] = text.split('⚠ Contradicted:')
  return (
    <>
      {statement}
      {contradiction !== undefined && <span className="contradicted">⚠ Contradicted:{contradiction}</span>}
    </>
  )
}

export function BulletList({ section, cite, compact }: { section?: Section; cite: Cite; compact?: boolean }) {
  if (!section || section.bullets.length === 0) return null
  return (
    <ul className={cn('bullets', compact && 'bullets-compact')}>
      {section.bullets.map((b, i) => (
        <li key={i}>
          <BulletText text={b.text} />
          <CiteChips ids={b.citations} cite={cite} />
        </li>
      ))}
    </ul>
  )
}

const PROVIDER_NAMES: Record<string, string> = { gemini: 'Gemini', openrouter: 'OpenRouter', ollama: 'Ollama' }

// Who wrote a section, honestly: "AI" (with the provider and the model that answered) only when
// a real model wrote it and every check passed
export function AuthorTag({ section, className }: { section?: Section; className?: string }) {
  if (!section) return null
  const label = cn('author-tag', className) // .author-tag sits at the right end of a section heading
  if (section.status === 'unavailable') return <Tag tone="bad" className={label}>Unavailable</Tag>
  if (!section.check.passed) return <Tag tone="bad" className={label}>Checks failed</Tag>
  switch (section.author) {
    case 'code':
      return <Tag className={label}>Computed by code · no AI</Tag>
    case 'template':
      return <Tag className={label}>Template (no AI)</Tag>
    case 'evidence':
      return <Tag tone="warn" className={label}>Source facts shown</Tag>
    default: {
      // "nvidia/nemotron-3.5-super-vl:free" shows as "nemotron-3.5-super-vl:free"; the full ID is in the tooltip
      const provider = PROVIDER_NAMES[section.provider ?? ''] ?? section.provider
      const model = section.written_by.split('/').pop()
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={cn('inline-flex min-w-0 max-w-full', label)}>
              <Tag tone="indigo" className="max-w-full">
                <span className="truncate">
                  AI · {provider} · {model}
                </span>
              </Tag>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            Written by {section.written_by} via {provider}. Every citation, number and date was checked by code.
          </TooltipContent>
        </Tooltip>
      )
    }
  }
}

// "Nothing on file", "unavailable", and why a first draft was rejected (detail on request)
export function SectionNotes({ section }: { section?: Section }) {
  if (!section) return null
  return (
    <>
      {section.note && <p className={cn('note', section.status === 'unavailable' && 'note-error')}>{section.note}</p>}
      {section.retry_note && (
        <div className="note-retry">
          {section.retry_note}
          {section.retry_errors.length > 0 && (
            <details>
              <summary>Details</summary>
              <ul>
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

export function StatusText({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`status tone-${tone}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  )
}
