// The briefing workspace (SPEC.md section 6). All logic stays in the Python API;
// this file only holds the screen's state and lays out the components.
import { useCallback, useEffect, useState } from 'react'
import { API_BASE, createBriefing, getUsers, resolveClient } from './api'
import type { Briefing, ClientInfo, ResolveResponse, UserInfo } from './api'
import { errorMessage } from './format'
import { AppBar } from './components/AppBar'
import { AuditDrawer } from './components/AuditDrawer'
import { BriefingPage } from './components/BriefingPage'
import { Toolbar } from './components/Toolbar'
import { Welcome } from './components/Welcome'

const DEMO_MEETING_DATE = '2026-11-18'
const linkParams = new URLSearchParams(window.location.search) // optional deep link: ?user=u2&client=NWC
const INITIAL_USER = linkParams.get('user') ?? 'u2'
let deepLinkHandled = false // React's dev mode runs effects twice; generate only once (one LLM call)

function App() {
  const [users, setUsers] = useState<UserInfo[]>([])
  const [userId, setUserId] = useState(INITIAL_USER)
  const [query, setQuery] = useState(linkParams.get('client') ?? 'Northwind Cap.')
  const [resolved, setResolved] = useState<ResolveResponse | null>(null)
  const [meetingDate, setMeetingDate] = useState(DEMO_MEETING_DATE)
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [auditOpen, setAuditOpen] = useState(false)

  const generate = useCallback(
    async (forUser: string, clientId: string) => {
      setLoading(true)
      setError(null)
      try {
        setBriefing(await createBriefing(forUser, clientId, meetingDate))
      } catch (e) {
        setBriefing(null)
        setError(errorMessage(e))
      } finally {
        setLoading(false)
      }
    },
    [meetingDate],
  )

  useEffect(() => {
    getUsers()
      .then(setUsers)
      .catch((e) => setError(`Cannot reach the API at ${API_BASE}: ${errorMessage(e)}`))
  }, [])

  useEffect(() => {
    // Deep link: resolve the client and generate straight away, once
    const client = linkParams.get('client')
    if (!client || deepLinkHandled) return
    deepLinkHandled = true
    resolveClient(INITIAL_USER, client)
      .then((r) => {
        setResolved(r)
        if (r.client) return generate(INITIAL_USER, r.client.client_id)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [generate])

  function changeUser(id: string) {
    setUserId(id)
    setBriefing(null) // never show one user's briefing to another
  }

  async function find(name: string = query) {
    setError(null)
    if (!name.trim()) return // nothing typed: don't send an empty query to the API
    try {
      setResolved(await resolveClient(userId, name.trim()))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function pickQuick(name: string) {
    setQuery(name)
    find(name)
  }

  function pickCandidate(client: ClientInfo) {
    setResolved({ query, client, matched_by: 'picked', error: null, candidates: [] })
  }

  return (
    <div className="app">
      <AppBar users={users} userId={userId} onUserChange={changeUser} onToggleAudit={() => setAuditOpen((o) => !o)} />
      <main className="page">
        <Toolbar
          query={query}
          onQueryChange={setQuery}
          onFind={() => find()}
          resolved={resolved}
          onPickCandidate={pickCandidate}
          meetingDate={meetingDate}
          onMeetingDateChange={setMeetingDate}
          onGenerate={() => resolved?.client && generate(userId, resolved.client.client_id)}
          loading={loading}
        />
        {error && <p className="note note-unavailable">{error}</p>}
        {loading && (
          <p className="note">
            Generating: the tools run first, then one LLM call; every section is validated before it is shown…
          </p>
        )}
        {!briefing && !loading && <Welcome onPick={pickQuick} />}
        {briefing && (
          <BriefingPage
            key={`${briefing.user_id}-${briefing.client_id}`}
            briefing={briefing}
            userId={userId}
            meetingDate={meetingDate}
            loading={loading}
            onRegenerate={() => generate(userId, briefing.client_id)}
          />
        )}
      </main>
      {auditOpen && <AuditDrawer key={userId} userId={userId} onClose={() => setAuditOpen(false)} />}
    </div>
  )
}

export default App
