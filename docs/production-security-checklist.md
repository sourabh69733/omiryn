# Omiryn Production Security Checklist

Last updated: July 30, 2026

This checklist tracks the privacy and security layer required before a real public launch.

## Public Trust Layer

- [x] Privacy Policy explains collected data, AI use, user controls, vendors, and deletion requests.
- [x] Terms explain eligibility, acceptable use, user content, AI limits, and suspension rights.
- [x] Safety page explains adult-only use, prohibited behavior, consent, reporting, and imported-context safety.
- [x] AI Disclosure explains where AI is used, limitations, and user control.
- [x] Contact page supports feedback, support, safety, privacy, correction, and deletion requests.
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

## Auth And Access Control

- [x] Production startup fails unless `AUTH_REQUIRED=true`.
- [ ] Production env uses Supabase Auth with production redirect URLs.
- [x] All private user-data routes require signed-in auth.
- [x] Admin routes allow only configured admin emails or user IDs.
- [x] Unauthenticated admin dev bypass is disabled in production.
- [ ] Staging and production auth configs are separate.

## Data And Storage

- [ ] Production uses Postgres, not SQLite.
- [x] New private tables require `user_id`.
- [x] Production startup fails if private tables contain rows without `user_id`.
- [ ] Run `scripts/data_ops/assign-legacy-data-to-user.sh --dry-run` and backfill/delete legacy anonymous rows before deployment.
- [ ] Daily backups are enabled.
- [ ] Restore process is tested.
- [x] User deletion process covers profile, chats, memories, photos, learned signals, usage logs, app events, feedback, data requests, and public leads where applicable.
- [ ] Add admin/internal view for deletion and export requests.
- [ ] Raw sensitive content is not written to application logs.

## Abuse Protection

- [x] Public event/contact endpoints have basic in-memory throttling.
- [x] Public email leads validate email format.
- [x] Chat messages have max length.
- [x] Manual memory imports have max length.
- [x] WhatsApp imports have max length.
- [ ] Add durable production rate limits using infrastructure, Redis, or provider controls.
- [ ] Add upload/file size limits at proxy/runtime level.
- [ ] Add alerts for repeated throttling or safety reports.

## Monitoring

- [x] Add first-party client error event capture.
- [x] Add request IDs.
- [ ] Monitor auth failures, chat failures, lead capture failures, and import failures.
- [ ] Monitor LLM provider rate limits and costs.

## Launch Gate

- [x] `npm run frontend:check` passes.
- [x] `npm run frontend:build` passes.
- [x] Backend tests pass.
- [ ] Public pages render on mobile and desktop.
- [ ] Sign-in, chat, memory import, deletion request, and contact flows are manually tested.
