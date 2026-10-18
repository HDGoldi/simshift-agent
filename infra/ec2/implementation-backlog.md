# Phase 2 EC2 implementation backlog

These items are deliberately deferred and are not prerequisites for Phase 1:

- Produce and verify complete Hugging Face offline caches with network-disabled startup tests.
- Define the stage-zero bootstrap and approved AMI compatibility contract for x86_64 CPU/CUDA hosts.
- Separate operator read-only EC2/VPC/endpoint/quota discovery IAM from the minimal runtime role.
- Implement and review private SSM, Logs, Bedrock Runtime, and S3 endpoint/route validation.
- Build deterministic offline bundles, external archive metadata, safe extraction, exact file manifests, and logical-artifact Merkle verification.
- Add CloudFormation and IAM artifacts only after independent review; do not claim them complete from documentation alone.
- Characterize the normative OFFLINE scenario on the cloud runtime and retain raw evidence before making semantic or performance claims.
- Validate CUDA compatibility, instance availability, quotas, cost controls, alarms, stop procedures, and teardown separately.

Every cloud mutation, deployment, paid test, stop, or deletion requires explicit operator authorization outside the Phase 1 workflow.
