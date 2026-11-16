// Shown before a briefing is generated: quick picks and how briefings are produced.
type Props = { onPick: (name: string) => void }

const QUICK_PICKS = ['NWC', 'Northwind Cap.', 'Helios', 'Arbor']

const STEPS = [
  ['1. Unify', 'Resolve the client across systems', 'Rules and fuzzy matching link aliases, merge duplicates and flag stale or conflicting facts. No LLM. Restricted records are filtered by your entitlements before anything is read.'],
  ['2. Retrieve and compute', 'Numbers from SQL, text from search', 'Metrics come from typed SQL tools and are formatted by code, never written by the model. Emails, notes and news are found with permission-aware hybrid search.'],
  ['3. Draft and verify', 'Cite every claim or drop it', 'One LLM call writes the narrative from the evidence. Code checks every citation and number before you see it, retries once, and otherwise shows the evidence itself.'],
]

export function Welcome({ onPick }: Props) {
  return (
    <>
      <div className="welcome">
        <span className="eyebrow">Meeting on 18 Nov 2026</span>
        <h1>Prepare a client briefing</h1>
        <p className="muted">
          Find a client above and generate a briefing. Try an alias to see how names are resolved:
        </p>
        <div className="quick-picks">
          {QUICK_PICKS.map((name) => (
            <button key={name} type="button" className="btn" onClick={() => onPick(name)}>
              {name}
            </button>
          ))}
        </div>
      </div>
      <section aria-label="How briefings are produced" className="steps">
        {STEPS.map(([eyebrow, title, text]) => (
          <div key={eyebrow} className="card step">
            <span className="eyebrow">{eyebrow}</span>
            <span className="strong">{title}</span>
            <span className="muted small">{text}</span>
          </div>
        ))}
      </section>
    </>
  )
}
