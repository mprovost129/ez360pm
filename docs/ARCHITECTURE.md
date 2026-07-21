# Application Architecture

## Architectural shape

EZ360PM should remain a modular Django monolith for the personal MVP:

- Django 6 with server-rendered templates and small progressive-JavaScript
  enhancements
- PostgreSQL as the system of record
- Redis for production cache/rate-limit support, not business state
- Bootstrap-based responsive application shell
- synchronous domain services for business operations
- provider adapters around email, PDF generation, and Stripe

The important boundary is the domain/service boundary, not a network boundary.
Splitting the workflow into services or a SPA would add operational cost without
improving the single-user product.

## Proposed Django apps

| App | Responsibility | Primary models |
| --- | --- | --- |
| `accounts` | Company identity, owner account, initial setup | `Company`, `User` |
| `intake` | Fast unstructured capture and archive workflow | `Note` |
| `clients` | Billing party and contacts | `Client`, `Contact` |
| `projects` | Job lifecycle and durable work tracking | `Project`, `TimeEntry` |
| `documents` | Proposals, invoices, credits, payments, delivery, PDF/public views | `Document`, `LineItem`, `InvoiceCredit`, `Payment`, `DocumentDelivery` |
| `core` | Dashboard, application shell, shared presentation utilities | no business models |

The starter's `users` app was renamed before the first migration. The implemented
`accounts.User` uses `AbstractUser` with the username field removed, unique email
as `USERNAME_FIELD`, and a required protected Company relationship.

## Dependency direction

```text
accounts <- clients <- projects <- documents
    ^           ^          ^           ^
    +--------- intake -----+-----------+

core reads scoped projections from the domain apps; domain apps do not depend on core.
provider adapters are called by documents services; models do not call providers.
```

Avoid circular imports by referring to models by app-label strings in field
declarations and importing inside service functions where needed.

## Company isolation

### Authenticated boundary

Every top-level company-owned model uses an abstract base with a required
`company` foreign key. It also exposes an explicit scoped queryset:

```python
class CompanyQuerySet(models.QuerySet):
    def for_company(self, company):
        return self.filter(company=company)
```

Views use a `CompanyScopedQuerysetMixin` whose `get_queryset()` calls
`.for_company(request.user.company)`. Forms receive `company` explicitly and
scope every related-object choice. Services receive `company` or the acting user
and retrieve records through a scoped queryset even when the caller already has
an ID.

Child records without a direct company column are scoped through their parent:

- Contact through `client__company`
- LineItem and Payment through `document__company`
- InvoiceCredit through both source and destination documents
- DocumentDelivery through `document__company`

Cross-company mismatches are rejected in model validation and services. Database
constraints enforce same-parent/type invariants where SQL can express them; tests
prove isolation for list, detail, create, update, delete, and action endpoints.

### Public boundary

Public document routes are the only business-data routes not scoped through a
logged-in user. They retrieve one document by an unguessable UUID token, return a
generic not-found response for invalid tokens, and then enforce document type and
state before showing or accepting an action.

Token possession grants only the narrow public-document capability. Public views
must not expose internal notes, other documents, database IDs, time entries,
payment references, or navigation into authenticated screens.

## Domain services

Business state changes belong in small transactional services. Views validate
HTTP input and call services; models define data and local validation; signals are
not used for core financial behavior.

Planned service surface:

| Service | Responsibility |
| --- | --- |
| `allocate_project_number` | Atomically allocate editable `YYMM###` numbers |
| `create_client_with_primary_contact` | Satisfy the cross-row client/contact invariant |
| `start_timer`, `stop_timer` | Enforce one running entry and authoritative timestamps |
| `build_hourly_invoice_lines` | Attach selected unbilled entries with chosen grouping |
| `release_invoice_time` | Explicitly reverse draft/void time attachment safely |
| `recalculate_document_totals` | Recompute line totals, tax, credits, and total |
| `send_document` | Validate sendability, deliver, record attempt, and transition state |
| `record_public_view` | Stamp only the first public view and transition sent to viewed |
| `accept_proposal`, `decline_proposal` | Lock response metadata and transition the project |
| `create_retainer_invoice` | Build a retainer from an accepted proposal snapshot |
| `apply_retainer_credit` | Lock source/destination and prevent duplicate over-crediting |
| `record_payment`, `change_payment`, `delete_payment` | Mutate received money and recalculate status |
| `activate_project_if_funded` | Move approved work to active only under the stated rule |
| `process_stripe_event` | Verify, deduplicate, and route a webhook to `record_payment` |

Services that allocate scarce values or change money use `transaction.atomic()`
and `select_for_update()` on the affected rows. They are designed to be safe when
the same request is repeated.

## State machines

Transitions are explicit service actions; arbitrary status dropdown edits are not
allowed once a record has left draft/lead state.

### Project

```text
lead --proposal accepted--> approved
approved --retainer fully paid or explicit no-retainer start--> active
active <--> on_hold
active/on_hold --explicit finish--> completed
lead/approved/active/on_hold --explicit close--> canceled
```

### Proposal

```text
draft --send--> sent --first public view--> viewed
sent/viewed --accept--> accepted
sent/viewed --decline--> declined
sent/viewed --withdraw--> withdrawn
```

### Invoice

```text
draft --send--> sent --first public view--> viewed
sent/viewed --partial payment--> partially_paid --remaining payment--> paid
sent/viewed/partially_paid --void--> void
```

`overdue` is a query/display condition, never a stored status. Payment deletion or
editing can move an invoice back from `paid`/`partially_paid` to its appropriate
sent/viewed state. These operations should be restricted to authenticated manual
payments and recorded in application logs.

## Financial correctness

- Store currency values as `Decimal`, never float.
- Calculate each line and tax using the rounding policy recorded in
  [Decisions](DECISIONS.md).
- Persist document totals as recalculated snapshots for fast display and audit;
  never accept totals from browser input.
- Derive `amount_paid` from Payment rows and `outstanding_balance` from total less
  payments. Do not store either field.
- Treat Payment as received money. A successful Stripe event and a manual payment
  use the same creation service.
- Calculate retainer availability as paid source-retainer amount minus all credits
  already sourced from it. Lock rows while applying a credit.
- Do not permit a credit to make a final invoice negative; unapplied retainer
  remains available.

## Time-entry attachment

`TimeEntry.line_item` is nullable and points to the generated invoice line. This
supports one line per entry, grouped descriptions, and one combined line: many
entries may point to one line.

Attachment and release happen in the same transaction as line creation/deletion.
Invoiced time is read-only. A void invoice retains its time attachment until the
user invokes the warned release action, reducing accidental double billing.

## Documents, delivery, and PDF

One canonical document context builds authenticated preview, public HTML, email
link metadata, and PDF output. This prevents the preview and client copy from
drifting. Proposal rich text is sanitized on input or before persistence and is
treated as already-sanitized at rendering time.

`DocumentDelivery` is a small supporting model needed by the specified “send
history” screen. It records recipients and the result of every delivery attempt;
`Document.sent_at` remains the timestamp of the first successful send.

PDF generation sits behind an adapter so the HTML-to-PDF library can be selected
after a deployment-compatibility spike. Generated PDFs do not become the source
of truth; they are reproducible from the preserved document data.

## Stripe boundary

The browser never decides the payable amount. The server reloads the invoice,
calculates its outstanding balance, confirms that it is payable, and creates a
Checkout Session containing the document token/identifier in metadata.

The webhook handler:

1. verifies the Stripe signature against the raw request body;
2. recognizes only supported successful-payment events;
3. resolves the company/document from trusted server-side metadata;
4. locks the invoice and checks the unique Payment Intent identifier;
5. calls the shared payment service; and
6. returns success for an already-processed event.

Provider event IDs may also be logged for diagnostics, but the unique nonblank
Payment Intent ID is the revenue-duplication guard required by the brief.

## Security and audit baseline

- Login and all mutation endpoints use CSRF protection.
- Django Axes remains enabled for brute-force protection.
- Public action endpoints receive basic rate limiting and generic error responses.
- Proposal rich text uses an allowlist sanitizer; template autoescaping stays on.
- Uploaded logos are validated by size/type and are never served as executable
  content.
- Acceptance stores signer name/email, accepted total, timestamp, and IP on the
  immutable accepted document record.
- Payments, accepted proposals, credits, and sent documents cannot be normally
  deleted.
- Logs include stable record identifiers and action outcomes but exclude document
  body text, credentials, public tokens, and unnecessary client details.

## Testing strategy

1. **Model/constraint tests:** uniqueness, check constraints, conditional timer
   constraint, validation, and deletion protection.
2. **Service tests:** totals, rounding, transitions, time release, retainer
   availability, payment recalculation, and idempotency.
3. **Request tests:** company isolation for every endpoint, public-token states,
   CSRF, form scoping, and permissions.
4. **Workflow tests:** one end-to-end test per roadmap exit gate using the real
   database and service layer.
5. **Rendering tests:** stable document context/totals plus focused HTML/PDF smoke
   tests rather than brittle full-page snapshots.

PostgreSQL is required in tests that exercise database-specific constraints;
SQLite is not an equivalent test backend for this application.
