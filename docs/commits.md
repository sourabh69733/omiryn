# Git Commit Standards

This document defines a simple commit message standard for this project.

We follow **Conventional Commits**.

## Commit Format

```txt
type(scope): short message
```

Example:

```txt
feat(auth): add Google login
```

## Common Commit Types

### 1. feat

Use when adding a new feature.

```txt
feat(auth): add Google login
```

```txt
feat(infra): add GCP Cloud Run service
```

---

### 2. fix

Use when fixing a bug.

```txt
fix(api): handle missing user profile
```

```txt
fix(auth): validate expired token
```

---

### 3. refactor

Use when changing code structure without changing behavior.

```txt
refactor(api): simplify router registration
```

```txt
refactor(infra): move Terraform files to infra directory
```

---

### 4. docs

Use when updating documentation only.

```txt
docs(readme): update local setup steps
```

```txt
docs(api): add authentication usage guide
```

---

### 5. chore

Use for maintenance work, tooling, dependencies, or config changes.

```txt
chore(deps): upgrade FastAPI version
```

```txt
chore(terraform): organize GCP infra files
```

---

### 6. test

Use when adding or updating tests.

```txt
test(auth): add login validation tests
```

```txt
test(api): add user profile API tests
```

---

### 7. style

Use for formatting-only changes. No logic should change.

```txt
style(api): format imports
```

```txt
style(ui): fix indentation in dashboard page
```

---

### 8. perf

Use when improving performance.

```txt
perf(api): optimize user lookup query
```

```txt
perf(db): add index on user email
```

---

### 9. ci

Use for CI/CD changes.

```txt
ci(github): add deployment workflow
```

```txt
ci(vercel): update build command
```

---

### 10. build

Use for build system or package changes.

```txt
build(docker): add production Dockerfile
```

```txt
build(node): update package lock file
```

---

## Good Commit Examples

```txt
feat(terraform): add GCP provider config
```

```txt
feat(api): add health check endpoint
```

```txt
fix(vercel): update FastAPI entrypoint
```

```txt
refactor(infra): separate GCP Terraform modules
```

```txt
docs(commit): add commit message standards
```

---

## Bad Commit Examples

Avoid vague messages.

```txt
changes
```

```txt
fix bug
```

```txt
update code
```

```txt
final changes
```

Better versions:

```txt
fix(api): handle empty request body
```

```txt
chore(config): update environment variables
```

```txt
refactor(auth): clean up token validation logic
```

---

## Commit Rules

### 1. Keep commits small

Good:

```txt
fix(auth): handle expired JWT token
```

Bad:

```txt
feat: update auth, infra, UI, database and docs
```

---

### 2. Commit one logical change at a time

Good:

```txt
feat(infra): add GCP Terraform setup
```

Then separately:

```txt
docs(infra): add Terraform setup instructions
```

Bad:

```txt
feat: add infra and update docs and fix API
```

---

### 3. Use present tense

Good:

```txt
add user profile endpoint
```

Bad:

```txt
added user profile endpoint
```

---

### 4. Keep message short and clear

Good:

```txt
fix(db): prevent duplicate user creation
```

Bad:

```txt
fix issue where sometimes duplicate users were getting created because validation was missing
```

---

### 5. Use scope when helpful

The scope tells which part of the project changed.

Examples:

```txt
feat(api): add user endpoint
```

```txt
fix(db): update migration order
```

```txt
chore(terraform): organize GCP files
```

```txt
docs(readme): add deployment guide
```

---

## Suggested Scopes

Use these scopes based on the project area.

```txt
api
auth
db
infra
terraform
gcp
vercel
supabase
ui
docs
deps
config
ci
```

Examples:

```txt
feat(gcp): add Cloud Run service
```

```txt
fix(supabase): update database connection string
```

```txt
chore(config): add sample env file
```

---