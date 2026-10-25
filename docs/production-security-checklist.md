# Omiryn Production Security Checklist

Last updated: October 10, 2026

This checklist tracks the privacy and security layer required before a real public launch.

## Public Trust Layer

- [x] Privacy Policy explains collected data, AI use, user controls, vendors, and deletion requests.
- [x] Terms explain eligibility, acceptable use, user content, AI limits, and suspension rights.
- [x] Safety page explains adult-only use, prohibited behavior, consent, reporting, and imported-context safety.
- [x] AI Disclosure explains where AI is used, limitations, and user control.
- [x] Contact page supports feedback, support, safety, privacy, correction, and deletion requests.
- [ ] (Drafted 2026-10-12 in `apps/landing/privacy.html`, needs owner review and a landing deploy) Update the Privacy Policy for the October 2026 controls (delete messages, Clear Omi, Temporary Chat, account delete), the retention windows below, and that chat text goes to AI model providers (DeepInfra, Mistral) to write replies.
- [ ] Replace personal support email with a branded address such as `hello@omiryn.com`.
- [ ] Legal review before wide public launch.

## In-App Notices

- [x] Chat composer warns that chats may create learned signals.
- [x] Style page explains learned signals are AI-inferred and may be wrong.
- [x] Memory import explains long-term context use.
- [x] WhatsApp import requires user permission and states Omiryn will not message contacts.
- [x] Profile form explains how profile details are used.
- [x] Add direct "Request data deletion" action in account settings.
- [x] Store signed-in export/deletion requests in the database.
- [x] Add learned-signal delete control.
- [x] Add learned-signal correction/edit controls.
- [x] Add signed-in Contact page for feedback, support, privacy, safety, and community invite requests.

## User Privacy Controls

- [x] Delete single or selected messages; what Omi learned only from them goes too (memories, vibe proof, notes, ratings), and chat summaries rebuild.
- [x] Clear Omi: delete every chat and everything Omi learned, keeping the account and profile (typed confirmation).
- [x] Temporary Chat: not in History, never learned from, deleted when the user leaves it or after 24 hours idle.
- [x] Reply ratings from the message menu, one per message, with undo.
- [x] Uploads (WhatsApp export, notes): links, emails and phone numbers are masked before storage; only the user's own lines can become memories; other people's lines are sent to the background model as context. Deleting an upload deletes what it taught. Since 2026-10-22 each upload also gets a digest (`upload_digests`, encrypted): summary, topics, plans and facts about the other person in the chat, each citing real lines. Facts about the other person stay in the digest, never in the user's memories or matching; the digest is deleted with the upload, with Clear Omi and with the account. The privacy page now says this (2026-10-22, pending owner review). Since 2026-10-23 the reply model can call `search_chats`, which reads only the signed-in user's own stored chats (never temporary chats) and sends the matching lines to the reply provider for that turn. Message chunks are embedded by the embedding provider (DeepInfra bge-m3) into `chat_chunk_embeddings`; vectors are deleted with the chat, any deleted message's chat, Clear Omi and the account.
- [ ] Web search tool (2026-10-25): when `TAVILY_API_KEY` is set, the reply model may send a short search query (not the chat) to Tavily. The tool tells the model never to include private people's names, the user's details or chat content, but a model can still slip: add Tavily to the privacy policy's vendor list before turning it on in prod. Page extracts are marked as data, never instructions (prompt injection), and each search costs a credit (at most 4 calls a round, 3 rounds a turn).

## Retention And Audit

- [x] Daily retention job in the API job worker (`src/storage/retention.py`): reply traces and context snapshots 30 days, background debug rows 90 days (free text scrubbed after 7), finished jobs and batch failures 30 days, stale temporary chats 24 hours, audit rows 365 days.
- [x] Chats, memories, vibe lines and profiles are never removed by retention; only the user's own deletes remove them.
- [x] `audit_events` table records chat, message, memory and upload deletes, Clear Omi, account delete, data requests, every admin view and each retention run. IDs and counts only, never text. Kept when an account is deleted.
- [x] Admins can list audit rows at `GET /api/admin/audit`.
- [ ] Encryption key rotation plan for `ENCRYPTION_MASTER_KEY`.

## Auth And Access Control

- [x] Production startup fails unless `AUTH_REQUIRED=true`.
- [x] Production startup fails unless Supabase, admin allowlist, encryption key, Postgres URL, and durable photo storage are configured.
- [ ] Production env uses Supabase Auth with production redirect URLs.
- [x] All private user-data routes require signed-in auth.
- [x] Admin routes allow only configured admin emails or user IDs.
- [x] Unauthenticated admin dev bypass is disabled in production.
- [x] Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are off in production.
- [x] Telegram webhook accepts only requests with the configured secret header; link codes are one-time, expire in 15 minutes and are stored hashed. Telegram is off unless `TELEGRAM_ENABLED=true`.
- [ ] Set a long random `TELEGRAM_WEBHOOK_SECRET` in production and keep the bot token in the secret manager.
- [x] Admin UI is deployed separately and the API no longer serves admin frontend assets.
- [ ] Add `https://admin.omiryn.com` to Supabase production redirect URLs.
- [ ] If overriding `CORS_ALLOWED_ORIGINS`, include `https://admin.omiryn.com`.
- [ ] Staging and production auth configs are separate.

## Data And Storage

- [x] Production startup rejects SQLite and requires Postgres.
- [ ] Production `DATABASE_URL` is configured to the real Cloud SQL/Postgres database.
- [x] New private tables require `user_id`.
- [x] Production startup fails if private tables contain rows without `user_id`.
- [ ] Run `scripts/data_ops/assign-legacy-data-to-user.sh --dry-run` and backfill/delete legacy anonymous rows before deployment.
- [ ] Daily backups are enabled.
- [ ] Restore process is tested.
- [x] User deletion process covers profile, chats, memories, photos, learned signals, usage logs, app events, feedback, data requests, Telegram links, and public leads where applicable.
- [x] Add admin/internal view for deletion and export requests.
- [x] Raw chat/import text is not written to application logs or provider error usage metadata.
- [x] Production startup requires profile photos to use GCS instead of ephemeral local disk.

## Abuse Protection

- [x] Public event/contact endpoints have basic in-memory throttling.
- [x] Public email leads validate email format.
- [x] Chat messages have max length.
- [x] Manual memory imports have max length.
- [x] WhatsApp imports have max length.
- [x] Production startup rejects profile photo upload limits above 10 MB.
- [x] Profile photos are capped at 4 by gallery slot validation; replacing photos is allowed after deleting an existing one.
- [x] Per-user rolling monthly quotas with automatic short burst protection cover chat, memory imports, and WhatsApp imports.
- [x] Make per-user chat and import quotas atomic and durable across Cloud Run instances using Postgres transaction locks.
- [ ] Add upload/file size limits at proxy/runtime level.
- [x] Add server-side profile photo decoding/validation, metadata stripping, and safe re-encoding so spoofed or malicious non-image uploads are rejected.
- [ ] Add alerts for repeated throttling or safety reports.

## Monitoring

- [x] Add first-party client error event capture.
- [x] Add request IDs.
- [ ] Monitor auth failures, chat failures, lead capture failures, and import failures.
- [ ] Monitor LLM provider rate limits and costs.

## Realtime Delivery

- [x] Add an authenticated, room-based WebSocket gateway and versioned event contract.
- [x] Keep the in-memory realtime hub for local development and single-instance deployments.
- [x] Connect the browser client with active-conversation subscriptions, heartbeat, and automatic reconnection.
- [ ] Before multi-instance production, add Redis/Memorystore Pub/Sub behind a broker interface for cross-instance delivery.
- [x] Treat the database as the source of truth; reconnect clients fetch messages missed during disconnection.
- [ ] Add a transactional outbox so saved messages are eventually published when the broker is temporarily unavailable.
- [ ] Test reconnects, duplicate events, ordering, expired tickets, instance restarts, and broker outages.
- [ ] Configure Cloud Run WebSocket timeout/reconnect behavior and monitor active connections, delivery failures, and broker latency.

## Launch Gate

- [x] `npm run web:check` passes.
- [x] `npm run web:build` passes.
- [x] `npm run admin:test`, `npm run admin:check`, and `npm run admin:build` pass.
- [x] Backend tests pass.
- [ ] Public pages render on mobile and desktop.
- [ ] Sign-in, chat, memory import, deletion request, and contact flows are manually tested.
- [ ] Admin Google sign-in, denied-user handling, refresh, and sign-out are manually tested on the production domains.
