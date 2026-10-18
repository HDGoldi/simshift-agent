# AWS deployment design — reviewable locally, not executed

## Status and selected topology

**IMPLEMENTED:** local application and non-provisioning opt-in tests only; no infrastructure artifact is complete. **VERIFIED:** generic Strands/AWS APIs and documented service limits cited below. **OBSERVED:** this workspace has no AWS credentials or usable container runtime; the local CPU Decider sampled about 11.234 GiB peak RSS. **SIMULATED:** telecom behavior. **UNVERIFIED:** account identity, Bedrock model/profile, IAM/SCP, quotas, subnet/endpoints, EC2 capacity, CUDA compatibility, price, deployment, and AWS execution. Nothing here claims a resource exists. CloudFormation, HF offline-cache hardening, stage-zero/AMI contracts, EC2 discovery IAM, private endpoint checks, bundle/Merkle validation, and cloud OFFLINE characterization are Phase 2 backlog items in [`../infra/ec2/implementation-backlog.md`](../infra/ec2/implementation-backlog.md), not local acceptance prerequisites.

Choose one persistent x86_64 EC2 host in `eu-central-1`, in a private subnet with **no Internet/NAT dependency**. Run the pinned Decider service as one warm process on `127.0.0.1:8099`; run SIMShift on that host through Systems Manager; call Bedrock using the instance role and a Bedrock Runtime interface endpoint. All application/dependency/model files come from a prebuilt, hash-verified S3 offline bundle. This topology matches the loopback-only Decider client and closes the prior private-subnet bootstrap gap.

`g4dn.2xlarge` (32 GiB host RAM, one 16 GiB T4) is the first parameterized benchmark candidate, **UNVERIFIED**, not a default guarantee. If quota/capacity/CUDA fails, select an x86_64 CPU instance with at least 16 GiB and preferably 32 GiB and make no latency claim. AgentCore microVM is rejected for the current checkpoint because observed CPU RSS exceeds its documented 8 GiB session maximum. AgentCore Instances is a later option, not the first slice.

## Phase 2 files (not implemented in Phase 1)

The following is a deferred design inventory. Their absence does not block the local-first slice, and this document does not claim they exist:

```text
infra/ec2/cloudformation.yaml
infra/ec2/parameters.example.json
infra/ec2/README.md
infra/ec2/iam/bedrock-policy.json
infra/ec2/systemd/decider.service
infra/ec2/systemd/simshift.env.example
infra/ec2/artifacts/manifest.schema.json
scripts/build-offline-bundle.sh
scripts/verify-offline-bundle.py
scripts/validate-artifact-manifest.py
scripts/bootstrap-host.sh
scripts/preflight-aws.sh
scripts/validate_iam_intent.py
constraints/linux-cpu.txt
constraints/linux-cuda.txt
```

No file initializes Git, provisions by default, embeds an account ID/credential, or supplies an unverified Bedrock model default. `infra/ec2/README.md` clearly separates local lint, authenticated read-only discovery, change-set review, deployment, run, stop, and delete. Deployment/run/teardown require separate user authorization.

## CloudFormation contract

Parameters have no account-specific defaults unless stated:

- `VpcId`, `PrivateSubnetId`, `PrivateRouteTableIds`, and `S3PrefixListId`.
- `InstanceType` (required; example file may show `g4dn.2xlarge` labeled benchmark candidate).
- `AmiId` (required approved x86_64 AMI; CUDA-compatible when GPU).
- `BedrockRegion` default `eu-central-1`.
- `BedrockResourceArns` list, required and rejecting empty/`*`; includes selected model/profile plus all destination foundation-model ARNs for an inference profile.
- `ArtifactBucketName`, `ArtifactObjectKey`, `ArtifactObjectVersion`, and `ArtifactBundleSha256`; no arbitrary HTTP URI.
- `DeciderDevice` `cpu|cuda`; `LogRetentionDays`; optional existing permissions-boundary ARN.

Resources are: one instance security group, one endpoint security group, gateway S3 endpoint on the supplied private route tables, interface endpoints in the private subnet for `ssm`, `ssmmessages`, `ec2messages` (retained where Region/agent supports it), `logs`, and `bedrock-runtime`; one encrypted EBS volume; instance role/profile; scoped log group; and EC2 instance. Private DNS is enabled for interface endpoints. The VPC must have DNS support/hostnames enabled; preflight treats otherwise as fatal. The EC2 resource has explicit `DependsOn` entries for all interface endpoints, the S3 gateway endpoint, and generated route/association resources so user data cannot race private connectivity creation.

There is no inbound rule for 8099 or SSH. The instance SG allows TCP 443 only to the endpoint SG/VPC endpoint addresses and the supplied regional S3 managed prefix list; no `0.0.0.0/0` or `::/0` egress. The endpoint SG allows 443 from the instance SG. Decider binds to loopback. SSM is the operator channel. EBS is encrypted, IMDSv2 is required, public IP association is disabled, and the instance runs an unprivileged service user.

The instance role allows:

- SSM managed-instance messaging required by the installed SSM agent.
- `s3:GetObject` and `s3:GetObjectVersion` only for the exact artifact bucket/key/version; optional `s3:GetBucketLocation` on that bucket.
- `logs:CreateLogStream`, `logs:DescribeLogStreams`, and `logs:PutLogEvents` only for the stack log group.
- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` only for supplied non-wildcard resources.

It grants no EC2/IAM mutation, broad `bedrock:*`, S3 listing/write, or static secrets. Read-only model/quota/offering discovery belongs to the operator identity, not runtime. The template/IAM validator fails wildcard actions/resources for Bedrock and artifact access.

## Offline bundle contract

Build the bundle on a compatible x86_64 networked build machine before deployment; do not build/download it on the private host. `scripts/build-offline-bundle.sh` is reviewable and explicit—it does not upload unless a separately authorized operator command does so. The non-circular layout is:

1. A deterministic `.tar.zst` archive is the S3 object. CloudFormation/operator input supplies its exact S3 version ID, byte length, and SHA-256 **outside** the archive. Bucket versioning is mandatory.
2. The archive contains `files.manifest.json`. That manifest explicitly excludes itself and lists every other regular file as `{path, bytes, sha256}` sorted by UTF-8 path bytes. It contains no archive digest.
3. Paths are normalized relative POSIX paths and reject absolute paths, empty/`.`/`..` segments, backslashes, duplicate or case-colliding entries, symlinks, hardlinks, devices, FIFOs, and sockets. The archive contains exactly the manifest plus its listed regular files—no extras.
4. `decider-manifest.json` records `files.manifest.json`'s exact byte SHA and references adapter/base/dependency artifacts by explicit listed file paths. Multi-file logical artifacts use the Merkle algorithm defined in `docs/decider-api.md`; no directory receives an undefined SHA.

The listed files include application source and `uv.lock`; a hash-pinned `requirements-linux-{cpu|cuda}.lock`; a complete wheelhouse; `strands-agents==1.61.1`; Decider source built from commit `930e...`; pinned adapter `216d...`; pinned base `b148...`; provenance/licenses/notices; device constraint and compatibility declarations; systemd units; and bootstrap scripts. CPU and CUDA archives are distinct and no lock is relabeled.

The build script downloads only immutable revisions, runs `python -m strands_decider.hf_export verify`, checks `provenance.json`, emits the internal manifest last, builds the archive deterministically (fixed ownership/mode/mtime/order), computes external metadata after the archive closes, and immediately calls the same `scripts/verify-offline-bundle.py` used by bootstrap. The required round-trip test builds a minimal fixture archive, verifies it, and proves that archive-byte changes, manifest self-inclusion, extra files, path anomalies, logical-root changes, and wrong external SHA all fail.

On host, bootstrap requests `GetObjectVersion` for the exact version, checks returned version/length and whole-archive SHA before extraction, safely extracts into a staging directory, verifies manifest exclusion and every file/hash/size, verifies logical roots plus Decider export/provenance, and atomically promotes `/opt/simshift/releases/<archive-sha>`. Dependencies install offline from the wheelhouse with `uv pip install --require-hashes --no-index --find-links ...`. Any missing/extra file, mismatch, wrong architecture/device declaration, or unsafe archive member is fatal; no service starts and the prior release remains selected.

## Endpoint and bootstrap preflight

`bootstrap-host.sh` must stop before installation/service enablement unless all checks succeed:

1. Acquire IMDSv2 token and confirm Region `eu-central-1` (do not persist instance/account identifiers).
2. For interface endpoints (`ssm`, `ssmmessages`, optional `ec2messages`, `logs`, `bedrock-runtime`), require private DNS enabled and resolved addresses inside the VPC; reject public resolution for these endpoints only.
3. For S3, do **not** require private DNS/private addresses. Query instance/VPC metadata and the CloudFormation-provided route table and assert it contains the regional S3 managed prefix-list route targeting the exact expected gateway endpoint ID. Then `HeadObject`/`GetObjectVersion` the exact bucket/key/version, assert the returned version and length, and verify archive SHA. VPC flow/route evidence is retained when available; route mismatch is fatal.
4. Confirm SSM agent is installed/running and its endpoint handshake succeeds.
5. Confirm CloudWatch Logs endpoint/auth by creating/using the scoped stream and writing one bootstrap status event.
6. Confirm Bedrock Runtime endpoint TLS/SigV4 reachability without paid inference using a harmless invalid/denied request whose expected HTTP authentication/validation response proves the private endpoint; do not treat DNS alone as sufficient. Actual model authorization remains `UNVERIFIED` until opt-in inference.
7. Confirm no route/default egress or listener exposes port 8099; confirm loopback bind after startup.
8. Validate Decider manifest/artifacts and exact health consistency before marking `decider.service` ready.

Failure is fatal and logged without credentials. Endpoint checks are planned for future CloudFormation/boot tests; local static lint alone would not be deployment proof.

## Services

`decider.service` runs as `simshift`, with read-only release/model directories, writable bounded cache/log paths, one worker, and:

```text
strands-decider serve <verified-local-checkpoint> \
  --device <cpu|cuda> --host 127.0.0.1 --port 8099 --strict-window
```

Systemd start limits and restart bursts are bounded. Readiness requires exact `/health` consistency with the trusted manifest; health strings are not presented as artifact attestation. The service never exposes health externally.

SIMShift is run on demand through SSM (or a bounded oneshot unit) with explicit scenario/trace destination. `simshift.env` contains non-secret `BEDROCK_REGION`, chosen model/profile reference, Decider URL, and manifest path. It contains no static AWS keys. Trace/evidence is copied to an approved S3 evidence prefix only by an optional separately scoped/operator-authorized path, not the runtime role defined above.

## Bedrock adapter and IAM

Runtime configuration requires:

```text
BEDROCK_REGION=eu-central-1
BEDROCK_INFERENCE_PROFILE=<account-verified ID/ARN>  # preferred when present
# or BEDROCK_MODEL_ID=<account-verified model ID>
```

The design has no public default because account availability is unknown. Strands 1.61.1 receives the profile through `model_id`, not a nonexistent `inference_profile` parameter:

```python
BedrockModel(
    region_name=region,
    model_id=inference_profile or model_id,
    temperature=0.0,
    max_tokens=600,
    boto_client_config=Config(
        connect_timeout=5, read_timeout=60,
        retries={"max_attempts": 2, "mode": "standard"},
    ),
)
```

A no-tools Agent explains sanitized post-tool evidence once. If both profile and model are set, profile wins and the selection is traced. Missing configuration fails before a Bedrock-mode run. Runtime explanation error cannot reverse a simulated action; enabled AWS integration testing treats it as test failure.

## Preflight, acceptance, and lifecycle

Current local non-provisioning acceptance commands are limited to the implemented Phase 1 tree:

```bash
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src patterns/capability_aware_router
uv run python scripts/check_license_headers.py
bash -n scripts/*.sh
```

The CloudFormation, IAM-intent, artifact-manifest, and offline-bundle commands described above are Phase 2 plans and are not runnable until those listed artifacts and their chosen lint dependencies are implemented. Future checks would prove only local shape/static policy. After explicit credential authorization, a future `scripts/preflight-aws.sh` may perform read-only STS identity (redacted), VPC/subnet/route/endpoint discovery, Bedrock model/profile discovery, EC2 offering/quota lookup, and CloudFormation validation. It must create nothing. A change set, deployment, paid inference, stopping, and deletion are separate operator actions requiring explicit approval.

Opt-in test against already authorized/running resources:

```bash
SIMSHIFT_RUN_AWS_INTEGRATION=1 \
BEDROCK_REGION=eu-central-1 \
BEDROCK_MODEL_ID='<account-verified-id>' \
STRANDS_DECIDER_URL=http://127.0.0.1:8099 \
STRANDS_DECIDER_MANIFEST=/opt/simshift/current/decider-manifest.json \
uv run pytest -q -m aws_integration
```

Without the opt-in, skip exactly `set SIMSHIFT_RUN_AWS_INTEGRATION=1`. Once enabled, missing credentials/config, endpoint/model denial, manifest/Decider failure, production-path semantic drift, or Bedrock failure fails; it never provisions. The AWS test first invokes the exact production coordinator for `BR_PROFILE` seed `20261018`, default `0.20` policy, and proposal-bound scripted simulated approval, asserting profile evaluation, all final gates, `ENABLED`, separate passing registration/telemetry checks, and `RESTORED`. Only then may the no-tools Bedrock agent explain that public evidence. The test also runs exact `OFFLINE` seed `20261019` with the real Decider and asserts safe escalation, no transition record/lifecycle event, no approval consumption, and unchanged profile. Preserve source/lock/manifest hashes, Region, instance class, actual model/profile, raw health/decision/tool/gate/check/explanation trace, and cold/warm labels before any AWS-hosted claim. Set budgets/alarms through the user's approved process, run GPU only during controlled windows, stop it after testing, and delete only when explicitly authorized.

## Alternatives rejected

NAT-based installation was not chosen because it weakens reproducibility and leaves third-party availability in bootstrap. Public Decider/private DNS options were rejected because the first slice only needs same-host loopback. AgentCore microVM cannot fit the observed CPU configuration; Lambda/App Runner/ordinary Fargate are poor 2B-model hosts. GPU ECS/EKS/SageMaker/AgentCore Instances remain plausible but add unvalidated packaging and operations beyond the first slice.

## Sources

Verified Strands and AWS research: [`.agents/tasks/strands-aws-research.md`](../.agents/tasks/strands-aws-research.md), including immutable Strands [`bedrock.py`](https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/models/bedrock.py) and direct caller [`_caller.py`](https://github.com/strands-agents/harness-sdk/blob/5cb880559e5ed88bd55de2779e72d060020f756b/strands-py/src/strands/tools/_caller.py). AWS references accessed 2026-10-18: [AgentCore limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html), [AgentCore Instances](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html), [Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html), [inference-profile IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html), and [EC2 accelerated specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html).