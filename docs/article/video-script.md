# SIMShift demo video script (final cut, 2:56)

Published: https://youtu.be/wL6Ksg_yTT4. The video is built from screenshots of the real UI (`make ui`, recorded real
Decider answers), animated diagrams and the committed results files. The SIMULATED FLEET badge is on screen throughout.
Narration is a synthetic voice (ElevenLabs); there is no music.

| Time | Screen | Narration (as subtitled) |
|---|---|---|
| 0:00–0:11 | Fleet dot grid turns red; title card | "When IoT devices lose connectivity, the wrong recovery action can be worse than doing nothing. SIMShift is a recovery agent that knows when not to switch." |
| 0:11–0:23 | Incident list (real UI) and the two model chips | "Everything here runs on a simulated fleet. The models are real: Strands Decider 2B picks each tool, and Amazon Bedrock reviews and reports." |
| 0:23–0:42 | Options table (real UI) beside the filter, decide, route, gate stages | "At every step, Decider answers one typed question: which tool next? A deterministic policy first removes the unsafe or pointless options, and says why. Decider chooses. A router decides whether to act. A gate checks again." |
| 0:42–1:08 | Confidence meter with the 0.5 threshold, then the decision trace (real UI) | "In Brazil, 3,200 trackers can't attach. Decider leans toward a retry, but at confidence 0.04. Below 0.5, the router won't act. It runs a read-only check instead: the data path, then the modem. The network rejects registration: a synthetic cause 17. Retrying is off the table." |
| 1:08–1:34 | Meter at 0.88, the ten gate checks, the approval dialog (real UI) and the recorded Bedrock review | "Now Decider picks a profile change, at 0.88. Depot trackers reach the eSIM manager over Wi-Fi, so the change can be delivered. Ten checks must pass. Nine are automatic. The tenth is a human approval, for this exact proposal. Bedrock reviews the plan, as advice only. Neither model can approve. I do." |
| 1:34–1:53 | Transition stepper to SUCCEEDED; fleet goes from red to green | "The virtual eIM delivers the switch, and the device reports back. SIMShift checks registration, data sessions and telemetry before calling it restored. Failed verification rolls back and hands off. A missing result needs network evidence, or hands off." |
| 1:53–2:08 | OFFLINE incident (real UI) and the blocked counterfactual | "Same agent, different evidence. These devices have no management path, and none is trying to attach. So it escalates. Force a profile change on a clone, and the gate blocks it before anything is sent." |
| 2:08–2:21 | AWS architecture: AgentCore Runtime, private Fargate Decider, Bedrock | "And it runs on AWS. The agent runs on Bedrock AgentCore Runtime, Decider on a private Fargate task. All six scenarios were recorded there." |
| 2:21–2:44 | Accuracy and latency table, five choosers | "On 60 generated incidents, Decider ended 97% correct, about a tenth of a second per choice on a laptop GPU. Bedrock alone: 92%, about two seconds. On a Fargate CPU, Decider takes about seven seconds. Synthetic incidents, not field results." |
| 2:44–2:56 | CapabilityAwareRouter code excerpt, then the repo link | "The reusable part: CapabilityAwareRouter. Filter, decide, route, gate. No telecom code. The link is in the description." |

Notes: every number comes from the committed results files (`docs/sample-runs/`, `docs/benchmark/`,
`docs/measurements.md`). The Bedrock plan review shown in scene 5 is the recorded one from `docs/sample-runs/orchestrated/BR_PROFILE.json`.
