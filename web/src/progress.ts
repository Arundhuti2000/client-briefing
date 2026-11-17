// Where each briefing is in the workflow (Check, Read, Share), per user and client.
// Kept in this browser only (localStorage): a convenience for the demo, not a record.
// What must be kept (follow-up tasks, the audit log) is written by the API.

export type Progress = {
  decisions: Record<string, string> // conflict flag evidence ID -> the source the banker trusts
  read: boolean // the Read step was opened
  approved: boolean // approved in Share
}

export const EMPTY_PROGRESS: Progress = { decisions: {}, read: false, approved: false }

const key = (userId: string, clientId: string) => `briefing-desk:${userId}:${clientId}`

export function loadProgress(userId: string, clientId: string): Progress {
  try {
    const saved = localStorage.getItem(key(userId, clientId))
    return saved ? { ...EMPTY_PROGRESS, ...JSON.parse(saved) } : EMPTY_PROGRESS
  } catch {
    return EMPTY_PROGRESS // storage blocked (private window): start fresh
  }
}

export function saveProgress(userId: string, clientId: string, progress: Progress): void {
  try {
    localStorage.setItem(key(userId, clientId), JSON.stringify(progress))
  } catch {
    // storage blocked: progress lasts for this visit only
  }
}

// What the meetings list says about a briefing
export type Status = 'needs-you' | 'ready' | 'read' | 'approved'

export function statusOf(conflicts: number, progress: Progress): Status {
  if (progress.approved) return 'approved'
  if (Object.keys(progress.decisions).length < conflicts) return 'needs-you'
  return progress.read ? 'read' : 'ready'
}

export function openDecisions(conflicts: number, progress: Progress): number {
  return Math.max(0, conflicts - Object.keys(progress.decisions).length)
}
