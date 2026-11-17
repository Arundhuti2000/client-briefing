// Small display helpers. Dates arrive as ISO strings from the API ("2026-09-15") and are
// shown the way the Python side writes them ("15 Sep 2026"), never as ISO.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const DAY_MS = 24 * 60 * 60 * 1000

function parts(iso: string): [number, number, number] {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return [year, month, day]
}

function utc(iso: string): number {
  const [year, month, day] = parts(iso)
  return Date.UTC(year, month - 1, day)
}

// "2026-09-15" -> "15 Sep 2026"
export function shortDate(iso: string): string {
  const [year, month, day] = parts(iso)
  return `${day} ${MONTHS[month - 1]} ${year}`
}

// "2026-09-15" -> "15 Sep"
export function dayMonth(iso: string): string {
  const [, month, day] = parts(iso)
  return `${day} ${MONTHS[month - 1]}`
}

// "2026-11-18" -> "Wed, 18 Nov 2026"
export function weekdayDate(iso: string): string {
  return `${WEEKDAYS[new Date(utc(iso)).getUTCDay()].slice(0, 3)}, ${shortDate(iso)}`
}

// Whole days from one date to a later one: ("2026-10-31", "2026-11-18") -> 18
export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((utc(toIso) - utc(fromIso)) / DAY_MS)
}

// The browser's local date, for "today" lines and the countdown
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

// "Monday, 16 Nov"
export function todayLine(now = new Date()): string {
  return `${WEEKDAYS[now.getDay()]}, ${now.getDate()} ${MONTHS[now.getMonth()]}`
}

// A timestamp in the browser's time zone: "17 Nov 2026 at 07:58"
export function dateTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()} at ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function greeting(now = new Date()): string {
  const hour = now.getHours()
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
}

// "Meeting in 2 days", "Meeting tomorrow", "Meeting was 3 days ago"
export function countdown(meetingIso: string, now = new Date()): string {
  const days = daysBetween(todayIso(now), meetingIso)
  if (days === 0) return 'Meeting today'
  if (days === 1) return 'Meeting tomorrow'
  if (days > 1) return `Meeting in ${days} days`
  return `Meeting was ${-days} day${days === -1 ? '' : 's'} ago`
}

// "Northwind Capital Partners" -> "NC"
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((w) => /^[A-Za-z]/.test(w))
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}

// 1 -> "1 thing", 2 -> "2 things"; nouns ending in s, x, ch or sh take "es" ("2 data fixes")
export function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : /(s|x|ch|sh)$/.test(noun) ? 'es' : 's'}`
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
