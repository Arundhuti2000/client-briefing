# AI Usage

This prototype was built with AI assistance, the way I'd expect an AI enablement team to work: **I set the direction and made the decisions against the assignment; AI tools did most of the implementation; and every phase was tested, reviewed and committed before the next one started.**

## Tools

| Tool | Used for |
| --- | --- |
| **Claude (chat)** | Breaking down the assignment, drafting the build spec with me, reviewing screenshots and output, and writing phase briefs |
| **Claude Code** | Writing the code, tests, evaluation and most documentation, phase by phase, from the spec |
| **Claude Design** | UI mockups for the meeting queue, briefing workspace, Clients and Evaluations pages |
| **Gemini 3.5 Flash Lite, OpenRouter (Nemotron 3.5 Super VL, free)** | The models that write briefing text inside the app |

## How I worked

1. **Spec first.** I turned the assignment into a written spec (`SPEC.md`, drafted with Claude, then edited and rewritten by me as the build evolved) and a short set of project rules (`CLAUDE.md`), including: *"Never let the LLM produce a number,"* *"every tool is read-only and filters restricted data inside the query,"* and *"keep code simple and readable; I need to explain every part."*
2. **One phase at a time.** Data → unification → tools and search → orchestration and validation → UI → evaluation. Each phase was run, checked and committed before the next.
3. **Written briefs for every change in direction,** so each decision has a record. The full list is in `DECISIONS.md`.
4. **AI output treated like a teammate's pull request:** run it, read it, test it, and push back when it's wrong.

---

## Decisions, mapped to the assignment

| Assignment asks for | My decision | Why |
| --- | --- | --- |
| A **synthetic data pack** with aliases, duplicates, stale or conflicting statements, missing IDs and restricted records | Realistic raw sources: 11 deliberately messy CSV exports loaded through **staging tables**, plus emails (.eml), notes and briefings (.md) and news (.txt). Twelve planted traps, one per data condition | The first version stored documents as tidy JSON. Real data arrives as exports and files from different systems, and the brief flagged **structured data** as the area to prove. Loading raw, then cleaning, shows the actual data engineering |
| **Data engineering** | All cleaning and unification by rules, no LLM: alias resolution, duplicate merging, staleness and conflict detection, each written as a flag | These must be exact, repeatable and auditable. An LLM could quietly merge the wrong clients or invent a conflict |
| **Structured SQL/API tools, function contracts, error handling** | Read-only tools with Pydantic contracts and typed errors; **numbers only from SQL, never from the LLM** | A wrong number in front of a client is the costliest error; the safest LLM is one that never produces numbers |
| **RAG and search** | **Hybrid search required** (keyword + vector, merged with Reciprocal Rank Fusion), with access filtered before scoring | Exact names and paraphrases both matter in client data. The initial plan deferred vectors; I made them required, and measured keyword vs vector vs hybrid |
| **Routing, task decomposition, context engineering** | A fixed seven-section plan for the briefing; question routing for follow-ups; evidence bundles with IDs as the LLM's only context | A briefing always needs the same seven answers, so a fixed plan is safer than a free agent. I identified that routing only covered model fallback and asked for real question routing |
| **Agentic search, MCP** | A bounded tool-calling loop (max 3 steps) only for document questions; numbers questions answered by code; an MCP server exposing the same read-only tools | Agentic behavior only where it adds value, always bounded and validated. MCP lets any approved assistant reuse the tools under the same access rules |
| **Identity and controls** | Entitlement filtering inside every query; restricted data never counted or hinted at; sharing blocked until a person decides every conflict; full audit log | At a bank, even knowing a restricted deal exists can be sensitive, and conflicts need human judgment |
| **Reimagine the workflow; UX and actions** | A briefing workspace (Gather → Check → Read → Share) instead of a memo, built from my Claude Design mockups using only real data | The assignment explicitly asks not to assume a memo or chatbot. I required the UI to use the design's layout but **never its sample data** |
| **"Where the LLM is and isn't used"** | Every section labeled honestly: computed by code, AI-written (with the model name), or template (no AI) | The answer should be visible on screen, not just in slides |
| **Evaluation: prove it's safe to run** | Zero-tolerance safety checks; precision/recall on retrieval and detectors; router accuracy; real-model faithfulness; a test that proves the safety check can fail; CI on every push | A green scorecard alone isn't proof, so I asked for metrics that could expose weaknesses |
| Evaluation that isn't **circular** | A **held-out dataset of new, realistic clients** that was never used to change any rule, with results reported as they came out | The first held-out attempt was a renamed copy of the dev data. I rejected it, because it couldn't show generalization |
| Working within **real constraints** | One LLM call per briefing, a disk cache, a request budget, and a provider fallback chain (Gemini → OpenRouter → local model → template) | Free tiers allow about 20–50 requests a day, and the demo can't depend on one provider |

---

## Where I changed the AI's direction

| AI's plan | My call | Result |
| --- | --- | --- |
| Streamlit UI, recommended for speed | React + FastAPI | A real API layer, and a UI matching the workflow design |
| Documents as JSON, defended as matching the first spec | Realistic file formats and CSV staging | Ingestion that reflects real systems |
| Add vector search later | Required from the start | Hybrid search, measured against each method alone |
| Keep held-out data out of the app | Show every dataset in the app; score each separately | Reviewers can see all the data the evaluation uses |
| A held-out set that renamed the dev clients | Replace it with genuinely new clients and wording | A held-out result that actually tests generalization |
| Briefing text with internal IDs, ISO dates and repeated conflicts | A plain-English wording standard | A briefing a banker can scan in two minutes |
| Model fallback only, no question routing | Real question routing | Routing that sends numbers questions to code, not the LLM |
| Workspace and pages not yet built | Complete the workflow and the Clients and Evaluations pages | The full Check → Read → Share workflow |
| A model returning 503s | Switch to Flash Lite only | Reliable generation within the free tier |

## AI proposals I evaluated and accepted

- **Router design:** keyword rules first, then meaning matching with a local embedding model, then the LLM only as a tie-breaker. Cheapest and most predictable first.
- **Validator rule 6** (no internal IDs in text). The goal was mine; the AI proposed enforcing it in code, and I chose to keep it.
- **Held-out process:** fix round 1's findings, keep it as development data, and create a fresh round 2.
- **Never showing "1 restricted record was withheld"** from the design mockup, because it would leak that a restricted record exists.
- **A hard request budget,** and a fix so template-mode evaluation can't replay AI answers.

## Guardrails on AI-generated work

- `make test` and `make eval` after every phase; **259 tests** at submission.
- **Zero-tolerance checks** (restricted leakage, injection, red team) fail the run and the CI build.
- `make eval-break` proves the leakage check fails when the access filter is off.
- **No hand-typed results:** README numbers are generated from the evaluation run.
- **Held-out failures are reported, not fixed to pass:** round 2 still fails Trap detection (11/14) and Routing (6/8), explained in the README.

## What I verified myself

Ran each phase's commands and read the output; opened the generated data and questioned its format; read the briefings as a banker would, which is how I found the readability problem; clicked through the app as both users to confirm the analyst never sees the restricted deal; configured and tested the model providers; and ran the real-model evaluation.

