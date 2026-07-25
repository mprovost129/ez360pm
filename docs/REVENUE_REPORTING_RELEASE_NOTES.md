# EZ360PM V1.1 — Revenue & Fees Release Notes

## What changed

The former month-only Revenue page is now a company-scoped cash-basis Revenue &
Fees report that can be used for calendar-year review.

- Period presets: this month, last month, this year, last year, calendar year,
  and custom inclusive dates.
- Payment-method filters: all, Stripe, check, cash, and other.
- Stripe-fee status filter: all fees or pending fees only.
- Summary totals: gross received, original processing fees, signed fee changes,
  net processing fees, refunds/other adjustments, and net received.
- Method summary and transaction ledger with client, project, invoice, method,
  reference, gross, fee, adjustment, net, and reconciliation status.
- CSV export and print-friendly full report using the same filters and accounting
  service as the on-screen report.
- Append-only refunds, disputes, dispute reversals, fee refunds, additional
  processing fees, and corrections.
- Append-only Stripe fee reconciliation history with safe status/error details.
- Closed-period protection through `Company.books_closed_through`.

## Database changes

Apply these migrations before using the updated report:

- `accounts.0003_company_books_closed_through`
- `documents.0007_paymentadjustment`
- `documents.0008_paymentfeereconciliationattempt`

## Local verification commands

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py data_audit --json --fail-on-warning
```

For macOS/Linux, use `.venv/bin/python` instead of
`.venv\Scripts\python.exe`.

## Before retiring FreshBooks

Complete the manual year-end drill in `docs/REVENUE_REPORTING_TODOS.md`. In
particular, compare one complete calendar year against Stripe's transaction
export and your check/cash records, resolve all pending fees, export the CSV,
lock the accepted period, and complete a database backup/restore drill.

This release reports payment-level net revenue. Stripe payout-to-bank batch
matching remains a deliberately separate optional milestone.
