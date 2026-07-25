# Revenue and Fee Reporting — V1.1 Status

## Purpose

This milestone is the reporting and audit layer required before EZ360PM becomes
the sole record of received business revenue. It uses cash-basis dates:

- payments are reported on `Payment.received_at`;
- refunds, chargebacks, fee corrections, and other adjustments are reported on
  `PaymentAdjustment.effective_at`; and
- net is `gross received - net processing fees + refunds/other signed adjustments`.

A pending Stripe fee is never presented as a confirmed zero-dollar fee. Any net
total containing a pending fee is labeled provisional.

## Implemented

### Reporting service and filters

- [x] One company-scoped service in `documents.revenue_reporting` supplies HTML,
  print, and CSV output.
- [x] Presets: this month, last month, this year, last year, calendar year, and
  custom inclusive dates.
- [x] Payment-method filters: all, Stripe, check, cash, and other.
- [x] Backward compatibility for the original `month=YYYY-MM` links.
- [x] Stable ledger ordering and full-report totals independent of pagination.
- [x] Invalid filter values fall back safely without widening company scope.

### Report experience

- [x] Page renamed **Revenue & Fees**.
- [x] Gross, confirmed processing fees, signed refunds/adjustments, provisional
  or final net, transaction count, and unresolved-fee count.
- [x] Predictable method summary including zero-value methods.
- [x] Transaction ledger with client, project, invoice, method, reference, gross,
  fee, adjustment, net, and fee status.
- [x] Print mode loads the complete filtered ledger without app navigation.
- [x] CSV export uses the same filters and service, includes a report summary,
  emits UTF-8, uses deterministic names, and protects text cells against
  spreadsheet formula injection.

### Financial history

- [x] Append-only `PaymentAdjustment` records for refunds, fee refunds,
  disputes, dispute reversals, corrections, and other adjustments.
- [x] Manual adjustment form; original payments remain unchanged.
- [x] Invoice balances and statuses include only adjustments marked as affecting
  the customer balance.
- [x] Stripe refund and dispute webhooks import idempotently by provider ID.
- [x] Stripe fee changes post signed adjustments rather than hiding history.
- [x] Company ownership is validated on every adjustment.
- [x] A company-level `books_closed_through` date blocks ordinary creation,
  editing, and deletion in closed periods.
- [x] Late provider events remain importable. When a fee is first resolved after
  its receipt period is closed, EZ360PM posts the fee as a current dated
  adjustment instead of rewriting the closed report.

### Stripe fee reconciliation

- [x] Pending fees are visible and can be retried for the selected report period.
- [x] `charge.succeeded` and `charge.updated` can reconcile fee information.
- [x] Provider API failures are logged without exposing Stripe secrets.
- [x] Persist an append-only history of every reconciliation attempt, including
  resolved, still-pending, and provider-error outcomes; show the latest attempt
  beside an unresolved fee in the ledger.

## Deliberately separate milestone

### Stripe payout-to-bank reconciliation

The V1.1 report is a payment-level revenue and fee ledger. It does not yet model
Stripe payouts or prove which Stripe balance transactions were grouped into each
bank deposit.

Add payout reconciliation only if exact bank-deposit matching is required:

- Stripe payout ID, status, arrival date, gross, fees, adjustments, and net;
- imported balance transactions associated with each payout;
- matched and unmatched totals; and
- payout replay/idempotency tests.

## Automated coverage added

- [x] Annual, custom-range, and payment-method filtering.
- [x] Inclusive dates, invalid filters, and company isolation.
- [x] Gross, fee, adjustment, and net calculations using Decimal values.
- [x] Pending fee display semantics, pending-only filtering, and latest-attempt
  audit details.
- [x] CSV rows, totals, and formula-injection protection.
- [x] Refund and dispute webhook replay/idempotency.
- [x] Invoice balance changes after refunds and reversals.
- [x] Closed-period safeguards and late-provider adjustment behavior.

## Manual year-end acceptance drill

Complete this before retiring FreshBooks:

1. Use a full calendar year containing Stripe, check, cash, and other receipts,
   partial payments, at least one refund/adjustment, and a reconciled fee.
2. Select the year and compare gross to the payment ledger.
3. Filter each method and verify the method totals sum to All methods.
4. Compare every Stripe gross amount and fee to Stripe's transaction export.
5. Compare check and cash rows to deposit/check records.
6. Export CSV and confirm its rows and summary equal the screen.
7. Confirm `gross - net fees + refunds/other signed adjustments = net` with no unexplained
   difference.
8. Resolve every pending Stripe fee. The settings form will reject a close
   date that includes an unresolved Stripe fee.
9. Set **Financial records locked through** to the accepted year-end date.
10. Store the CSV outside EZ360PM and complete a database backup/restore drill.

The milestone is operationally complete only when this drill succeeds without a
spreadsheet repair or direct database edit.
