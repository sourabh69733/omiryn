# Omiryn Production Security Checklist

Last updated: July 26, 2026

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
- [ ] Add direct "Request data deletion" action in account settings.
- [ ] Add learned-signal delete/correction controls.

## Auth And Access Control

- [ ] Production env sets `AUTH_REQUIRED=true`.
- [ ] Production env uses Supabase Auth with production redirect URLs.
- [ ] All private user-data routes require `current_user` or stricter auth.
- [ ] Admin routes allow only configured admin emails.
- [ ] Staging and production auth configs are separate.

## Data And Storage

- [ ] Production uses Postgres, not SQLite.
- [ ] Daily backups are enabled.
- [ ] Restore process is tested.
- [ ] User deletion process covers profile, chats, memories, photos, learned signals, usage logs, and public leads where applicable.
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

- [ ] Add error tracking.
- [ ] Add request IDs.
- [ ] Monitor auth failures, chat failures, lead capture failures, and import failures.
- [ ] Monitor LLM provider rate limits and costs.

## Launch Gate

- [ ] `npm run frontend:check` passes.
- [ ] `npm run frontend:build` passes.
- [ ] Backend tests pass.
- [ ] Public pages render on mobile and desktop.
- [ ] Sign-in, chat, memory import, deletion request, and contact flows are manually tested.
