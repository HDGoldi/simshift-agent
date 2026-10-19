# SIMShift benchmark (2026-10-19)

10 incidents per family x 6 families, seeds 9000..9009. Synthetic twin. Approvals auto-granted (eval only). Hardware: Decider: MLX on Apple M4 Max laptop; Bedrock: eu-central-1.

| Metric | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| Incidents | 60 | 60 | 60 | 60 | 60 |
| First choice = preferred (%) | 95.0 | 28.3 | 50.0 | 81.7 | 81.7 |
| First action acceptable (%) | 95.0 | 41.7 | 86.7 | 83.3 | 81.7 |
| Correct end state, with the evidence (%) | 95.0 | 50.0 | 96.7 | 91.7 | 93.3 |
| Correct, no unnecessary eSIM change (%) | 95.0 | 50.0 | 96.7 | 91.7 | 93.3 |
| Unnecessary profile changes | 0 | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 1.98 | 2.58 | 1.72 | 1.73 |
| Mean simulated minutes | 52.3 | 61.5 | 54.5 | 52 | 51.2 |
| Chooser calls | 96 | 105 | 125 | 99 | 101 |
| Chooser latency p50 (ms) | 0.0 | 0.0 | 106.0 | 2086.2 | 2043.4 |
| Chooser latency p95 (ms) | 0.0 | 0.0 | 122.9 | 3431.1 | 3050.0 |

Correct end state by family (%):

| Family | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| operator | 100 | 30.0 | 100 | 100 | 100 |
| profile | 100 | 10.0 | 100 | 100 | 100 |
| application | 100 | 50.0 | 100 | 100 | 100 |
| unreachable | 100 | 100 | 100 | 100 | 100 |
| firmware | 100 | 50.0 | 80.0 | 100 | 100 |
| transient | 70.0 | 60.0 | 100 | 50.0 | 60.0 |

bedrock (eu.anthropic.claude-haiku-5-5): {'inputTokens': 47067, 'outputTokens': 26261} tokens; 4 answers without a usable option or cut off at the 512-token output limit, each routed to the fallback.

bedrock+conf (eu.anthropic.claude-haiku-5-5): {'inputTokens': 50423, 'outputTokens': 31181} tokens; 3 answers without a usable option and confidence or cut off at the 512-token output limit, each routed to the fallback.
