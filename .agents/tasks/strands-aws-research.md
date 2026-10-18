# SIMShift — Strands Agents and AWS architecture research

**Research/source access date:** 2026-10-18
**Scope:** Current first-party Strands Agents Python APIs, Amazon Bedrock integration, causal Decider-to-Strands tool routing, and realistic AWS hosting for the Strands controller and Decider 2B.
**Cloud activity:** No paid inference, deployment, or resource mutation was performed. An unauthenticated AWS CLI preflight failed before any service listing; details are in §10.

## 1. Executive recommendation

### Safest MVP

Use **one persistent x86_64 NVIDIA GPU EC2 instance in `eu-central-1`** for the first AWS vertical slice. Run the pinned Decider process and the SIMShift FastAPI/Strands controller on that host, bind the unauthenticated Decider server to loopback (or use the engine in-process), and give the EC2 instance role narrowly scoped Bedrock inference permission. A **`g4dn.2xlarge` is a reasonable first benchmark candidate**, not a guaranteed final size: AWS documents 32 GiB host memory and one 16 GiB NVIDIA T4; the current Decider source supports CUDA. Keep the instance running and warm only for test/demo windows, then stop it.

This is the lowest-risk route because it has one deployment, no cross-service network path, no AgentCore microVM memory/image conflict, no ARM64/CUDA packaging mismatch, and an official Strands-on-EC2 deployment path. It still needs account verification for EC2 GPU quota/capacity, `RunInstances`/`PassRole`, Bedrock model availability, and actual warm latency and cost.

### Fallbacks

1. **No GPU quota/capacity:** use a memory-sufficient CPU EC2 instance for functional completion. The already-observed local pinned Decider run needed about 11.234 GiB peak RSS and took seconds per request; therefore select at least 16 GiB, preferably 32 GiB, keep it warm, and make no low-latency claim. This is slower but preserves the required real causal decision.
2. **Managed split architecture:** put only the lightweight code-based Strands+Bedrock controller in an AgentCore Runtime microVM and put Decider on **AgentCore Runtime Instances** with a supported NVIDIA GPU in Frankfurt or Ireland. This is operationally attractive later, but it adds an adapter, VPC/service setup, AgentCore IAM, first-session EC2 provisioning latency, and an AgentCore management fee.
3. **If AgentCore Instances is unavailable but managed model serving is required:** a custom SageMaker real-time endpoint is technically possible, but no first-party Decider SageMaker handler/image was found. Treat it as a later engineering project, not the hackathon critical path.

Do **not** put the present Decider 2B checkpoint inside an AgentCore microVM, Lambda, App Runner, or ordinary Fargate task for the MVP. The measured CPU model exceeds the AgentCore microVM's hard 8 GiB/session limit; the model/runtime artifacts and cold initialization are also a poor serverless fit. Lightweight Strands controllers can run on those services, but the model should be separate.

## 2. Status vocabulary and source precedence

- **VERIFIED FACT:** directly supported by the pinned first-party Strands source/release, official Decider source, or current AWS documentation.
- **OBSERVED:** measured in this workspace by the prior Decider research or by the preflight in this task; not a general service guarantee.
- **ACCOUNT-SPECIFIC UNKNOWN:** requires authenticated read-only checks in the intended AWS account/Region.
- **RECOMMENDATION:** architecture or operational judgment, not a vendor guarantee.

For exact Python behavior, the immutable Strands source is stronger than an unversioned docs page. For AWS availability, use the current per-feature AgentCore Region matrix rather than a marketing FAQ summary. Prices and quotas are especially time/account sensitive and must be rechecked before deployment.

## 3. Immutable software pins

### Strands Agents Python

**VERIFIED FACT**

| Item | Pin/evidence |
|---|---|
| Python package | `strands-agents==1.61.1` |
| Release | `python/v1.61.1`, published 2026-10-15 |
| Immutable release commit | `5cb880559e5ed88bd55de2779e72d060020f756b` |
| Python requirement | `>=3.10` (local Python 3.11.15 is compatible) |
| Wheel SHA-256 | `ee0720a0dacdfa2fc745f7260a58d9868067d7bd16c2cfbcb7631475fc0258dd` |
| sdist SHA-256 | `ccf14ac4b7a036f0460ca0a9e09407540910c0d2906729e8ceed097eb502e803` |
| License | Apache-2.0 in the first-party repository |

Pin the direct dependency exactly and lock all transitive dependencies in the project lockfile. `strands-agents` permits broad `boto3`/`botocore` ranges, so the package pin alone is not a complete reproducibility lock.

Primary sources:

- PyPI release and hashes: <https://pypi.org/project/strands-agents/1.61.1/>
- First-party release: <https://github.com/strands-agents/harness-sdk/releases/tag/python/v1.61.1>
- Immutable source tree: <https://github.com/strands-agents/harness-sdk/tree/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py>
- Apache license: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/LICENSE.APACHE>

All accessed 2026-10-18.

### Decider pins inherited and independently relevant

The complete model/API validation is in [`decider-research.md`](./decider-research.md). The AWS architecture must preserve these immutable pins:

- Decider source: `strands-labs/strands-decider` commit `930e6d5de16309be32579f5631a7369a3322140c`.
- Checkpoint: `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` commit `216d1ccb46a9e9b036eb9187b248db98480f77d4`.
- Base model: `Qwen/Qwen3.5-2B-Base` commit `b1485b2fa6dfa1287294f269f5fb618e03d52d7c`.
- Code, released adapter/head, and base declare Apache-2.0.

Official sources (accessed 2026-10-18):

- <https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c>
- <https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610/tree/216d1ccb46a9e9b036eb9187b248db98480f77d4>
- <https://huggingface.co/Qwen/Qwen3.5-2B-Base/tree/b1485b2fa6dfa1287294f269f5fb618e03d52d7c>

## 4. Exact Strands tool APIs and causal routing

### Registration and invocation

**VERIFIED FACT:** In Python 1.61.1, the public imports are:

```python
from strands import Agent, tool
from strands.models import BedrockModel
```

A function becomes a Strands tool with `@tool`; type hints plus the docstring generate its schema. It is registered by passing it in `Agent(tools=[...])`:

```python
@tool
def simulate_retry_with_backoff(incident_id: str) -> dict:
    """Run one bounded simulated retry.

    Args:
        incident_id: Synthetic incident identifier.
    """
    return {"incident_id": incident_id, "attempted": True}

agent = Agent(model=bedrock_model, tools=[simulate_retry_with_backoff])
```

Registered tools can be inspected through `agent.tool_names` and `agent.tool_registry.get_all_tools_config()`.

There are two invocation paths:

1. `agent("natural-language request")`: the model sees tool definitions and decides if/which tool to call. **Do not use this for SIMShift's primary selection**, because Bedrock would preselect the tool.
2. `agent.tool.simulate_retry_with_backoff(incident_id="BR_PROFILE")`: a direct, keyword-only programmatic invocation. The pinned `_ToolCaller` constructs a Strands `ToolUse`, executes it through `ToolExecutor._stream`, and returns a Strands `ToolResult`; it does not ask the model to choose the tool. This is the verified causal seam SIMShift needs.

Python's pinned implementation resolves an exact tool name and also maps underscores to registered hyphens. Use simple exact snake-case names and an explicit allowlisted map rather than relying on name normalization. Direct calls are recorded in history by default. If made while another invocation is active, `record_direct_tool_call=False` is required; the recommended architecture dispatches outside a Bedrock invocation, so this concurrency exception is avoided.

Immutable sources:

- Public imports: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/__init__.py>
- Tool decorator: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/tools/decorator.py>
- Agent registration: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/agent/agent.py>
- Direct caller: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/tools/_caller.py>
- First-party tool guide at the pinned tag: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/tools/using-tools.mdx>
- First-party custom tool guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/tools/custom-tools.mdx>

Accessed 2026-10-18.

### Simplest architecture that proves Decider causality

**RECOMMENDATION:** capability-filter first, call Decider second, validate the returned label, then invoke the corresponding registered tool directly. Use a separate no-tools Bedrock agent for explanation. This makes it structurally impossible for Bedrock to select the recovery tool.

```python
import os
from collections.abc import Callable

from strands import Agent, tool
from strands.models import BedrockModel

@tool
def simulate_retry_with_backoff(incident_id: str) -> dict:
    """Run a bounded retry in the deterministic simulator."""
    ...

@tool
def query_firmware_modem_diagnostics(incident_id: str) -> dict:
    """Read synthetic modem and firmware diagnostics."""
    ...

@tool
def prepare_guarded_profile_transition(incident_id: str) -> dict:
    """Evaluate prerequisites only; never enable a profile."""
    ...

region = os.environ["BEDROCK_REGION"]
model_or_profile = (
    os.environ.get("BEDROCK_INFERENCE_PROFILE")
    or os.environ["BEDROCK_MODEL_ID"]
)

bedrock = BedrockModel(
    region_name=region,
    model_id=model_or_profile,
    max_tokens=600,
    temperature=0.0,
)

tool_host = Agent(
    model=bedrock,  # constructed but not called during direct dispatch
    tools=[
        simulate_retry_with_backoff,
        query_firmware_modem_diagnostics,
        prepare_guarded_profile_transition,
    ],
)
explainer = Agent(model=bedrock, tools=[])

# Avoid arbitrary getattr: every Decider output must match this allowlist.
DISPATCH: dict[str, Callable[[str], object]] = {
    "retry_connection": lambda incident_id: tool_host.tool.simulate_retry_with_backoff(
        incident_id=incident_id
    ),
    "investigate_device": lambda incident_id: tool_host.tool.query_firmware_modem_diagnostics(
        incident_id=incident_id
    ),
    "evaluate_profile_change": lambda incident_id: tool_host.tool.prepare_guarded_profile_transition(
        incident_id=incident_id
    ),
}

def route(incident_id: str, observable_state: dict) -> object:
    eligible, removed = capability_filter(observable_state)
    decision = decider.choice(observable_state, eligible)  # real /v1/systemone
    if decision.choice not in eligible or decision.choice not in DISPATCH:
        raise ValueError("Decider returned a non-admissible tool")
    deterministic_policy_recheck(decision.choice, observable_state)
    result = DISPATCH[decision.choice](incident_id)
    trace(decision=decision, eligible=eligible, removed=removed, result=result)
    return result
```

Required proof tests:

- Replace only the Decider result with each admissible label and assert exactly the same-named registered Strands tool runs.
- Assert filtered/forbidden labels never enter the request and are rejected if returned.
- Spy on `BedrockModel.stream`; it must have zero calls before/directly during tool dispatch.
- Call the no-tools `explainer` only after tool evidence exists; its output may explain but cannot authorize or select execution.
- `evaluate_profile_change` must map only to a prerequisite/approval tool. A deterministic simulator method performs an approved virtual transition later.

An `InterventionHandler.before_tool_call` remains useful as defense in depth, and the first-party Decider repository demonstrates that hook, but it is not needed to establish primary selection. It should recheck policy, not turn Bedrock's proposed tool into Decider's nominal choice.

## 5. Version-correct Bedrock integration

### Strands configuration contract

**VERIFIED FACT:** `BedrockModel` 1.61.1 accepts keyword-only `region_name`, `boto_session`, `boto_client_config`, `endpoint_url`, and model settings including `model_id`, `max_tokens`, `temperature`, `top_p`, `streaming`, and guardrail/cache options. Supplying both `region_name` and `boto_session` raises `ValueError`. It creates a `bedrock-runtime` client and passes `self.config["model_id"]` as Bedrock Converse/ConverseStream's `modelId`.

The safe application contract is:

```text
BEDROCK_REGION=eu-central-1
BEDROCK_MODEL_ID=<account-verified foundation model ID>
BEDROCK_INFERENCE_PROFILE=<optional account-verified system profile ID or application profile ARN>
```

If `BEDROCK_INFERENCE_PROFILE` is set, use it as `BedrockModel(model_id=...)`; there is no separate Strands `inference_profile=` parameter. Bedrock's Converse API accepts a foundation model or inference profile in `modelId`. Explicitly require the Region and model/profile instead of inheriting Strands' changing default model.

Sources (accessed 2026-10-18):

- Immutable constructor and request building: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/models/bedrock.py>
- First-party Strands Bedrock guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/model-providers/amazon-bedrock.mdx>
- Bedrock Converse API: <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html>
- Inference profiles: <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles.html>

### Model/profile selection

**VERIFIED FACT:** `eu-central-1` has Bedrock control-plane and runtime endpoints. A geographic EU inference profile keeps processing inside its listed geography; a global profile can route worldwide. AWS says cross-Region routing has no added routing charge, pricing is based on the source Region, and global profiles are approximately 10% cheaper, but global routing requires accepting global processing and appropriate SCP behavior. Inference profiles do not support Provisioned Throughput.

**ACCOUNT-SPECIFIC UNKNOWN:** no model ID or inference profile was validated in this account because there are no credentials. Model/profile availability, lifecycle status, first-use access, Marketplace enablement where applicable, EU/global routing allowance, and actual token quotas are unresolved.

**RECOMMENDATION:** for MVP, use the least expensive small text model or geographic EU system-defined profile returned by authenticated listing in `eu-central-1`, preferably an Amazon model to avoid third-party Marketplace onboarding. Do not put an unverified model ID in the public default. Record the exact selected ID/ARN and Region in every trace. If data residency is not required and the account's SCP permits it, a global profile may improve availability/cost; otherwise select an EU profile.

Read-only discovery after credentials are available:

```bash
aws bedrock list-foundation-models \
  --region eu-central-1 \
  --by-output-modality TEXT \
  --by-inference-type ON_DEMAND

aws bedrock list-inference-profiles \
  --region eu-central-1 \
  --type-equals SYSTEM_DEFINED
```

Relevant official APIs:

- <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html>
- <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListInferenceProfiles.html>
- <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html>
- <https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html>
- Bedrock endpoints: <https://docs.aws.amazon.com/general/latest/gr/bedrock.html>

All accessed 2026-10-18.

## 6. Hosting options and tradeoffs

| Option | Strands+Bedrock controller | Decider 2B | Assessment |
|---|---|---|---|
| **Single GPU EC2** | Yes; official Strands guide, instance role calls Bedrock | Yes; CUDA on same host, loopback/in-process | **Recommended MVP.** Fewest moving pieces; persistent warm model. User manages OS, process, ingress, scaling, patching, and shutdown. |
| **CPU EC2** | Yes | Yes, with enough RAM | Functional fallback. Prior local observation was seconds/request and 11.234 GiB peak RSS. Do not promise interactive GPU latency. |
| **AgentCore microVM** | Good fit for controller; CodeZip or ARM64 container | **No for current checkpoint** | Hard 2 vCPU/8 GiB per session and 2 GiB image cap; direct code zip is 250 MB compressed/750 MB uncompressed. Use only as a thin caller. |
| **AgentCore Instances** | Yes | Yes on supported NVIDIA families | Promising managed option. EC2 managed instances run in the customer's account; x86_64/arm64, VPC, EBS, GPU, up to 14-day sessions. First invocation provisions EC2 and is slower. |
| **ECS on EC2 GPU / EKS GPU nodes** | Yes | Yes | Technically sound, but cluster/container/device-plugin work is unjustified for one demo unless the team already operates it. |
| **Ordinary ECS Fargate** | Good lightweight controller fit | Poor | Official Strands guide exists, but no GPU; CPU model is large/slow. Container build is also blocked locally at present. |
| **Lambda** | Possible short controller/explainer | No | Official Strands layer/guide exists, but model artifacts, initialization, memory, and cold starts make Decider a bad fit. |
| **App Runner** | Possible HTTP controller | No practical GPU path | Easy web service, but not a realistic 2B local model host. |
| **SageMaker real-time custom endpoint** | Usually separate controller | Plausible custom container | Managed inference/autoscaling, but no first-party Decider handler or validated image was found. More packaging/IAM/cost work than EC2. |

Official Strands deployment guides, pinned release (accessed 2026-10-18):

- EC2: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_amazon_ec2.mdx>
- AgentCore: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_bedrock_agentcore/python.mdx>
- Fargate: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_aws_fargate.mdx>
- Lambda: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_aws_lambda.mdx>
- EKS: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_amazon_eks.mdx>
- App Runner: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_aws_apprunner.mdx>

### EC2 candidate and accelerator constraints

**VERIFIED FACT:** AWS documents `g4dn.2xlarge` as x86_64 with 32 GiB host memory and one NVIDIA T4 with 16 GiB GPU memory. The Decider source supports CUDA, CPU, MPS, and MLX; only CUDA/CPU are relevant to Linux AWS. It has no AWS Neuron backend, so Inferentia/`inf2` is not a drop-in option even though AgentCore Instances supports `inf2`.

**RECOMMENDATION:** benchmark `g4dn.2xlarge` first; compare `g5.xlarge`/`g5.2xlarge` only if available and justified. Validate CUDA, `flash-linear-attention`, `causal-conv1d`, model load, peak RAM/VRAM, one- and concurrent-request latency, and recovery after restart. One Uvicorn worker avoids duplicating model memory.

Sources:

- EC2 accelerated-computing specifications: <https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html>
- Decider inference backends: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/docs/inference.md>

Accessed 2026-10-18.

## 7. AgentCore: only the currently supported paths

### Regional support

**VERIFIED FACT:** the current per-feature matrix says:

- AgentCore Runtime **microVMs** are supported in `eu-central-1` (Frankfurt) and all other European Regions listed in the matrix.
- AgentCore Runtime **Instances** are supported only in these Regions: US East (N. Virginia, Ohio), US West (Oregon), Europe (Frankfurt, Ireland), Asia Pacific (Mumbai, Singapore, Sydney, Tokyo). Among the relevant European choices, use Frankfurt or Ireland; Instances is not currently marked supported in London, Milan, Paris, Spain, or Stockholm.
- The high-level FAQ says AgentCore is available in fifteen Regions, while the newer per-feature matrix is broader and feature-specific. Deployment decisions should follow the matrix.

Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html> (accessed 2026-10-18).

### MicroVM constraints

**VERIFIED FACT:** one Runtime session has a non-adjustable maximum of **2 vCPU / 8 GiB**. Container image maximum is **2 GiB**. Direct code packages are **250 MB compressed / 750 MB uncompressed**. A synchronous request can run 15 minutes; asynchronous jobs up to 8 hours; request/response payload maximum is 100 MB. MicroVM Linux containers are ARM64.

The prior real CPU Decider smoke sampled **11.234 GiB peak RSS**, with about 4.3 GiB base cache, 225 MiB adapter snapshot, and 1.1 GiB environment. Therefore the current checkpoint does not fit the documented microVM memory allocation as tested. Downloading weights at startup does not fix memory; baking them also conflicts with image/package limits.

Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html> (accessed 2026-10-18).

### Instances constraints and fit

**VERIFIED FACT:** AgentCore Instances provisions and operates EC2 managed instances in the customer's account. It supports x86_64 and arm64, VPC networking, persistent EBS, multiple agents per session, and sessions up to 14 days. First invocation with a new session ID provisions the EC2 instance, so it is slower; later invocations reuse it. After a stop, invoking the same session can provision a new instance and reattach volumes. Supported NVIDIA families are `g4dn`, `g5`, `g6`, `g6e`, `gr6`, `g6f`, `gr6f`, and `g7e`; AgentCore supplies GPU drivers. It also lists `inf2`, but Decider lacks Neuron support.

A capacity provider defines instance types, networking, storage, and infrastructure roles and cannot be materially edited after creation. Each runtime still has its own execution role. EC2, EBS, and networking are visible/billable in the customer account.

Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html> (accessed 2026-10-18).

### Packaging/service contract

AgentCore's code-based route is the relevant one; the managed harness should not own the SIMShift loop because the project must prove Decider, not Bedrock/harness, owns primary tool selection.

- CodeZip is the default current AgentCore CLI build and does not require Docker.
- Container deployment requires ECR and, for microVMs, an ARM64 image. The current local container runtime is unusable, so it is not an immediate route.
- The AgentCore HTTP protocol uses port 8080 and `/invocations` (with other supported protocols including MCP, A2A, and AG-UI). The shipped Decider server exposes `/v1/systemone` and `/health`, so it is **not directly an AgentCore agent contract**. Wrap it or load its engine inside an AgentCore-compatible app.
- The first-party Strands wrapper uses `BedrockAgentCoreApp` and `@app.entrypoint` for code-based agent functions.

Sources:

- Service contract: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html>
- Current CLI/CodeZip flow: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-toolkit.html>
- Strands AgentCore guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_bedrock_agentcore/python.mdx>

Accessed 2026-10-18.

## 8. IAM and network boundaries

### Bedrock runtime role

**VERIFIED FACT:** Converse requires `bedrock:InvokeModel`; streaming needs `bedrock:InvokeModelWithResponseStream`. For an inference profile, IAM must allow the profile resource **and every destination foundation-model ARN associated with it**. `bedrock:ListFoundationModels`, `bedrock:ListInferenceProfiles`, and `bedrock:GetInferenceProfile` are read-only discovery permissions and need not remain on the production runtime role.

Minimal intent, with resource ARNs filled from authenticated discovery:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ],
    "Resource": [
      "<selected-profile-or-model-ARN>",
      "<each-profile-destination-foundation-model-ARN>"
    ]
  }]
}
```

Do not use static access keys on EC2/AgentCore. Use the EC2 instance profile or AgentCore runtime execution role. If pulling a private, SHA-verified model copy from S3, add only `s3:GetObject` for that prefix and KMS decrypt if applicable. CloudWatch logging permissions should be scoped to the application's log group.

Sources:

- Inference profile prerequisites/IAM: <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html>
- Bedrock IAM examples: <https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html>

Accessed 2026-10-18.

### AgentCore deployment/runtime roles

**VERIFIED FACT:** AWS's AgentCore CLI policy is intentionally broad for development (IAM role management, `PassRole`, CodeBuild, S3, ECR, logs, and AgentCore/CDK operations). AWS explicitly recommends custom least privilege for production. The runtime execution role needs Bedrock and observability permissions actually used. Instances additionally use an instance profile for system logs and an infrastructure role that AgentCore assumes to provision/manage EC2, ENIs, networking, and storage.

Source: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html> (accessed 2026-10-18).

### Decider network boundary

**VERIFIED FACT:** the Decider FastAPI server has no built-in authentication or TLS. For the single-host MVP, bind it to `127.0.0.1` and expose only the SIMShift API through an authenticated/TLS endpoint. For a split deployment, place Decider in private subnets/security groups, authenticate service-to-service calls, and never open port 8099 to the public Internet. Validate health without leaking checkpoint paths or internal details publicly.

## 9. Artifacts, licensing, cold starts, cost, and quotas

### Model artifacts and licensing

- The Decider adapter/head, base model, and source declare Apache-2.0. Preserve notices and attribution when redistributing.
- The model artifact's license file warns that training datasets have mixed terms. Do not publish training data or claim rights beyond the released artifacts.
- Pin both Hugging Face revisions, verify the exported checkpoint before serving, and record SHA/revision in `/health`/trace evidence.
- A host needs roughly the already-observed 4.3 GiB base cache plus adapter/runtime space; allocate materially more disk for CUDA wheels, logs, rollback versions, and temporary downloads. Persistent EBS or an immutable AMI avoids downloading on every boot.
- If copying model files into S3/ECR/AMI, review redistribution/notice obligations and secure the bucket/image. Do not bake account credentials.

### Cold starts

**OBSERVED locally, not AWS guarantees:** pinned CPU app/model load was 24.519 s on first load and 13.738 s with files cached; a repeat three-question evaluation took about 3.020 s. GPU startup and inference are unmeasured.

**RECOMMENDATION:** initialize one Decider engine at process startup, keep it warm for the demo, use readiness only after model load, and record cold and warm latency separately. On EC2, instance boot plus model initialization is the cold path. AgentCore Instances explicitly provisions EC2 on a new session's first invocation; persistent EBS saves downloads but not all provisioning/load time. MicroVM/Lambda scale-to-zero behavior is attractive for the light controller, not for this model.

### Costs

**VERIFIED FACT, prices accessed 2026-10-18:**

- AgentCore microVM pricing page lists v1 CPU `$0.0895/vCPU-hour` and memory `$0.00945/GB-hour`; v2 consumption CPU `$0.1276/vCPU-hour` and memory `$0.0169/GB-hour`. It bills per second with a one-second minimum and includes application/system usage; ECR/S3 and network are separate.
- AgentCore Instances charges the underlying EC2 instance in the customer account **plus an AgentCore management fee calculated from public EC2 On-Demand price**; EBS and transfer are additional. Savings Plans/Reserved Instances apply to EC2 compute, not the management fee. The static page text inspected did not expose a safe universal fee percentage, so do not invent one—use the current calculator/console.
- EC2 On-Demand Linux instances are billed by the second with a 60-second minimum; EBS, data transfer, public IPv4, load balancer/NAT, and logs can add cost.
- Bedrock is model-, Region-, and token-dependent. Cross-Region routing has no extra routing fee; AWS currently describes global profiles as approximately 10% cheaper than geographic profiles. Capture actual input/output tokens and price against the exact model/profile pricing page.

Sources:

- AgentCore pricing: <https://aws.amazon.com/bedrock/agentcore/pricing/>
- EC2 On-Demand pricing: <https://aws.amazon.com/ec2/pricing/on-demand/>
- Bedrock pricing: <https://aws.amazon.com/bedrock/pricing/>

**RECOMMENDATION:** use an AWS Budget and alarm before provisioning, tag all resources, run one GPU only during controlled benchmark/demo windows, and stop/delete according to the user's explicit deployment workflow. Promotional credits are not a reason to leave GPU compute running.

### Quotas/account constraints

**VERIFIED FACT:** Bedrock model inference is token-quota controlled (embedding exceptions use RPM), and AWS says effective account quotas can vary by Region, account age/history, and approved increases. AgentCore's 2 vCPU/8 GiB session maximum and image/package limits are non-adjustable. GPU EC2 uses accelerator-family quotas and can also face zonal capacity shortages.

**ACCOUNT-SPECIFIC UNKNOWN:** current `G and VT` On-Demand vCPU quota, exact instance offerings/capacity, Bedrock TPM, model/profile access, AgentCore runtime/capacity-provider quotas, SCP denies, Marketplace enablement, VPC/NAT/PrivateLink availability, and budget limits.

Source: <https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html> and <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html> (accessed 2026-10-18).

## 10. Read-only AWS preflight actually performed

Commands run on 2026-10-18:

```bash
aws configure list
aws sts get-caller-identity --output json
```

Redacted result (there were no identifiers to redact):

```text
profile    : <not set>
access_key : <not set>
secret_key : <not set>
region     : us-east-1  (environment)

aws: [ERROR]: An error occurred (NoCredentials): Unable to locate credentials.
```

**OBSERVED:** no authenticated AWS call succeeded. Therefore no caller identity, Bedrock model list, inference profile list, AgentCore availability, service quota, EC2 offering, or AWS resource was inspected in an account. **No Bedrock or Decider paid inference was invoked.** Public AWS documentation, GitHub, Hugging Face, and PyPI were accessed over HTTPS only.

After credentials are intentionally supplied, the harmless read-only preflight should include:

```bash
aws sts get-caller-identity                         # redact account/ARN in evidence
aws configure get region
aws bedrock list-foundation-models --region eu-central-1 \
  --by-output-modality TEXT --by-inference-type ON_DEMAND
aws bedrock list-inference-profiles --region eu-central-1 \
  --type-equals SYSTEM_DEFINED
aws ec2 describe-instance-type-offerings --region eu-central-1 \
  --location-type availability-zone \
  --filters Name=instance-type,Values=g4dn.2xlarge,g5.xlarge,g5.2xlarge
aws service-quotas list-service-quotas --service-code ec2 --region eu-central-1
aws service-quotas list-service-quotas --service-code bedrock --region eu-central-1
```

These commands list metadata only and do not invoke a model or create resources. Service Quotas output can be large; preserve only relevant quota names/values and redact account-linked fields.

## 11. Concrete MVP deployment sequence (recommendation, not executed)

1. Keep `strands-agents==1.61.1`, Decider source SHA, checkpoint SHA, base SHA, and all transitive dependencies in a lockfile.
2. Implement the explicit direct-call dispatch in §4 and prove Bedrock's invocation count is zero until after a tool result.
3. Add deterministic capability filtering and policy recheck before every direct call; profile evaluation cannot execute profile enablement.
4. Obtain credentials and run only the read-only checks in §10. Select a verified Bedrock text model or EU profile; record its ID/ARN and destination model ARNs.
5. Verify `g4dn.2xlarge` (or approved alternative) quota/offering and current hourly estimate in `eu-central-1`.
6. Build on an x86_64 CUDA-compatible EC2 image. Use an instance role, encrypted EBS, Session Manager rather than open SSH where possible, loopback Decider, and a supervised service (`systemd` or container) with startup/readiness checks.
7. Run one paid smoke only after explicit authorization in the implementation/deployment step. Capture Region, model/profile, Strands version, Decider revisions, tool list, raw decision, causal tool result, Bedrock token usage, cold/warm latency, and CloudWatch trace.
8. Shut down compute when not actively testing. Do not claim AgentCore, Bedrock, or AWS model invocation until the trace proves it.

## 12. Final fact/unknown/recommendation split

### Verified facts

- Strands Agents Python `1.61.1` and immutable release commit/hash are current and Python 3.11-compatible.
- `@tool` + `Agent(tools=[...])` registers functions; `agent.tool.<name>(keyword=...)` directly invokes a registered tool through the Strands executor without model tool selection.
- `BedrockModel(region_name=..., model_id=...)` is the pinned integration; `model_id` can carry a Bedrock inference profile ID/ARN because it is passed to Converse's `modelId`.
- Frankfurt supports Bedrock and AgentCore microVMs; the current feature matrix also supports AgentCore Instances there.
- AgentCore microVMs cannot host the measured current CPU Decider configuration within the 8 GiB hard session ceiling.
- AgentCore Instances supports selected NVIDIA GPU families and persistent EC2/EBS sessions; plain GPU EC2 is directly compatible with Decider CUDA.
- No AWS credentials or authenticated service access were available here.

### Account-specific unknowns

- Which Bedrock text model/profile is enabled and appropriate in `eu-central-1`.
- Bedrock/EC2/AgentCore quotas, SCPs, IAM, budget, GPU capacity, model lifecycle, and Marketplace status.
- Actual GPU load time, RAM/VRAM, decision latency, throughput, and cost.
- Whether AgentCore Instances permissions and its added management cost are acceptable.

### Recommendations

- Build the first honest AWS vertical slice on one warm GPU EC2 host; use CPU EC2 if GPU is blocked.
- Keep Bedrock entirely out of selection: direct-dispatch the Decider label to a registered Strands tool, then call a separate no-tools Bedrock explainer.
- Use explicit Region/model/profile environment configuration and no changing SDK default.
- Treat AgentCore microVM as a later lightweight controller host only; evaluate AgentCore Instances after the EC2 vertical slice works.
- Publish only observed latency/cost/results and preserve raw causal traces.

## 13. Source ledger

All sources below are first-party and were accessed 2026-10-18.

### Strands

1. Release `python/v1.61.1`: <https://github.com/strands-agents/harness-sdk/releases/tag/python/v1.61.1>
2. Immutable Python source: <https://github.com/strands-agents/harness-sdk/tree/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py>
3. Agent implementation: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/agent/agent.py>
4. Direct tool caller: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/tools/_caller.py>
5. Bedrock provider: <https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/models/bedrock.py>
6. PyPI package: <https://pypi.org/project/strands-agents/1.61.1/>
7. Tool guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/tools/using-tools.mdx>
8. Custom tools: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/tools/custom-tools.mdx>
9. Bedrock integration guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/model-providers/amazon-bedrock.mdx>
10. AgentCore deployment guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_bedrock_agentcore/python.mdx>
11. EC2 deployment guide: <https://github.com/strands-agents/harness-sdk/blob/python/v1.61.1/site/src/content/docs/user-guide/sdk/deploy/deploy_to_amazon_ec2.mdx>

### Decider/model

12. Decider source revision: <https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c>
13. Decider API schema: <https://github.com/strands-labs/strands-decider/blob/930e6d5de16309be32579f5631a7369a3322140c/src/strands_decider/schema.py>
14. Decider Strands examples: <https://github.com/strands-labs/strands-decider/tree/930e6d5de16309be32579f5631a7369a3322140c/examples/strands>
15. Pinned checkpoint: <https://huggingface.co/StrandsAgents/strands-decider-2B-qwen3.5-v1-2610/tree/216d1ccb46a9e9b036eb9187b248db98480f77d4>
16. Pinned base: <https://huggingface.co/Qwen/Qwen3.5-2B-Base/tree/b1485b2fa6dfa1287294f269f5fb618e03d52d7c>

### AWS

17. Bedrock Converse: <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html>
18. Bedrock model listing: <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html>
19. Inference profile listing: <https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListInferenceProfiles.html>
20. Inference profiles: <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles.html>
21. Inference profile IAM: <https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html>
22. Cross-Region inference: <https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html>
23. Bedrock quotas: <https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html>
24. Bedrock endpoints: <https://docs.aws.amazon.com/general/latest/gr/bedrock.html>
25. AgentCore feature/Region matrix: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html>
26. AgentCore limits: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html>
27. AgentCore Instances: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html>
28. AgentCore service contract: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html>
29. AgentCore IAM: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html>
30. AgentCore CLI/CodeZip quickstart: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-toolkit.html>
31. EC2 accelerated instance specifications: <https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html>
32. AgentCore pricing: <https://aws.amazon.com/bedrock/agentcore/pricing/>
33. Bedrock pricing: <https://aws.amazon.com/bedrock/pricing/>
34. EC2 On-Demand pricing: <https://aws.amazon.com/ec2/pricing/on-demand/>
