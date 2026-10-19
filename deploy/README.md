# Deploying SIMShift on AWS

The orchestrator runs on Bedrock AgentCore Runtime and calls the pinned Strands Decider 2B on a private ECS Fargate
task. Design and network rules: [docs/architecture.md](../docs/architecture.md#aws-deployment). Measured runs:
[docs/measurements.md](../docs/measurements.md#deployed-on-aws-eu-central-1).

Needs: an AWS profile allowed to create the resources below, Docker (arm64 builds), Node 20+, `uv`, the
strands-decider clone at `930e6d5d` with both model snapshots in the local Hugging Face cache (see the README's
"Live" section), and private subnets with a NAT or endpoints for ECR, S3, CloudWatch Logs and `bedrock-runtime`.
Every create call below sets the tags `environment` and `component`; change the values to your account's rules.

```bash
export AWS_PROFILE=<your-profile> AWS_REGION=eu-central-1
VPC=<vpc-id> SUBNETS=<subnet-a>,<subnet-b>    # private subnets

# 1. Private DNS namespace for the Decider (Cloud Map), then the Decider stack at zero tasks
aws servicediscovery create-private-dns-namespace --name simshift.local --vpc $VPC \
  --tags Key=environment,Value=dev Key=component,Value=ai
aws cloudformation deploy --stack-name simshift-decider --template-file deploy/decider/decider.yaml \
  --capabilities CAPABILITY_NAMED_IAM --tags environment=dev component=ai \
  --parameter-overrides VpcId=$VPC SubnetIds=$SUBNETS NamespaceId=<namespace-id> DesiredCount=0

# 2. Decider image (weights baked in, no download at start), pushed to the stack's repository
deploy/decider/build.sh simshift-decider:930e6d5d   # DECIDER_SRC and HF_HUB_CACHE override the default paths
REPO=$(aws cloudformation describe-stacks --stack-name simshift-decider \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)
aws ecr get-login-password | docker login --username AWS --password-stdin ${REPO%%/*}
docker tag simshift-decider:930e6d5d $REPO:930e6d5d && docker push $REPO:930e6d5d

# 3. AgentCore runtime. Put the stack's RuntimeSecurityGroupId and your subnets into
#    deploy/agentcore/agentcore/agentcore.json, and your account into aws-targets.json (gitignored):
#    [{"name": "default", "account": "<account-id>", "region": "eu-central-1"}]
npm i -g @aws/agentcore@0.31.1
make agentcore-bundle                       # copies simshift/ and patterns/ next to main.py
cd deploy/agentcore && agentcore deploy --dry-run -y && agentcore deploy -y && cd ../..
```

Every `agentcore deploy` turns on CloudWatch Transaction Search for the whole account and sets the X-Ray indexing
rule `Default` to 100%, although this runtime has OpenTelemetry off. Set it back to 1% after each deploy:
`aws xray update-indexing-rule --name Default --rule '{"Probabilistic":{"DesiredSamplingPercentage":1}}'`.

## Run

```bash
aws ecs update-service --cluster simshift --service decider --desired-count 1   # about 3 minutes to healthy
.venv/bin/python deploy/invoke.py TRANSIENT --out runs/aws-transient.json
.venv/bin/python deploy/invoke.py BR_PROFILE                     # stops at the approval gate, prints the proposal id
.venv/bin/python deploy/invoke.py BR_PROFILE --approve-id <id>   # a human approved that id: the switch runs
aws ecs update-service --cluster simshift --service decider --desired-count 0   # stop paying for the task
```

`invoke.py` writes a trace only if every Decider call reached the deployed Decider and Bedrock reported no error.
The approved call re-runs the whole incident, so Bedrock writes a new plan review that the human has not read; the
approval was given after the review from the first call, and the gate does not read either review. In the recorded
Brazil runs the first review recommended proceeding and the second did not (it asked for a staged canary). The twin is deterministic, so the proposal id is the same in both calls; any other id
leaves the proposal pending.

## Tear down

```bash
aws cloudformation delete-stack --stack-name AgentCore-simshift-default   # the AgentCore runtime and its role
aws cloudformation wait stack-delete-complete --stack-name AgentCore-simshift-default   # releases the runtime's ENIs
aws ecr batch-delete-image --repository-name simshift-decider --image-ids imageTag=930e6d5d
aws cloudformation delete-stack --stack-name simshift-decider
aws cloudformation wait stack-delete-complete --stack-name simshift-decider   # the namespace must be empty first
aws servicediscovery delete-namespace --id <namespace-id>
```

Left behind, delete by hand if you want them gone: the runtime's log group under `/aws/bedrock-agentcore/runtimes/`
(the service creates it, not the stack) and the account-wide Transaction Search setting
(`aws xray update-trace-segment-destination --destination XRay` turns it off; other runtimes may use it).
