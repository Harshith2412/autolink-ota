# Optional AWS deployment

**Status: not deployed or validated.** No AWS credentials or Terraform were available in the build environment.
Nothing here runs automatically, and applying it creates billable resources.

## What the Terraform creates (`infrastructure/terraform/main.tf`)

- A versioned, KMS-encrypted, private S3 bucket for firmware objects with a TLS-only bucket policy
- A CloudWatch log group with configurable retention
- A least-privilege IAM policy for the backend runtime (S3 get/put under `firmware/`, log writes)

It deliberately does not create compute. API Gateway + Lambda would not fit this backend well: image downloads
need Range requests and long transfers, and the device protocol is chatty, so a container service (ECS Fargate or
App Runner) behind an ALB with TLS is the more natural host.

## Steps

```bash
cd infrastructure/terraform
terraform init && terraform validate
terraform plan -out plan.tfplan      # review resources and cost
terraform apply plan.tfplan
```

Then run the backend container (`infrastructure/docker/backend.Dockerfile`) with the IAM policy attached,
switch `LocalBlobStore` for `S3BlobStore` in `create_app` (not wired to configuration yet), send structured logs
(already JSON on stderr) to the log group, and terminate TLS at the load balancer. The S3 store code exists but has
never been executed.

PostgreSQL (RDS) would also be needed for more than one backend instance; the repository layer uses portable SQL
but the driver integration is not implemented (`docs/known-limitations.md`).

Tear down with `terraform destroy` (the bucket must be emptied first because `force_destroy = false`).
