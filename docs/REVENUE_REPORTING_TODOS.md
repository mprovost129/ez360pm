# Revenue and Refund Reporting Status

> **Current as of 2026-08-01.** This file describes the live implementation.

## Current accounting behavior

- `Payment` is the source record for money received, dated by `received_at`.
- `PaymentRefund` is an append-only record for money returned, dated by
  `effective_at`.
- `Payment.refunded_amount` is a transactionally maintained cache used for fast
  invoice balance calculations. The deployment data audit verifies it against
  the refund ledger.
- Cash-basis revenue for a period is payments received in the period minus
  refunds effective in the period.
- Confirmed processing fees reduce net deposited revenue. A pending Stripe fee
  remains visibly pending rather than being treated as confirmed.
- Manual refund entries only record money already returned outside EZ360PM.
  EZ360PM does not initiate a refund with Stripe or a bank.

## Implemented safeguards

- Refund amount database constraints and transactional row locking.
- Multiple partial refunds without rewriting earlier history.
- Application-level prevention of edits, bulk updates, and deletion of refund
  history.
- Manual refund protection when retainer funds are already applied to a final
  invoice.
- Durable Stripe event IDs and processing states without storing raw webhook
  payloads.
- Retryable out-of-order Stripe refund events.
- Durable operator-review state for disputes and invalid reconciliation events.
- Company-scoped dashboard, revenue, CRM, and AI summaries using refund-aware
  totals.
- Tests for refund replay, ledger/cache drift, effective dates, retainer credit
  protection, and dispute visibility.

## Operational acceptance still required

Deterministic tests do not prove live-provider configuration. Before relying on
EZ360PM as the sole financial record:

1. Confirm Stripe sends the enabled event types to the production webhook and
   receives successful responses.
2. Perform one controlled live payment and compare amount, fee, invoice status,
   and internal notification with Stripe.
3. If a real refund occurs, confirm its effective date and amount appear in the
   revenue report and invoice history.
4. Review every `stripe_event_attention` warning from `data_audit` against the
   Stripe Dashboard.
5. Compare a full calendar period by payment method with bank/check records and
   Stripe exports.
6. Complete and document a database backup/restore drill.

## Deliberately deferred

- Initiating refunds from EZ360PM.
- Dispute evidence submission or automatic chargeback accounting.
- Stripe payout-to-bank reconciliation.
- Expense accounting, closed accounting periods, tax filings, and general-ledger
  integration.
- Full CSV/print accounting ledger exports.

These should be added only with explicit product rules and acceptance tests;
they must not be inferred from the presence of Stripe webhook events.
