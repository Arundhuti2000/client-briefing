// Numbered citation chips. Every evidence ID gets a number in the order it first
// appears on the page; selecting a chip shows that source in the right-hand column.
import type { Briefing } from './api'

export type Cite = {
  number: (evidenceId: string) => number
  total: number
  selected: string | null
  select: (evidenceId: string) => void
}

export function sectionCitations(b: Briefing, sectionId: string): string[] {
  const section = b.sections.find((s) => s.id === sectionId)
  return section ? section.bullets.flatMap((bullet) => bullet.citations) : []
}

// The page order of the cards, so chip numbers read top to bottom
export function numberSources(b: Briefing): Map<string, number> {
  const ordered = [
    ...sectionCitations(b, 'client_overview'),
    ...b.what_changed.flatMap((c) => c.evidence_ids),
    ...sectionCitations(b, 'client_said'),
    ...b.actions.map((a) => a.evidence_id),
    ...sectionCitations(b, 'open_items'),
    ...b.metrics.map((m) => m.evidence_id),
    ...b.opportunities.map((o) => o.evidence_id),
    ...sectionCitations(b, 'opportunities'),
    ...sectionCitations(b, 'news'),
    ...b.flags.flatMap((f) => [f.evidence_id, ...f.source_ids]),
    ...sectionCitations(b, 'talking_points'),
  ]
  const numbers = new Map<string, number>()
  for (const id of ordered) if (!numbers.has(id)) numbers.set(id, numbers.size + 1)
  return numbers
}
