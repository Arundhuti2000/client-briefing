// Small display helpers shared by the components.

// "SQL:opportunities:OPP-NOR-TM" -> "OPP-NOR-TM", "DOC:note_001" -> "note_001", "FLAG:F007" -> "F007"
export function chipLabel(evidenceId: string): string {
  const [kind, ...rest] = evidenceId.split(':')
  if (kind === 'SQL') return rest.slice(1).join(':') // drop the table name; it's in the tooltip
  return rest.join(':')
}

// "2026-09-15" -> "15 Sep 2026"
export function shortDate(iso: string | null): string {
  if (!iso) return 'none on file'
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
