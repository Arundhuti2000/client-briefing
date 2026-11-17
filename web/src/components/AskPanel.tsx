// "Ask a follow-up": a question about this client, routed and answered by the API
// (POST /briefings/{client_id}/ask). Under each answer: the route, how it was chosen,
// the tools called, and who wrote it.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { askFollowUp } from '../api'
import type { Answer, Briefing } from '../api'
import type { Cite } from '../cite'
import { errorMessage } from '../format'
import { BulletText, CiteChips, Tag } from './common'
import type { Tone } from './common'
import { Button } from '@/components/ui/button'

type Props = { briefing: Briefing; userId: string; answers: Answer[]; onAnswer: (a: Answer) => void; cite: Cite }

const ROUTE_NAMES: Record<string, string> = {
  metrics: 'Metrics', people: 'People', pipeline: 'Pipeline', actions: 'Actions', data_quality: 'Data quality',
  documents: 'Documents', news: 'News', out_of_scope: 'Out of scope',
}
const METHOD_NAMES: Record<Answer['method'], string> = {
  rule: 'keyword rule', meaning: 'meaning match', llm: 'AI router', default: 'default (document search)',
}
const PROVIDER_NAMES: Record<string, string> = { gemini: 'Gemini', openrouter: 'OpenRouter', ollama: 'Ollama' }

// Who wrote the answer, honestly
function writer(a: Answer): [Tone, string] {
  const ai = a.provider ? `${PROVIDER_NAMES[a.provider] ?? a.provider} · ${a.model?.split('/').pop()}` : ''
  switch (a.answered_by) {
    case 'code':
      return ['muted', 'Code from SQL · no AI']
    case 'ai':
      return ['indigo', `AI · ${ai} · checks passed`]
    case 'evidence':
      return ['warn', ai ? `Couldn't summarize (${ai}) · evidence shown` : 'No AI answer · evidence shown']
    default:
      return ['muted', 'Refused · no tools, no AI']
  }
}

function AnswerCard({ answer: a, cite }: { answer: Answer; cite: Cite }) {
  const [tone, label] = writer(a)
  return (
    <div className="answer">
      <p className="answer-q">{a.question}</p>
      {a.note && <p className="note">{a.note}</p>}
      {a.bullets.length > 0 && (
        <ul className="bullets bullets-compact">
          {a.bullets.map((b, i) => (
            <li key={i}>
              <BulletText text={b.text} />
              <CiteChips ids={b.citations} cite={cite} />
            </li>
          ))}
        </ul>
      )}
      <div className="answer-meta">
        <Tag tone={tone}>{label}</Tag>
        <span>
          Route: <strong>{ROUTE_NAMES[a.route] ?? a.route}</strong>, chosen by {METHOD_NAMES[a.method]}
          {a.reason && ` (${a.reason})`}
        </span>
        <span>Tools: {a.tools_called.length ? a.tools_called.join(', ') : 'none'}</span>
        {a.llm_steps > 0 && <span>{a.llm_steps} AI step{a.llm_steps === 1 ? '' : 's'}</span>}
      </div>
    </div>
  )
}

export function AskPanel({ briefing: b, userId, answers, onAnswer, cite }: Props) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const q = question.trim()
    if (!q || busy) return
    setBusy(true)
    setError(null)
    try {
      onAnswer(await askFollowUp(userId, b.client_id, q))
      setQuestion('')
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel panel-pad" aria-labelledby="ask-title">
      <div className="panel-head">
        <h3 id="ask-title" className="h3">
          Ask a follow-up
        </h3>
        <span className="sub">Same tools, access rules and checks as the briefing</span>
      </div>
      <form className="ask-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="ask-input">
          Your question about {b.client_name}
        </label>
        <input
          id="ask-input"
          className="ask-input"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={'e.g. "Who is the CFO?" or "What did they say about FX hedging?"'}
        />
        <Button type="submit" size="lg" disabled={busy || !question.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </Button>
      </form>
      {error && <p className="note note-error">{error}</p>}
      {answers.map((a, i) => (
        <AnswerCard key={answers.length - i} answer={a} cite={cite} />
      ))}
    </section>
  )
}
