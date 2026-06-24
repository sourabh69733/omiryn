# Omiryn GCP Terraform

Terraform owns the base infrastructure:

- required GCP APIs
- Artifact Registry
- Cloud SQL Postgres
- Secret Manager secret containers
- Cloud Run runtime service account
- IAM for Secret Manager and Cloud SQL
- optional Cloud Run service

Secret values are intentionally not stored in Terraform state. Use
`scripts/gcp-set-secret.sh` to add secret versions.

## First Run

```bash
cd infra/gcp
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`, then:

```bash
terraform init
terraform plan
terraform apply
```

For the lowest-cost dev instance, keep:

```hcl
sql_edition           = "ENTERPRISE"
sql_tier              = "db-f1-micro"
sql_public_ip_enabled = true
```

`ENTERPRISE_PLUS` needs a larger performance-optimized tier, so it will reject
`db-f1-micro`.

The simple setup keeps public IPv4 enabled because Cloud SQL requires at least
one connectivity path. Cloud Run can still use the Cloud SQL connector/socket.

If you want Terraform to create the Cloud SQL user too:

```bash
terraform apply -var='sql_user_password=your-db-password'
```

## Add Secret Values

From the project root:

```bash
./scripts/gcp-sync-secrets.sh
```

Or update one secret manually:

```bash
DATABASE_URL='postgresql+psycopg://...' \
  ./scripts/gcp-set-secret.sh omiryn-database-url DATABASE_URL

ENCRYPTION_MASTER_KEY='...' \
  ./scripts/gcp-set-secret.sh omiryn-encryption-master-key ENCRYPTION_MASTER_KEY
```

## Deploy App Image

Use the deploy script from the project root:

```bash
./scripts/gcp-deploy.sh
```

The deploy script is still useful because app image rollout is operational work,
not base infrastructure.

## Optional: Let Terraform Own Cloud Run

After the first image has been pushed, set:

```hcl
create_cloud_run_service = true
container_image          = "REGION-docker.pkg.dev/PROJECT/REPO/omiryn:TAG"
```

Then run:

```bash
terraform plan
terraform apply
```

## Optional: Custom Domain With HTTPS Load Balancer

After the Cloud Run service exists, set:

```hcl
create_https_load_balancer = true
load_balancer_domain_names = ["app.example.com"]
```

Then run:

```bash
terraform plan
terraform apply
```

Point your domain DNS to the `load_balancer_ip` output:

```text
A app.example.com -> LOAD_BALANCER_IP
```

The Google-managed certificate becomes active after DNS points to the load
balancer. It may take a while to provision.
