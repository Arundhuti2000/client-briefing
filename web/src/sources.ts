// One icon per kind of source, so a reader can tell an email from a SQL figure at a glance.
// Used by the citation chips, the source panel, Gather's "Sources read" and Check's options.
import {
  BookOpen, Building2, ChartColumn, FileText, LifeBuoy, ListChecks, Mail, Newspaper, NotebookPen, Target,
  TriangleAlert, Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type SourceTone = 'indigo' | 'good' | 'warn' | 'muted'
export type SourceKind = { icon: LucideIcon; name: string; tone: SourceTone }

// Keyed by the evidence's `source` (the table, or the document's origin)
const KINDS: Record<string, SourceKind> = {
  clients: { icon: Building2, name: 'CRM', tone: 'indigo' },
  coverage: { icon: Users, name: 'CRM coverage', tone: 'indigo' },
  contacts: { icon: Users, name: 'CRM contacts', tone: 'indigo' },
  revenue_metrics: { icon: ChartColumn, name: 'Finance (SQL)', tone: 'good' },
  holdings: { icon: ChartColumn, name: 'Balances (SQL)', tone: 'good' },
  performance: { icon: ChartColumn, name: 'Performance (SQL)', tone: 'good' },
  opportunities: { icon: Target, name: 'Pipeline', tone: 'indigo' },
  open_actions: { icon: ListChecks, name: 'Actions', tone: 'warn' },
  service_issues: { icon: LifeBuoy, name: 'Service desk', tone: 'warn' },
  data_quality_flags: { icon: TriangleAlert, name: 'Data-quality flag', tone: 'warn' },
  email: { icon: Mail, name: 'Email', tone: 'muted' },
  crm_notes: { icon: NotebookPen, name: 'Meeting note', tone: 'muted' },
  briefing_archive: { icon: FileText, name: 'Prior briefing', tone: 'muted' },
  internal_research: { icon: BookOpen, name: 'Research', tone: 'muted' },
  news: { icon: Newspaper, name: 'News', tone: 'muted' },
}

// The kind of a source. Any other document source is a news publication ("Reuters").
// Without evidence (e.g. an excluded document a flag points at), the ID's prefix decides.
export function sourceKind(source: string | null | undefined, evidenceId = ''): SourceKind {
  if (source && KINDS[source]) return KINDS[source]
  if (source) return { ...KINDS.news, name: source }
  if (evidenceId.startsWith('FLAG:')) return KINDS.data_quality_flags
  const table = evidenceId.startsWith('SQL:') ? evidenceId.split(':')[1] : ''
  return KINDS[table] ?? { icon: FileText, name: 'Document', tone: 'muted' }
}
