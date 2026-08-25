# Standalone Admin App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the existing backend-served admin website into a standalone Cloudflare-hosted Vite app without weakening backend authorization or losing current admin pages.

**Architecture:** `apps/admin` owns the browser application and authenticates through Supabase Google OAuth. It calls the Cloud Run `/api/admin/*` endpoints with bearer tokens; FastAPI remains the only authorization authority and no longer serves admin static files.

**Tech Stack:** Vite 6, vanilla ES modules, Supabase JS, Cloudflare static assets, FastAPI, pytest/unittest, Node test runner

**Spec:** `docs/admin-app-separation-design.md`

## Global Constraints

- Preserve Dashboard, Users, Requests, and Usage behavior.
- Do not rewrite the existing admin dashboard to React during this migration.
- Never put a Supabase service-role key or backend secret in the frontend.
- Every admin API request must carry the current Supabase bearer token.
- Backend `require_admin_user` remains authoritative for both `ADMIN_EMAILS` and `ADMIN_USER_IDS`.
- Cloud Run must not serve admin HTML, JavaScript, or CSS after migration.
- Admin API responses must use `Cache-Control: no-store`.
- Production admin origin is exactly `https://admin.omiryn.com`.

---

### Task 1: Authenticated Admin API Client

**Files:**
- Create: `apps/admin/src/api.js`
- Create: `apps/admin/src/api.test.js`
- Create: `apps/admin/src/auth.js`

**Interfaces:**
- Produces: `buildApiUrl(baseUrl, path): string`
- Produces: `createAdminFetch({ apiBaseUrl, fetchImpl, getAccessToken, onUnauthorized }): (path, init?) => Promise<Response>`
- Produces: `ensureAdminSession(): Promise<boolean>`
- Produces: `signInWithGoogle(): Promise<void>`
- Produces: `signOut(): Promise<void>`
- Produces: `adminFetch(path, init?): Promise<Response>`

- [ ] **Step 1: Write failing URL and bearer-header tests**

```js
test("builds backend URLs without duplicate slashes", () => {
  assert.equal(buildApiUrl("https://api.omiryn.com/", "/api/admin/overview"),
    "https://api.omiryn.com/api/admin/overview");
});

test("adds the current bearer token to admin requests", async () => {
  let received;
  const adminFetch = createAdminFetch({
    apiBaseUrl: "https://api.omiryn.com",
    getAccessToken: async () => "admin-token",
    fetchImpl: async (url, init) => {
      received = { url, headers: new Headers(init.headers) };
      return new Response("{}", { status: 200 });
    },
    onUnauthorized: async () => {},
  });
  await adminFetch("/api/admin/overview");
  assert.equal(received.headers.get("Authorization"), "Bearer admin-token");
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test apps/admin/src/api.test.js`

Expected: FAIL because `apps/admin/src/api.js` does not exist.

- [ ] **Step 3: Implement the dependency-injected API helper**

Implement URL normalization, bearer header injection, and a `401` callback. Do not treat `403` as unauthenticated because it means the identity is valid but not authorized.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `node --test apps/admin/src/api.test.js`

Expected: all API helper tests pass.

- [ ] **Step 5: Implement Supabase auth adapter**

Use `/api/auth/config`, `createClient`, `auth.getSession()`, Google OAuth with the current page as `redirectTo`, and local sign-out. Export a production `adminFetch` configured from `VITE_API_BASE_URL`.

- [ ] **Step 6: Check syntax**

Run: `node --check apps/admin/src/api.js && node --check apps/admin/src/auth.js`

Expected: both files parse successfully.

- [ ] **Step 7: Commit**

```bash
git add apps/admin/src/api.js apps/admin/src/api.test.js apps/admin/src/auth.js
git commit -m "feat: add authenticated admin API client"
```

---

### Task 2: Standalone Admin Frontend

**Files:**
- Create: `apps/admin/index.html`
- Create: `apps/admin/src/main.js`
- Create: `apps/admin/src/styles.css`
- Source: `src/admin/static/index.html`
- Source: `src/admin/static/app.js`
- Source: `src/admin/static/styles.css`

**Interfaces:**
- Consumes: `adminFetch`, `ensureAdminSession`, `signInWithGoogle`, and `signOut` from Task 1.
- Produces: standalone routes `/`, `/users`, `/requests`, and `/usage`.

- [ ] **Step 1: Write failing shell contract test**

Create `apps/admin/src/shell.test.js` that reads `apps/admin/index.html` and asserts it contains `#admin-auth`, `#admin-app`, `#admin-sign-in`, `#admin-sign-out`, and `/src/main.js`, and does not contain `/admin/static/`.

- [ ] **Step 2: Run the shell test and verify RED**

Run: `node --test apps/admin/src/shell.test.js`

Expected: FAIL because the standalone shell does not exist.

- [ ] **Step 3: Move the existing shell and assets**

Copy the existing admin markup and styles into `apps/admin`, change navigation links from `/admin/...` to domain-root routes, load `/src/main.js` as a module, and add dedicated loading, Google sign-in, access-denied, and sign-out controls. Keep the operational dashboard markup unchanged.

- [ ] **Step 4: Adapt the existing JavaScript**

Move `src/admin/static/app.js` to `apps/admin/src/main.js`, import the Task 1 auth functions, replace all four direct `fetch(...)` calls with `adminFetch(...)`, update `routeName()` for `/`, `/users`, `/requests`, and `/usage`, and start dashboard loading only after `ensureAdminSession()` succeeds.

On `403`, hide `#admin-app`, show the access-denied state, and retain the sign-out command. On `401`, show sign-in. Other errors remain in the current admin status/error UI.

- [ ] **Step 5: Run shell and syntax tests**

Run: `node --test apps/admin/src/shell.test.js && node --check apps/admin/src/main.js`

Expected: all tests pass and JavaScript parses.

- [ ] **Step 6: Verify no unauthenticated fetch remains**

Run: `rg -n "fetch\\(" apps/admin/src`

Expected: direct network calls exist only inside the auth/API modules; dashboard code uses `adminFetch`.

- [ ] **Step 7: Commit**

```bash
git add apps/admin/index.html apps/admin/src/main.js apps/admin/src/styles.css apps/admin/src/shell.test.js
git commit -m "feat: move admin dashboard into standalone app"
```

---

### Task 3: Remove Backend Static Admin Serving

**Files:**
- Modify: `tests/test_agent_submissions.py:2639-2717`
- Modify: `src/admin/routes.py:1-24`
- Modify: `src/api/main.py:9-12,77-82`
- Delete: `src/admin/static/index.html`
- Delete: `src/admin/static/app.js`
- Delete: `src/admin/static/styles.css`

**Interfaces:**
- Preserves: all `/api/admin/*` endpoint contracts.
- Removes: `/admin`, `/admin/users`, `/admin/requests`, `/admin/usage`, and `/admin/static/*` from Cloud Run.

- [ ] **Step 1: Replace backend-shell tests with failing separation tests**

Add the admin page paths and `/admin/static/app.js` to `test_backend_does_not_serve_frontend_pages`. Remove tests whose only purpose is the old backend shell. Keep the non-admin API rejection test.

- [ ] **Step 2: Add failing no-store API test**

With an admin dependency override, call `/api/admin/overview` and assert `response.headers["Cache-Control"] == "no-store"`.

- [ ] **Step 3: Run focused backend tests and verify RED**

Run: `pytest tests/test_agent_submissions.py -k "admin_pages or backend_does_not_serve or admin_api" -q`

Expected: FAIL because backend admin pages still exist and admin API responses lack `no-store`.

- [ ] **Step 4: Remove shell routes and static mount**

Delete `ADMIN_STATIC_DIR`, `ADMIN_SHELL_HEADERS`, `FileResponse`, and all `/admin*` shell route decorators from `src/admin/routes.py`. Remove the admin static mount and related import from `src/api/main.py`. Keep the profile-photo static mount and `NoCacheStaticFiles` class.

- [ ] **Step 5: Add admin API cache protection**

In `request_monitoring_middleware`, set `Cache-Control: no-store` whenever `request.url.path.startswith("/api/admin/")`.

- [ ] **Step 6: Delete old static files and run tests**

Run: `pytest tests/test_agent_submissions.py -k "admin or backend_does_not_serve_frontend_pages" -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/admin/routes.py src/api/main.py src/admin/static tests/test_agent_submissions.py
git commit -m "refactor: stop serving admin frontend from API"
```

---

### Task 4: Build and Cloudflare Deployment Configuration

**Files:**
- Create: `apps/admin/vite.config.js`
- Create: `apps/admin/wrangler.jsonc`
- Modify: `package.json`
- Modify: `src/security/config.py`
- Modify: production CORS tests near `tests/test_production_security_config.py`

**Interfaces:**
- Produces scripts: `admin:dev`, `admin:test`, `admin:check`, `admin:build`, `admin:preview`, `admin:deploy`.
- Produces Vite local origin: `http://127.0.0.1:5176`.
- Produces Cloudflare Worker name: `omiryn-admin`.

- [ ] **Step 1: Write failing CORS default test**

Assert `configured_cors_origins()` includes `https://admin.omiryn.com` when `CORS_ALLOWED_ORIGINS` is unset.

- [ ] **Step 2: Run the CORS test and verify RED**

Run: `pytest tests/test_production_security_config.py -q`

Expected: the new admin-origin assertion fails.

- [ ] **Step 3: Add the admin default origin**

Append `https://admin.omiryn.com` to `DEFAULT_CORS_ORIGINS` without changing explicit environment override behavior.

- [ ] **Step 4: Add Vite and Wrangler configs**

Configure Vite root `apps/admin`, port `5176`, `/api` proxy through `VITE_API_PROXY_TARGET`, output `apps/admin/dist`, and root base `/`. Configure Wrangler static assets at `./dist` with SPA fallback.

- [ ] **Step 5: Add package scripts**

Set:

```json
"admin:dev": "vite --config apps/admin/vite.config.js",
"admin:test": "node --test apps/admin/src/*.test.js",
"admin:check": "node --check apps/admin/src/api.js && node --check apps/admin/src/auth.js && node --check apps/admin/src/main.js",
"admin:build": "vite build --config apps/admin/vite.config.js",
"admin:preview": "vite preview --config apps/admin/vite.config.js",
"admin:deploy": "npx wrangler deploy --config apps/admin/wrangler.jsonc"
```

Append `npm run admin:build` to the root `build` script.

- [ ] **Step 6: Run build and test suite**

Run: `npm run admin:test && npm run admin:check && npm run admin:build && pytest tests/test_production_security_config.py -q`

Expected: all checks pass and `apps/admin/dist/index.html` exists.

- [ ] **Step 7: Commit**

```bash
git add apps/admin/vite.config.js apps/admin/wrangler.jsonc package.json src/security/config.py tests/test_production_security_config.py
git commit -m "build: add standalone admin deployment"
```

---

### Task 5: End-to-End Verification and Deployment Documentation

**Files:**
- Modify: `docs/gcp-deployment.md`
- Modify: `docs/production-security-checklist.md`

**Interfaces:**
- Documents: Cloudflare build/deploy commands, `VITE_API_BASE_URL`, CORS origin, Supabase redirect URL, and backend admin allowlist configuration.

- [ ] **Step 1: Start local API and admin servers**

Run the API using the repository start convention and run `npm run admin:dev`. Use `ADMIN_ALLOW_UNAUTHENTICATED_DEV=true` only for backend API development; the standalone frontend still exercises its explicit auth state logic through tests.

- [ ] **Step 2: Verify the browser experience**

At desktop and mobile widths, verify the sign-in state, dashboard layout, `/users`, `/requests`, `/usage`, refresh, access-denied state, and sign-out. Confirm there is no horizontal overflow or overlapping text.

- [ ] **Step 3: Run complete focused verification**

Run:

```bash
npm run admin:test
npm run admin:check
npm run admin:build
pytest tests/test_agent_submissions.py -k "admin or backend_does_not_serve_frontend_pages" -q
pytest tests/test_production_security_config.py -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 4: Document production configuration**

Document `admin.omiryn.com`, the Cloud Run API URL in `VITE_API_BASE_URL`, Supabase OAuth redirect allowlisting for `https://admin.omiryn.com`, `ADMIN_EMAILS`/`ADMIN_USER_IDS`, and inclusion of the admin origin in CORS.

- [ ] **Step 5: Commit**

```bash
git add docs/gcp-deployment.md docs/production-security-checklist.md
git commit -m "docs: document standalone admin deployment"
```

