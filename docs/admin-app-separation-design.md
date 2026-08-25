# Admin App Separation Design

## Goal

Move the existing Omiryn admin website from backend-served static files into an independently built and deployed `apps/admin` frontend at `admin.omiryn.com`, while retaining the protected `/api/admin/*` backend APIs.

## Scope

The migration preserves the existing Dashboard, Users, Requests, and Usage views. It changes deployment and authentication boundaries, not the admin data contracts or visible features. Role-specific visibility, field masking, and audit logging remain a separate security milestone after this migration.

## Architecture

- `apps/admin` is a standalone Vite application deployed through Cloudflare Workers static assets.
- The app reads its backend origin from `VITE_API_BASE_URL`, matching the existing web application convention.
- The app obtains Supabase public configuration from `/api/auth/config`, signs administrators in with Google, and sends the Supabase access token as a bearer token on every admin API request.
- The backend continues to enforce `ADMIN_EMAILS` and `ADMIN_USER_IDS` through `require_admin_user`. The frontend never decides whether an account is an administrator.
- Cloud Run serves `/api/admin/*` only. It no longer mounts or serves the admin HTML, JavaScript, or CSS.

## Frontend Structure

- `apps/admin/index.html`: Vite entry document.
- `apps/admin/src/main.js`: application bootstrap and existing admin behavior.
- `apps/admin/src/auth.js`: Supabase session, Google sign-in, sign-out, and authenticated API fetch.
- `apps/admin/src/styles.css`: existing admin styling plus sign-in, forbidden, loading, and error states.
- `apps/admin/public/assets`: admin brand assets if required.
- `apps/admin/vite.config.js`: local backend proxy and port `5176`.
- `apps/admin/wrangler.jsonc`: Cloudflare static asset deployment with SPA fallback.

The current vanilla JavaScript admin UI is migrated without a React rewrite. This keeps the deployment change isolated. Components can be migrated incrementally after parity is verified.

## Authentication Flow

1. Load the Supabase configuration from the backend.
2. Restore an existing Supabase browser session, if present.
3. If no session exists, show a Google sign-in screen.
4. Call `/api/admin/overview` with `Authorization: Bearer <access-token>`.
5. On `401`, return to sign-in. On `403`, show an access-denied screen and allow sign-out.
6. All other admin requests use the same authenticated fetch helper.

The Supabase anonymous key is public configuration, not a secret. Admin authorization remains exclusively server-side.

## Backend Changes

- Remove the `/admin/static` mount and backend HTML shell routes.
- Keep all existing `/api/admin/*` routes and their `require_admin_user` dependency.
- Add `https://admin.omiryn.com` to the default allowed CORS origins.
- Keep production startup validation requiring at least one configured admin.

## Deployment

Root package scripts provide `admin:dev`, `admin:check`, `admin:build`, `admin:preview`, and `admin:deploy`. The root `build` script includes the admin build. Cloudflare serves `admin.omiryn.com`; the app calls the Cloud Run backend directly.

## Testing

- Frontend unit tests verify API URL construction, bearer headers, and handling of unauthenticated and forbidden responses.
- Backend tests verify admin APIs remain protected and the removed backend `/admin` shell is no longer served.
- Build validation checks TypeScript/JavaScript and creates the Cloudflare asset directory.
- Browser verification covers sign-in, access denied, dashboard navigation, and responsive layout.

## Security Boundaries

- Cloudflare hosting is not an authorization boundary.
- Every `/api/admin/*` endpoint continues to require a verified Supabase identity and backend allowlist membership.
- No service-role key or backend secret is included in the frontend bundle.
- The app does not persist admin API responses outside normal browser memory.
- Admin APIs return `Cache-Control: no-store` as a follow-up hardening change within this migration if not already present.
