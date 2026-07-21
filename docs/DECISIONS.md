# Product and Technical Decisions

This is a lightweight decision log for assumptions that affect implementation.
“Working” decisions may be revised before their roadmap phase begins; changing a
locked decision requires an explicit update to the product specification.

## Locked by the MVP specification

| Decision | Consequence |
| --- | --- |
| One user and one company initially | no signup, onboarding, subscriptions, roles, or invitations |
| Company ownership from the first migration | authenticated business queries are always company-scoped |
| One Document model for proposals and invoices | shared lines, totals, preview, PDF, email, and public mechanics |
| Payment is the only representation of received money | no mark-paid shortcut; revenue sums Payment rows |
| Running timer is a persisted TimeEntry | it survives browser/server lifecycle and only one may run per user |
| All projects are timed | flat-fee time supports profitability but is not billed as hourly work |
| Retainers are linked credits, not negative line items | tax and accounting trail remain explicit |
| Sent documents are preserved | withdraw proposals, void invoices, delete drafts only |
| Overdue and balances are derived | they cannot drift from due dates, totals, or payments |

## Working implementation decisions

| Decision | Rationale |
| --- | --- |
| Rename `users` to `accounts` before initial migration (implemented) | matches the brief while change is still inexpensive |
| Base User on `AbstractUser`, remove username, authenticate by unique email (implemented) | retains Django admin/auth compatibility and meets the custom-user requirement |
| Use a modular server-rendered Django monolith | best fit for a solo operational tool and current starter |
| Use explicit transactional services, not signals, for financial/state changes | makes ordering, locking, repetition, and tests visible |
| Add `DocumentDelivery` | recipient selection and send history otherwise have no durable representation |
| Use a locked sequence record for generated numbers | avoids collision-prone `max + 1` logic and remains SaaS-safe |
| Treat the accepted Document fields as the durable acceptance record | accepted proposals are immutable and permanent; avoid duplicate acceptance storage |
| Use `PROTECT` around financial history | prevents accidental cascade deletion of audit records |
| Store timestamps in UTC and localize at presentation boundaries | required for durable timers and consistent server behavior |
| Choose the PDF engine behind an adapter | preserves rendering design if deployment constraints force a library change |

## Questions to resolve before the named phase

None of these blocks roadmap/design work. The default is the stated working
assumption if no different product decision is made by the deadline.

| By phase | Question | Working assumption |
| --- | --- | --- |
| 0 | What timezone determines “today,” project numbering month, and dashboard periods? | `America/New_York` for the personal company; store instants in UTC |
| 1 | Can project number overrides use any text or only `YYMM###`? | allow nonblank text up to field length if company-unique |
| 3 | What are proposal and invoice number formats? | independent company sequences, `P-YY-####` and `I-YY-####` |
| 3 | What currency and tax rounding policy apply? | USD; round each line total and each line's tax half-up to cents |
| 3 | What default invoice terms/due interval applies? | no implicit terms; require due date when preparing an invoice for send |
| 3 | Which PDF engine works reliably in the deployment image? | run a short HTML/CSS fidelity and Render build spike before selection |
| 3 | May manual payments exceed outstanding balance? | reject accidental overpayment; no refund/credit-balance workflow in MVP |
| 4 | What exactly makes a retainer “required” for automatic activation? | a created/sent retainer is required; otherwise activation is explicit |
| 4 | Can multiple proposal recipients sign? | first valid acceptance is final; delivery may have multiple recipients |
| 5 | Which outbound email provider and reply-to address are used? | provider via environment; reply-to Company email |
| 5 | Which Stripe event and ID are canonical? | fulfilled Checkout Session resolved to its successful Payment Intent |
| 7 | What production retention and backup recovery targets are acceptable? | daily managed PostgreSQL backups plus a documented restore drill |

## Known specification tensions

These are reconciliations, not feature additions:

1. The specification says each Client has “exactly one” primary Contact, while the
   database rule says “at most one.” PostgreSQL can enforce at most one with a
   conditional unique constraint; transactional client/contact workflows enforce
   at least one.
2. The current starter uses `users.User(AbstractBaseUser)` while the specification
   names `accounts.User(AbstractUser)`. Resolve this before initial migrations as
   described above.
3. The specification requests document send history but lists only `sent_at` on
   Document. `DocumentDelivery` supplies the missing one-to-many audit data.
4. Proposal acceptance calls for a durable record and also stores all acceptance
   fields on the permanent accepted Document. The MVP treats that immutable
   Document snapshot as the record; a second table is unnecessary unless legal or
   audit requirements later demand a full event ledger.
5. Payment has no direct company field in the field list, despite a general
   company-integrity rule. It is scoped through its invoice, avoiding duplicated
   ownership while still preventing cross-company access.

## Change discipline

When a working assumption changes, update this file, the affected design document,
and tests in the same change. Do not encode unresolved product policy in a view or
template without recording it here.
