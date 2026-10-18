# Builder Center article outline

**Title:** SIMShift: Teaching an IoT Recovery Agent When *Not* to Switch eSIMs
**Tags:** `#strands-decider-2b` `#tool-selection`
**Length:** about 1,500–2,000 words, which is roughly an 8-minute read.

| # | Section | Words | Rule it covers |
|---|---|---:|---|
| 1 | Hook + TL;DR | 120 | What the agent does |
| 2 | The problem | 200 | Creativity |
| 3 | What SIMShift does | 200 | **Required:** describe the agent |
| 4 | The decision Decider makes | 300 | **Required:** name the decision |
| 5 | Architecture | 250 | Decider + Bedrock pairing |
| 6 | Safety: hard checks, not trust | 200 | Low-confidence handling |
| 7 | Results | 250 | Encouraged: latency, cost, accuracy |
| 8 | Reusable pattern | 250 | **Required:** pattern in repo |
| 9 | Limits + what I learned | 150 | Honesty, communication |
| 10 | Links | 50 | Repo, video, license |

---

### 1. Hook + TL;DR
- Open with one line: "The wrong recovery action can be worse than doing nothing."
- Add a 3-bullet TL;DR covering the agent, Decider's job, and the reusable router.
- Show a hero GIF of the Brazil cluster going red, then green.

### 2. The problem
- Cellular IoT fleets roam between networks and carry several eSIM profiles.
- Failures happen at different layers: radio, data session, firmware, app, or management.
- Reflexive "switch the eSIM" can make downtime longer. It can also cut off a device for good.
- Three terms, each defined in one line: operator reselection, profile switch, management path.

### 3. What SIMShift does
- It takes in a simulated incident, then filters the safe tools.
- Decider picks the next tool, the tool runs, and the agent checks again.
- Use the six scenario families as a small table. Make clear only 3 are in the MVP.
- Add a clear disclosure: all devices, networks and eSIM operations are simulated.

### 4. The decision Decider makes *(most important)*
- Quote the exact typed question.
- Show the option set as a table of option, tool, and limits.
- Show one real request/response pair from a logged run, not the sample from the handoff.
- Explain how the choice routes to a Strands tool, with a code snippet.
- Explain how we prove it matters: flip the choice and a different tool runs (`test_decider_controls_tool`).

### 5. Architecture
- Include the diagram from the handoff, §5.
- Add a role table:

| Part | Does | Doesn't |
|---|---|---|
| Decider 2B | Picks the next tool | Authorize |
| Bedrock | Plans and explains | Authorize |
| Policy | Hard yes/no checks | Guess |
| Simulator | Runs the outcomes | Touch real networks |

- List the AWS hosting used. Give the real services and region.

### 6. Safety: hard checks, not trust
- The filter runs before Decider, so forbidden options are never offered.
- A profile change needs four checks: capability, reachability, permission, and approval.
- Walk through the Offline case: the forced switch is blocked and logged.
- On low confidence, the agent gathers more evidence or escalates. Give the real threshold and how it was tuned.

### 7. Results *(real numbers only)*
- Setup: how many scenarios, the held-out split, seeds, hardware, and model version.
- Compare three strategies: rules-only, Bedrock-only, and Decider + Bedrock.
- Metrics: resolved, unnecessary switches, forbidden executions, p50/p95 latency, Bedrock calls/tokens.
- Include at least one negative finding.
- If the results are thin, cut this to one measured A/B and say so.

### 8. Reusable pattern: `CapabilityAwareRecoveryRouter`
- Link to `patterns/capability_aware_router/`.
- Explain what it is in 3 lines: state in, your filter, your tools, a typed choice and trace out.
- Add a 10–15 line usage snippet.
- Show the non-telecom example, such as a cloud-ops incident.
- Explain how to adapt it: swap the questions, options and policy.

### 9. Limits + what I learned
- This is not GSMA SGP.32 certified. It touches no real carriers or eUICCs.
- The simulator is simplified, and it reasons per cohort, not per device.
- State real Decider latency on the chosen hardware, including cold start.
- Give 2–3 honest lessons, such as "probability ≠ calibrated confidence".

### 10. Links
- Public repo (OSI license named), video (YouTube/Vimeo), and the hackathon page.

---

### Before publishing
- Every number comes from a real run.
- Include no employer data, no customer data, and no AWS or GSMA logos.
- Apply both tags exactly.
- Check that the article reads clearly logged out.
