# CapabilityAwareRouter — a Strands Decider 2B tool-selection pattern

> **Reusable decision pattern** for the Strands Decider 2B hackathon (`#strands-decider-2b` `#tool-selection`).
> Worked examples: [`example.py`](example.py) (web-service remediation) and [`simshift/agent.py`](../../simshift/agent.py)
> (IoT connectivity recovery: `make_router()` builds the router, `Incident.step()` calls `router.step()` each turn).

**Pattern tag:** `#tool-selection` · **Model:** `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` · **Domain-free** (no telecom code)

Many agents can call several tools, and in a given state some of those tools are unsafe or pointless. This pattern lets a small
decision model pick the **next tool**, but only from options that a deterministic policy has already allowed.
The decision model never authorizes anything.

```
state ─► policy(state) removes inadmissible options (and records why)
      ─► Decider `choice` question over the remaining options
      ─► confidence-aware route:  act | gather_evidence | fallback
      ─► agent.tool.<selected>()   (a real Strands tool call, recorded in agent.messages)
      ─► the same policy runs again as an InterventionHandler right before the tool executes
```

## The typed question

One `choice` question per step. The option set is your `options` dict minus whatever `policy(state)` excludes:

```json
{"state": {...your observable state...},
 "questions": {"next_tool": {"type": "choice",
   "instructions": "<your question>",
   "criteria": {"option_a": "what it does; when it suits", "option_b": "..."}}}}
```

Decider returns `choice`, `probabilities` (over the admissible options) and `confidence`. The confidence is
derived from the distribution as `(N·p_max − 1)/(N − 1)`; it is not a calibrated probability of being correct.

### Verified API

Verified on 2026-10-18 with live calls against `strands-labs/strands-decider` @ `930e6d5d`, served by
`strands-decider serve`. The endpoints are `POST /v1/systemone` and `GET /health`. Besides `choice`, the server
supports `noul` (yes/no) and `score` question types; the spike in `spikes/decider_spike.py` exercised `choice` and
`noul`, and this pattern uses only `choice`. Below is the recorded `Decision.raw` from step 3 of the Brazil run
([`docs/sample-runs/BR_PROFILE.json`](../../docs/sample-runs/BR_PROFILE.json)). `DeciderClient` flattens the server's
`answers.next_tool` plus the top-level `model` and `latency_ms` into this shape and adds its own `client_latency_ms`:

```json
{"choice": "evaluate_profile_change", "probabilities": {"retry_connection": 0.0939, "evaluate_profile_change": 0.8742, "escalate_or_wait": 0.0319}, "confidence": 0.8113, "model": "strands-decider-2B-qwen3.5-v1-2610", "latency_ms": 482.22, "client_latency_ms": 484.0}
```

## Routing rule

| Condition | Route | What runs |
|---|---|---|
| `confidence >= act_threshold` (default 0.5) | `act` | Decider's choice |
| below the threshold, a read-only option is admissible | `gather_evidence` | the **most probable read-only** option |
| below the threshold, no read-only option left | `fallback` | your fallback (hold / hand off) |
| only the fallback is admissible | `fallback` | no model call |
| Decider unreachable, a malformed answer, or a choice outside the offered options | `fallback` | your fallback; the error or raw answer is kept in the decision |
| an answer that does not fit the question: probabilities not over exactly the offered options, not summing to 1, a choice that is not the most probable option, or a confidence that is not `(N·p_max − 1)/(N − 1)` | `fallback` | your fallback; every real answer we recorded passes these checks |

Excluded options are never shown to the model. The router does not offer forbidden actions and then hope the model avoids them.

## Use it

```python
from patterns.capability_aware_router.router import CapabilityAwareRouter, DeciderClient

router = CapabilityAwareRouter(
    decider=DeciderClient("http://127.0.0.1:8099"),
    instructions="Which next remediation step most safely restores the service?",
    options={"rollback_release": "...", "inspect_logs": "Read-only: ...", "page_oncall": "..."},
    tools={"rollback_release": "rollback_release", "inspect_logs": "inspect_logs", "page_oncall": "page_oncall"},
    policy=lambda s: {} if s["previous_release_available"] else {"rollback_release": "nothing to roll back to"},
    fallback="page_oncall",
    read_only=frozenset({"inspect_logs"}),
)
agent = Agent(model=..., tools=[...], interventions=[router.gate(lambda: current_state)])
decision, tool_result = router.step(agent, current_state)   # decision.raw = exact Decider answer
```

`policy` maps state to `{excluded_option: reason}`. `router.gate(state_fn)` is a Strands `InterventionHandler`.
It denies any routed tool that the policy excludes, whether Decider, an LLM or a direct call triggered it, and it
fails closed if the policy raises.

To rerun a saved trace without a Decider server, pass `ReplayDecider([...recorded Decision dicts...])` as `decider`.
It returns the recorded answers in order and refuses, which sends the step to the fallback, as soon as the live state,
question or options differ from the recording.

## Adapting it

1. Write the **options** as `name -> description`, and put *when each option suits* into the description. The model
   only sees these words, so they matter more than the names.
2. Write the **policy** as a pure function of observable state that returns `{option: reason}` for everything that is
   unsafe or pointless right now. Keep it deterministic. Anything you would refuse in a code review belongs here, not
   in the prompt.
3. Pick a **fallback** that is always safe (hold, hand off, page a human) and mark the **read-only** options.
4. Keep hidden or evaluator-only facts out of `state`. Decider sees exactly what you pass.
5. Record `Decision` objects. They carry the question, the state, what was excluded and why, the raw answer and the
   route, which is what you need for an audit and for `ReplayDecider`.

## Let an LLM run the loop without letting it pick the tool

In SIMShift a Bedrock model runs the Strands agent loop, but it only gets two tools and neither takes an argument:
`get_incident_state` and `advance_recovery`. The second one calls `router.step(...)` on an inner agent that holds
the routed tools and the gate ([`simshift/orchestrator.py`](../../simshift/orchestrator.py)). The LLM decides when to
look, when to continue and how to report. It has no parameter through which it could name a tool, skip the policy or
approve anything. The tests in [`tests/test_orchestrator.py`](../../tests/test_orchestrator.py) drive the real Strands
event loop with a scripted model to check exactly that.

Run the self-contained, non-telecom example (it needs a local Decider server):

```bash
strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device mlx --port 8099   # or --device cpu
python -m patterns.capability_aware_router.example
pytest patterns/capability_aware_router/tests      # no model or AWS needed
```

## Compared with a plain filter-then-choose router

Filtering the options and letting a model pick from the rest is the common starting point. This pattern adds six
things on top:
- **A second gate at execution.** The same policy runs again as a Strands `InterventionHandler` before any routed
  tool, so a tool excluded in the current state is denied even when it is called directly.
- **Confidence routes.** Acting needs confidence ≥ `act_threshold`. Below it, the most probable read-only option runs
  to gather evidence, and if no read-only option is left, the fallback runs.
- **Answer checks.** The probabilities must cover exactly the offered options, be numbers in [0, 1] and sum to 1. The
  choice must be the most probable option, and the confidence must match its formula.
- **Fail closed.** An outage, an off-menu choice, or a malformed or inconsistent answer goes to the fallback; it never
  crashes the step.
- **Replay.** `ReplayDecider` re-runs a saved trace without a model and refuses an answer recorded for a different
  question.
- **No tool choice for the orchestrating LLM.** An LLM can drive the loop through zero-argument tools without ever
  choosing the tool (see above).

## Tested properties

One file per property in [`tests/`](tests/). No model download and no AWS.

- `test_tool_routing.py`: changing the Decider choice changes which Strands tool executes.
- `test_capability_filter.py`: excluded options never reach the model, and no model call is made when only the
  fallback is admissible.
- `test_low_confidence.py`: below the threshold the most probable read-only option runs, else the fallback.
- `test_forbidden_action.py`: the gate blocks an excluded tool on any call path, including a direct call.
- `test_fail_closed.py`: an outage, an off-menu choice, a malformed answer or an inconsistent answer each route to
  the fallback.
- `test_replay.py`: a recorded answer is never applied to a changed state, and recorded outages replay at their own step.
- `test_pattern_is_domain_free.py`: nothing in the pattern imports SIMShift code.

## Limits

- `act_threshold` is a starting value. Tune it on held-out cases for your domain.
- Use the Decider HTTP server one request at a time. Upstream docs list a concurrency race, the server has no
  authentication, and upstream labels it as meant for local experiments.
- Option descriptions matter. Writing *when each tool suits* into the description noticeably changed choices in
  SIMShift's dev scenarios (tuning, not a held-out measurement).
