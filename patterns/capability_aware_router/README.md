# CapabilityAwareRouter — a Strands Decider 2B tool-selection pattern

> **Reusable decision pattern** for the Strands Decider 2B hackathon (`#strands-decider-2b` `#tool-selection`).
> Worked examples: [`example.py`](example.py) (web-service remediation) and [`simshift/agent.py`](../../simshift/agent.py)
> (IoT connectivity recovery: `make_router()` builds the router, `run()` calls `router.step()` each turn).

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

Run the self-contained, non-telecom example (it needs a local Decider server):

```bash
strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --device mlx --port 8099   # or --device cpu
python -m patterns.capability_aware_router.example
pytest patterns/capability_aware_router/tests      # no model or AWS needed
```

## Tested properties

- `test_tool_routing_follows_decider_choice`: changing the Decider choice changes which Strands tool executes.
- `test_capability_filter_never_offers_excluded_option`: excluded options never reach the model.
- `test_low_confidence_gathers_evidence_then_falls_back`: the low-confidence routes.
- `test_forbidden_action_denied_even_on_direct_call`: the gate blocks excluded tools on any call path.
- `test_only_fallback_admissible_skips_model_call`: no model call when there is nothing to decide.
- `test_decider_failure_fails_closed` and `test_non_admissible_choice_falls_back`: an outage or an off-menu answer routes to the fallback.
- `test_malformed_answer_fails_closed`: an answer with a missing or mistyped field routes to the fallback.
- `test_replay_refuses_a_different_question` and `test_replay_keeps_recorded_outages_in_order`: a recorded answer is
  never applied to a changed state, and recorded outages replay at their own step.

## Limits

- `act_threshold` is a starting value. Tune it on held-out cases for your domain.
- Use the Decider HTTP server one request at a time. Upstream docs list a concurrency race, the server has no
  authentication, and upstream labels it as meant for local experiments.
- Option descriptions matter. Writing *when each tool suits* into the description measurably changed choices in SIMShift.
