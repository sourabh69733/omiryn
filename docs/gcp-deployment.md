# GCP Deployment

This is the simple Cloud Run + Cloud SQL path for Omiryn.

Preferred split:

- Terraform creates infrastructure.
- Scripts build/deploy images, set secret values, read logs, and run one-off jobs.

## 1. Prepare Config

```bash
cp scripts/gcp-env.example .gcp.env
```

Edit `.gcp.env` with your project, region, service, and secret names.

## 2. Create Infrastructure With Terraform

```bash
cd infra/gcp
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`, then run:

```bash
terraform init
terraform plan
terraform apply
```

If Terraform is creating the database user:

```bash
terraform apply -var='sql_user_password=your-db-password'
```

Terraform outputs the Cloud SQL connection name and socket-style
`DATABASE_URL` template.

Copy these outputs into `.gcp.env`:

```bash
GCP_CLOUDSQL_CONNECTION_NAME=...
GCP_RUNTIME_SERVICE_ACCOUNT=...
```

## 3. Local Docker Debugging

Build the same image shape used for Cloud Run:

```bash
./scripts/docker-build.sh
```

Run locally on port `8080`:

```bash
./scripts/docker-run.sh
```

Open:

```bash
curl http://127.0.0.1:8080/health
```

Shell into the image:

```bash
./scripts/docker-shell.sh
```

Equivalent raw commands:

```bash
docker build -t omiryn:local .
docker run --rm --env-file .env -p 8080:8080 -e PORT=8080 omiryn:local
```

The helper scripts are safer than raw `docker run` for local debugging because
they strip shell-style quotes from env values, rewrite local Postgres hosts from
`localhost` to `host.docker.internal`, and mount `./data` into `/app/data` for
SQLite.

Override common settings:

```bash
IMAGE_TAG=test HOST_PORT=9000 ENV_FILE=.env ./scripts/docker-run.sh
```

## 4. Alternative: Bootstrap With Scripts

Use this only if you are not using Terraform yet.

```bash
./scripts/gcp-bootstrap.sh
```

This enables required APIs and creates the Artifact Registry repository.

Create Cloud SQL Postgres:

Set `DB_PASSWORD` in your shell or `.gcp.env`, then run:

```bash
./scripts/gcp-create-cloudsql.sh
```

Copy the printed Cloud SQL connection name into `.gcp.env` as:

```bash
GCP_CLOUDSQL_CONNECTION_NAME=project:region:instance
```

Use the printed socket-style `DATABASE_URL` as your Cloud Run database URL.

## 5. Create Secret Values

Examples:

```bash
DATABASE_URL='postgresql+psycopg://...' \
  ./scripts/gcp-set-secret.sh omiryn-database-url DATABASE_URL

ENCRYPTION_MASTER_KEY='...' \
  ./scripts/gcp-set-secret.sh omiryn-encryption-master-key ENCRYPTION_MASTER_KEY

SUPABASE_URL='https://...' \
  ./scripts/gcp-set-secret.sh omiryn-supabase-url SUPABASE_URL

SUPABASE_ANON_KEY='...' \
  ./scripts/gcp-set-secret.sh omiryn-supabase-anon-key SUPABASE_ANON_KEY
```

## 6. Deploy

```bash
./scripts/gcp-deploy.sh
```

## 7. Verify

```bash
./scripts/gcp-health.sh
./scripts/gcp-logs.sh
```

## 8. Encrypt Existing Data

Dry run first:

```bash
DRY_RUN=true ./scripts/gcp-encrypt-backfill.sh
```

Then run the real migration:

```bash
DRY_RUN=false ./scripts/gcp-encrypt-backfill.sh
```

Keep `ENCRYPTION_MASTER_KEY` safe. If it is lost, encrypted chats and context cannot be recovered.
