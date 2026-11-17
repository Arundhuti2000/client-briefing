// The app shell: sidebar + either the meeting queue or one client's briefing workspace.
// All logic stays in the Python API; this file only holds the screen's state.
import { useCallback, useEffect, useState } from 'react'
import { API_BASE, createBriefing, getClients, getUsers, resolveClient } from './api'
import type { Briefing, ClientSummary, UserInfo } from './api'
import { errorMessage } from './format'
import { loadProgress, saveProgress } from './progress'
import type { Progress } from './progress'
import { AuditDrawer } from './components/AuditDrawer'
import { BriefingPage } from './components/BriefingPage'
import type { Step } from './components/BriefingPage'
import { ClientsPage } from './components/ClientsPage'
import { DataHealthPage } from './components/DataHealthPage'
import { EvaluationsPage } from './components/EvaluationsPage'
import { MeetingsPage } from './components/MeetingsPage'
import { Sidebar } from './components/Sidebar'
import type { Page } from './components/Sidebar'

const STEPS: Step[] = ['gather', 'check', 'read', 'share']
const linkParams = new URLSearchParams(window.location.search) // deep links: ?user=u2&client=NWC&step=read, ?page=clients
const INITIAL_USER = linkParams.get('user') ?? 'u2'
const BACK_LABELS: Record<Page, string> = { meetings: 'All meetings', clients: 'All clients', health: 'Data health', evals: 'Evaluations' }
const PAGES: Page[] = ['meetings', 'clients', 'health', 'evals']
const INITIAL_PAGE = PAGES.find((p) => p === linkParams.get('page')) ?? 'meetings'
let deepLinkHandled = false // React's dev mode runs effects twice; generate only once (one LLM call)

function App() {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [userId, setUserId] = useState(INITIAL_USER)
  const [clients, setClients] = useState<ClientSummary[] | null>(null)
  const [page, setPage] = useState<Page>(INITIAL_PAGE)
  const [clientId, setClientId] = useState<string | null>(null) // set: that client's briefing, on top of `page`
  const [step, setStep] = useState<Step>('gather')
  const [briefings, setBriefings] = useState<Record<string, Briefing>>({}) // "user:client" -> briefing
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<Record<string, Progress>>({})
  const [auditOpen, setAuditOpen] = useState(false)

  const key = (forUser: string, id: string) => `${forUser}:${id}`

  const generate = useCallback(async (forUser: string, id: string) => {
    const k = key(forUser, id)
    setLoadingKey(k)
    setError(null)
    try {
      const b = await createBriefing(forUser, id)
      setBriefings((all) => ({ ...all, [k]: b }))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoadingKey((current) => (current === k ? null : current))
    }
  }, [])

  useEffect(() => {
    getUsers()
      .then(setUsers)
      .catch((e) => setError(`Cannot reach the API at ${API_BASE}: ${errorMessage(e)}`))
  }, [])

  useEffect(() => {
    let cancelled = false
    getClients(userId)
      .then((c) => !cancelled && setClients(c))
      .catch((e) => !cancelled && setError(errorMessage(e)))
    return () => {
      cancelled = true
    }
  }, [userId])

  useEffect(() => {
    // Deep link: resolve the client and generate straight away, once
    const name = linkParams.get('client')
    if (!name || deepLinkHandled) return
    deepLinkHandled = true
    const linkStep = STEPS.find((s) => s === linkParams.get('step')) ?? 'gather'
    resolveClient(INITIAL_USER, name)
      .then((r) => {
        if (!r.client) return setError(`No client matches “${name}” confidently.`)
        setClientId(r.client.client_id)
        setStep(linkStep)
        return generate(INITIAL_USER, r.client.client_id)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [generate])

  const progressOf = (id: string) => progress[id] ?? loadProgress(userId, id)

  function updateProgress(id: string, change: Partial<Progress>) {
    const next = { ...progressOf(id), ...change }
    saveProgress(userId, id, next)
    setProgress((all) => ({ ...all, [id]: next }))
  }

  function goTo(id: string, s: Step) {
    setStep(s)
    if (s === 'read') updateProgress(id, { read: true })
  }

  function open(id: string, s: Step) {
    setClientId(id)
    setError(null)
    goTo(id, s)
    if (!briefings[key(userId, id)]) generate(userId, id)
  }

  function changeUser(id: string) {
    // Never show one user's briefing, progress or meetings to another
    setUserId(id)
    setClients(null)
    setBriefings({})
    setProgress({})
    setClientId(null)
    setError(null)
  }

  const me = users.find((u) => u.user_id === userId)
  return (
    <div className="shell">
      <Sidebar
        users={users}
        userId={userId}
        onUserChange={changeUser}
        meetingCount={clients ? clients.length : null}
        page={clientId ? 'meetings' : page}
        onNavigate={(p) => {
          setPage(p)
          setClientId(null)
        }}
        onAudit={() => setAuditOpen((o) => !o)}
      />
      <main className="main">
        {clientId === null ? (
          <>
            {error && <p className="note note-error" style={{ maxWidth: 1180, margin: '0 auto 16px' }}>{error}</p>}
            {page === 'meetings' && (
              <MeetingsPage
                clients={clients}
                firstName={me ? me.name.split(' ')[0] : ''}
                userId={userId}
                progressOf={progressOf}
                onOpen={open}
              />
            )}
            {page === 'clients' && <ClientsPage clients={clients} onOpen={open} />}
            {page === 'health' && <DataHealthPage clients={clients} onOpen={open} />}
            {page === 'evals' && <EvaluationsPage key={userId} userId={userId} />}
          </>
        ) : (
          <BriefingPage
            key={key(userId, clientId)}
            userId={userId}
            summary={clients?.find((c) => c.client_id === clientId)}
            briefing={briefings[key(userId, clientId)] ?? null}
            loading={loadingKey === key(userId, clientId)}
            error={error}
            step={step}
            progress={progressOf(clientId)}
            onStep={(s) => goTo(clientId, s)}
            onProgress={(change) => updateProgress(clientId, change)}
            backLabel={BACK_LABELS[page]}
            onBack={() => setClientId(null)}
            onRetry={() => generate(userId, clientId)}
          />
        )}
      </main>
      {auditOpen && <AuditDrawer key={userId} userId={userId} userName={me?.name ?? ''} onClose={() => setAuditOpen(false)} />}
    </div>
  )
}

export default App
