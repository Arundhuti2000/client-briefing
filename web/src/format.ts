// Small display helpers shared by the components.

// "SQL:opportunities:OPP-NOR-TM" -> "OPP-NOR-TM", "DOC:note_001" -> "note_001", "FLAG:F007" -> "F007"
export function chipLabel(evidenceId: string): string {
  const [kind, ...rest] = evidenceId.split(':')
  if (kind === 'SQL') return rest.slice(1).join(':') // drop the table name; it's in the tooltip
  return rest.join(':')
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-09-15" -> "15 Sep 2026" (the same format the Python side uses; browsers vary, e.g. "Sept")
export function shortDate(iso: string | null): string {
  if (!iso) return 'none on file'
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return `${day} ${MONTHS[month - 1]} ${year}`
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
