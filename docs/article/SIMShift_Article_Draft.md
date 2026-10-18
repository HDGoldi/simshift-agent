# SIMShift: Teaching an IoT Recovery Agent When *Not* to Switch eSIMs

`#strands-decider-2b` `#tool-selection`

> **Draft status:** Numbers below come from real logged runs on 2026-10-18 (`logs/trace.jsonl`, `evaluation/results/2026-10-18T162818Z-heldout.json`). Items still marked `[TODO]` need the AWS deploy, Bedrock access, the public repo or the video. Delete these notes before publishing.

> **The wrong recovery action can be worse than doing nothing.**

**TL;DR**
- **SIMShift** is an autonomous agent for recovering connectivity in cellular IoT fleets. It is built with Strands Agents and paired with Amazon Bedrock.
- **Strands Decider 2B owns one causal decision.** At every step, it picks which recovery or diagnostic tool runs next, from a set already filtered for safety.
- **On 30 held-out synthetic incidents**, Decider picked an acceptable first tool 96.7% of the time, resolved all 30 correctly, and made zero forbidden executions.
- **The reusable part** is `CapabilityAwareRouter`, a small, domain-free pattern you can drop into any Strands agent that has to choose among risky tools.

![Recovery Decision Inspector: Brazil cohort restored after a guarded, human-approved profile switch](../screenshots/brazil-restored.png)

*Everything in this project is simulated: the devices, networks, eSIM profiles and management commands. No real carrier, eUICC or customer data is touched.*

---

## 1. The problem: a fast fix that makes things worse

Picture a logistics company tracking 100,000 shipping containers. Each tracker has a cellular modem and an eSIM. That eSIM can hold more than one subscription profile, and each profile can allow more than one mobile network.

One morning, 3,200 trackers in Brazil go quiet. The tempting fix is "switch them to the other eSIM profile." Sometimes that is right. Often it is not:

- The **network** may be the problem. Another operator on the *same* profile would fix it with no profile change at all.
- The **cellular link may be fine**. Devices register, but your cloud ingestion broke. Switching profiles fixes nothing and adds downtime.
- The **device may be unreachable**. With no management path, a remote profile command never arrives. A half-finished change can strand the device.
- The **firmware** may be stuck in a restart loop. Any network action is noise.

So the hard part isn't *doing* a recovery action. It's *choosing* the right next one. Three terms used throughout:

| Term | Meaning |
|---|---|
| Operator reselection | Try another network the *current* profile already allows |
| Profile switch | Enable a *different installed* subscription on the eUICC |
| Management path | A working channel to send the device a command |

## 2. What SIMShift does

SIMShift works on **incident cohorts**: groups of devices with the same symptoms. It does not work device by device. For each incident it runs a short loop:

1. **Observe** the cohort's state, written as short plain sentences.
2. **Filter** the tool list with deterministic policy, removing anything not permitted right now.
3. **Decide**: Strands Decider 2B picks the most useful next tool from what's left.
4. **Act**: the chosen Strands tool runs against a deterministic digital twin.
5. **Reassess**: observe again. Repeat, escalate, or report recovery. Bedrock explains the outcome.

The demo ships three scenarios, each designed to require a *different* decision:

| Scenario | Evidence | Right move | Lesson |
|---|---|---|---|
| Brazil: profile recovery | Attach success 4%, no allowed alternate operator, alternate profile installed, management path reachable | Evaluate a guarded profile change | Switching is right *here*, and only after checks |
| Offline: no management path | No heartbeat for 720 min, management path not reachable | Escalate or wait | Don't pretend a remote command works |
| Japan: false outage | 99.7% registration success, only 2% of app messages acknowledged | Investigate the data path | The network isn't the problem |

The evaluation covers three more families in the twin: operator outage, firmware loop and a transient blip.

## 3. The decision Strands Decider 2B makes

This is the heart of the project. Decider 2B answers **one typed `choice` question**, at every step of the loop:

> **Given the current cellular connectivity symptoms, existing diagnostic evidence, and admissible tools, which next tool is most useful for safely advancing service restoration? Do not assume that an unverified recovery path works.**

The last sentence matters. It pushes the model away from "switching will surely work."

The full option set before filtering:

| Option | Strands tool | Limit |
|---|---|---|
| `retry_connection` | `simulate_retry_with_backoff` | Bounded, rate-limited |
| `try_allowed_operator` | `simulate_operator_reselection` | Only operators the active profile allows |
| `investigate_device` | `query_firmware_modem_diagnostics` | Read-only |
| `investigate_data_path` | `query_apn_session_app_diagnostics` | Read-only |
| `evaluate_profile_change` | `prepare_guarded_profile_transition` | Never enables a profile directly |
| `escalate_or_wait` | `defer_or_escalate` | Hold or hand to a human |

The Brazil request to `POST /v1/systemone`. The policy already removed `retry_connection` (retry budget spent) and `try_allowed_operator` (no permitted alternate operator), so only four options are offered:

```json
{
  "state": "Incident: Persistent cellular attach failures in Brazil cohort. 3200 devices affected.\nNetwork registration (attach) success: 4.0%.\nActive data sessions: 3.0%.\nApplication messages acknowledged by the cloud: 3.0%.\nLast heartbeat: 1 minutes ago.\nManagement path to the devices: reachable.\nActive eSIM profile: profile_A.\nAlternate eSIM profile installed: yes.\nPermitted alternate operator on active profile: no.\nRetries already attempted: 3.\nRecent firmware change: no.",
  "questions": {
    "next_option": {
      "type": "choice",
      "instructions": "Given the current cellular connectivity symptoms, existing diagnostic evidence, and admissible tools, which next tool is most useful for safely advancing service restoration? Do not assume that an unverified recovery path works.",
      "criteria": {
        "investigate_device": "read-only modem and firmware diagnostics; fits device resets or firmware cohorts",
        "investigate_data_path": "read-only APN, data session and application ingestion diagnostics; fits devices that are registered but whose data is not arriving",
        "evaluate_profile_change": "check feasibility of enabling a different installed eSIM profile; does not execute it",
        "escalate_or_wait": "hold and hand to a human team; fits cases where no remote action can reach the devices, or the root cause is outside the cellular layer"
      }
    },
    "evidence_sufficient": {
      "type": "noul",
      "instructions": "Is the current evidence sufficient to choose a next step confidently?"
    }
  }
}
```

What came back, as logged (`2026-10-18T14:55:16Z`, CPU):

```json
{
  "model": "strands-decider-2B-qwen3.5-v1-2610",
  "latency_ms": 9956.75,
  "answers": {
    "next_option": {
      "choice": "evaluate_profile_change",
      "probabilities": {
        "investigate_device": 0.0911,
        "investigate_data_path": 0.2939,
        "evaluate_profile_change": 0.5529,
        "escalate_or_wait": 0.0621
      },
      "confidence": 0.4039
    },
    "evidence_sufficient": { "noul": 0.5036 }
  }
}
```

The checkpoint is pinned to `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, revision `216d1ccb46a9e9b036eb9187b248db98480f77d4`, installed with `strands-decider==0.1.0`.

**How the choice drives the agent.** The Decider output isn't advice that Bedrock may ignore. It is the key that selects the tool. This is the core of `router.py`, trimmed:

```python
def step(self, state):
    allowed, removed = self.admissible(state)              # deterministic filter
    criteria = {n: self.options[n].description for n in allowed}
    decision = self.decider.choose(self.describe(state), self.question, criteria)

    if decision.choice not in allowed:                     # never run an off-list pick
        raise NonAdmissibleChoice(decision.choice)

    target = decision.choice
    if decision.confidence < self.low_confidence:          # hold back, or a safe fallback
        if not (self.fallback and self.fallback in allowed):
            return result_with(outcome="low_confidence")
        target = self.fallback

    if target in self.policy.removed(state, [target]):     # re-check right before acting
        raise NonAdmissibleChoice(target)

    opt = self.options[target]
    if opt.risky and not (self.approve and self.approve(state, opt)):
        return result_with(outcome="awaiting_approval")    # a human decides

    return result_with(executed=target, tool_output=opt.tool(state))  # the choice picks the tool
```

**Bedrock can't override it.** The Strands agent on Bedrock sees only two tools: `get_incident_state` and `advance_recovery`. The second takes no arguments. The six recovery tools are never shown to Bedrock, so it has no way to pick one. A test checks that extra input from Bedrock can't steer the choice.

**Proof that it is causal, not decoration.** The test `test_decider_controls_tool` injects a different admissible Decider choice and asserts that a different Strands tool executes. A second test, `test_decider_is_real`, calls the pinned Decider runtime, not a fixture.

Why a small decision model here? This choice happens **many times per incident**, across many incidents. It is a bounded, typed pick among a handful of options. That is exactly the kind of choice a small model can own. A large model is then saved for the parts that need language: plans and explanations.

## 4. Architecture

```text
      Browser UI: fleet view | decision inspector | eUICC inspector
                              |
                    API / scenario controller
                              |
          Strands recovery agent (Bedrock model, 2 tools)
                 +------------+------------+
                 |                         |
          Strands Decider 2B          Amazon Bedrock
          next-tool choice            plans + explanations
                 +------------+------------+
                              |
             Deterministic capability / policy gate
                 +------------+------------+
                 |                         |
          Cellular fleet twin       Virtual eIM / IPA / eUICC
                 +------------+------------+
                              |
                    Outcome + event trace
```

| Part | Does | Does not |
|---|---|---|
| Strands Decider 2B | Picks the next tool, with probabilities | Authorize anything |
| Amazon Bedrock (`[TODO: model ID]`) | Recovery plans, explanations, the final report | Pick a tool or authorize anything |
| Policy gate | Hard checks: capability, reachability, permission, approval | Guess |
| Digital twin | Deterministic, seeded outcomes; hidden root causes | Touch real networks |

**On AWS:** `[TODO: real services and region once deployed. Planned: agent on Amazon Bedrock AgentCore Runtime; Decider in a container; UI on a static host.]`

The hidden root cause of each scenario is visible **only to the simulator and evaluator**. It never appears in a Decider or Bedrock prompt. The tests `test_no_truth_leakage`, `test_twin_never_leaks_truth` and `test_no_label_leaks_into_state_text` enforce this.

## 5. Safety: hard checks, not trust

Probabilistic models make mistakes, so SIMShift never asks one to be the safety mechanism.

- **Filter before deciding.** Forbidden options are removed *before* Decider sees the list, and the trace records why. Decider is never handed a dangerous option in the hope it will skip it.
- **Re-check before acting.** The chosen option is validated again just before the tool runs.
- **Profile changes need five gates.** The eUICC must support remote enable, an alternate profile must be installed, a management path must be reachable, the owner must permit profile changes, and a human must approve. `evaluate_profile_change` only *opens* this workflow. It never flips a profile on its own. Only then does the virtual eIM -> IPA -> eUICC chain run.
- **Restored means two layers.** Network registration *and* application telemetry must both reach at least 95%. A cohort that registers but sends no data is not fixed.
- **Bounded loop.** There is a step limit and a retry budget. A failed action is observed and reassessed, not blindly repeated.

**The Offline case in action.** With no heartbeat and no management path, the filter removed three options: `try_allowed_operator`, `investigate_device` and `evaluate_profile_change`. Decider chose `escalate_or_wait` from the remaining three (probability 0.572, confidence 0.358). We then *forced* a profile change from the UI. The gate blocked it with `BLOCKED: no reachable management path`, and the trace logged the attempt.

![Offline cohort: Decider escalates; a forced profile change is blocked](../screenshots/offline-blocked.png)

Across every benchmark run, forbidden **executions** were zero. Forbidden **proposals** were zero too, by construction: a removed option is never offered, and the router refuses any choice outside the allowed list.

**Low confidence.** The router has a confidence bar. Below it, the agent runs only a safe read-only fallback, or nothing. In the current build the bar is `0.0`. Real confidences in the benchmark were 0.09-0.54, and any bar I tried by hand stopped good decisions too. The benchmark below shows where a tuned bar should sit.

## 6. Results

**Setup:** 30 held-out synthetic incidents, 5 in each of 6 families (operator, profile, application, unreachable, firmware, transient). Held-out seeds start at 9000; dev seeds start at 1000, so no variant appears in both. Some cases include misleading details, such as an unrelated firmware change. Every strategy gets the same state text, the same filtered options, the same guards and the same twin. Approvals are auto-granted in the benchmark, but the five gates still apply. Decider ran on CPU: x86_64, 4 vCPU, no GPU.

| Metric (held-out, n=30) | Rules-only | Random (filtered) | Decider 2B |
|---|---:|---:|---:|
| First tool acceptable | 100% | 30.0% | **96.7%** |
| Resolved correctly | 100% | 53.3% | **100%** |
| Unnecessary profile changes | 0 | 7 | **1** |
| Forbidden executions | 0 | 0 | **0** |
| Mean steps per incident | 1.33 | 2.57 | 1.43 |
| Mean simulated downtime | 25.8 min | 47.8 min | 27.7 min |
| Decision latency p50 / p95 | — | — | 10.6 s / 12.2 s |

How to read this:

- **Random** picks any option the filter allows. Its 53% shows how much the safety filter does on its own: even a coin toss can't run anything forbidden. Its 7 needless profile switches show what the filter can't do.
- **Rules-only** scored a perfect 100%, and that is less impressive than it looks. I wrote those rules and these scenario families together, so they fit each other by design. Real fleets won't be that tidy. The point of Decider is that it reads plain-language state, so new evidence doesn't need a new hand-written rule.
- **Bedrock-only** is built into the harness but not run yet. `[TODO: Bedrock-only column, Bedrock calls and tokens per incident, once Bedrock access works.]`

**Decider by family:** 100% acceptable first tool on operator, profile, application, unreachable and transient. 80% on firmware.

**Where Decider struggled.** The one miss was `firmware-9001`. Decider wandered: retry -> profile change -> retry -> device diagnostics -> escalate. That took 5 decisions and 95 simulated minutes, and made the only needless profile switch in the run. Its confidence stayed between 0.09 and 0.24 the whole time. The switch went through only because the benchmark auto-approves; in the UI, a human would have seen it first.

**Confidence is a useful signal.** First-step confidence split the cases cleanly:

| First-step confidence | Incidents | Acceptable first tool |
|---|---:|---:|
| below 0.3 | 6 | 83.3% |
| 0.3 or higher | 24 | 100% |

So a bar near 0.3, with "gather more evidence" as the fallback, would have caught the one bad case. With 30 cases this is a hint, not proof.

**Latency.** On this 4-vCPU CPU box, one decision took 10.6 s at p50 and 12.2 s at p95. One loaded model uses about 9.9 GB of RAM. Published figures are about 115 ms median on GPU. Those are different hardware, so I don't compare them directly. `[TODO: cold start and warm latency on the deployed AWS hardware.]`

## 7. The reusable pattern: `CapabilityAwareRouter`

📁 [`patterns/capability_aware_router/`](TODO-repo-link/patterns/capability_aware_router)

**What it is:** you give it state, your own policy rules, and your own tools. It removes what isn't allowed and asks Decider 2B to pick the next tool. It runs that tool and returns a typed outcome and a full trace. It contains **no telecom code**.

```python
from patterns.capability_aware_router import (
    CapabilityAwareRouter, HttpDeciderClient, Option, Rule, RulePolicy,
)

router = CapabilityAwareRouter(
    question="Which next action most safely restores the service?",
    options=[
        Option("restart_service", "restart; fits crashes with no recent change", restart_service),
        Option("roll_back_deploy", "roll back; fits errors right after a deploy", roll_back, risky=True),
        Option("read_logs", "read-only: collect recent logs", read_logs),
    ],
    policy=RulePolicy([Rule("restart_service", lambda s: s["restarts"] >= 3, "restart budget spent")]),
    decider=HttpDeciderClient("http://127.0.0.1:8099"),
    describe=lambda s: f"Error rate {s['error_rate']:.0%}; deployed {s['mins_since_deploy']} min ago.",
    low_confidence=0.3,          # tune on your own labelled cases
    fallback="read_logs",        # safe, read-only
    approve=my_human_check,      # required for risky=True options
)
result = router.step(state)
print(result.outcome, result.executed, result.to_trace())
```

It gives you three guarantees for free:

- **Risky options need approval.** Without it, nothing runs.
- **Low confidence holds back.** Below the bar, only the safe fallback runs, or nothing.
- **Off-list choices are refused.** The router won't run a choice the policy didn't allow.

The folder includes `example.py`, which routes a **cloud-ops incident** with no telecom involved. Its tests cover tool routing, capability filtering, low confidence and forbidden actions.

**Adapt it** by swapping three things: the question, the option set, and the policy. The loop, filtering, re-check and trace stay the same. It fits cloud remediation, data-pipeline repair, robotics, or any agent where *which* tool runs matters more than *how fast*.

## 8. Limits and what I learned

**Limits**
- This is not GSMA SGP.32 certified. eIM, IPA and eUICC are simplified virtual models, with no SM-DP+, no real profile downloads, and no carrier calls.
- The agent reasons per cohort, not per device. The "100,000 devices" are a simulated fleet.
- Results come from 30 synthetic incidents I designed. Real fleets are messier.
- Decider took about 10 s per decision on a 4-vCPU CPU box. That is fine for a demo step, but too slow for a tight loop without a GPU.

**Lessons**
1. **How you write the state matters a lot.** My first version sent raw data fields. Japan then picked "profile change", by 0.337 to 0.335. Rewritten as plain sentences, Japan picked the data path at 0.62.
2. **Never give the model a one-option list.** Early on, the Offline filter left only "escalate". Decider wasn't choosing; it was stamping. Keeping the safe, device-free options in the list made it a real decision.
3. **Top-choice probability is not calibrated confidence.** Even correct picks often had confidence near 0.4, or 0.09 at the low end. Tune the bar on your own labelled cases; the 0.3 split above came from data, not a guess.
4. **Filtering before the model sees options is simpler and safer** than asking the model to avoid them. The most useful trace field turned out to be "why this option was removed".

## 9. Links

- **Code (Apache-2.0):** `[TODO: public repo URL]`
- **Demo video (under 3 min):** `[TODO: YouTube/Vimeo URL]`
- **Reusable pattern:** `[TODO: repo URL]/patterns/capability_aware_router`
- **Hackathon:** [Agent Experience Hackathon: Strands Decider](https://builder.aws.com/build/hackathons/4f50957c-1d08-37ab-b11c-97516b9adeb4/agent-experience-hackathon-strands-decider)

---

*The smartest recovery agent isn't the one that switches fastest. It's the one that knows when to switch, when to investigate, and when not to act.*

`#strands-decider-2b` `#tool-selection`
