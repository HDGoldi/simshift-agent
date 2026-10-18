# Capability-Aware Router

**Reusable Strands Decider 2B decision pattern · `#tool-selection`**

Your agent can call several tools, and some of them are risky. This pattern lets a small, fast decision model pick the **next tool**. A deterministic policy decides what is **allowed**, so the model can never run something unsafe.

```text
state ─▶ policy filter ─▶ Decider 2B "choice" ─▶ re-check ─▶ (approve if risky) ─▶ tool
             │ removed + reason        │ choice, probabilities, confidence
             ▼                         ▼
                         trace (one dict per step)
```

There's no domain code in here. It uses the standard library only, and has no dependency on `strands-decider` or torch. It talks to a running Decider server over HTTP.

## The decision

| Part | Value |
|---|---|
| Question type | `choice` |
| Question | Yours, e.g. *"Which next action most safely restores the service?"* |
| Option set | Your `Option`s **after** policy filtering. Each `description` is sent as that option's `criteria` text |
| Extra question | `noul`: *"Is the current evidence sufficient to choose a next step confidently?"* (recorded, not acted on) |
| Wire format | `POST /v1/systemone` (strands-decider 0.1.0) |

## Guarantees (each one tested in `tests/`)

| Guarantee | Test |
|---|---|
| The model's choice decides which tool runs | `test_tool_routing.py` |
| Removed options are never shown to the model; reasons are recorded | `test_capability_filter.py` |
| Below `low_confidence`, nothing runs, or only the allowed `fallback` does | `test_low_confidence.py` |
| A choice outside the allowed set is refused; risky options need `approve` | `test_forbidden_action.py` |

## Use it

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

Run the cloud-ops example:

```bash
strands-decider serve StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 --port 8099
python -m patterns.capability_aware_router.example            # real model
python -m patterns.capability_aware_router.example --fake     # wiring only, no model
python -m pytest patterns/capability_aware_router/tests       # no model needed
```

## Adapting it

Swap three things: the **question**, the **options** (with descriptions and tools), and the **policy**.

Tips from building SIMShift:
- **Describe state in plain sentences.** Raw data fields gave worse choices in our tests.
- **Don't leave one option.** If the policy removes all but one, the model isn't really deciding. Keep a safe read-only or escalate option.
- **Confidence is not accuracy.** Tune `low_confidence` on labelled cases from your own domain.

## Using it inside a Strands agent

`router.step()` is a plain function. You can call it from your agent loop, wrap it as a Strands `@tool`, or call it from a `before_tool_call` intervention. See the upstream [strands-decider examples](https://github.com/strands-labs/strands-decider/tree/main/examples/strands) for the intervention seam.

## License

Apache-2.0, same as the parent repository.
