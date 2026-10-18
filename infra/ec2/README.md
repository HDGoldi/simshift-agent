# EC2 deployment status

No EC2, IAM, VPC endpoint, S3 bundle, AMI, or CloudFormation deployment artifact is complete or verified in Phase 1. The implemented vertical slice runs locally and accepts only a loopback Decider endpoint.

The topology in [`../../docs/aws-deployment.md`](../../docs/aws-deployment.md) is a design for later review, not proof that resources exist. The `aws_integration` test may target only resources that an operator has already deployed and separately authorized; it performs inference checks and never provisions, modifies, or deletes cloud resources.

Phase 2 implementation work is listed in [`implementation-backlog.md`](implementation-backlog.md). It remains non-blocking for the local-first slice.
