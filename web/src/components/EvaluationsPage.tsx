// Evaluations: the last `make eval` (GET /evaluations), laid out like the design: a verdict
// card, then tabs. Every number comes from the report; failure messages (which can name
// restricted records) stay in the terminal, so this page shows counts and statuses only.
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Check, ShieldAlert, ShieldCheck } from 'lucide-react'
import { ApiError, getEvaluations } from '../api'
import type { EvalCheck, EvalNote, EvalReport, EvalRun, JudgeHistory, QualityReport, RetrievalReport } from '../api'
import { dateTime, errorMessage } from '../format'
import type { Tone } from './common'

// One scorecard: a dataset written one way (template or live models). dev2 was held-out
// round 1 until its result was recorded; holdout is the current held-out set.
type Dataset = 'dev' | 'dev2' | 'holdout'
const DATASET_NAMES: Record<Dataset, string> = { dev: 'Dev', dev2: 'Dev 2', holdout: 'Holdout' }
type View = { key: string; label: string; data: Dataset; run: EvalRun }

const TABS = [
  ['overview', 'Overview'],
  ['traps', 'Planted traps'],
  ['retrieval', 'Retrieval'],
  ['detectors', 'Detectors'],
  ['router', 'Router and AI text'],
  ['proves', 'What it proves'],
] as const
type TabId = (typeof TABS)[number][0]
const WITH_DATASET: TabId[] = ['overview', 'retrieval', 'detectors']
// Deep link, like the app's others: ?page=evals&tab=router
const LINK_TAB = TABS.find(([id]) => id === new URLSearchParams(window.location.search).get('tab'))?.[0]

const METHODS = [
  ['bm25', 'BM25 only'],
  ['vector', 'Vector only'],
  ['hybrid', 'Hybrid (RRF)'], // the one the app's search uses
] as const
const METRICS = [
  ['precision@5', 'Precision@5'],
  ['recall@5', 'Recall@5'],
  ['mrr', 'MRR'],
  ['ndcg@5', 'nDCG@5'],
] as const

// ---- reading the report ------------------------------------------------------------

const sum = (ns: number[]) => ns.reduce((a, b) => a + b, 0)
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const pct = (n: number) => `${Math.round(n * 100)}%`
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const measured = (c: EvalCheck) => capitalize(c.measures.replaceAll('_', '-')) // "must_include facts" -> "Must-include facts"
const toneOf = (score: number): Tone => (score >= 0.95 ? 'good' : score >= 0.8 ? 'warn' : 'bad')

function viewName(data: Dataset, provider: string) {
  return `${DATASET_NAMES[data]} · ${provider === 'mock' ? 'template' : 'live models'}`
}

function viewsOf(report: EvalReport): View[] {
  return [...report.runs, ...(report.holdout_runs ?? [])].map((run) => {
    const data: Dataset = run.dataset ?? 'dev'
    return { key: `${data}:${run.provider}`, label: viewName(data, run.provider), data, run }
  })
}

// A check's result as numbers: "17/18 (94%)" -> 1 bad of 18; "2 (in 12 checks)" -> 2 bad of 12
function counts(c: EvalCheck) {
  const zero = /^(\d+) \(in (\d+) checks\)/.exec(c.result)
  if (zero) return { bad: Number(zero[1]), total: Number(zero[2]) }
  const ratio = /^(\d+)\/(\d+)/.exec(c.result)
  return ratio ? { bad: Number(ratio[2]) - Number(ratio[1]), total: Number(ratio[2]) } : { bad: 0, total: 0 }
}

// Older reports wrote the note as plain "Proves: ..." and "Doesn't prove: ..." lines
function noteOf(q: QualityReport): EvalNote {
  if (!Array.isArray(q.note)) return q.note
  const proves = q.note.filter((line) => line.startsWith('Proves:'))
  return {
    proves: proves.map((line) => capitalize(line.replace(/^Proves:\s*/, ''))),
    not_proves: q.note
      .filter((line) => !proves.includes(line))
      .map((line) => ({ title: '', detail: capitalize(line.replace(/^Doesn't prove:\s*/, '')) })),
  }
}

function viewNote(v: View) {
  if (v.data === 'holdout') return 'Held-out data (round 2) the rules were never tuned on: the fairest estimate.'
  if (v.data === 'dev2')
    return 'Second development set: held-out round 1, whose result was recorded before its four gaps were fixed. Now a regression test.'
  if (v.run.provider === 'mock') return 'Development data, briefings written by the template (no AI). The rules were built on this set.'
  return `The same development data, written by the LLM chain (${v.run.provider.replaceAll(',', ', ')}). Models: ${v.run.models}.`
}

// ---- small pieces ---------------------------------------------------------------------

function Bar({ value, tone }: { value: number; tone: Tone | 'grey' }) {
  return (
    <div className={`bar is-${tone}`} aria-hidden="true">
      <span style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} />
    </div>
  )
}

function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`status tone-${tone}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  )
}

// ---- the verdict card -------------------------------------------------------------------

function Verdict({ views, quality }: { views: View[]; quality?: QualityReport }) {
  const checks = views.flatMap((v) => v.run.checks.map((c) => ({ ...c, run: v.label })))
  const failing = checks.filter((c) => !c.passed)
  const zero = checks.filter((c) => c.zero_tolerance).map(counts)
  const zeroBad = sum(zero.map((z) => z.bad))
  const tone: Tone = zeroBad > 0 ? 'bad' : failing.length > 0 ? 'warn' : 'good'
  const Icon = tone === 'good' ? ShieldCheck : ShieldAlert
  const stats: [string, number][] = [
    ['briefings', sum(views.map((v) => v.run.cases))],
    ['planted traps', views[0].run.traps.length],
  ]
  if (quality) stats.push(['detector cases', sum(Object.values(quality.detectors).map((d) => d.cases))])
  return (
    <section className="panel verdict" aria-labelledby="verdict">
      <span className={`verdict-icon is-${tone}`}>
        <Icon aria-hidden="true" size={26} strokeWidth={2.4} />
      </span>
      <div className="verdict-text">
        <h2 id="verdict">
          {failing.length === 0
            ? `All ${views[0].run.checks.length} checks pass on all ${plural(views.length, 'run')}`
            : `${plural(failing.length, 'check')} failing`}
        </h2>
        <p className="note">
          {plural(zeroBad, 'failure')} in {sum(zero.map((z) => z.total))} zero-tolerance checks (restricted leaks,
          injection, red team).{' '}
          {failing.length > 0 && <>Failing: {failing.map((c) => `${c.name} on ${c.run}`).join('; ')}. </>}
          The break test turns the access filter off to prove these checks can fail.
        </p>
      </div>
      <dl className="stat-row">
        {stats.map(([label, n]) => (
          <div key={label} className="stat">
            <dt>{label}</dt>
            <dd className="mono">{n}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

// ---- tabs -------------------------------------------------------------------------------

function Overview({ view }: { view: View }) {
  const { run } = view
  const latency = /median ([\d.]+ s), max ([\d.]+ s)/.exec(run.latency)
  return (
    <>
      <p className="note">{viewNote(view)}</p>
      <div className="zero-grid">
        {run.checks
          .filter((c) => c.zero_tolerance)
          .map((c) => {
            const { bad, total } = counts(c)
            return (
              <div key={c.name} className="panel zero-card">
                <div className="zero-head">
                  <span className="h3">{c.name}</span>
                  <span className="zero-tag">Zero tolerance</span>
                </div>
                <div className="zero-num">
                  <span className={`big-num mono tone-${bad ? 'bad' : 'good'}`}>{bad}</span>
                  <span className="note">
                    {bad === 1 ? 'failure' : 'failures'} in {plural(total, 'check')}
                  </span>
                </div>
                <span className="sub">{measured(c)}</span>
              </div>
            )
          })}
      </div>

      <section className="panel" aria-labelledby="gates">
        <div className="panel-head gates-head">
          <h3 id="gates" className="h3">
            Quality gates
          </h3>
          <span className="sub">
            {view.label} · {plural(run.cases, 'briefing')}
          </span>
        </div>
        {run.checks
          .filter((c) => !c.zero_tolerance)
          .map((c) => {
            const { bad, total } = counts(c)
            return (
              <div key={c.name} className="gate-row">
                <div className="gate-name">
                  <span className="strong">{c.name}</span>
                  <span className="sub">{measured(c)}</span>
                </div>
                <div className="gate-bar">
                  <Bar value={total ? (total - bad) / total : 0} tone={c.passed ? 'good' : 'bad'} />
                  <span className="gate-score mono">
                    {total - bad}/{total}
                  </span>
                </div>
                <span className="gate-target">target {c.target.replace('>=', '≥')}</span>
                <Status tone={c.passed ? 'good' : 'bad'}>{c.passed ? 'Pass' : 'Fail'}</Status>
              </div>
            )
          })}
      </section>

      <div className="stat-cards">
        <div className="panel stat-card">
          <span className="note">Time to build one briefing</span>
          <span className="stat-card-value mono">
            {latency ? (
              <>
                {latency[1]} <small>median · {latency[2]} max</small>
              </>
            ) : (
              run.latency
            )}
          </span>
        </div>
        <div className="panel stat-card">
          <span className="note">AI cost per briefing</span>
          <span className="stat-card-value mono">
            {run.cost
              ? `${plural(run.cost.requests, 'request')} · ${run.cost.tokens_in + run.cost.tokens_out} tokens`
              : '–'}
          </span>
          <span className="small muted">
            {run.provider === 'mock'
              ? 'Template mode, no model used'
              : `Cache hits per briefing: ${run.cost?.cache_hits ?? 0} · ${run.models}`}
          </span>
        </div>
      </div>
    </>
  )
}

function Traps({ views }: { views: View[] }) {
  const traps = views[0].run.traps
  return (
    <>
      <p className="note">
        {traps.length} messy-data situations planted on purpose. Each one must be caught on every run.
      </p>
      <div className="trap-grid">
        {traps.map((t) => {
          const statuses = views.map((v) => ({
            label: v.label,
            status: v.run.traps.find((x) => x.trap_id === t.trap_id)?.status ?? 'not checked',
          }))
          const missed = statuses.some((s) => s.status === 'FAIL')
          const caught = statuses.some((s) => s.status === 'PASS')
          return (
            <div key={t.trap_id} className="trap-card">
              <div className="trap-head">
                <span className="id-chip mono">{t.trap_id}</span>
                <span className="strong">{t.what}</span>
              </div>
              <div className="chips">
                {t.checks.map((c) => (
                  <span key={c} className="chip">
                    {c}
                  </span>
                ))}
              </div>
              <div className="trap-runs">
                {statuses.map((s) => (
                  <span key={s.label} className="run-dot">
                    <span
                      className={`dot ${s.status === 'PASS' ? 'is-good' : s.status === 'FAIL' ? 'is-bad' : ''}`}
                      aria-hidden="true"
                    />
                    {s.label}
                    <span className="sr-only">: {s.status === 'not checked' ? 'not checked' : s.status.toLowerCase()}</span>
                  </span>
                ))}
                <span className={`trap-verdict tone-${missed ? 'bad' : caught ? 'good' : 'muted'}`}>
                  {missed ? 'Missed' : caught ? 'Caught' : 'Not checked'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

function Retrieval({ report }: { report?: RetrievalReport }) {
  if (!report) return <p className="note">No retrieval scores for this dataset.</p>
  return (
    <>
      <p className="note">
        Top 5 documents per question, with access filtering on. {plural(report.scored, 'question')} scored.
      </p>
      <div className="method-grid">
        {METHODS.map(([id, name]) => {
          const inUse = id === 'hybrid'
          return (
            <div key={id} className={`method-card ${inUse ? 'is-on' : ''}`}>
              <div className="method-head">
                <span className="h3">{name}</span>
                {inUse && <span className="in-use">In use</span>}
              </div>
              {METRICS.map(([key, label]) => {
                const value = report.methods[id]?.[key] ?? 0
                return (
                  <div key={key} className="metric-row">
                    <span className="metric-label">{label}</span>
                    <Bar value={value} tone={inUse ? 'indigo' : 'grey'} />
                    <span className="metric-val mono">{value.toFixed(2)}</span>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
      <div className="callout-row">
        <div className={`callout ${report.restricted_retrieved === 0 ? 'is-good' : 'is-bad'}`}>
          <span className="callout-num mono">{report.restricted_retrieved}</span>
          <span>restricted documents returned to a user without access</span>
        </div>
        <p className="callout is-plain">
          Precision@5 looks low because most questions have only one or two relevant documents, so five results can't
          all be relevant. Recall and MRR are the numbers to watch.
        </p>
      </div>
    </>
  )
}

function Detectors({ report, note }: { report?: QualityReport['detectors'][string]; note: EvalNote | null }) {
  if (!report) return <p className="note">No detector scores for this dataset.</p>
  const caveat = note?.not_proves.find((n) => n.title === 'Unbiased detector scores')
  return (
    <>
      <p className="note">
        Generated variations: aliases, typos, suffixes, case, look-alikes, true conflicts and near-misses.{' '}
        {plural(report.cases, 'case')}.
      </p>
      <section className="panel table-scroll">
        <table className="grid-table det-table">
          <thead>
            <tr>
              <th>Detector</th>
              <th>Cases</th>
              <th>Precision</th>
              <th>Recall</th>
              <th>F1</th>
              <th>Mistakes</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(report.detectors).map(([name, d]) => {
              const mistakes = [
                ...d.false_positives.map((x) => `False alarm: ${x}`),
                ...d.false_negatives.map((x) => `Missed: ${x}`),
              ]
              return (
                <tr key={name}>
                  <td className="strong">{name}</td>
                  <td className="mono">{d.cases}</td>
                  {[d.precision, d.recall, d.f1].map((v, i) => (
                    <td key={i} className={`mono strong tone-${toneOf(v)}`}>
                      {v.toFixed(2)}
                    </td>
                  ))}
                  <td>
                    {mistakes.length === 0 ? (
                      <span className="muted">None</span>
                    ) : (
                      <details>
                        <summary className="small">{plural(mistakes.length, 'mistake')}</summary>
                        <ul className="mistakes">
                          {mistakes.map((m) => (
                            <li key={m}>{m}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
      {caveat && <p className="callout is-warn">{caveat.detail}</p>}
    </>
  )
}

function RouterAndAI({ q, judge }: { q: QualityReport; judge?: JudgeHistory }) {
  const r = q.router
  const right = sum(r.confusion.map((row, i) => row[i] ?? 0))
  const route = (name: string) => name.replaceAll('_', ' ')
  const runName = (key: string) => {
    const m = /^(\w+) \((.*)\)$/.exec(key) // "dev (mock)"
    return m && m[1] in DATASET_NAMES ? viewName(m[1] as Dataset, m[2]) : key
  }
  const faith = Object.entries(q.faithfulness)
  const scored = faith.filter(([, f]) => f.claims > 0)
  const template = faith.filter(([, f]) => f.claims === 0)
  return (
    <div className="cols">
      <section className="panel panel-pad col-wide" aria-labelledby="q-router">
        <div className="panel-head">
          <h3 id="q-router" className="h3">
            Question router
          </h3>
          <span className={`mono strong tone-${toneOf(r.accuracy)}`}>
            {right}/{r.questions} · {pct(r.accuracy)}
          </span>
          <span className="sub">Rows: expected route. Columns: where it went.</span>
        </div>
        <div className="table-scroll">
          <table className="heatmap">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Expected route</span>
                </th>
                {r.routes.map((name) => (
                  <th key={name} scope="col" title={route(name)}>
                    {route(name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {r.routes.map((name, i) => (
                <tr key={name}>
                  <th scope="row">{route(name)}</th>
                  {(r.confusion[i] ?? []).map((n, j) => {
                    const hit = i === j && n > 0
                    const miss = i !== j && n > 0
                    return (
                      <td
                        key={j}
                        className={`mono ${hit ? 'is-hit' : miss ? 'is-miss' : ''}`}
                        style={
                          hit
                            ? { background: `color-mix(in srgb, var(--indigo) ${Math.min(12 + n * 7, 70)}%, var(--surface))` }
                            : undefined
                        }
                      >
                        {n || ''}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {r.misroutes.length > 0 && (
          <div className="miss-callout">
            <span className="mono strong">{plural(r.misroutes.length, 'miss', 'misses')}</span>
            <ul>
              {r.misroutes.map((m) => (
                <li key={m}>{m.replace(' -> ', ' → ').replaceAll('_', ' ')}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="panel panel-pad col-narrow" aria-labelledby="q-faith">
        <h3 id="q-faith" className="h3">
          Are AI-written sentences backed by sources?
        </h3>
        {scored.map(([key, f]) => (
          <div key={key} className="faith-card">
            <span className="faith-kicker">{runName(key)}</span>
            <span className="faith-num mono">
              {f.supported}
              <small>/{f.claims}</small>
            </span>
            <span className="note">claims supported by their sources ({pct(f.faithfulness ?? 0)})</span>
            <Bar value={f.faithfulness ?? 0} tone="indigo" />
            <span className="small muted">
              First drafts rejected by the validator: {f.first_drafts_rejected} of {f.llm_sections}
            </span>
          </div>
        ))}
        {template.length > 0 && (
          <div className="stack">
            <span className="strong">{template.map(([key]) => runName(key)).join(' and ')}</span>
            <span className="note">
              No AI-written text in {template.length === 1 ? 'this run' : 'these runs'}. Use{' '}
              <code className="code">make eval-real</code> to score them with a model.
            </span>
          </div>
        )}
        <div className="faith-card">
          <span className="faith-kicker">AI judge (second opinion)</span>
          {judge ? (
            <>
              <span className="faith-num mono">
                {judge.verdicts.supported ?? 0}
                <small>/{judge.claims}</small>
              </span>
              <span className="note">
                claims the judge found supported; {judge.verdicts.unsupported ?? 0} unsupported,{' '}
                {judge.verdicts.contradicted ?? 0} contradicted
              </span>
              <Bar value={judge.claims ? (judge.verdicts.supported ?? 0) / judge.claims : 0} tone="indigo" />
              <span className="small muted">
                Judged by {judge.judges.join(', ')}; written by {judge.writers.join(', ')}.
                {judge.agreement_with_overlap !== null &&
                  ` Agrees with the word-overlap check on ${pct(judge.agreement_with_overlap)} of claims.`}
                {judge.self_judged && ' The judge is the same model as the writer.'}
              </span>
            </>
          ) : (
            <span className="note">
              Not run yet. Use <code className="code">make eval-judge</code>.
            </span>
          )}
        </div>
      </section>
    </div>
  )
}

function Proves({ note }: { note: EvalNote }) {
  return (
    <div className="cols">
      <section className="panel panel-pad col-half" aria-labelledby="proves">
        <h3 id="proves" className="h3 head-dot">
          <span className="dot is-good" aria-hidden="true" />
          What this proves
        </h3>
        {note.proves.map((line) => (
          <div key={line} className="prove-row">
            <span className="prove-icon" aria-hidden="true">
              <Check size={11} strokeWidth={3.4} />
            </span>
            <span>{line}</span>
          </div>
        ))}
      </section>
      <section className="panel panel-pad col-half" aria-labelledby="not-proves">
        <h3 id="not-proves" className="h3 head-dot">
          <span className="dot is-warn" aria-hidden="true" />
          What it does not prove yet
        </h3>
        {note.not_proves.map((item) => (
          <div key={item.title + item.detail} className="prove-row">
            <span className="prove-icon is-warn" aria-hidden="true">
              !
            </span>
            <div className="stack">
              {item.title && <span className="strong">{item.title}</span>}
              <span className="note">{item.detail}</span>
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}

// ---- the page ---------------------------------------------------------------------------

export function EvaluationsPage({ userId }: { userId: string }) {
  const [report, setReport] = useState<EvalReport | null>(null)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabId>(LINK_TAB ?? 'overview')
  const [viewKey, setViewKey] = useState('')

  useEffect(() => {
    let cancelled = false
    getEvaluations(userId)
      .then((r) => !cancelled && setReport(r))
      .catch((e) => {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 404) setMissing(true)
        else setError(errorMessage(e))
      })
    return () => {
      cancelled = true
    }
  }, [userId])

  const views = report ? viewsOf(report) : []
  const view = views.find((v) => v.key === viewKey) ?? views[0]
  const q = report?.quality
  const note = q ? noteOf(q) : null
  // Overview switches between runs; retrieval and detectors only between datasets
  const firstOfEach = views.filter((v, i) => views.findIndex((w) => w.data === v.data) === i)
  const options =
    tab === 'overview'
      ? views.map((v) => ({ key: v.key, label: v.label, on: v.key === view?.key }))
      : firstOfEach.map((v) => ({ key: v.key, label: DATASET_NAMES[v.data], on: v.data === view?.data }))
  const needsQuality = <p className="note">No quality report in this run. Run make eval again.</p>

  return (
    <div className="container">
      <div className="page-head">
        <div>
          {report && <span className="sub">Last run {dateTime(report.ran_at)} · scored by code, not by AI</span>}
          <h1 className="page-title">Evaluations</h1>
          <p className="lead">
            Every golden case, re-run on fresh data: the development set and a held-out set the rules were never tuned
            on.
          </p>
        </div>
        <div className="cmd-box">
          <span className="sub">Run in the project folder</span>
          <div className="cmd-list">
            <code className="code">make eval</code>
            <code className="code">make eval-break</code>
            <code className="code">make eval-real</code>
          </div>
        </div>
      </div>

      {error && <p className="note note-error">{error}</p>}
      {missing && (
        <div className="panel panel-pad">
          <p className="note">
            No scorecard yet. Run <code className="code">make eval</code> in the project folder, then reload this page.
          </p>
        </div>
      )}
      {!report && !missing && !error && <p className="note">Loading the last run…</p>}

      {report && view && (
        <>
          <Verdict views={views} quality={q} />

          <div className="tabs-row">
            <div role="tablist" aria-label="Evaluation sections" className="eval-tabs">
              {TABS.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  id={`eval-tab-${id}`}
                  aria-controls="eval-panel"
                  aria-selected={tab === id}
                  className="eval-tab"
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {WITH_DATASET.includes(tab) && (
              <div className="ds-switch">
                <span className="sub">Dataset</span>
                <div role="radiogroup" aria-label="Dataset" className="segmented">
                  {options.map((o) => (
                    <button key={o.key} type="button" role="radio" aria-checked={o.on} onClick={() => setViewKey(o.key)}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div role="tabpanel" id="eval-panel" aria-labelledby={`eval-tab-${tab}`} className="eval-panel">
            {tab === 'overview' && <Overview view={view} />}
            {tab === 'traps' && <Traps views={views} />}
            {tab === 'retrieval' && (q ? <Retrieval report={q.retrieval[view.data]} /> : needsQuality)}
            {tab === 'detectors' && (q ? <Detectors report={q.detectors[view.data]} note={note} /> : needsQuality)}
            {tab === 'router' && (q ? <RouterAndAI q={q} judge={report.judge} /> : needsQuality)}
            {tab === 'proves' && (note ? <Proves note={note} /> : needsQuality)}
          </div>
        </>
      )}
    </div>
  )
}
