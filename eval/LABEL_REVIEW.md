# Retrieval label pre-review

The retrieval metrics (P@5, R@5, MRR, nDCG@5) depend on labels written with AI assistance: for each question, the
documents that answer it. This file is a pre-review for a person to decide on; **no label file was
changed** (`eval/retrieval_set.yaml`, `eval/dev2/retrieval_set.yaml`, `eval/holdout/retrieval_set.yaml`).

For every question it shows the labelled relevant documents and the top 5 results of the hybrid
search the app uses (BM25 + vectors, merged with RRF), each with its title and date. The question
lists and top 5 come from `python -m eval.label_review`, run on fresh copies of each dataset (the dev
data includes the red-team documents, as in `make eval`). The notes come from an automated pre-review (Claude Code), for the developer to review;
human review is pending.

Kinds of note:
- **Missing**: a document that answers the question is not labelled.
- **Questionable**: a labelled document doesn't actually answer the question.
- **Borderline**: a judgment call; the current label is defensible.
- **No answer in any document**: the question can't be answered from documents as written.
- **Retrieval miss**: the label looks right; search ranks it below 5 (a search limit, not a label problem).

## Summary of notes

| Dataset # | Question | Kind | Note |
| --- | --- | --- | --- |
| Dev #1 | What did the client commit to on FX hedging? | Questionable | `note_003` is a client ask to *explore* FX hedging, not a commitment; only `note_001` says the client committed ($50M by Q4). Consider dropping `note_003`. |
| Dev #6 | What do they want to know about a liquidity sweep? | Missing | `email_901` (Priya asks for the liquidity sweep account documents) and `note_901` (Priya asked for a summary of the liquidity sweep options) are about the sweep but unlabelled. They are the red-team documents, added to the dev data after these labels were written; they carry injection lines, but as sources they are relevant. Consider adding both. |
| Dev #9 | Do they want to upsize the credit facility? | Borderline | `brief_001` lists "Size a possible credit facility upsize" as the bank's priority, not the client's request. The current labels look right. |
| Dev #10 | What did Priya Shah ask for? | Missing | Priya asked for more than the labels show: `email_001` (the July call agenda a week ahead), `email_003` (a treasury management workshop and a liquidity sweep), `email_901` and `note_901` (liquidity sweep documents and options). Consider adding all four. |
| Dev #11 | What are their plans for European credit funds? | Missing | `email_005` says "Our first European credit fund closed in October" and is unlabelled; consider adding it. `research_001` is labelled but ranked below 5: a retrieval miss, not a label problem. |
| Dev #12 | Did they close a new fund? | Missing | `email_005` also says the first European credit fund closed in October; consider adding it. |
| Dev #18 | How large is the planned green bond? | Questionable | `research_002` and `brief_003` mention green bonds but give no size; only `note_005` ($500M) answers "how large". Consider dropping the other two. |
| Dev #26 | Why are ACH payment files being rejected? | Borderline | `email_007` says exceptions are still happening but not why; `note_006` gives the cause (the September file format change). |
| Dev #27 | When will the ACH file format be fixed? | No answer in any document | No document gives a fix date: `email_007` asks the bank to confirm it and `note_006` asks for a firm date. The labels are the closest documents; decide whether this question should expect nothing. |
| Dev 2 #6 | Which suppliers would use supply chain finance? | Questionable | `research_201` is a generic sector note about supplier finance, not this client's suppliers; `email_201` (the new CFO asks for the supply chain finance proposal and the timeline for onboarding "our produce suppliers") is unlabelled. Consider swapping them. |
| Dev 2 #7 | How leveraged is Harbor & Pine? | Retrieval miss | The label looks right (`research_201` gives net leverage of 1.6x), but search ranks it below 5. |
| Dev 2 #12 | What is Project Merlin? | Retrieval miss | The label looks right: `research_212` is the credit view on the same AeroParts deal, but it never says "Project Merlin", so search misses it. |
| Holdout #2 | When does the Mexico plant start production? | Questionable | Only `note_301` gives the start (production starts in the second quarter of 2027). `news_301` (the plant will be built) and `research_301` (a sector note) don't say when; consider dropping them. |
| Holdout #5 | Why are payments to Mexican suppliers failing? | No answer in any document | `email_302` only says payments are still being rejected. The cause (a missing purpose code) is in the service-issues table, not in any document, so document search can't answer this question. |
| Holdout #10 | How big was the growth round? | Questionable | Only `news_311` gives the size ($90 million); `note_311` says a round is being raised but not how big. Consider dropping `note_311`. |

Every other question looked right: its labelled documents answer it, and no unlabelled document in the top 5 does.

## Dev (`eval/retrieval_set.yaml`)

### 1. What did the client commit to on FX hedging?  (C001, as u2)
- Labelled relevant: `note_001`, `note_003`
- Hybrid top 5:
  1. `note_001` (labelled) Quarterly review with NWC (2026-09-15)
  2. `note_003` (labelled) Annual review with Northwind Capital Partners (2026-01-22)
  3. `research_001` Sector note: asset managers expanding into Europe (2026-08-12)
  4. `brief_001` Prior briefing: Northwind Capital Partners (2026-03-10)
  5. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, questionable):** `note_003` is a client ask to *explore* FX hedging, not a commitment; only `note_001` says the client committed ($50M by Q4). Consider dropping `note_003`.

### 2. Who said Dana Lee is the CFO?  (C001, as u2)
- Labelled relevant: `email_001`
- Hybrid top 5:
  1. `note_001` Quarterly review with NWC (2026-09-15)
  2. `email_001` (labelled) July call agenda (2026-06-10)
  3. `news_001` Northwind Capital Partners closes first European credit fund at $1.2B (2026-10-08)
- Check: every labelled doc is in the top 5.

### 3. When is the July call and who joins it?  (C001, as u2)
- Labelled relevant: `email_001`
- Hybrid top 5:
  1. `email_001` (labelled) July call agenda (2026-06-10)
  2. `note_002` Call with Priya Shah, Northwind Cap. (2026-05-20)
  3. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
- Check: every labelled doc is in the top 5.

### 4. Is there an updated cash forecast for Q4?  (C001, as u2)
- Labelled relevant: `email_002`
- Hybrid top 5:
  1. `email_002` (labelled) Updated Q4 cash forecast (2026-10-02)
  2. `note_001` Quarterly review with NWC (2026-09-15)
  3. `note_003` Annual review with Northwind Capital Partners (2026-01-22)
  4. `email_004` KYC refresh due by December 15 (2026-08-05)
  5. `email_001` July call agenda (2026-06-10)
- Check: every labelled doc is in the top 5.

### 5. Did the client ask for a treasury management workshop?  (C001, as u2)
- Labelled relevant: `email_003`
- Hybrid top 5:
  1. `email_003` (labelled) Treasury management workshop (2026-10-22)
  2. `email_005` Agenda for our November meeting (2026-10-30)
  3. `note_001` Quarterly review with NWC (2026-09-15)
  4. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
  5. `email_002` Updated Q4 cash forecast (2026-10-02)
- Check: every labelled doc is in the top 5.

### 6. What do they want to know about a liquidity sweep?  (C001, as u2)
- Labelled relevant: `email_003`
- Hybrid top 5:
  1. `email_901` Sweep account documents (2026-11-02)
  2. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
  3. `email_003` (labelled) Treasury management workshop (2026-10-22)
  4. `note_001` Quarterly review with NWC (2026-09-15)
  5. `brief_001` Prior briefing: Northwind Capital Partners (2026-03-10)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, missing):** `email_901` (Priya asks for the liquidity sweep account documents) and `note_901` (Priya asked for a summary of the liquidity sweep options) are about the sweep but unlabelled. They are the red-team documents, added to the dev data after these labels were written; they carry injection lines, but as sources they are relevant. Consider adding both.

### 7. When are the KYC documents due?  (C001, as u2)
- Labelled relevant: `email_004`
- Hybrid top 5:
  1. `email_004` (labelled) KYC refresh due by December 15 (2026-08-05)
  2. `email_901` Sweep account documents (2026-11-02)
  3. `email_001` July call agenda (2026-06-10)
  4. `email_003` Treasury management workshop (2026-10-22)
  5. `note_002` Call with Priya Shah, Northwind Cap. (2026-05-20)
- Check: every labelled doc is in the top 5.

### 8. What does the client want to cover at the November meeting?  (C001, as u2)
- Labelled relevant: `email_005`
- Hybrid top 5:
  1. `email_005` (labelled) Agenda for our November meeting (2026-10-30)
  2. `email_002` Updated Q4 cash forecast (2026-10-02)
  3. `email_901` Sweep account documents (2026-11-02)
  4. `email_001` July call agenda (2026-06-10)
  5. `email_003` Treasury management workshop (2026-10-22)
- Check: every labelled doc is in the top 5.

### 9. Do they want to upsize the credit facility?  (C001, as u2)
- Labelled relevant: `note_002`, `note_001`, `email_005`
- Hybrid top 5:
  1. `email_005` (labelled) Agenda for our November meeting (2026-10-30)
  2. `note_002` (labelled) Call with Priya Shah, Northwind Cap. (2026-05-20)
  3. `email_001` July call agenda (2026-06-10)
  4. `note_001` (labelled) Quarterly review with NWC (2026-09-15)
  5. `news_901` Northwind Capital Partners hires a head of private credit (2026-11-05)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, borderline):** `brief_001` lists "Size a possible credit facility upsize" as the bank's priority, not the client's request. The current labels look right.

### 10. What did Priya Shah ask for?  (C001, as u2)
- Labelled relevant: `note_002`, `note_001`
- Hybrid top 5:
  1. `note_002` (labelled) Call with Priya Shah, Northwind Cap. (2026-05-20)
  2. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
  3. `note_001` (labelled) Quarterly review with NWC (2026-09-15)
  4. `email_001` July call agenda (2026-06-10)
  5. `email_003` Treasury management workshop (2026-10-22)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, missing):** Priya asked for more than the labels show: `email_001` (the July call agenda a week ahead), `email_003` (a treasury management workshop and a liquidity sweep), `email_901` and `note_901` (liquidity sweep documents and options). Consider adding all four.

### 11. What are their plans for European credit funds?  (C001, as u2)
- Labelled relevant: `note_003`, `news_001`, `research_001`
- Hybrid top 5:
  1. `note_003` (labelled) Annual review with Northwind Capital Partners (2026-01-22)
  2. `email_005` Agenda for our November meeting (2026-10-30)
  3. `note_001` Quarterly review with NWC (2026-09-15)
  4. `news_001` (labelled) Northwind Capital Partners closes first European credit fund at $1.2B (2026-10-08)
  5. `note_002` Call with Priya Shah, Northwind Cap. (2026-05-20)
- Check: labelled docs not in the top 5: research_001.
- **Note (pre-review, missing):** `email_005` says "Our first European credit fund closed in October" and is unlabelled; consider adding it. `research_001` is labelled but ranked below 5: a retrieval miss, not a label problem.

### 12. Did they close a new fund?  (C001, as u2)
- Labelled relevant: `news_001`
- Hybrid top 5:
  1. `news_001` (labelled) Northwind Capital Partners closes first European credit fund at $1.2B (2026-10-08)
  2. `email_005` Agenda for our November meeting (2026-10-30)
  3. `note_001` Quarterly review with NWC (2026-09-15)
  4. `note_003` Annual review with Northwind Capital Partners (2026-01-22)
  5. `note_002` Call with Priya Shah, Northwind Cap. (2026-05-20)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, missing):** `email_005` also says the first European credit fund closed in October; consider adding it.

### 13. Are they opening an office in London?  (C001, as u2)
- Labelled relevant: `news_002`
- Hybrid top 5:
  1. `news_002` (labelled) Northwind Capital to open London office (2026-10-27)
  2. `email_003` Treasury management workshop (2026-10-22)
  3. `news_901` Northwind Capital Partners hires a head of private credit (2026-11-05)
  4. `email_005` Agenda for our November meeting (2026-10-30)
- Check: every labelled doc is in the top 5.

### 14. What revenue did the last briefing report?  (C001, as u2)
- Labelled relevant: `brief_001`
- Hybrid top 5:
  1. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
  2. `brief_001` (labelled) Prior briefing: Northwind Capital Partners (2026-03-10)
  3. `email_003` Treasury management workshop (2026-10-22)
  4. `note_001` Quarterly review with NWC (2026-09-15)
  5. `note_003` Annual review with Northwind Capital Partners (2026-01-22)
- Check: every labelled doc is in the top 5.

### 15. How are asset managers using FX hedging in Europe?  (C001, as u2)
- Labelled relevant: `research_001`
- Hybrid top 5:
  1. `research_001` (labelled) Sector note: asset managers expanding into Europe (2026-08-12)
  2. `brief_001` Prior briefing: Northwind Capital Partners (2026-03-10)
  3. `note_003` Annual review with Northwind Capital Partners (2026-01-22)
  4. `note_001` Quarterly review with NWC (2026-09-15)
  5. `email_003` Treasury management workshop (2026-10-22)
- Check: every labelled doc is in the top 5.

### 16. What was discussed at the quarterly review in September?  (C001, as u2)
- Labelled relevant: `note_001`
- Hybrid top 5:
  1. `note_001` (labelled) Quarterly review with NWC (2026-09-15)
  2. `note_003` Annual review with Northwind Capital Partners (2026-01-22)
  3. `email_001` July call agenda (2026-06-10)
  4. `email_005` Agenda for our November meeting (2026-10-30)
  5. `note_901` Call with Northwind Cap. about next steps (2026-09-10)
- Check: every labelled doc is in the top 5.

### 17. Why do supplier payments miss the same-day window?  (C002, as u2)
- Labelled relevant: `email_006`
- Hybrid top 5:
  1. `email_006` (labelled) Payment cut-off times (2026-10-12)
  2. `brief_003` Prior briefing: Helios Energy Group (2026-07-01)
- Check: every labelled doc is in the top 5.

### 18. How large is the planned green bond?  (C002, as u2)
- Labelled relevant: `note_005`, `research_002`, `brief_003`
- Hybrid top 5:
  1. `note_005` (labelled) Meeting with Helios finance and treasury (2026-10-05)
  2. `research_002` (labelled) Utilities outlook (2026-09-01)
  3. `brief_003` (labelled) Prior briefing: Helios Energy Group (2026-07-01)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, questionable):** `research_002` and `brief_003` mention green bonds but give no size; only `note_005` ($500M) answers "how large". Consider dropping the other two.

### 19. What did Marcus Webb discuss with us in October?  (C002, as u2)
- Labelled relevant: `note_005`
- Hybrid top 5:
  1. `note_005` (labelled) Meeting with Helios finance and treasury (2026-10-05)
- Check: every labelled doc is in the top 5.

### 20. Is the board considering an acquisition?  (C002, as u1)
- Labelled relevant: `note_004`
- Hybrid top 5:
  1. `note_004` (labelled) Confidential - Project Sunrise (2026-09-30)
- Check: every labelled doc is in the top 5.

### 21. What is Project Sunrise?  (C002, as u1)
- Labelled relevant: `note_004`
- Hybrid top 5:
  1. `note_004` (labelled) Confidential - Project Sunrise (2026-09-30)
  2. `brief_003` Prior briefing: Helios Energy Group (2026-07-01)
  3. `news_004` Helios Energy posts record solar output (2026-10-18)
- Check: every labelled doc is in the top 5.

### 22. Is the board considering an acquisition?  (C002, as u2)
- Labelled relevant: none (nothing should be found)
- Hybrid top 5:
  (nothing returned)
- Check: every labelled doc is in the top 5.

### 23. How did Helios do on solar output?  (C002, as u2)
- Labelled relevant: `news_004`
- Hybrid top 5:
  1. `news_004` (labelled) Helios Energy posts record solar output (2026-10-18)
  2. `brief_003` Prior briefing: Helios Energy Group (2026-07-01)
  3. `note_005` Meeting with Helios finance and treasury (2026-10-05)
  4. `research_002` Utilities outlook (2026-09-01)
- Check: every labelled doc is in the top 5.

### 24. What were the focus areas in the last Helios briefing?  (C002, as u2)
- Labelled relevant: `brief_003`
- Hybrid top 5:
  1. `brief_003` (labelled) Prior briefing: Helios Energy Group (2026-07-01)
  2. `news_004` Helios Energy posts record solar output (2026-10-18)
  3. `note_005` Meeting with Helios finance and treasury (2026-10-05)
  4. `research_002` Utilities outlook (2026-09-01)
- Check: every labelled doc is in the top 5.

### 25. Can renewables be funded with green bonds?  (C002, as u2)
- Labelled relevant: `research_002`, `note_005`
- Hybrid top 5:
  1. `research_002` (labelled) Utilities outlook (2026-09-01)
  2. `note_005` (labelled) Meeting with Helios finance and treasury (2026-10-05)
  3. `brief_003` Prior briefing: Helios Energy Group (2026-07-01)
  4. `email_006` Payment cut-off times (2026-10-12)
  5. `news_004` Helios Energy posts record solar output (2026-10-18)
- Check: every labelled doc is in the top 5.

### 26. Why are ACH payment files being rejected?  (C003, as u2)
- Labelled relevant: `note_006`, `email_007`
- Hybrid top 5:
  1. `note_006` (labelled) Call with Ben Carter, AHS (2026-10-01)
  2. `email_007` (labelled) ACH file format fix date (2026-10-20)
  3. `research_003` Healthcare providers note (2026-08-30)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, borderline):** `email_007` says exceptions are still happening but not why; `note_006` gives the cause (the September file format change).

### 27. When will the ACH file format be fixed?  (C003, as u2)
- Labelled relevant: `email_007`, `note_006`
- Hybrid top 5:
  1. `email_007` (labelled) ACH file format fix date (2026-10-20)
  2. `note_006` (labelled) Call with Ben Carter, AHS (2026-10-01)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, no answer in any document):** No document gives a fix date: `email_007` asks the bank to confirm it and `note_006` asks for a firm date. The labels are the closest documents; decide whether this question should expect nothing.

### 28. Is Arbor Health opening new clinics?  (C003, as u2)
- Labelled relevant: `news_006`
- Hybrid top 5:
  1. `news_006` (labelled) Arbor Health Systems opens two Ohio clinics (2026-09-20)
  2. `research_003` Healthcare providers note (2026-08-30)
  3. `brief_002` Prior briefing: Arbor Health Systems (2026-06-15)
- Check: every labelled doc is in the top 5.

### 29. Who is the day-to-day treasury contact?  (C003, as u2)
- Labelled relevant: `brief_002`, `note_006`
- Hybrid top 5:
  1. `brief_002` (labelled) Prior briefing: Arbor Health Systems (2026-06-15)
  2. `note_006` (labelled) Call with Ben Carter, AHS (2026-10-01)
- Check: every labelled doc is in the top 5.

### 30. Are hospital systems consolidating their banking?  (C003, as u2)
- Labelled relevant: `research_003`
- Hybrid top 5:
  1. `research_003` (labelled) Healthcare providers note (2026-08-30)
  2. `news_006` Arbor Health Systems opens two Ohio clinics (2026-09-20)
  3. `brief_002` Prior briefing: Arbor Health Systems (2026-06-15)
- Check: every labelled doc is in the top 5.

## Dev 2 (`eval/dev2/retrieval_set.yaml`)

### 1. Who is Harbor & Pine's new CFO?  (C201, as u2)
- Labelled relevant: `email_201`, `news_202`
- Hybrid top 5:
  1. `email_201` (labelled) Introduction - new CFO at Harbor & Pine (2026-10-20)
  2. `news_202` (labelled) Grocer Harbor & Pine names new finance chief (2026-11-02)
  3. `news_201` Harbor & Pine to open 12 stores in upstate New York (2026-10-07)
  4. `note_201` Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
  5. `research_201` Grocery: regional chains grow stores as margins tighten (2026-08-12)
- Check: every labelled doc is in the top 5.

### 2. How many stores are they opening in upstate New York?  (C201, as u2)
- Labelled relevant: `note_201`, `news_201`
- Hybrid top 5:
  1. `news_201` (labelled) Harbor & Pine to open 12 stores in upstate New York (2026-10-07)
  2. `note_201` (labelled) Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
  3. `email_202` RE: Merchant services pricing (2026-10-16)
  4. `news_202` Grocer Harbor & Pine names new finance chief (2026-11-02)
  5. `research_201` Grocery: regional chains grow stores as margins tighten (2026-08-12)
- Check: every labelled doc is in the top 5.

### 3. Why did they stay with their current card processor?  (C201, as u2)
- Labelled relevant: `email_202`
- Hybrid top 5:
  1. `email_202` (labelled) RE: Merchant services pricing (2026-10-16)
  2. `note_201` Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
  3. `brief_201` Account plan update: Harbor & Pine Foods (2026-10-26)
- Check: every labelled doc is in the top 5.

### 4. When will we get the updated W-9?  (C201, as u2)
- Labelled relevant: `email_203`
- Hybrid top 5:
  1. `email_203` (labelled) W-9 request (2026-08-27)
  2. `news_201` Harbor & Pine to open 12 stores in upstate New York (2026-10-07)
  3. `note_201` Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
- Check: every labelled doc is in the top 5.

### 5. What revenue did the October account plan report?  (C201, as u2)
- Labelled relevant: `brief_201`
- Hybrid top 5:
  1. `brief_201` (labelled) Account plan update: Harbor & Pine Foods (2026-10-26)
  2. `email_202` RE: Merchant services pricing (2026-10-16)
  3. `email_201` Introduction - new CFO at Harbor & Pine (2026-10-20)
  4. `email_203` W-9 request (2026-08-27)
  5. `note_201` Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
- Check: every labelled doc is in the top 5.

### 6. Which suppliers would use supply chain finance?  (C201, as u2)
- Labelled relevant: `note_201`, `brief_201`, `research_201`
- Hybrid top 5:
  1. `email_201` Introduction - new CFO at Harbor & Pine (2026-10-20)
  2. `research_201` (labelled) Grocery: regional chains grow stores as margins tighten (2026-08-12)
  3. `brief_201` (labelled) Account plan update: Harbor & Pine Foods (2026-10-26)
  4. `email_202` RE: Merchant services pricing (2026-10-16)
  5. `note_201` (labelled) Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, questionable):** `research_201` is a generic sector note about supplier finance, not this client's suppliers; `email_201` (the new CFO asks for the supply chain finance proposal and the timeline for onboarding "our produce suppliers") is unlabelled. Consider swapping them.

### 7. How leveraged is Harbor & Pine?  (C201, as u2)
- Labelled relevant: `research_201`
- Hybrid top 5:
  1. `email_201` Introduction - new CFO at Harbor & Pine (2026-10-20)
  2. `news_202` Grocer Harbor & Pine names new finance chief (2026-11-02)
  3. `brief_201` Account plan update: Harbor & Pine Foods (2026-10-26)
  4. `news_201` Harbor & Pine to open 12 stores in upstate New York (2026-10-07)
  5. `note_201` Quarterly review - Harbor & Pine Foods, Portland HQ (2026-09-24)
- Check: labelled docs not in the top 5: research_201.
- **Note (pre-review, retrieval miss):** The label looks right (`research_201` gives net leverage of 1.6x), but search ranks it below 5.

### 8. How much of their dollar purchases do they want to hedge?  (C202, as u2)
- Labelled relevant: `note_211`
- Hybrid top 5:
  1. `note_211` (labelled) Treasury catch-up with Kestrel Aviation, Stansted (2026-07-28)
- Check: every labelled doc is in the top 5.

### 9. When does the second Stansted hangar open?  (C202, as u2)
- Labelled relevant: `note_211`
- Hybrid top 5:
  1. `note_211` (labelled) Treasury catch-up with Kestrel Aviation, Stansted (2026-07-28)
  2. `email_211` Forward pricing and hangar visit (2026-11-05)
  3. `research_211` Aircraft maintenance: hangar space is the constraint (2026-09-10)
  4. `news_211` Kestrel Aviation wins Northlink maintenance contract (2026-10-14)
- Check: every labelled doc is in the top 5.

### 10. When is the hangar site visit?  (C202, as u2)
- Labelled relevant: `email_211`
- Hybrid top 5:
  1. `email_211` (labelled) Forward pricing and hangar visit (2026-11-05)
  2. `research_211` Aircraft maintenance: hangar space is the constraint (2026-09-10)
  3. `note_211` Treasury catch-up with Kestrel Aviation, Stansted (2026-07-28)
- Check: every labelled doc is in the top 5.

### 11. What maintenance contract did Kestrel win?  (C202, as u2)
- Labelled relevant: `news_211`
- Hybrid top 5:
  1. `news_211` (labelled) Kestrel Aviation wins Northlink maintenance contract (2026-10-14)
  2. `note_211` Treasury catch-up with Kestrel Aviation, Stansted (2026-07-28)
  3. `email_211` Forward pricing and hangar visit (2026-11-05)
  4. `research_211` Aircraft maintenance: hangar space is the constraint (2026-09-10)
- Check: every labelled doc is in the top 5.

### 12. What is Project Merlin?  (C202, as u1)
- Labelled relevant: `note_212`, `research_212`
- Hybrid top 5:
  1. `note_212` (labelled) Strictly confidential - Project Merlin (2026-10-29)
- Check: labelled docs not in the top 5: research_212.
- **Note (pre-review, retrieval miss):** The label looks right: `research_212` is the credit view on the same AeroParts deal, but it never says "Project Merlin", so search misses it.

### 13. What is Project Merlin?  (C202, as u2)
- Labelled relevant: none (nothing should be found)
- Hybrid top 5:
  (nothing returned)
- Check: every labelled doc is in the top 5.

### 14. How many supplier invoices does Copperleaf process a month?  (C203, as u2)
- Labelled relevant: `note_221`
- Hybrid top 5:
  1. `note_221` (labelled) Introductory meeting: Copperleaf Dental Partners, Columbus (2026-10-08)
  2. `news_221` Copperleaf Dental Partners buys three Indiana practices (2026-09-29)
  3. `email_221` Payables portal follow-up (2026-11-03)
- Check: every labelled doc is in the top 5.

### 15. Which references did Jenna Liu ask for?  (C203, as u2)
- Labelled relevant: `email_221`
- Hybrid top 5:
  1. `note_221` Introductory meeting: Copperleaf Dental Partners, Columbus (2026-10-08)
  2. `email_221` (labelled) Payables portal follow-up (2026-11-03)
- Check: every labelled doc is in the top 5.

## Holdout (`eval/holdout/retrieval_set.yaml`)

### 1. How much of their US invoices did they want to finance?  (C301, as u2)
- Labelled relevant: `note_301`
- Hybrid top 5:
  1. `note_301` (labelled) Plant visit - Vossberg, Stuttgart (2026-09-17)
  2. `email_301` Vossberg numbers before the plant visit (2026-08-04)
  3. `research_301` German auto suppliers move production closer to US customers (2026-09-03)
  4. `email_302` Hedging proposal (2026-11-02)
- Check: every labelled doc is in the top 5.

### 2. When does the Mexico plant start production?  (C301, as u2)
- Labelled relevant: `note_301`, `news_301`, `research_301`
- Hybrid top 5:
  1. `note_301` (labelled) Plant visit - Vossberg, Stuttgart (2026-09-17)
  2. `research_301` (labelled) German auto suppliers move production closer to US customers (2026-09-03)
  3. `email_301` Vossberg numbers before the plant visit (2026-08-04)
- Check: labelled docs not in the top 5: news_301.
- **Note (pre-review, questionable):** Only `note_301` gives the start (production starts in the second quarter of 2027). `news_301` (the plant will be built) and `research_301` (a sector note) don't say when; consider dropping them.

### 3. When does Jonas Weber need the hedging proposal?  (C301, as u2)
- Labelled relevant: `email_302`
- Hybrid top 5:
  1. `email_302` (labelled) Hedging proposal (2026-11-02)
  2. `note_301` Plant visit - Vossberg, Stuttgart (2026-09-17)
  3. `email_301` Vossberg numbers before the plant visit (2026-08-04)
- Check: every labelled doc is in the top 5.

### 4. What was relationship revenue before the plant visit?  (C301, as u2)
- Labelled relevant: `email_301`
- Hybrid top 5:
  1. `email_301` (labelled) Vossberg numbers before the plant visit (2026-08-04)
  2. `note_301` Plant visit - Vossberg, Stuttgart (2026-09-17)
  3. `research_301` German auto suppliers move production closer to US customers (2026-09-03)
- Check: every labelled doc is in the top 5.

### 5. Why are payments to Mexican suppliers failing?  (C301, as u2)
- Labelled relevant: `email_302`
- Hybrid top 5:
  1. `research_301` German auto suppliers move production closer to US customers (2026-09-03)
  2. `email_302` (labelled) Hedging proposal (2026-11-02)
  3. `note_301` Plant visit - Vossberg, Stuttgart (2026-09-17)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, no answer in any document):** `email_302` only says payments are still being rejected. The cause (a missing purpose code) is in the service-issues table, not in any document, so document search can't answer this question.

### 6. What is Project Lindwurm?  (C301, as u1)
- Labelled relevant: `brief_301`
- Hybrid top 5:
  1. `brief_301` (labelled) Deal team briefing: Project Lindwurm (2026-10-30)
- Check: every labelled doc is in the top 5.

### 7. What is Project Lindwurm?  (C301, as u2)
- Labelled relevant: none (nothing should be found)
- Hybrid top 5:
  (nothing returned)
- Check: every labelled doc is in the top 5.

### 8. How much cash do they keep in money market funds?  (C302, as u2)
- Labelled relevant: `email_311`
- Hybrid top 5:
  1. `email_311` (labelled) Money market funds (2026-04-09)
  2. `email_312` Lattice Ridge Q3 investor update (2026-10-28)
  3. `note_311` Quarterly meeting with Lattice Ridge, Austin (2026-10-14)
- Check: every labelled doc is in the top 5.

### 9. How fast is annual recurring revenue growing?  (C302, as u2)
- Labelled relevant: `email_312`
- Hybrid top 5:
  1. `email_312` (labelled) Lattice Ridge Q3 investor update (2026-10-28)
  2. `note_311` Quarterly meeting with Lattice Ridge, Austin (2026-10-14)
  3. `news_311` Lattice Ridge raises $90 million to expand factory analytics (2026-11-05)
- Check: every labelled doc is in the top 5.

### 10. How big was the growth round?  (C302, as u2)
- Labelled relevant: `news_311`, `note_311`
- Hybrid top 5:
  1. `news_311` (labelled) Lattice Ridge raises $90 million to expand factory analytics (2026-11-05)
  2. `note_311` (labelled) Quarterly meeting with Lattice Ridge, Austin (2026-10-14)
- Check: every labelled doc is in the top 5.
- **Note (pre-review, questionable):** Only `news_311` gives the size ($90 million); `note_311` says a round is being raised but not how big. Consider dropping `note_311`.

### 11. Can the credit facility be sized on recurring revenue?  (C302, as u2)
- Labelled relevant: `note_311`
- Hybrid top 5:
  1. `email_312` Lattice Ridge Q3 investor update (2026-10-28)
  2. `note_311` (labelled) Quarterly meeting with Lattice Ridge, Austin (2026-10-14)
  3. `email_311` Money market funds (2026-04-09)
- Check: every labelled doc is in the top 5.

### 12. When will the KYC documents arrive?  (C302, as u2)
- Labelled relevant: `email_313`
- Hybrid top 5:
  1. `email_313` (labelled) KYC renewal (2026-07-22)
  2. `email_312` Lattice Ridge Q3 investor update (2026-10-28)
- Check: every labelled doc is in the top 5.

### 13. How many yards does Cedar Hollow run?  (C303, as u2)
- Labelled relevant: `note_321`
- Hybrid top 5:
  1. `note_321` (labelled) Yard visit, Barrie, Ontario (2026-10-21)
  2. `news_322` Canadian building suppliers brace for a slower spring (2026-10-30)
  3. `email_321` Equipment finance (2026-11-09)
- Check: every labelled doc is in the top 5.

### 14. When do they want the equipment term sheet?  (C303, as u2)
- Labelled relevant: `email_321`
- Hybrid top 5:
  1. `email_321` (labelled) Equipment finance (2026-11-09)
  2. `note_321` Yard visit, Barrie, Ontario (2026-10-21)
- Check: every labelled doc is in the top 5.

### 15. How seasonal is their business?  (C303, as u2)
- Labelled relevant: `note_321`
- Hybrid top 5:
  1. `note_321` (labelled) Yard visit, Barrie, Ontario (2026-10-21)
  2. `email_321` Equipment finance (2026-11-09)
  3. `news_322` Canadian building suppliers brace for a slower spring (2026-10-30)
- Check: every labelled doc is in the top 5.
