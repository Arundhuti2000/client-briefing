// Evaluations: the golden-set scorecard from the last `make eval` run (GET /evaluations).
// Counts and statuses only; the failure detail stays in the terminal.
import { useEffect, useState } from 'react'
import { ApiError, getEvaluations } from '../api'
import type { EvalReport } from '../api'
import { dateTime, errorMessage } from '../format'
import { Tag } from './common'

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
            Every golden case run against fresh data, scored by code. Restricted leakage and injection are
            zero-tolerance: one failure fails the run.
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
      {report?.runs.map((run) => (
        <section key={run.provider} className="panel" aria-labelledby={`eval-${run.provider}`}>
          <div className="panel-head" style={{ padding: '18px 22px 10px' }}>
            <h2 id={`eval-${run.provider}`} className="h2">
              Scorecard · {run.provider === 'mock' ? 'template (no AI)' : run.provider}
            </h2>
            <span className="sub">
              {run.cases} briefings · LLM: {run.models}
            </span>
          </div>
          <div className="table-scroll">
            <table className="grid-table">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>What it measures</th>
                  <th>Result</th>
                  <th>Target</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {run.checks.map((c) => (
                  <tr key={c.name}>
                    <td style={{ fontWeight: 600 }}>
                      {c.name}
                      {c.zero_tolerance && <span className="small muted"> · zero tolerance</span>}
                    </td>
                    <td>{c.measures}</td>
                    <td className="mono">{c.result}</td>
                    <td className="mono">{c.target}</td>
                    <td>
                      <Tag tone={c.passed ? 'good' : 'bad'}>{c.passed ? 'Pass' : 'Fail'}</Tag>
                    </td>
                  </tr>
                ))}
                <tr>
                  <td style={{ fontWeight: 600 }}>Latency</td>
                  <td>Time to build one briefing</td>
                  <td className="mono">{run.latency}</td>
                  <td className="mono">report</td>
                  <td />
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
                {run.traps.map((t) => (
                  <tr key={t.trap_id}>
                    <td className="mono" style={{ width: 48 }}>
                      {t.trap_id}
                    </td>
                    <td>{t.what}</td>
                    <td className="muted">{t.checks.join(', ')}</td>
                    <td>
                      <Tag tone={t.status === 'PASS' ? 'good' : t.status === 'FAIL' ? 'bad' : 'muted'}>
                        {t.status === 'PASS' ? 'Pass' : t.status === 'FAIL' ? 'Fail' : 'Not checked'}
                      </Tag>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  )
}
