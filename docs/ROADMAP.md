## V1.16 - OpenAI request observability and model stability

- [x] Assign one unique `X-Client-Request-Id` to every logical OpenAI Responses API call.
- [x] Persist client-generated troubleshooting IDs even when a timeout prevents an OpenAI response ID from returning.
- [x] Preserve OpenAI response request IDs from successful and rejected requests.
- [x] Include both identifier types in the metadata-only AI audit CSV.
- [x] Support optional `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` scoping through the official SDK.
- [x] Add informational deployment and readiness guidance for mutable model aliases versus dated snapshots.
- [x] Extend the contract evaluation to verify request guards and client-request tracking.
- [ ] Run migrations, the Django suite, contract evaluation, live baseline, and readiness gate in the normal environment.

Release details: [AI Assistant V1.16](RELEASE_NOTES_AI_ASSISTANT_V1_16.md).


## V1.15 - AI workflow completion and usability

- [x] Add bounded multi-turn context using recent redacted summaries from the same user, company, and browser conversation.
- [x] Keep current-message explicit write intent mandatory; earlier turns cannot authorize a write.
- [x] Add server-verified current-page context for supported client, project, proposal, invoice, and intake-note pages.
- [x] Re-query every page object through the authenticated company boundary and exclude sensitive free text.
- [x] Add a persistent Action Center for pending confirmations and recent outcomes.
- [x] Reload pending confirmations in the assistant drawer and expire stale actions automatically.
- [x] Document the AI completion point and stop speculative AI development until real-use evidence exists.
- [ ] Run the full Django suite and controlled pilot in the normal environment.

Release details: [AI Assistant V1.15](RELEASE_NOTES_AI_ASSISTANT_V1_15.md).
Completion boundary: [AI Upgrade Completion Point](AI_UPGRADE_COMPLETION.md).


## V1.14 - AI manual client follow-ups and evidence

- [x] Add company-scoped follow-up context for open proposals, retainers, and invoices.
- [x] Add one-at-a-time AI follow-up drafting with exact recipient, subject, and message preview.
- [x] Require the existing external-commit acknowledgement and fresh document snapshot before sending.
- [x] Block repeat AI follow-ups inside a configurable minimum interval.
- [x] Preserve follow-up purpose and type on every successful or failed delivery record.
- [x] Add company-scoped delivery/outcome evidence and CSV export without claiming causation.
- [x] Keep schedules, repeating reminders, batch delivery, refunds, paid-invoice changes, and money movement unavailable.
- [ ] Validate repeated manual follow-ups in real use before designing one narrow scheduled reminder workflow.

Release details: [AI Assistant V1.14](RELEASE_NOTES_AI_ASSISTANT_V1_14.md).


## V1.13 - AI controlled document draft revisions

- [x] Add a company-scoped read tool for one editable proposal or invoice draft.
- [x] Add proposal-draft revision with exact section, pricing-line, and total previews.
- [x] Add invoice-draft revision for dates, terms, payment setting, and client-facing
  line descriptions without allowing AI to change rates, quantities, taxes,
  credits, time links, or totals.
- [x] Require financial-draft confirmation and explicit current-message intent.
- [x] Reject issued documents, ambiguous references, cross-company records, stale
  previews, and line items from another invoice.
- [x] Extend metadata-only draft-quality evidence to manually created drafts that
  receive a confirmed AI revision.
- [x] Keep issuing, sending, refunds, paid-invoice changes, and money movement
  outside the revision tools.
- [ ] Validate the tools with real proposal and invoice drafts before considering
  any scheduled revision or reminder workflow.

Release details: [AI Assistant V1.13](RELEASE_NOTES_AI_ASSISTANT_V1_13.md).


## V1.12 - AI document draft quality evidence

- [x] Track AI-created proposals, retainer invoices, and final invoices from creation
  through revision, issue, delivery, and draft deletion.
- [x] Store metadata and content hashes only; do not duplicate proposal sections,
  terms, notes, or line-item descriptions.
- [x] Classify finalized drafts as used as-is, edited then used, or abandoned.
- [x] Add company-scoped adoption, revision, stale-draft, and time-to-issue reporting.
- [x] Add a metadata-only CSV export and regression coverage for isolation,
  lifecycle tracking, deletion, and privacy.
- [ ] Gather real-use evidence before selecting any scheduled draft or reminder workflow.


## V1.5 - AI controlled delivery and lifecycle actions

- [x] Add fresh final-confirmation cards for document issue and delivery.
- [x] Restrict AI-selected recipients to contacts on the document client.
- [x] Re-read locked documents and reject stale totals, dates, line items, payments, recipients, or time attachments.
- [x] Preserve custom email subject/message and every successful or failed delivery attempt.
- [x] Add confirmed proposal withdrawal, unpaid-invoice voiding, manual payment entry, and void-invoice time release.
- [x] Upgrade AI project-status changes to the external-commit confirmation level.
- [x] Keep refunds, paid-invoice alteration, deletion of financial history, and money movement outside the assistant.
- [ ] Run the full runtime suite and controlled real-use validation before enabling V1.5 in production.

## V1.11 - AI controlled pilot operations

- [x] Add company access modes for staff-only, selected-user, or all-user pilots.
- [x] Add per-user selected access without exposing company scope to OpenAI.
- [x] Add response helpful/not-helpful feedback tied to the exact interaction.
- [x] Add company-scoped incident reporting; critical incidents pause AI immediately.
- [x] Add configurable automatic suspension after repeated failed interactions.
- [x] Add staff-only pilot operations, emergency pause/resume, incident resolution,
  and feedback review screens.
- [x] Add readiness checks for pilot access, circuit-breaker state, unresolved
  high-severity incidents, and minimum real-use feedback.
- [x] Add a management-command rollback path for suspend/resume and selected-user access.
- [ ] Run the Django suite, OpenAI live baseline, and a controlled real-use pilot
  before considering scheduled drafts or reminders.

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
4. All work is timed, including fixed-fee projects.
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

## AI assistant milestone - V1.4

- [x] OpenAI Responses API foundation, read-only tools, note/timer controls, and
  structured CRM/project actions.
- [x] Add guarded financial-document draft tools for proposals, retainers, and
  final invoices.
- [x] Reuse existing document, time attachment, Decimal total, and retainer-credit
  services; AI never calculates or persists authoritative totals directly.
- [x] Keep every AI-created document in Draft and open the ordinary document
  editor for review.
- [ ] Complete the runtime Django suite and manual real-use validation before
  production enablement.
- [x] Phase 5 controlled issuing, sending, voiding, manual payment recording,
  and time release is implemented with exact final confirmation. Refunds, paid
  invoice changes, deletion of financial history, and money movement remain unavailable.

## Delivery map

### V1 status - 2026-07-24

- **Phases 0-7 code: complete and tested.** The account, isolation,
  intake, client/contact, project, timer/time-entry, invoice, proposal,
  acceptance, retainer, credit, manual/Stripe payment, email delivery, webhook,
  public rendering/PDF, dashboard, revenue, outstanding-balance, settings,
  command, health, usability-hardening, and regression tests pass on PostgreSQL.
  Lint, Django system checks, migration-drift checks, the deployment check, and
  the read-only data audit pass.
- **Initial Render deployment: complete and in real use.** The authenticated
  application, owner access, database, static assets, media storage, email,
  public documents, and Stripe workflow have been exercised from the deployed
  environment. The shared production startup gate applies migrations and blocks startup when
  deployment or data-audit gates fail.
- **Phase 7 operational validation: in progress.** The launch baseline includes
  a read-only data
  audit, machine-readable monitoring output, backup/restore and webhook replay
  drills, secret-safe/non-root container builds, release security gates,
  proxy-aware HTTPS, PostgreSQL TLS/persistent-connection controls, stdout
  logging, private/no-store public-document responses, print styling, an
  accessibility skip link, and a privacy-safe real-use issue log.
  The remaining V1 evidence is provider-level rather than application code:
  complete the first isolated backup restore and Stripe webhook replay drills,
  then keep logging recurring friction during real use.
- **Next milestone:** freeze speculative V1 feature work, complete the first
  restore/replay drills, and prioritize only evidence from the real-use log.

### V1.1 FreshBooks replacement: annual revenue and fee reporting

**Priority:** complete before FreshBooks is retired and before speculative PM or
SaaS feature expansion. The existing `Payment` records remain the accounting
source of truth; this milestone upgrades reporting, auditability, and export.
Detailed implementation notes and acceptance tests are in
[Revenue and fee reporting TODOs](REVENUE_REPORTING_TODOS.md).

#### Required reporting experience

- [x] Replace the month-only Revenue filter with reusable date presets: This
  month, Last month, This year, Last year, a specific calendar year, and a
  custom inclusive start/end date. Preserve the selected range in pagination
  and exports.
- [x] Add a payment-method filter for All, Stripe, Check, Cash, and Other; allow
  it to combine with every date range.
- [x] Show report-level Gross received, Processing fees, Refunds/adjustments,
  and Net received. Keep cash-basis recognition tied to `Payment.received_at`.
- [x] Show a method summary table with payment count, gross, fees,
  refunds/adjustments, and net for each method, including zero rows so the
  report is predictable.
- [x] Replace the gross-only payment list with an auditable ledger: received
  date, client, project, invoice number, method, reference/check number, gross,
  fee, refund/adjustment, net, and fee status.
- [x] Make `fee_pending=True` visibly distinct from a confirmed $0.00 fee and
  exclude unresolved transactions from any label that claims a final net bank
  amount.
- [x] Add filtered CSV export using the same scoped queryset and selected
  filters as the on-screen report. Include a generated-at timestamp, company,
  filter range, and all ledger columns.
- [x] Add a print-friendly annual summary suitable for year-end review. PDF
  export is optional if browser print produces a complete, legible report.

#### Accounting completeness

- [x] Decide and document the refund/chargeback model before the first real
  refund occurs. Prefer append-only `PaymentAdjustment` records rather than
  editing or deleting original receipts.
- [x] Import Stripe refund, dispute, and fee-reversal events idempotently and
  reflect them in gross, fees, refunds/adjustments, and net totals.
- [x] Add an explicit reconciliation action and attempt history for unresolved
  Stripe fees. Do not silently treat missing provider data as zero.
- [x] Add a dedicated operator-facing queue for Stripe adjustment-import failures.
  Verified refund, dispute, and fee-adjustment failures are recorded without raw
  payloads, grouped by Stripe event ID across retries, and automatically resolved
  after a successful replay. Operators can review and resolve the queue in Django
  Administration.
- [x] Define V1.1 as payment-level net reporting and explicitly defer Stripe
  payout-to-bank reconciliation as a separate optional milestone.
- [x] Prevent edits/deletes that would rewrite closed-period financial history;
  corrections should be represented by dated adjustment records and an audit
  trail.

#### Exit gate

In January, selecting the prior calendar year must show every company-scoped
manual and Stripe receipt, filter correctly by payment method, expose each
Stripe fee and unresolved fee, account for refunds/adjustments, reconcile gross minus net fees plus refunds/other adjustments to net, and export the same rows and totals to CSV.
Manual comparison against Stripe and bank/check records must produce no
unexplained difference. The application work for this milestone is complete;
retiring FreshBooks still requires the manual year-end acceptance drill and a
successful backup/restore test.

### Current Phase 7 backlog - 2026-07-23

#### Correctness

- [x] **Fix exact-duration editing for stopped timer entries.** A timer that has
  accumulated paused time retains `paused_duration` when its Hours/Minutes are
  edited. The form sets `end_time = start_time + entered duration`, then the
  displayed duration subtracts the old pause total again. Editing an entry to
  exactly 6 hours must display and bill exactly 6 hours, regardless of its
  original pauses. Reset or consistently recalculate the pause fields during a
  manual duration edit, and add regression tests for paused-and-resumed entries.
- [x] **Expose guarded manual project status changes.** Keep new projects at
  Lead, place the existing status choices directly on the Project detail
  dashboard, require explicit confirmation when the status changes, preserve all
  financial/history records, and prevent hold/complete/cancel while the project
  timer is running. Keep status out of Edit Project so record details and
  workflow state remain separate actions.

#### Estimate, proposal, and invoice experience

- [x] Treat a draft proposal as the internal estimate stage; clarify the UI as
  "Estimate / Draft Proposal" without introducing a duplicate Estimate model.
- [x] Consolidate document preparation into one proposal/invoice builder with
  project/customer context, scope, pricing, terms, internal notes, totals, and
  preview visible in one workflow.
  - [x] First pass: add readiness, price/time entry, preview, and lifecycle
    actions to the existing draft detail screen.
  - [x] Finish the workflow by embedding draft settings on both document pages,
    embedding new scope-section entry on the proposal page, and returning each
    save directly to the refreshed customer preview.
- [x] Clarify customer-facing versus internal inputs. Rename ambiguous fields
  such as Notes, Rate, Quantity, Tax rate, Invoice kind, and Accept payments,
  with explicit help text where a mistake could reach a customer.
- [x] Reduce repetitive setup: keep a project fixed when launched from its
  detail page, hide automatic document numbers unless overridden, default line
  quantity and tax, and provide sensible reusable terms and invoice due dates.
  - [x] Lock project context; default quantity, tax, and a 30-day invoice due
    date; explain automatic numbering.
  - [x] Add company settings for reusable proposal terms, invoice terms,
    invoice due days, and default tax rate.
- [x] Improve pricing-line input with inline editing, calculated line/document
  totals, Save and add another, currency/percentage formatting, and controls
  that use the existing line ordering.
  - [x] First pass: default common values, calculate line and taxed totals live,
    and keep the add-price form on the document draft.
  - [x] Add adjacent up/down controls that persist the existing line order.
- [x] Add a draft-readiness summary for customer/project, scope, positive
  pricing, terms, total, and recipient email, followed by a clear Review and
  send path instead of disconnected issue and email actions.
- [x] Improve proposal preparation with an obvious Scope of work starting
  section, adjacent edit/reorder controls, an accurate customer preview, and a
  calculated dollar preview when creating a percentage retainer.
  - [x] Default Scope of work and show a live percentage-retainer amount.
- [x] Replace the raw unbilled-time checkbox list with rows showing date,
  description, hours, rate, and amount; include Select all and a grouping
  preview before attaching entries to an invoice.
  - [x] Detailed selectable rows and Select all are implemented.
- [x] Make final-invoice reconciliation clearer by surfacing available retainer
  credit, offering Apply maximum available credit, and warning when final
  pricing differs from the accepted proposal or project fixed fee.
  - [x] Show available credit, prefill the safe maximum for one retainer, and
    warn when invoice charges differ from the accepted proposal.

#### Delivery and payment clarity

- [x] Label document activity as "Link opened" and explain that automated email
  security scanners can trigger the first-open timestamp.
- [x] Send one idempotent internal email notification for each successful Stripe
  Payment Intent and retain the attempt in the invoice delivery history.
- [x] Reconcile an initially unavailable Stripe fee from later `charge.succeeded`
  or `charge.updated` webhooks so gross revenue, fees, and net revenue stay
  accurate without creating a second payment.

#### Current-feature improvement queue

- [x] Finish the single-page proposal/invoice builder with inline pricing edits,
  Save and add another, and continuously visible totals and preview.
  - [x] Add separate Save and review / Save and add another paths that return to
    the live document preview or the next-line form.
  - [x] Edit existing price lines directly inside the draft preview and
    recalculate document totals after each save.
- [x] Add company-scoped search to Clients, Projects, Proposals, and Invoices by
  the identifiers and customer details used during daily work.
- [x] Add Resend to same recipient and Retry failed delivery actions while
  preserving every email attempt in delivery history.
- [x] Let Quick Note conversion find and attach an existing client before
  creating a new one, reducing accidental duplicate customer records.
- [x] Distinguish a Stripe fee that is awaiting provider data from a confirmed
  zero fee, then show the reconciled amount when it arrives.
- [x] Add filtered hours, billable value, and today's total to the Time page and
  warn about overlapping manual time entries.
- [x] Prioritize dashboard attention lists by age and expose how long leads,
  drafts, unpaid invoices, and unbilled time have been waiting.
- [x] Send an internal notification when a proposal is declined and make the
  customer's response prominent on the proposal.
- [x] Allow an existing proposal or draft invoice to be duplicated into a new
  draft without copying lifecycle or payment history.
- [x] Group project-page actions by workflow stage so the most likely next
  action is prominent and secondary actions remain available.
- [x] Correct the project workflow anchors so proposal and retainer actions land
  on their actual document sections instead of Notes or Recent time.
- [x] Render project proposals and invoices as independent collections so each
  section retains an accurate empty state when only the other document type
  exists.
- [x] Preserve the originating project and search text while switching proposal
  status filters or clearing a search, avoiding a jump back to all projects.
- [x] Give Project, Proposal, and Outstanding Invoice filters a consistent,
  accessible active state and reset pagination whenever the filter changes.
- [x] Keep the Client Time tab fast with its latest-25 limit while showing the
  full time-entry count and clearly explaining when older entries are omitted;
  retain all completed time in the client summary total.
- [x] Preserve the selected Client detail tab in the URL hash and restore it on
  reload, allowing direct links to Projects, Invoices, Proposals, Time,
  Payments, Credits, Notes, or Summary without resetting to Projects.
- [x] Align document filters with their real lifecycles: expose Withdrawn for
  proposals, reject invoice-only proposal filters, and remove proposal-only
  choices from the Invoice status field.
- [x] Make Show archived on Intake Notes display archived notes only, with a
  matching heading and no open-note or cross-company records mixed into the
  archive view.
- [x] Distinguish empty Client and Project accounts from searches or status
  filters with no matches, and provide a clear way back to the full list.
- [x] Normalize invalid or obsolete Project and Proposal status parameters to
  All so the visible active filter, search form, and unfiltered results cannot
  disagree or keep propagating a stale status value.
- [x] Preserve Client context when New project is launched from a client: lock
  the company-scoped client selection and prefill its billing address as an
  editable project-site starting point.

### Post-V1 code-review backlog - 2026-07-25

These items came from the post-todo code, workflow, deployment, and recovery
audit. They improve the reliability and operability of existing features; they
do not add new product areas.

#### Payment and accounting resilience

- [x] Make Stripe Checkout creation idempotent for an invoice balance, reuse an
  active session where practical, and avoid holding a database transaction open
  during the provider request.
- [x] Shorten the Stripe webhook acknowledgement path so provider lookups and
  internal email delivery cannot cause otherwise-successful events to time out;
  preserve idempotent replay and operator visibility for later work.
- [x] Use provider event or balance-transaction dates consistently for imported
  refunds, disputes, reversals, and fee adjustments so delayed webhook delivery
  cannot move activity into the wrong accounting period.
- [x] Strengthen fixed-fee final-invoice checks: fall back to the project fixed
  fee when no accepted proposal exists and expose cumulative final-invoice
  pricing before another invoice is issued.
- [x] Add a recoverable retry path for failed acceptance, decline, and payment
  notification emails while preserving the original delivery attempt.

#### Deployment, access, and security resilience

- [x] Use one production entrypoint for Docker and Render that runs migrations,
  Django deployment checks, the custom deployment check, and the data audit
  before Gunicorn starts.
- [x] Include cache connectivity in readiness and convert public-action cache
  failures into an explicit, logged `503` response instead of an unhandled
  server error.
- [x] Finish account recovery by exposing authenticated password change and the
  email password-reset workflow, with tests and usable navigation from login and
  settings.
- [x] Normalize login email input so capitalization and surrounding whitespace
  do not prevent an otherwise-valid owner login.
- [x] Restrict Django Administration to superusers until reusable company-scoped
  admin querysets and foreign-key choices are implemented.

#### Maintenance and scale hygiene

- [x] Add PostgreSQL-backed GitHub Actions for lint, tests, migration drift, and
  deployment checks, plus automated dependency-update configuration.
  - [x] Exercise the migrated production settings against PostgreSQL and Redis,
    run the data audit and dependency check, and build the production Docker
    image so CI verifies the same startup artifacts used by Render.
  - [x] Keep CI credentials disposable, grant the workflow read-only repository
    access, cancel superseded runs, and bound each run to 30 minutes.
- [x] Split production and development dependencies and remove build-only tools
  from the final production image where practical.
- [x] Reduce `.env.example` to settings actually consumed by the application,
  replace real-looking values with placeholders, and document `DB_SSLMODE`.
- [x] Render the configured company logo in customer-facing proposal and invoice
  HTML, PDFs, and delivery emails with a safe fallback when no logo exists.
- [x] Keep internal invoice notes out of customer PDFs as well as public HTML;
  the PDF builder no longer renders the internal-only `Document.notes` field.
- [x] Harden CSV spreadsheet-formula neutralization for leading control
  characters or whitespace and add regression coverage.
- [x] Batch or bound synchronous Stripe fee reconciliation and move revenue
  pagination/aggregation closer to the database when measured data volume makes
  the current in-memory report expensive.
- [x] Clarify client-level received-money summaries as gross versus net after
  refunds and adjustments.
- [x] Remove or connect dead recovery templates/helpers and distinguish provider
  lookup outages from genuinely unmatched Stripe adjustment events.

### Workflow traceability

| Required workflow step | Primary delivery phase | Proof at the exit gate |
| --- | --- | --- |
| 1. Inbound job lands immediately | Phase 1 | body-only quick note is captured and preserved |
| 2. Client and primary contact are added | Phase 1 | transactional client/contact creation succeeds |
| 3. Project is opened with billing data | Phase 1 | numbered lead project is usable from its detail page |
| 4. Proposal is sent and publicly accepted | Phase 4 | immutable accepted proposal advances project to approved |
| 5. Retainer invoice is paid | Phases 4-5 | manual and Stripe payments share one accounting path |
| 6. Every work session is timed | Phase 2 | durable timer and manual entry cover hourly/fixed-fee work |
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
- Show estimated versus actual hours for both hourly and fixed-fee projects.
- Verify timer recovery after reload, logout, browser close, and server restart.

**Exit gate**

The user can time real work for a week without duplicate running timers or lost
sessions; the server timestamp remains authoritative and fixed-fee time appears in
project performance data.

### Phase 3 - Invoices and manual payments (code complete)

**Goal:** reach the first practical FreshBooks-replacement checkpoint.

- Add `Document`, `LineItem`, totals calculation, numbering, invoice drafts, and
  a canonical preview/PDF rendering path.
- Generate hourly invoice lines from uninvoiced time using all three grouping
  options; generate the standard fixed-fee line.
- Implement draft line removal/deletion time-release rules.
- Add public invoice rendering and sent/viewed/void lifecycle behavior.
- Add `Payment`, manual check/cash/other entry, status recalculation, and
  outstanding balance.
- Prevent deletion of sent or paid records and add explicit void/release actions.

**Exit gate**

An hourly or fixed-fee project can produce an accurate invoice, PDF, manual
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

## V1.4 - OpenAI API, CRM actions, and document drafts

**Implementation status:** Phases 0-5 are implemented through V1.5. Production enablement is
held behind migration, full tests, provider configuration, and the manual
validation checklist. Phase 6 remains planned.

**Goal:** add a natural-language command layer without allowing a model to bypass
company scope, workflow services, deterministic financial logic, or human review.

Implementation is split into guarded phases:

1. AI boundary, provider adapter, tool registry, audit records, and threat tests.
2. Read-only company-scoped questions and record navigation.
3. Quick-note capture and timer control through existing services.
4. Client/contact/project create and update with duplicate checks and field diffs.
5. Proposal and invoice drafting through existing document services.
6. Controlled issue/send and financial lifecycle actions with mandatory final
   confirmation.
7. Real-use refinement, cost controls, and later SaaS tenant controls.

The detailed tasks, safety levels, and phase exit gates are maintained in
[AI Assistant Roadmap](AI_ASSISTANT_ROADMAP.md). No AI phase begins until the
current end-to-end application workflow and financial reporting are trusted in
real use.

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


## AI V1.6 real-use refinement

- [x] Add local, read-only workflow alerts to the assistant drawer.
- [x] Add dismissals and bounded refresh/item controls.
- [x] Personalize fixed command suggestions from completed actions without prompt training.
- [x] Add AI usage, cost, latency, confirmation, cancellation, and failure reporting.
- [x] Log safe operational refinement events.
- [ ] Observe real usage before adding scheduled drafts or reminders.
- [x] Keep every send and financial commit behind the existing final confirmation.

Release details: [AI Assistant V1.6](RELEASE_NOTES_AI_ASSISTANT_V1_6.md).


## AI V1.7 production hardening

- [x] Wrap every provider tool result in a server-owned untrusted-data security envelope.
- [x] Flag instruction-like text inside stored business data without executing or deleting it.
- [x] Require the current user message to explicitly authorize the matching write tool.
- [x] Bound serialized tool output and fail closed when a lookup is too broad.
- [x] Expand prompt-injection, tenant-isolation, financial reconciliation, timer lifecycle, duplicate, stale-data, and retry regression coverage.
- [x] Add deployment checks for the new output boundary and explicit-write-intent setting.
- [ ] Run the Django runtime suite and manual V1.7 security checklist in the normal project environment before production enablement.

Release details: [AI Assistant V1.7](RELEASE_NOTES_AI_ASSISTANT_V1_7.md).

## AI V1.8 company controls and privacy

- [x] Add one company-owned AI policy record and settings screen.
- [x] Add OpenAI model selection constrained by a deployment allowlist.
- [x] Add company controls for low-risk writes, CRM/project writes, financial
  drafts, external/financial commits, and proactive alerts.
- [x] Remove disabled capability tools from provider requests and recheck policy
  at confirmation execution.
- [x] Add company-wide monthly request and estimated-cost limits that fail closed
  before the provider call.
- [x] Add privacy acknowledgement, redacted-summary controls, and company-specific
  read-only retention.
- [x] Add company-scoped current-month usage indicators and metadata-only audit CSV.
- [x] Make the retention cleanup command use company policy by default.
- [ ] Run the full Django suite and manual V1.8 checklist in the normal environment.
- [ ] Map company allowances to SaaS subscription plans only when the SaaS billing
  design begins.
- [ ] Keep scheduled drafts and reminders deferred until repeated manual approvals
  provide evidence for one narrow workflow.

Release details: [AI Assistant V1.8](RELEASE_NOTES_AI_ASSISTANT_V1_8.md).


## AI V1.9 evaluation and provider review

- [x] Add strict static contract checks for every registered AI tool and provider guard.
- [x] Add live read-only OpenAI evaluation suites for core business reads and safety boundaries.
- [x] Fail a case and automatically cancel any unexpected prepared action.
- [x] Store company-scoped evaluation history without storing business tool outputs.
- [x] Report actual tools, pass/fail, tokens, estimated cost, and latency.
- [x] Add deployment/CI JSON output and an evaluation-history screen.
- [x] Complete an initial OpenAI provider security and data-processing review.
- [ ] Run the full Django suite, contract suite, and live core/security suites in the normal environment.
- [ ] Keep scheduled drafts and reminders deferred until repeated manual approvals provide evidence for one narrow workflow.

Release details: [AI Assistant V1.9](RELEASE_NOTES_AI_ASSISTANT_V1_9.md).


## AI V1.10 controlled-use readiness

- [x] Add a company-scoped readiness checklist for platform configuration, company policy, model, usage limits, evaluations, and recent reliability.
- [x] Add a minimal tool-free OpenAI Responses API connection test for the selected model.
- [x] Record connection-test request ID, tokens, estimated cost, latency, and exact pass/fail contract.
- [x] Require a recent passing static contract result and full read-only live baseline for a ready result.
- [x] Add a fail-closed `check_ai_readiness` deployment command with JSON output.
- [x] Add readiness and connection-test regression coverage.
- [ ] Run the full Django suite, connection test, live baseline, and readiness command in the normal environment.
- [ ] Keep scheduled drafts and reminders deferred until repeated real-use approvals identify one narrow, justified workflow.

Release details: [AI Assistant V1.10](RELEASE_NOTES_AI_ASSISTANT_V1_10.md).
