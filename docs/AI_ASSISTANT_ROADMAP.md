# EZ360PM AI Assistant Roadmap

## Purpose

Add AI only where it reduces daily administrative work in the existing EZ360PM
workflow. The assistant is not a second application, a general-purpose chatbot,
or an autonomous bookkeeper. It interprets natural-language requests, retrieves
company-scoped information, and proposes or performs narrowly defined EZ360PM
actions through the same validated domain services used by the existing UI.

The target experience is a command bar available from desktop and mobile:

> Start a timer for the Smith addition. Working on roof revisions.
>
> Create a client and lead project from this intake note.
>
> Prepare the final invoice for project 2607004 using all unbilled time grouped
> by description and the available retainer credit.

## Implementation status

- **Phases 0-5:** functional implementation is present through V1.5. The unchecked
  exhaustive security/regression test TODOs, runtime suite, and manual real-use
  exit gates are still required before enabling production use.
- **Phase 6 operational refinement:** V1.6 adds local proactive flags, dismissals,
  personalized fixed-command suggestions, and usage/reliability metrics.
- **Production hardening:** V1.7 adds explicit current-message authorization for
  every write tool, server security envelopes around untrusted tool results, bounded
  tool-output size, and the remaining injection/isolation/retry regression coverage.
  Scheduled drafts or reminders remain intentionally deferred until real-use evidence exists.
- **Company controls and privacy:** V1.8 adds per-company enablement, OpenAI model
  allowlists, action-category controls, company request/cost limits, privacy
  acknowledgement, configurable read-only retention, and metadata-only audit export.
- **Evaluation and provider review:** V1.9 adds static tool-contract checks, read-only
  live OpenAI evaluation suites, persistent pass/fail baselines, and an initial
  provider security/data-processing review. Scheduled drafts or reminders remain
  intentionally deferred until real-use evidence exists.
- **Controlled-use readiness:** V1.10 adds a tool-free OpenAI connection test,
  company-scoped launch checklist, evaluation freshness checks, and a fail-closed
  deployment command. It does not relax any confirmation or financial boundary.
- **Controlled pilot operations:** V1.11 adds staff/all/selected-user access,
  response feedback, incident reporting, an automatic failure circuit breaker,
  emergency pause/resume controls, and readiness checks for unresolved incidents
  and pilot evidence. It does not add scheduled or autonomous actions.
- **Draft-quality evidence:** V1.12 adds metadata-only tracking for AI-created
  proposals and invoices through revision, issue, successful delivery, and draft
  deletion. It records hashes, changed field names, counts, totals, and timestamps
  rather than duplicating customer-facing text. Scheduled actions remain deferred.
- **Controlled draft revisions:** V1.13 adds financial-draft tools that revise
  existing editable proposals and invoices after a field-level confirmation.
  Proposal scope and pricing may be replaced with a total preview. Invoice
  revisions are limited to safe header/text fields and line descriptions; rates,
  quantities, taxes, credits, time links, and totals remain immutable to AI.
- **Manual follow-up evidence:** V1.14 adds one-at-a-time proposal, retainer,
  invoice, and overdue-invoice follow-up drafting and delivery. Every reminder
  shows the exact recipient, subject, and message, requires the existing final
  confirmation, enforces a repeat interval, and records delivery plus later
  response/payment evidence. It does not schedule, repeat, or batch-send.
- **Workflow completion and usability:** V1.15 adds bounded multi-turn context
  from redacted summaries, server-verified current-page context, and a persistent
  Action Center for confirmations after navigation. This is the recommended
  stopping point for code-side AI development before controlled real use.
- **OpenAI operational observability:** V1.16 adds a unique client-generated
  troubleshooting ID to every OpenAI request, persists both client and provider
  request IDs, supports explicit OpenAI organization/project scoping, and warns
  when mutable model aliases require especially careful evaluation freshness.
- Setup, retention, deployment, and validation instructions are in
  [AI Assistant Setup and Operations](AI_ASSISTANT_SETUP.md).

## Non-negotiable safety rules

1. **No direct model or database access from the language model.** Every read and
   write goes through a registered, server-owned tool that calls an existing or
   new domain service.
2. **The server supplies identity and company scope.** The model never chooses,
   accepts, or overrides a Company or User ID.
3. **Money stays deterministic.** Decimal calculations, taxes, credits, invoice
   totals, balances, and payment status remain in EZ360PM services.
4. **External and financial actions require review.** Issuing, sending, voiding,
   withdrawing, recording payments, releasing billed time, and changing accepted
   or paid documents never happen without a visible final confirmation.
5. **Retrieved text is data, not instruction.** Notes, client messages, project
   descriptions, and document content cannot redefine the assistant's rules or
   authorize actions.
6. **Every write is auditable and repeat-safe.** Store the acting user, company,
   request summary, tool name, validated arguments, result, confirmation state,
   timestamps, and an idempotency key.
7. **Ambiguity stops execution.** When client/project/document resolution is not
   unique, the assistant presents choices rather than guessing.
8. **The standard UI remains complete.** No essential workflow may require AI.

## Action risk levels

| Level | Behavior | Initial examples |
| --- | --- | --- |
| Read | Execute immediately | search, summarize project, list overdue invoices |
| Low-risk write | Show a concise confirmation | create note, start/pause/resume/stop timer |
| Structured write | Preview exact field changes before save | create/update client, contact, project |
| Financial draft | Create draft only, then open normal editor | proposal draft, invoice draft, attach time, apply credit |
| External/financial commit | Mandatory final preview and explicit confirmation | issue/send document, record payment, void/withdraw, release time |
| Prohibited autonomous action | Never execute without purpose-built human workflow | delete financial history, refund money, alter paid invoice, move funds |

## Phase 0 - Foundation and threat model

**Goal:** establish an AI boundary that cannot bypass company isolation or domain
rules before connecting a model provider.

### TODOs

- [x] Create an `assistant` Django app with no business-record ownership of its
  own beyond AI interactions, action attempts, confirmations, and provider usage.
- [x] Define a provider-neutral model adapter so OpenAI or another provider can
  be replaced without changing domain tools.
- [x] Add settings and deployment checks for provider API key, enabled/disabled
  state, selected model, timeout, maximum tool rounds, and monthly cost guard.
- [x] Create an explicit tool registry. Tools receive `request.user` or a
  server-created action context; they never receive a model-selected company ID.
- [x] Define typed JSON schemas for every tool input and output. Reject unknown
  fields and free-form ORM lookup instructions.
- [x] Add an `AIInteraction` record for prompt summary, response summary, token
  usage, model/provider, latency, outcome, and redacted error details.
- [x] Add an `AIActionAttempt` record for tool, risk level, normalized arguments,
  dry-run result, confirmation, idempotency key, execution result, and related
  object references.
- [x] Define retention and deletion rules. Do not store full sensitive prompts by
  default when a structured/redacted summary is sufficient.
- [x] Add prompt-injection tests using stored Notes and Project text, verify
  sensitive Client/Proposal/Invoice free text is excluded from general search tools,
  and require explicit current-message write intent before any non-read tool.
- [x] Add company-isolation tests across collection reads, reference reads,
  financial summaries, document draft/delivery tools, CRM writes, and confirmation
  endpoints; also reject server-owned scope fields from every registered schema.
- [x] Add rate limits, request-size limits, tool-round limits, provider timeouts,
  and a fail-closed response when the provider is unavailable.
- [x] Add an AI feature flag so the assistant can be disabled without affecting
  ordinary EZ360PM workflows.

### Exit gate

A mocked model can request registered read tools, but cannot submit a company ID,
call an unregistered operation, perform a write without the required confirmation,
or expose another company's record.

## Phase 1 - Read-only business assistant

**Goal:** provide immediate value with no business-data mutation.

### Initial questions to support

- What needs my attention today?
- Which projects are waiting for a retainer?
- Which proposals were opened but not answered?
- Which invoices are overdue or partially paid?
- How much unbilled time exists by project?
- What did I work on last Tuesday?
- What has the Smith project earned and what is its effective hourly rate?
- How much revenue came from Stripe, checks, cash, and other methods this year?
- How much did Stripe deduct in fees?
- Which records are missing email, site-address, rate, or billing information?

### TODOs

- [x] Implement company-scoped search tools for Clients, Contacts, Projects,
  Notes, Time Entries, Proposals, Invoices, Payments, and revenue reports.
- [x] Reuse the existing dashboard and reporting query/services instead of
  reproducing financial aggregation inside prompts.
- [x] Return record identifiers, display labels, allowed follow-up actions, and
  direct application URLs from tools.
- [x] Add ambiguity handling for similar client and project names.
- [x] Add citations/links in assistant responses back to the exact EZ360PM record
  or filtered list that supports the answer.
- [x] Prevent internal-only fields, public tokens, payment references, provider
  secrets, and unrelated contact data from being returned unnecessarily.
- [x] Add read-tool regression tests for company isolation, query limits, empty
  results, invalid dates, and financial total reconciliation. Runtime execution is
  still required in the normal project environment.
- [x] Add a desktop/mobile command bar and a conversation drawer that never
  obstructs the persistent timer.

### Exit gate

The assistant answers the supported questions from scoped application data, and
all financial answers reconcile to the existing report screens and exports.

## Phase 2 - Quick capture and timer control

**Goal:** automate the lowest-risk, highest-frequency actions.

### TODOs

- [x] Add `create_note` through the existing intake validation path.
- [x] Add `start_timer`, `pause_timer`, `resume_timer`, and `stop_timer` tools
  using the existing timer services.
- [x] Resolve project references by exact number first, then unique company-scoped
  name/client matches; show choices when ambiguous.
- [x] Require a concise confirmation before starting a timer on a resolved
  project; stop/pause/resume may use one-step confirmation because the active
  timer is already known.
- [x] Surface existing service errors clearly, including a running timer on
  another project or a project status that does not accept time.
- [x] Add idempotency so retries cannot create duplicate notes or timer entries.
- [x] Add voice-friendly command handling through device dictation without
  introducing a separate audio-storage requirement.
- [x] Add tests for duplicate submissions, ambiguous project names, browser
  retries, stopped/paused state, and cross-company project IDs. Runtime execution
  is still required in the normal project environment.

### Exit gate

A user can dictate an intake note and control the complete timer lifecycle from
mobile while the ordinary timer widget remains accurate after reload.

## Phase 3 - Client, contact, and project actions

**Goal:** convert natural-language intake into structured CRM records without
silent overwrites or duplicates.

### TODOs

- [x] Add `update_client` and contact-management domain services so AI and forms
  share one transactional path.
- [x] Add `update_project_details` service separate from status transitions.
- [x] Implement dry-run tools for create/update client, add/update contact, set
  primary contact, create project, and update project details.
- [x] Build duplicate detection using normalized email, phone, client/company
  name, and address; return possible matches before create.
- [x] Parse intake notes into proposed Client, Contact, and Project fields while
  preserving the original Note unchanged.
- [x] Offer explicit actions: attach to existing record, create missing records,
  edit proposed values, or cancel.
- [x] Show field-level diffs for updates; never silently blank an omitted field.
- [x] Keep project status changes on the existing dedicated status workflow and
  call `change_project_status` only after a separate confirmation.
- [x] Add validation for same-company relationships and locked client/project
  context.
- [x] Add tests for duplicates, partial contact data, multiple contacts, primary
  contact changes, address persistence, invalid billing combinations, stale data,
  and retries. Runtime execution is still required in the normal project environment.

### Exit gate

An intake note can become a reviewed Client + primary Contact + lead Project, and
routine field updates show an exact diff before the shared services save them.

## Phase 4 - Proposal and invoice drafting

**Goal:** reduce document preparation time while preserving the existing editor
and deterministic financial logic.

### TODOs

- [x] Add project-context tools that gather approved proposal data, unbilled
  time, retainers, company defaults, and eligible recipients.
- [x] Generate proposal scope/terms as editable draft content only. Label AI text
  clearly until the user saves or edits it.
- [x] Generate client-facing invoice descriptions from selected time entries
  without changing the original entries.
- [x] Add `prepare_proposal_draft`, `prepare_retainer_invoice_draft`, and
  `prepare_final_invoice_draft` tools that call existing document services.
- [x] Allow explicit time grouping: individual, identical description, or one
  combined line.
- [x] Allow application of available retainer credit only through the existing
  credit service and never beyond the service-calculated maximum.
- [x] Open the normal proposal/invoice detail screen after draft creation for
  review and editing.
- [x] Never let model arithmetic determine line totals, tax, fees, credits, or
  balances.
- [x] Add tests for fixed-fee, hourly, no-retainer, partial-retainer, unbilled
  time, duplicate tool calls, and cross-company inputs. The full runtime suite
  must still pass in the normal development environment.

### Exit gate

The assistant can create accurate drafts for the main project paths, but no
customer receives or gains access to a document without the existing issue/send
workflow.

## Phase 5 - Controlled issue, send, and lifecycle actions

**Goal:** allow natural-language initiation of consequential actions while
retaining a hard human approval boundary.

### TODOs

- [x] Build a mandatory final confirmation card for issue/send showing document
  type, number, client, project, recipient, total/balance, due date, payment
  availability, and resulting state.
- [x] Require a new confirmation token immediately before execution; a previous
  conversational "yes" is not sufficient after document data changes.
- [x] Re-read and lock the document during execution so the confirmation cannot
  apply to stale totals or recipients.
- [x] Call existing issue and delivery services; preserve all delivery attempts.
- [x] Support draft email wording but never allow hidden recipients or an email
  address not selected from the company-scoped contact list without explicit
  review.
- [x] Add similarly strict confirmation flows for project status changes,
  proposal withdrawal, invoice voiding, manual payment recording, and releasing
  invoice time.
- [x] Keep refunds, paid-invoice modifications, deletion of financial history,
  and money movement outside the assistant unless a later purpose-built workflow
  is separately designed and approved.
- [x] Add stale-confirmation, double-submit, provider failure, delivery failure,
  and idempotency tests.

### Exit gate

A document can be prepared through conversation, but issue/send occurs only from
an exact, current, auditable confirmation and produces the same history as the
ordinary UI.

## Phase 6 - Real-use refinement and optional automation

**Goal:** improve only the assistant behavior supported by real EZ360PM usage.

### TODOs

- [x] Log corrections, abandoned actions, ambiguity events, tool failures,
  suggestion use, and dismissals without storing unnecessary sensitive content.
- [x] Add metadata-only AI document-draft instrumentation for revision events,
  changed field categories, issue/adoption outcome, first successful delivery, and
  deletion while still a draft. Do not retain duplicate customer-facing text.
- [x] Measure task completion, confirmation cancellation, tool failure, latency,
  and provider cost by capability.
- [x] Add saved command suggestions based on common actions, not private prompt
  training.
- [x] Add proactive read-only flags for stale leads, forgotten running timers,
  approved projects without funded retainers, unbilled completed work, and missing
  recipient data.
- [x] Keep proactive messages dismissible and bounded by configurable item and
  refresh limits.
- [x] Add manually initiated, one-at-a-time proposal and invoice follow-up drafting
  with exact recipient/message confirmation, repeat protection, and evidence
  reporting before considering any scheduled workflow.
- [ ] Consider scheduled drafts/reminders only after the same follow-up action has
  been repeatedly approved manually and the V1.14 evidence report shows acceptable
  delivery, correction, and outcome patterns; sending remains separately controlled.
- [x] Reassess model/provider, retention, and cost controls before exposing AI to
  SaaS customers. V1.8 adds company policy controls and V1.9 documents the initial
  OpenAI provider security/data-processing review.
- [x] Add repeatable contract and live read-only evaluations before model, prompt,
  tool, or SDK changes are approved for production.
- [x] Add controlled-pilot access, helpful/not-helpful response ratings, issue
  reporting, and a company-scoped operations screen.
- [x] Add a fail-closed circuit breaker that pauses only the AI layer after a
  configurable cluster of failures; ordinary EZ360PM remains available.
- [x] Add bounded redacted multi-turn context that remains scoped to one user,
  company, conversation, and recent time window.
- [x] Add server-verified current-page context for natural references such as
  “this project” without trusting browser-supplied ownership.
- [x] Add a persistent user-scoped Action Center so pending confirmations survive
  drawer closure and navigation.

### Exit gate

Real-use evidence shows the assistant reduces recurring work without increasing
financial corrections, duplicate records, privacy risk, or support burden.

## Code-side completion point

V1.16 completes the currently recommended AI implementation and operational observability. Additional AI
features should be driven by controlled-pilot evidence. Scheduled preparation
may be considered only after repeated manual approvals; autonomous sending,
refunds, paid-invoice changes, financial-history deletion, and money movement
remain outside the assistant. See `AI_UPGRADE_COMPLETION.md`.

## SaaS conversion requirements

Before the assistant is enabled for customer companies:

- [x] Add per-company AI enablement, usage allowance, and administrator controls.
- [ ] Map the implemented company request/cost allowances to future SaaS plans.
- [x] Add company-specific retention/consent settings and an in-app privacy disclosure.
  Public SaaS legal language still requires review.
- [x] Prevent one tenant's prompts, tool results, files, examples, or cached
  context from entering another tenant's request.
- [x] Add per-company request and cost limits with a fail-closed state.
- [x] Add company-scoped usage reporting and metadata-only audit export without
  exposing prompts, arguments, or unrelated customer content.
- [x] Add selected-user rollout controls and an emergency company AI pause/resume
  path before broad tenant enablement.
- [x] Complete an initial technical security and data-processing review of the
  selected model provider. See `OPENAI_PROVIDER_REVIEW.md`.
- [ ] Complete customer-facing legal/privacy review and any required DPA or ZDR
  approval before public SaaS launch.

## Recommended delivery order

1. Complete real-use validation of the existing application.
2. Implement Phase 0 and Phase 1 only.
3. Use the read-only assistant until its record resolution is trustworthy.
4. Add Phase 2 timer and quick-capture actions.
5. Add Phase 3 CRM/project writes with field-level confirmation.
6. Add Phase 4 financial/document drafts.
7. Add Phase 5 issue/send only after repeated successful draft use.
8. Let evidence—not the desire for an AI label—determine Phase 6.
