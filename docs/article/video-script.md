# SIMShift demo video script (target 2:45)

Everything shown is the real UI (`python -m simshift.web --bedrock`) with the live Decider server and Bedrock, or
the recorded replay (`make ui`) if the Decider server is not running. Keep the SIMULATED FLEET badge in frame.

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:15 | UI home, incident list | "When IoT devices lose connectivity, the wrong recovery action can be worse than doing nothing. SIMShift is a recovery agent that knows when not to switch. Everything here is a simulated fleet; the models are real." |
| 0:15–0:35 | Click `BR_PROFILE`. Point at the typed question and the options table | "Strands Decider 2B answers one typed question at every step: which tool next. Before it sees the options, a deterministic policy removes the ones that are unsafe or pointless, and says why." |
| 0:35–1:05 | Next step twice. Point at probabilities, confidence, route | "Decider leans towards retrying, but with low confidence. Below 0.5 the router does not act on that. It runs the most probable read-only check instead. The modem diagnostics find a registration reject, a synthetic cause 17, from the serving network. From now on, retrying is off the table." |
| 1:05–1:35 | Next step. The approval dialog opens. Point at the gate checklist and the Bedrock review | "Now Decider picks a profile change at 0.88. These depot trackers can still reach the eSIM manager over a Wi-Fi gateway, so the change can be delivered. Nine of the ten checks pass: management path reachable, no other operator on this profile, reject evidence, and so on. The tenth is a human approval for this exact proposal. Bedrock reviews the plan and suggests a staged rollout, as advice only. Neither model can approve. I do." |
| 1:35–1:55 | Approve. The transition path runs to SUCCEEDED; fleet dots turn green | "The virtual eIM delivers the switch, the device reports the result, and SIMShift checks registration, data sessions and application telemetry before it calls this restored. If verification failed, it would roll back and hand off. If the result never arrived, it would accept the switch only on independent network evidence, and otherwise hand off." |
| 1:55–2:20 | Click `OFFLINE`, Run to end, then "What if: evaluate_profile_change" | "Same agent, different evidence. These devices have no management path, and the network check finds no device even trying to attach, so escalation is the only option left. And if someone forces a profile change on a clone, the gate blocks it before anything is sent. SIMShift never pretends an offline device accepted an OTA command." |
| 2:20–2:40 | Benchmark table from `docs/benchmark/` | "On 60 generated incidents, the same router and gate ran five choosers. Decider ended 97% of them correctly at about a tenth of a second a choice. Bedrock choosing alone ended 92% correctly at about two seconds. These are synthetic incidents we designed, so it shows the parts work together, not field results." |
| 2:40–2:50 | Pattern README | "The reusable part is CapabilityAwareRouter: filter, decide, route, gate. No telecom code. Link in the description." |

Recording notes: use the committed results file for every number spoken. Do not show terminals with AWS profile names
or account IDs. No music unless it is licensed for this use.
