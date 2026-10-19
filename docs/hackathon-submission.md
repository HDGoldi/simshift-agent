# Hackathon submission checklist

**Event:** Agent Experience Hackathon: Strands Decider (AWS Builder Center), submissions close 2026-10-23 23:59 PT.
**Tags:** `#strands-decider-2b` `#tool-selection`

| Requirement (from the official rules) | Where it is | Status |
|---|---|---|
| Working agent built on AWS | Strands agent; Bedrock in eu-central-1; AgentCore Runtime + Decider on Fargate planned | partly: Bedrock on AWS, hosting pending |
| Strands Decider 2B handles at least one meaningful decision | next-tool selection at every step; the choice decides which Strands tool runs ([README](../README.md#the-decision-decider-makes)) | done |
| Paired with Amazon Bedrock for the generative part | profile-change plan review, outcome explanation, and an orchestrator mode where Bedrock runs the loop through two zero-argument tools ([`simshift/orchestrator.py`](../simshift/orchestrator.py)) | done; 6 live orchestrated runs recorded |
| Public code repository with the agent's source | this repository | done |
| Reusable Decider decision pattern, clearly labeled: typed question + options, wiring, short note | [`patterns/capability_aware_router/`](../patterns/capability_aware_router/README.md) | done |
| Approved OSI license | [Apache-2.0](../LICENSE) | done |
| Article on AWS Builder Center | draft: [`docs/article/article.md`](article/article.md); Builder Center link: _TBD_ | draft done, publishing pending |
| Public demo video under 3 minutes (YouTube/Vimeo/Facebook/Youku), no unlicensed marks or music | script: [`docs/article/video-script.md`](article/video-script.md); link: _TBD_ | script done, recording pending |
| Original, not previously published | first public commit 2026-10-18, during the submission period | done |

Encouraged, not required: a measured latency/cost comparison against an LLM, decision accuracy, low-confidence
handling. All three are in: low-confidence routing is visible in every trace, and
[`docs/benchmark/`](benchmark/) compares rules, random, Decider and two Bedrock-only choosers (with and without a
stated confidence) on 60 generated incidents, with accuracy, latency and Bedrock token counts
([measurements](measurements.md#benchmark)).
Latency on AWS hardware is not measured yet.

## Pre-submit QA

- [ ] Open the repo logged out: README, LICENSE, pattern README and tests are visible.
- [ ] Open the video logged out: it is public and under 3:00.
- [ ] The article names the Decider decision, the Bedrock role, and the limitations.
- [ ] Both tags are applied exactly.
- [ ] No credentials, account IDs or real customer data in the repo or video.
- [ ] Every number in the article and video matches a committed file (`docs/measurements.md`, `docs/benchmark/`).
- [ ] The UI screenshots and the video show the SIMULATED FLEET badge.
- [ ] Telecom claims stay within [telecom-fidelity.md](telecom-fidelity.md): nothing is called standards-validated,
      certified or SGP.32-compliant, and every "not modelled" item is still not claimed anywhere.
