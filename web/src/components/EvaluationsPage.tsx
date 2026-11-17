// Evaluations: the last `make eval` (GET /evaluations). The pass/fail scorecard on the dev
// and held-out datasets side by side, then the quality metrics report and what it proves.
// Counts and statuses only; the failure detail stays in the terminal.
import { useEffect, useState } from 'react'
import { ApiError, getEvaluations } from '../api'
import type { EvalReport, EvalRun, QualityReport } from '../api'
import { dateTime, errorMessage } from '../format'
import { Tag } from './common'

const runName = (run: EvalRun) =>
  `${run.dataset === 'holdout' ? 'Holdout' : 'Dev'} · ${run.provider === 'mock' ? 'template' : run.provider}`
const pct = (n: number) => `${Math.round(n * 100)}%`
const pair = (dev?: number, hold?: number, as = (n: number) => n.toFixed(2)) =>
  `${dev === undefined ? '–' : as(dev)} | ${hold === undefined ? '–' : as(hold)}`

function Scorecards({ runs }: { runs: EvalRun[] }) {
  const first = runs[0]
  return (
    <section className="panel" aria-labelledby="eval-score">
      <div className="panel-head" style={{ padding: '18px 22px 10px' }}>
        <h2 id="eval-score" className="h2">
          Scorecard
        </h2>
        <span className="sub">{runs.map((r) => `${runName(r)}: ${r.cases} briefings`).join(' · ')}</span>
      </div>
      <div className="table-scroll">
        <table className="grid-table">
          <thead>
            <tr>
              <th>Check</th>
              <th>What it measures</th>
              {runs.map((r) => (
                <th key={runName(r)}>{runName(r)}</th>
              ))}
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {first.checks.map((c, i) => (
              <tr key={c.name}>
                <td style={{ fontWeight: 600 }}>
                  {c.name}
                  {c.zero_tolerance && <span className="small muted"> · zero tolerance</span>}
                </td>
                <td>{c.measures}</td>
                {runs.map((r) => {
                  const cell = r.checks[i]
                  return (
                    <td key={runName(r)} className="mono">
                      {cell ? (
                        <>
                          {cell.result} <Tag tone={cell.passed ? 'good' : 'bad'}>{cell.passed ? 'Pass' : 'Fail'}</Tag>
                        </>
                      ) : (
                        '–'
                      )}
                    </td>
                  )
                })}
                <td className="mono">{c.target}</td>
              </tr>
            ))}
            <tr>
              <td style={{ fontWeight: 600 }}>Latency</td>
              <td>Time to build one briefing</td>
              {runs.map((r) => (
                <td key={runName(r)} className="mono">
                  {r.latency}
                </td>
              ))}
              <td className="mono">report</td>
            </tr>
            <tr>
              <td style={{ fontWeight: 600 }}>Cost per briefing</td>
              <td>LLM requests, tokens, cache hits</td>
              {runs.map((r) => (
                <td key={runName(r)} className="mono">
                  {r.cost ? `${r.cost.requests} req · ${r.cost.tokens_in + r.cost.tokens_out} tok · ${r.cost.cache_hits} cached` : '–'}
                </td>
              ))}
              <td className="mono">report</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="panel-head" style={{ padding: '18px 22px 10px' }}>
        <h3 className="h3">Planted traps and the checks that cover them</h3>
      </div>
      <div className="table-scroll" style={{ paddingBottom: 8 }}>
        <table className="grid-table">
          <tbody>
            {first.traps.map((t, i) => (
              <tr key={t.trap_id}>
                <td className="mono" style={{ width: 48 }}>
                  {t.trap_id}
                </td>
                <td>{t.what}</td>
                <td className="muted">{t.checks.join(', ')}</td>
                {runs.map((r) => {
                  const status = r.traps[i]?.status
                  return (
                    <td key={runName(r)}>
                      <Tag tone={status === 'PASS' ? 'good' : status === 'FAIL' ? 'bad' : 'muted'}>
                        {runName(r).split(' · ')[0]}: {status === 'PASS' ? 'Pass' : status === 'FAIL' ? 'Fail' : 'Not checked'}
                      </Tag>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Quality({ q }: { q: QualityReport }) {
  const dev = q.retrieval.dev
  const hold = q.retrieval.holdout
  const metrics: [keyof typeof dev.methods.bm25, string][] = [
    ['precision@5', 'Precision@5'],
    ['recall@5', 'Recall@5'],
    ['mrr', 'MRR'],
    ['ndcg@5', 'nDCG@5'],
  ]
  return (
    <>
      <section className="panel panel-pad" aria-labelledby="q-retrieval">
        <div className="panel-head">
          <h2 id="q-retrieval" className="h2">
            Retrieval
          </h2>
          <span className="sub">
            Top 5 documents, entitlement filtering on · dev {dev.scored} questions | holdout {hold?.scored ?? 0} questions
          </span>
        </div>
        <div className="table-scroll">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Method (dev | holdout)</th>
                {metrics.map(([, label]) => (
                  <th key={label}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(['bm25', 'vector', 'hybrid'] as const).map((m) => (
                <tr key={m}>
                  <td style={{ fontWeight: 600 }}>{m === 'bm25' ? 'BM25 only' : m === 'vector' ? 'Vector only' : 'Hybrid (RRF)'}</td>
                  {metrics.map(([key]) => (
                    <td key={key} className="mono">
                      {pair(dev.methods[m][key], hold?.methods[m][key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">
          Restricted documents retrieved for a user without access: {pair(dev.restricted_retrieved, hold?.restricted_retrieved, String)}
        </p>
      </section>

      <section className="panel panel-pad" aria-labelledby="q-detectors">
        <div className="panel-head">
          <h2 id="q-detectors" className="h2">
            Detectors on generated perturbations
          </h2>
          <span className="sub">
            {q.detectors.dev.cases} dev | {q.detectors.holdout?.cases ?? 0} holdout cases: aliases, typos, suffixes, case,
            look-alikes, true conflicts and near-misses
          </span>
        </div>
        <div className="table-scroll">
          <table className="grid-table">
            <thead>
              <tr>
                <th>Detector (dev | holdout)</th>
                <th>Cases</th>
                <th>Precision</th>
                <th>Recall</th>
                <th>F1</th>
                <th>Mistakes</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(q.detectors.dev.detectors).map(([name, d]) => {
                const h = q.detectors.holdout?.detectors[name]
                const mistakes = [
                  ...d.false_positives.map((x) => `FP · ${x}`),
                  ...d.false_negatives.map((x) => `FN · ${x}`),
                  ...(h?.false_positives ?? []).map((x) => `FP · ${x}`),
                  ...(h?.false_negatives ?? []).map((x) => `FN · ${x}`),
                ]
                return (
                  <tr key={name}>
                    <td style={{ fontWeight: 600 }}>{name}</td>
                    <td className="mono">{pair(d.cases, h?.cases, String)}</td>
                    <td className="mono">{pair(d.precision, h?.precision)}</td>
                    <td className="mono">{pair(d.recall, h?.recall)}</td>
                    <td className="mono">{pair(d.f1, h?.f1)}</td>
                    <td>
                      {mistakes.length === 0 ? (
                        <span className="muted">None</span>
                      ) : (
                        <details>
                          <summary className="small">{mistakes.length} cases</summary>
                          <ul className="bullets bullets-compact" style={{ fontSize: 12 }}>
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
        </div>
      </section>

      <div className="cols">
        <section className="panel panel-pad col-wide" aria-labelledby="q-router">
          <div className="panel-head">
            <h2 id="q-router" className="h2">
              Router
            </h2>
            <span className="sub">
              {pct(q.router.accuracy)} of {q.router.questions} labelled questions · rows: expected, columns: routed to
            </span>
          </div>
          <div className="table-scroll">
            <table className="grid-table">
              <thead>
                <tr>
                  <th />
                  {q.router.routes.map((r) => (
                    <th key={r} className="small">
                      {r.replace('_', ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {q.router.routes.map((expected, i) => (
                  <tr key={expected}>
                    <td className="small" style={{ fontWeight: 600 }}>
                      {expected.replace('_', ' ')}
                    </td>
                    {q.router.confusion[i].map((n, j) => (
                      <td key={j} className="mono" style={{ fontWeight: i === j ? 700 : 400, color: n && i !== j ? 'var(--bad)' : undefined }}>
                        {n || ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {q.router.misroutes.map((m) => (
            <p key={m} className="note">
              {m}
            </p>
          ))}
        </section>

        <section className="panel panel-pad col-narrow" aria-labelledby="q-faith">
          <h2 id="q-faith" className="h2">
            Faithfulness of AI-written bullets
          </h2>
          {Object.entries(q.faithfulness).map(([name, f]) => (
            <div key={name} className="stack" style={{ gap: 4 }}>
              <span style={{ fontWeight: 600 }}>{name}</span>
              <span className="note">
                {f.claims
                  ? `${f.supported} of ${f.claims} claims supported by their sources (${pct(f.faithfulness ?? 0)}); first drafts rejected by the validator: ${f.first_drafts_rejected} of ${f.llm_sections}`
                  : 'No AI-written bullets: template mode. Run make eval-real.'}
              </span>
            </div>
          ))}
        </section>
      </div>

      <section className="panel panel-pad" aria-labelledby="q-note" style={{ background: 'var(--warn-panel)' }}>
        <h2 id="q-note" className="h2" style={{ color: 'var(--warn-ink)' }}>
          What this does and doesn't prove
        </h2>
        <ul className="bullets bullets-compact" style={{ color: 'var(--warn-ink-2)' }}>
          {q.note.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
    </>
  )
}

export function EvaluationsPage({ userId }: { userId: string }) {
  const [report, setReport] = useState<EvalReport | null>(null)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  return (
    <div className="container">
      <div className="page-head">
        <div>
          <h1 className="page-title">Evaluations</h1>
          <p className="lead">
            Every golden case run against fresh data, scored by code, on the development data and on a held-out dataset
            the rules were never tuned on. Restricted leakage, injection and the red team are zero-tolerance.
          </p>
          {report && <span className="sub">Last run {dateTime(report.ran_at)}</span>}
        </div>
      </div>
      {error && <p className="note note-error">{error}</p>}
      {missing && (
        <div className="panel panel-pad">
          <p className="note">
            No scorecard yet. Run <code className="mono">make eval</code> in the project folder, then reload this page.
          </p>
        </div>
      )}
      {report && <Scorecards runs={[...report.runs, ...(report.holdout_runs ?? [])]} />}
      {report?.quality && <Quality q={report.quality} />}
    </div>
  )
}
