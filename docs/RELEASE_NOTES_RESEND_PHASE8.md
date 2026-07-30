# Resend Transactional Email Phase 8

## Outcome

EZ360PM now has a provider-neutral transactional email boundary. Production is
configured for the Resend HTTPS API, while development remains on Django's safe
console backend and Gmail/Google Workspace SMTP remains an explicit rollback.

## Implemented

- Added a Resend-backed Django email backend so password recovery and
  application-owned messages use the same production transport.
- Routed document, follow-up, client-form, acceptance, decline, payment, and
  form-submission email through one transactional service.
- Expanded durable delivery history with provider, provider message ID, project
  form target, delivery state, and last provider-event timestamp.
- Added a signed `/webhooks/resend/` endpoint with Svix verification,
  `svix-id` deduplication, unknown-event retention, and out-of-order protection.
- Added delivered, delayed, bounced, failed, complained, and suppressed states.
- Reused the same Resend idempotency identity after uncertain timeouts to avoid
  duplicate customer email; confirmed retries remain separate audit attempts.
- Added integration readiness details without exposing credentials.
- Updated development and Render environment templates, deployment instructions,
  data-model/architecture notes, and the production rollback procedure.

## Production cutover still required

1. Create the Resend account and verify a dedicated sending subdomain.
2. Publish Resend's SPF and DKIM records, then add DMARC deliberately.
3. Add the Phase 8 email values from `.env.render.example` to Render.
4. Register `https://<public-host>/webhooks/resend/` for the documented events.
5. Deploy, run controlled document/form/password-reset sends, and verify provider
   IDs plus delivered events in EZ360PM.
6. Replay one webhook and exercise the Gmail SMTP rollback before removing its
   production credential.

Official setup references: [Resend domains](https://resend.com/docs/dashboard/domains/introduction),
[webhook verification](https://resend.com/docs/webhooks/verify-webhooks-requests),
and [event types](https://resend.com/docs/webhooks/event-types).

## Validation

- 241 core business tests pass.
- 190 AI tests pass.
- Ruff, dependency integrity, migration-drift, and whitespace checks pass.
