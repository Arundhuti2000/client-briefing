// Numbered citation chips. Every evidence ID gets a number in the order it first
// appears in the Read step; selecting a chip shows that source in the right-hand panel.
import type { Briefing } from './api'

export type Cite = {
  number: (evidenceId: string) => number
  describe: (evidenceId: string) => { label: string; source: string | null } // for the chip's icon and tooltip
  selected: string | null
  select: (evidenceId: string) => void
}

export function sectionOf(b: Briefing, sectionId: string) {
  return b.sections.find((s) => s.id === sectionId)
}

export function sectionCitations(b: Briefing, sectionId: string): string[] {
  return sectionOf(b, sectionId)?.bullets.flatMap((bullet) => bullet.citations) ?? []
}

// The order of the Read step, top to bottom, then the agenda on the right
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
