# SIMShift: When Not to Switch (2:50 video script)

Read at a calm pace, about 150 words a minute. The script has about 410 spoken words. `[brackets]` mark real values to fill in from your live run. Never put in made-up numbers.

---

### 0:00–0:20 · The problem

**Screen:** Dark fleet map with a "SIMULATED FLEET" badge. The Brazil cluster turns red and the counter drops to 3,200 offline.

**Voice:**
> "This is a simulated fleet of a hundred thousand cellular IoT trackers. Suddenly, 3,200 devices in Brazil go silent. The obvious fix is to switch their eSIM profile. But the wrong recovery action can be worse than doing nothing. SIMShift is an agent that knows the difference."

---

### 0:20–0:50 · Decider's real choice

**Screen:** Recovery Decision Inspector. Highlight four things in order:
1. Incident state (attach rate `[0.04]`, alternate profile installed, management path reachable).
2. Options removed by policy: `try_allowed_operator`, with the reason "no permitted operator on active profile".
3. The typed question and the four remaining options.
4. Decider's live output: `evaluate_profile_change`, probability `[p]`, latency `[ms]`.

Then zoom on the trace line `choice → tool: prepare_guarded_profile_transition`.

**Voice:**
> "First, a deterministic policy filter removes anything unsafe. Here, no other operator is allowed on this subscription, so that option is gone, and the trace says why. Then Strands Decider 2B answers one typed question: which next tool safely moves recovery forward? It picks 'evaluate profile change' with probability [p], in [x] milliseconds. That choice is not decoration. It decides which Strands tool runs next."

---

### 0:50–1:20 · Safe recovery

**Screen:** Bedrock explanation panel, then a policy checklist that ticks green (capability, reachability, permission, approval). Then the virtual eUICC inspector: Profile A → Profile B. The map turns green and the counter climbs. Show both "registration ✓" and "telemetry ✓".

**Voice:**
> "Amazon Bedrock drafts the recovery plan and explains its uncertainty. But no model authorizes the change. Hard checks do: is the eUICC capable, is the device reachable, do we have permission, did a human approve? Only then does the virtual eSIM manager enable the alternate profile. We confirm recovery twice, at network registration and at application telemetry."

---

### 1:20–1:45 · The counterexample

**Screen:** Load the `OFFLINE` scenario: 1,250 devices with no heartbeat. Decider picks `escalate_or_wait` `[p]`. Click "Force profile change". A red "BLOCKED: no management path" banner appears and is logged in the trace.

**Voice:**
> "Now a harder case. These devices have no heartbeat and no management path. A remote profile switch simply cannot reach them. Decider chooses to escalate. And if we force the switch anyway, the guard blocks it and records why. Knowing when not to act is the feature."

---

### 1:45–2:15 · Evidence

**Screen:** Benchmarks panel showing three bars (rules-only, Bedrock-only, Decider + Bedrock). Rows: resolved, unnecessary switches, forbidden executions = 0, median decision latency, Bedrock calls. Add the caption "`[N]` held-out synthetic scenarios, seed-locked".

**Voice:**
> "We tested three strategies on [N] held-out synthetic incidents, with the same tools and the same rules. Decider plus Bedrock resolved [x] percent, made [y] unnecessary profile switches, and used [z] percent fewer Bedrock calls. Forbidden executions: zero, in every strategy, because the guard is deterministic. Where Decider lost, we say so in the article."

*If the benchmark isn't ready, swap in a single honest line: "Decider choice vs Bedrock choice on the same case: latency and calls." Do not fake bars.*

---

### 2:15–2:50 · Reusable pattern and close

**Screen:** GitHub `patterns/capability_aware_router/README.md` showing the typed question, the option set, and a 10-line usage snippet. Run its tests and show them green. Then a non-telecom `example.py` run. End card: repo URL, article URL, `#strands-decider-2b #tool-selection`.

**Voice:**
> "The core is a reusable pattern: the Capability-Aware Recovery Router. You give it state, your policy filter, and your tools. It filters what's unsafe, lets Decider pick the next tool, and hands back a typed choice and a full trace. It has no telecom code inside. Here it is routing a cloud-ops incident instead. It's open source, with tests. The smartest recovery agent isn't the one that switches fastest. It's the one that knows when to switch, when to investigate, and when not to act."

---

### Recording rules

| Check | Why |
|---|---|
| Record the real running app | Rules need Decider "actually working" |
| Use no music, or royalty-free music you own | No copyrighted music allowed |
| Use no AWS or GSMA logos | No trademarks without permission |
| Keep the "SIMULATED" badge on screen | Honest about fake data |
| Keep it under 3:00 | Judges stop at 3:00 |
| Make it a public YouTube or Vimeo link | Must be a public, approved host |
