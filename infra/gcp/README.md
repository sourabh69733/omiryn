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

If you want Terraform to create the Cloud SQL user too:

```bash
terraform apply -var='sql_user_password=your-db-password'
```

## Add Secret Values

From the project root:

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
