# SIMShift benchmark (2026-10-18)

10 incidents per family x 6 families, seeds 9000..9009. Synthetic twin. Approvals auto-granted (eval only). Hardware: Decider: MLX on Apple M4 Max laptop; Bedrock: eu-central-1.

| Metric | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| Incidents | 60 | 60 | 60 | 60 | 60 |
| First choice = preferred (%) | 95.0 | 31.7 | 50.0 | 83.3 | 78.3 |
| First action acceptable (%) | 95.0 | 46.7 | 86.7 | 83.3 | 81.7 |
| Correct end state, with the evidence (%) | 95.0 | 51.7 | 96.7 | 93.3 | 90.0 |
| Correct, no unnecessary eSIM change (%) | 95.0 | 51.7 | 96.7 | 93.3 | 90.0 |
| Unnecessary profile changes | 0 | 0 | 0 | 0 | 0 |
| Forbidden executions (audited) | 0 | 0 | 0 | 0 | 0 |
| Mean steps | 1.93 | 2.05 | 2.58 | 1.75 | 1.7 |
| Mean simulated minutes | 52.3 | 62.6 | 54.5 | 51.5 | 52.6 |
| Chooser calls | 96 | 113 | 135 | 101 | 100 |
| Chooser latency p50 (ms) | 0.0 | 0.0 | 100.9 | 2060.4 | 2065.9 |
| Chooser latency p95 (ms) | 0.0 | 0.0 | 128.3 | 3140.3 | 3295.7 |

Correct end state by family (%):

| Family | rules | random | decider | bedrock | bedrock+conf |
|---|---:|---:|---:|---:|---:|
| operator | 100 | 30.0 | 100 | 100 | 90.0 |
| profile | 100 | 20.0 | 100 | 100 | 100 |
| application | 100 | 50.0 | 100 | 100 | 100 |
| unreachable | 100 | 100 | 100 | 100 | 100 |
| firmware | 100 | 60.0 | 80.0 | 100 | 100 |
| transient | 70.0 | 50.0 | 100 | 60.0 | 50.0 |

bedrock (eu.anthropic.claude-haiku-5-5): {'inputTokens': 45739, 'outputTokens': 24820} tokens; 5 answers without a usable option or cut off at the 512-token output limit, each routed to the fallback.

bedrock+conf (eu.anthropic.claude-haiku-5-5): {'inputTokens': 45044, 'outputTokens': 26739} tokens; 10 answers without a usable option and confidence or cut off at the 512-token output limit, each routed to the fallback.
