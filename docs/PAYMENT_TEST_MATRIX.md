# Payment System Test Matrix

EZ360PM's ordinary automated tests never use production Stripe credentials,
open a real Checkout session, charge a card, or send a real email. Payment tests
override Stripe settings with unmistakable fake test values and replace every
Stripe network call with deterministic test doubles. One positive webhook test
uses Stripe's real SDK locally to verify an HMAC signature; it performs no
network request.

## Automated coverage

| Payment behavior | Verification | Primary tests |
| --- | --- | --- |
| Invoice totals, tax rounding, amount due, partial/full status, and reversal | Service and database tests | `documents/tests/test_billing.py` |
| Deposit invoice displays the full project total but collects only the deposit | Workflow and Checkout amount tests | `documents/tests/test_proposals.py`, `documents/tests/test_payment_system.py` |
| Final invoice applies paid deposits and preserves the invoice series | Workflow tests | `documents/tests/test_proposals.py` |
| Checkout amount comes from the locked server-side balance | Stripe service tests | `documents/tests/test_automation.py`, `documents/tests/test_payment_system.py` |
| Draft, paid, void, disabled, and zero-balance invoices cannot open Checkout | Provider-boundary tests | `documents/tests/test_payment_system.py` |
| Checkout carries invoice/company metadata, customer email, USD, and the configured key | Provider-contract tests | `documents/tests/test_payment_system.py` |
| Public Checkout failure redirects safely without recording revenue | View tests | `documents/tests/test_payment_system.py` |
| Public Checkout attempts are rate limited before calling Stripe | Abuse-control test | `documents/tests/test_payment_system.py` |
| Webhook accepts POST only and refuses incomplete configuration | Endpoint tests | `documents/tests/test_payment_system.py` |
| Stripe SDK accepts a valid signed raw payload and rejects an invalid signature | Local cryptographic endpoint tests | `documents/tests/test_payment_system.py`, `documents/tests/test_automation.py` |
| Missing metadata, wrong company, wrong currency, and unknown invoices create no payment | Reconciliation rejection tests | `documents/tests/test_automation.py`, `documents/tests/test_payment_system.py` |
| Unpaid and unrelated Stripe events create no revenue | No-op event tests | `documents/tests/test_payment_system.py` |
| Completed and asynchronous payments create the correct payment and invoice status | Webhook/service tests | `documents/tests/test_automation.py`, `documents/tests/test_payment_system.py` |
| Duplicate webhook delivery creates one payment and one notification | Replay/idempotency tests | `documents/tests/test_automation.py`, `documents/tests/test_payment_system.py` |
| A payment intent cannot move between invoices | Service invariant tests | `documents/tests/test_billing.py` |
| A captured payment is preserved if the balance changed after Checkout opened | Race/regression test | `documents/tests/test_automation.py` |
| Stripe fees, pending fees, later fee reconciliation, gross, and net revenue | Provider and reporting tests | `documents/tests/test_automation.py`, `core/tests/test_reporting.py` |
| Payment remains recorded if the internal notification email fails | Failure-path test | `documents/tests/test_payment_system.py` |
| Stripe payments cannot be edited or deleted through manual-payment views | Financial-history protection test | `documents/tests/test_payment_system.py` |
| Manual refunds append dated records and cannot edit or delete prior history | Ledger and immutability tests | `documents/tests/test_payment_system.py` |
| Applied retainer credits cannot be underfunded by a manual refund | Cross-invoice invariant test | `documents/tests/test_payment_system.py` |
| A Stripe refund arriving before its payment is retained and succeeds on replay | Out-of-order webhook test | `documents/tests/test_payment_system.py` |
| Stripe disputes are retained as operator-review events without raw payloads | Durable review-state test | `documents/tests/test_payment_system.py`, `core/tests/test_data_audit.py` |
| Refunds affect revenue on their effective date and reconcile dashboard/report/AI totals | Cash-basis reporting tests | `core/tests/test_reporting.py`, `assistant/tests/test_assistant.py` |
| Refund ledger/cache drift blocks the data audit | Deployment integrity test | `core/tests/test_data_audit.py` |
| Company-scoped invoice, payment, revenue, and dashboard data | Tenant-isolation/reporting tests | `documents/tests/test_billing.py`, `core/tests/test_reporting.py`, `clients/tests/test_client_detail.py` |

Run the focused payment boundary suite with:

```powershell
python manage.py test documents.tests.test_payment_system -v 1
```

Run all document, invoice, delivery, and payment tests with:

```powershell
python manage.py test documents.tests -v 1
```

GitHub's quality workflow runs the complete Django suite on every pull request
and push to `main`, using disposable CI configuration rather than Render
credentials.

## What remains a provider-level check

Deterministic tests prove EZ360PM behavior, but cannot prove the state of the
live Stripe account. The following remain controlled operational checks:

- the Render webhook URL and live webhook signing secret match Stripe;
- the intended live event types are enabled in Stripe;
- a real hosted Checkout page loads under the production account;
- Stripe delivers an event to Render and receives HTTP 200;
- an actual settlement, payout, refund, dispute, or Stripe Dashboard setting
  behaves as configured by Stripe.

EZ360PM records manual and Stripe refunds and flags Stripe disputes for review.
It does not initiate refunds, adjudicate disputes, or reconcile Stripe payouts
to bank deposits; those remain provider-level and accounting acceptance checks.
