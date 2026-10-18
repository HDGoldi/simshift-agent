# Hackathon submission checklist

**Event:** Agent Experience Hackathon: Strands Decider (AWS Builder Center), submissions close 2026-10-23 23:59 PT.
**Tags:** `#strands-decider-2b` `#tool-selection`

| Requirement (from the official rules) | Where it is | Status |
|---|---|---|
| Working agent built on AWS | Strands agent; Bedrock in eu-central-1; AgentCore Runtime + Decider on Fargate planned | partly: Bedrock on AWS, hosting pending |
| Strands Decider 2B handles at least one meaningful decision | next-tool selection at every step; the choice decides which Strands tool runs ([README](../README.md#the-decision-decider-makes)) | done |
| Paired with Amazon Bedrock for the generative part | profile-change plan review + outcome explanation ([`simshift/agent.py`](../simshift/agent.py)) | done |
| Public code repository with the agent's source | this repository | done |
| Reusable Decider decision pattern, clearly labeled: typed question + options, wiring, short note | [`patterns/capability_aware_router/`](../patterns/capability_aware_router/README.md) | done |
| Approved OSI license | [Apache-2.0](../LICENSE) | done |
| Article on AWS Builder Center | link: _TBD_ | pending |
| Public demo video under 3 minutes (YouTube/Vimeo/Facebook/Youku), no unlicensed marks or music | link: _TBD_ | pending |
| Original, not previously published | first public commit 2026-10-18, during the submission period | done |

Encouraged, not required: a measured latency/cost comparison against an LLM, decision accuracy, low-confidence
handling. Low-confidence handling is implemented and visible in the traces ([measurements](measurements.md)).
The comparison is not done yet.

## Pre-submit QA

- [ ] Open the repo logged out: README, LICENSE, pattern README and tests are visible.
- [ ] Open the video logged out: it is public and under 3:00.
- [ ] The article names the Decider decision, the Bedrock role, and the limitations.
- [ ] Both tags are applied exactly.
- [ ] No credentials, account IDs or real customer data in the repo or video.
