# Release Notes: AI Assistant V1.2 Foundation, Read Tools, and Timer/Note Actions

## Added

- New provider-neutral `assistant` Django app.
- OpenAI Responses API adapter with strict function tools and `store=false`.
- Global desktop/mobile assistant drawer.
- Company-scoped read tools for workflow attention, records, time, invoices,
  proposals, payments, revenue, Stripe fees, retainers, and missing information.
- Confirmation-backed quick-note and timer lifecycle actions.
- `AIInteraction` usage/audit summaries and `AIActionAttempt` confirmation audit.
- Idempotency, confirmation expiry, CSRF-protected execution, rate/request/tool
  limits, provider timeout, feature flag, deployment checks, and cost guard.
- Shared `core.reporting` payment aggregation used by Revenue and AI reporting.
- AI history cleanup command and setup/operations guide.
- Regression tests for tenant isolation, unknown tool fields, prompt injection,
  revenue reconciliation, ambiguity, idempotency, confirmation, cancellation,
  and repeated confirmation.

## Deliberately not included

- Client/contact/project creation or editing.
- Project status changes through AI.
- Proposal or invoice drafting.
- Issuing, sending, voiding, payments, refunds, or other financial commits.
- Autonomous or scheduled actions.

Those remain in Phases 3-6 of `docs/AI_ASSISTANT_ROADMAP.md`.

## Required deployment steps

1. Configure the environment variables in `docs/AI_ASSISTANT_SETUP.md`.
2. Run `python manage.py migrate`.
3. Run `python manage.py collectstatic --noinput`.
4. Run `python manage.py check --deploy`.
5. Run `python manage.py test assistant` and the full project suite.
6. Enable the feature only after the manual validation checklist passes.
