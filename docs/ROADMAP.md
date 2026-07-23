# EZ360PM Personal MVP Roadmap

This roadmap turns the [personal MVP specification](ez360pm_personal_mvp.docx)
into an implementation sequence for the existing Django starter. It is organized
around usable vertical slices, not isolated model completion.

## Product outcome

EZ360PM replaces FreshBooks for Provost Home Design when one authenticated user
can complete this path without maintaining a parallel system:

> Capture inquiry -> create client and project -> send proposal -> record
> acceptance -> collect retainer -> track all work -> send final invoice ->
> record payment -> review received revenue

The personal build is single-user, but all business data and authenticated
queries are company-scoped so multi-company SaaS features can be added later.

## Non-negotiable rules

1. Every feature must support one of the eight workflow steps in the source
   specification. Everything else remains deferred.
2. Every authenticated business-record query starts from
   `request.user.company`; bare primary-key lookups are prohibited.
3. All received money is represented by a `Payment`. Invoice status is never a
   substitute for a payment record.
4. All work is timed, including flat-fee projects.
5. Sent financial documents are preserved. They are withdrawn or voided, not
   deleted.
6. Totals, payment status, state transitions, number allocation, and Stripe
   webhook handling live in transactional services rather than views or model
   signals.
7. A milestone is complete only when its primary workflow is covered by tests
   and works in the deployed environment.

## Starting point

The repository began as a Django 6 starter with PostgreSQL/Redis configuration,
an email-as-username user, authentication templates, Docker/production settings,
Bootstrap, and a minimal home page. Phase 0 implementation has now established
`accounts.Company`, `accounts.User(AbstractUser)`, the initial migration,
company-scoping primitives, authenticated application shell, owner bootstrap,
health/deployment checks, environment template, and foundation tests.

The configured development database has the initial migrations applied. An owner
has intentionally not been created automatically because its password must be
provided securely at bootstrap time.

The architecture, relationships, and screen map are detailed in:

- [Architecture](ARCHITECTURE.md)
- [Data model](DATA_MODEL.md)
- [Screen and workflow design](SCREEN_FLOWS.md)
- [Decisions and open questions](DECISIONS.md)
- [Deployment and integration setup](DEPLOYMENT.md)

## Delivery map

### Implementation status - 2026-07-21

- **Phases 0-6 code: complete and tested.** The account, isolation,
  intake, client/contact, project, timer/time-entry, invoice, proposal,
  acceptance, retainer, credit, manual/Stripe payment, email delivery, webhook,
  public rendering/PDF, dashboard, revenue, outstanding-balance, settings,
  command, and health tests pass on PostgreSQL. Lint, dependency, Django system
  checks, migration-drift checks, and the deployment check pass.
- **Phase 0 operations: pending.** Bootstrap the real owner with an environment-
  supplied password and deploy the authenticated shell.
- **Phase 7: in progress.** The launch baseline now includes a read-only data
  audit, machine-readable monitoring output, backup/restore and webhook replay
  drills, secret-safe/non-root container builds, release security gates,
  proxy-aware HTTPS, PostgreSQL TLS/persistent-connection controls, stdout
  logging, private/no-store public-document responses, print styling, an
  accessibility skip link, and a privacy-safe real-use issue log.
  Evidence-driven product hardening still requires production usage.
- **Next milestone:** deploy, complete the first restore/replay drills, and log
  recurring workflow friction during real use.

### Current Phase 7 backlog - 2026-07-23

#### Correctness

- [x] **Fix exact-duration editing for stopped timer entries.** A timer that has
  accumulated paused time retains `paused_duration` when its Hours/Minutes are
  edited. The form sets `end_time = start_time + entered duration`, then the
  displayed duration subtracts the old pause total again. Editing an entry to
  exactly 6 hours must display and bill exactly 6 hours, regardless of its
  original pauses. Reset or consistently recalculate the pause fields during a
  manual duration edit, and add regression tests for paused-and-resumed entries.

#### Estimate, proposal, and invoice experience

- [x] Treat a draft proposal as the internal estimate stage; clarify the UI as
  "Estimate / Draft Proposal" without introducing a duplicate Estimate model.
- [ ] Consolidate document preparation into one proposal/invoice builder with
  project/customer context, scope, pricing, terms, internal notes, totals, and
  preview visible in one workflow.
  - [x] First pass: add readiness, price/time entry, preview, and lifecycle
    actions to the existing draft detail screen.
- [x] Clarify customer-facing versus internal inputs. Rename ambiguous fields
  such as Notes, Rate, Quantity, Tax rate, Invoice kind, and Accept payments,
  with explicit help text where a mistake could reach a customer.
- [ ] Reduce repetitive setup: keep a project fixed when launched from its
  detail page, hide automatic document numbers unless overridden, default line
  quantity and tax, and provide sensible reusable terms and invoice due dates.
  - [x] Lock project context; default quantity, tax, and a 30-day invoice due
    date; explain automatic numbering.
- [ ] Improve pricing-line input with inline editing, calculated line/document
  totals, Save and add another, currency/percentage formatting, and controls
  that use the existing line ordering.
  - [x] First pass: default common values, calculate line and taxed totals live,
    and keep the add-price form on the document draft.
- [x] Add a draft-readiness summary for customer/project, scope, positive
  pricing, terms, total, and recipient email, followed by a clear Review and
  send path instead of disconnected issue and email actions.
- [ ] Improve proposal preparation with an obvious Scope of work starting
  section, adjacent edit/reorder controls, an accurate customer preview, and a
  calculated dollar preview when creating a percentage retainer.
  - [x] Default Scope of work and show a live percentage-retainer amount.
- [ ] Replace the raw unbilled-time checkbox list with rows showing date,
  description, hours, rate, and amount; include Select all and a grouping
  preview before attaching entries to an invoice.
  - [x] Detailed selectable rows and Select all are implemented.
- [ ] Make final-invoice reconciliation clearer by surfacing available retainer
  credit, offering Apply maximum available credit, and warning when final
  pricing differs from the accepted proposal or project fixed fee.
  - [x] Show available credit, prefill the safe maximum for one retainer, and
    warn when invoice charges differ from the accepted proposal.

### Workflow traceability

| Required workflow step | Primary delivery phase | Proof at the exit gate |
| --- | --- | --- |
| 1. Inbound job lands immediately | Phase 1 | body-only quick note is captured and preserved |
| 2. Client and primary contact are added | Phase 1 | transactional client/contact creation succeeds |
| 3. Project is opened with billing data | Phase 1 | numbered lead project is usable from its detail page |
| 4. Proposal is sent and publicly accepted | Phase 4 | immutable accepted proposal advances project to approved |
| 5. Retainer invoice is paid | Phases 4-5 | manual and Stripe payments share one accounting path |
| 6. Every work session is timed | Phase 2 | durable timer and manual entry cover hourly/flat-fee work |
| 7. Final invoice applies retainer credit | Phase 4 | credit trail and totals reconcile on the final invoice |
| 8. Payments become received revenue | Phases 3 and 6 | Payment rows drive status, balance, and revenue reports |

### Phase 0 - Foundation and guardrails (code complete)

**Goal:** establish the boundaries that all later work depends on.

- Rename `users` to `accounts` and implement `accounts.User` from
  `AbstractUser` before the first migration.
- Add `Company`, the required `User.company` relationship, company-scoped base
  querysets/mixins, and cross-company validation helpers.
- Split the monolith into the domain apps described in the architecture.
- Add an idempotent setup command that creates the initial company and owner.
- Require login for the application shell and replace the placeholder home page
  with an empty dashboard shell.
- Add test factories/builders and initial tenant-isolation tests.
- Add a committed `.env.example`, system checks for required production
  settings, and a deployment smoke check.
- Deploy the empty authenticated shell before domain development begins.

**Exit gate**

- A fresh database can be migrated and initialized with one command.
- The owner can log in and sees only the assigned company.
- Automated tests prove that a user cannot retrieve another company's record by
  changing a URL identifier.
- The deployed health check, static files, login, and database connection work.

### Phase 1 - Intake, clients, and projects (code complete)

**Goal:** replace the notebook/inbox portion of the current workflow.

- Build five-second quick-note capture, newest-first note list, editing,
  attachment, and archive behavior.
- Build transactional Client + Contact creation with exactly one primary contact.
- Add create-client-from-note while preserving the original note text.
- Build Project CRUD, site and permitting fields, billing configuration, and
  editable `YYMM###` number generation.
- Add lead/client/project lists and detail screens to the application shell.

**Exit gate**

A new call can be captured with only note text, converted into a client with a
primary contact, attached to a newly numbered lead project, and archived without
losing the original intake wording.

### Phase 2 - Durable time tracking (code complete)

**Goal:** make EZ360PM the source of truth for project time.

- Add the conditional one-running-entry-per-user database constraint.
- Build start/stop services and the persistent timer widget.
- Add manual entry, filters, edit rules, billable flag, and project summaries.
- Show estimated versus actual hours for both hourly and flat-fee projects.
- Verify timer recovery after reload, logout, browser close, and server restart.

**Exit gate**

The user can time real work for a week without duplicate running timers or lost
sessions; the server timestamp remains authoritative and flat-fee time appears in
project performance data.

### Phase 3 - Invoices and manual payments (code complete)

**Goal:** reach the first practical FreshBooks-replacement checkpoint.

- Add `Document`, `LineItem`, totals calculation, numbering, invoice drafts, and
  a canonical preview/PDF rendering path.
- Generate hourly invoice lines from uninvoiced time using all three grouping
  options; generate the standard flat-fee line.
- Implement draft line removal/deletion time-release rules.
- Add public invoice rendering and sent/viewed/void lifecycle behavior.
- Add `Payment`, manual check/cash/other entry, status recalculation, and
  outstanding balance.
- Prevent deletion of sent or paid records and add explicit void/release actions.

**Exit gate**

An hourly or flat-fee project can produce an accurate invoice, PDF, manual
payment, and audit-preserving paid history. Time cannot be accidentally billed
twice through ordinary UI actions.

### Phase 4 - Proposals, acceptance, retainers, and final invoices (code complete)

**Goal:** complete the entire business workflow without payment automation.

- Add proposal body sections, terms/notes sanitization, pricing, preview, and
  public rendering.
- Activate a stable public proposal link when issuing. Recipient selection,
  outbound email, and delivery-attempt history move together in Phase 5 so an
  issue action never falsely claims an email was sent.
- Implement public accept/decline, acceptance snapshot metadata, and the
  `lead -> approved` transition.
- Create retainer invoices from accepted proposals by percentage or fixed amount.
- Activate a project when its required retainer is fully paid, or through an
  explicit no-retainer start action.
- Add `InvoiceCredit`, available-retainer calculation, and final invoice credit
  presentation below taxable charges.
- Prompt—but never automatically force—project completion after final payment.

**Exit gate: personal MVP / FreshBooks replacement**

The complete product outcome at the top of this file works end to end using
manual payment recording. Proposal acceptance, retainer payment, time, final
invoice credit, final payment, and project history reconcile correctly.

### Phase 5 - Email and Stripe automation (code complete)

**Goal:** remove manual delivery and online-payment friction without changing the
accounting model.

- Send proposal/invoice email through the same previewed public document.
- Record each delivery attempt, recipients, provider result, and sent timestamp.
- Send internal acceptance notification.
- Create Stripe Checkout Sessions only for the current outstanding balance.
- Verify webhook signatures and create payments through the same payment service
  used by manual entry.
- Enforce idempotency with the unique Payment Intent identifier and transactional
  webhook processing.
- Show payment availability/configuration status in Settings.

**Exit gate**

Repeated webhook delivery cannot duplicate revenue; a successful Stripe payment
and a manually recorded check produce the same invoice status and revenue result.

### Phase 6 - Attention dashboard and financial insight (code complete)

**Goal:** surface what needs action without creating a general reporting product.

- Add dashboard groups for leads, approved projects awaiting a retainer, active
  projects, unbilled time, drafts, unpaid/overdue invoices, and current-month
  received revenue.
- Add project actual hours and effective hourly rate.
- Add Revenue month aggregation from successful Payment rows and a separate
  outstanding-invoice view.
- Add settings for company identity, defaults, logo, and integration status.

**Exit gate**

Every dashboard number traces to a scoped query and reconciles to its detail list;
revenue totals equal Payment records rather than invoice totals.

### Phase 7 - Real-use hardening

**Goal:** polish only the friction observed during at least one month of real use.

Launch baseline implemented: `data_audit` verifies financial/document/time
relationships without modifying them; the deployment guide defines health
monitoring, restore, audit, and webhook replay drills; and `REAL_USE_LOG.md`
defines the evidence threshold for product changes.

- Keep a short issue log tied to actual jobs and rank fixes by frequency and risk.
- Improve performance, accessibility, mobile quick capture, and print output
  where measurements show a problem.
- Exercise backup/restore, production monitoring, webhook replay, and document
  audit recovery.
- Revisit SaaS onboarding only after the personal workflow is stable.

## Quality gates used in every phase

- **Isolation:** request and form querysets are scoped; cross-company IDs are
  rejected without revealing whether the object exists.
- **Integrity:** database constraints cover invariants that can be expressed in
  PostgreSQL; transactional services cover cross-row invariants.
- **Money:** `Decimal` only, explicit rounding rules, and totals recalculated by a
  single service.
- **Lifecycle:** transition tests cover allowed, rejected, and repeated actions.
- **Security:** authorization, CSRF, output sanitization, public-token state checks,
  and Stripe signature verification are tested where applicable.
- **Usability:** the phase's primary flow is exercised at desktop and narrow
  viewport sizes with keyboard access.
- **Operations:** migrations, deployment checks, logging, and rollback notes ship
  with the feature.

## Explicitly deferred

Tasks, calendars, file attachments, recurring invoices, expenses, portal
accounts, teams and roles, global search, automated reminders, advanced reports,
templates, imports/exports, accounting integrations, and enhanced authentication
remain out of scope. They do not enter this roadmap without evidence from real
use that they remove recurring workflow friction.
