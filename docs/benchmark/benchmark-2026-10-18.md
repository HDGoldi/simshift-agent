# SIMShift benchmark (2026-10-18)

10 incidents per family x 6 families, seeds 9000..9009. Synthetic twin. Approvals auto-granted (eval only). Hardware: Decider: MLX on Apple M4 Max laptop; Bedrock: eu-central-1.

| Metric | rules | random | decider | bedrock |
|---|---:|---:|---:|---:|
| Incidents | 60 | 60 | 60 | 60 |
| First choice = preferred (%) | 95.0 | 31.7 | 50.0 | 81.7 |
| First action acceptable (%) | 95.0 | 46.7 | 86.7 | 81.7 |
| Correct end state (%) | 95.0 | 66.7 | 100.0 | 95.0 |
| Correct, no unnecessary eSIM change (%) | 95.0 | 66.7 | 100.0 | 95.0 |
| Unnecessary profile changes | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 2.05 | 2.58 | 1.72 |
| Mean simulated minutes | 52.3 | 62.6 | 54.5 | 50.2 |
| Chooser calls | 96 | 113 | 135 | 100 |
| Chooser latency p50 (ms) | 0.0 | 0.0 | 100.3 | 1908.2 |
| Chooser latency p95 (ms) | 0.0 | 0.0 | 128.7 | 3192.5 |

Correct end state by family (%):

| Family | rules | random | decider | bedrock |
|---|---:|---:|---:|---:|
| operator | 100 | 30.0 | 100 | 100 |
| profile | 100 | 20.0 | 100 | 100 |
| application | 100 | 100 | 100 | 100 |
| unreachable | 100 | 100 | 100 | 100 |
| firmware | 100 | 100 | 100 | 100 |
| transient | 70.0 | 50.0 | 100 | 70.0 |

Bedrock (eu.anthropic.claude-haiku-5-5): {'inputTokens': 45245, 'outputTokens': 22834} tokens, 5 answers without exactly one option name or cut off at the 512-token output limit; each was routed to the fallback.
