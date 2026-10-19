# SIMShift benchmark (2026-10-19)

10 incidents per family x 6 families, seeds 9000..9009. Synthetic twin. Approvals auto-granted (eval only). Hardware: Decider: MLX on Apple M4 Max laptop; Bedrock: eu-central-1.

| Metric | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| Incidents | 60 | 60 | 60 | 60 | 60 |
| First choice = preferred (%) | 95.0 | 31.7 | 50.0 | 81.7 | 81.7 |
| First action acceptable (%) | 95.0 | 46.7 | 86.7 | 81.7 | 83.3 |
| Correct end state, with the evidence (%) | 95.0 | 51.7 | 96.7 | 91.7 | 88.3 |
| Correct, no unnecessary eSIM change (%) | 95.0 | 51.7 | 96.7 | 91.7 | 88.3 |
| Unnecessary profile changes | 0 | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 2.05 | 2.58 | 1.7 | 1.72 |
| Mean simulated minutes | 52.3 | 62.6 | 54.5 | 50.8 | 53.8 |
| Chooser calls | 96 | 113 | 135 | 100 | 100 |
| Chooser latency p50 (ms) | 0.0 | 0.0 | 93.9 | 2026.4 | 2050.6 |
| Chooser latency p95 (ms) | 0.0 | 0.0 | 118.8 | 3334.0 | 3292.3 |

Correct end state by family (%):

| Family | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| operator | 100 | 30.0 | 100 | 100 | 100 |
| profile | 100 | 20.0 | 100 | 100 | 100 |
| application | 100 | 50.0 | 100 | 90.0 | 100 |
| unreachable | 100 | 100 | 100 | 100 | 100 |
| firmware | 100 | 60.0 | 80.0 | 100 | 100 |
| transient | 70.0 | 50.0 | 100 | 60.0 | 30.0 |

bedrock (eu.anthropic.claude-haiku-5-5): {'inputTokens': 47679, 'outputTokens': 26994} tokens; 6 answers without a usable option or cut off at the 512-token output limit, each routed to the fallback.

bedrock+conf (eu.anthropic.claude-haiku-5-5): {'inputTokens': 50040, 'outputTokens': 31930} tokens; 8 answers without a usable option and confidence or cut off at the 512-token output limit, each routed to the fallback.
