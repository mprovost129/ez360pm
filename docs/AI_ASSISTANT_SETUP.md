# EZ360PM AI Assistant Setup and Operations

## Current implementation

V1.17 includes the guarded action phases, production hardening, company-level AI controls, production evaluation, controlled-use readiness, and pilot operations:

- **Foundation:** provider adapter, strict tool registry, redacted interaction logs,
  auditable pending actions, rate limits, request limits, cost guard, feature flag,
  and security checks.
- **Read-only assistant:** clients, contacts, projects, notes, time, proposals,
  invoices, payments, revenue/fees, missing information, overdue invoices,
  unanswered proposals, projects waiting for retainers, and dashboard attention.
- **Low-risk actions:** create a quick note and start, pause, resume, or stop the
  timer.
- **Structured CRM actions:** create/update clients, add/update contacts, set a
  primary contact, create/update projects, change project status through the
  dedicated workflow, attach intake notes, and convert a note into a reviewed
  client + primary contact + lead project.
- **Financial-document drafts:** gather project/document context, prepare editable
  proposal drafts, create retainer drafts from accepted proposals, and prepare
  final invoice drafts from deterministic fixed-fee or time-entry services with
  optional paid-retainer credit. AI-authored descriptions never replace the
  original time entries.
- **Controlled draft revisions:** inspect one existing editable draft, revise
  proposal scope/pricing with a total preview, or revise invoice dates, terms,
  payment settings, and client-facing descriptions without changing invoice
  amounts, credits, time links, or original time-entry text.
- **Conversation and page context:** reuse a bounded number of recent redacted
  summaries in one browser conversation, resolve supported current-page records
  through the authenticated company boundary, and restore pending confirmations
  through the Action Center.
- **Manual client follow-ups:** prepare one proposal, retainer, invoice, or
  overdue-invoice reminder using current document state and eligible client
  contacts. The exact recipient, subject, and message require the external-commit
  confirmation. Follow-ups are never scheduled, repeated, or batch-sent.

Every write displays Confirm, Revise, and Cancel controls before an existing
EZ360PM domain service executes it. Draft tools open the normal document editor
after creation. V1.5 added exact final confirmation for issue/send and other
consequential actions. V1.6 adds local workflow alerts, dismissals, personalized
fixed-command suggestions, and an AI usage/reliability report. V1.7 adds a
server-enforced explicit-write-intent boundary, security-wrapped untrusted tool
results, output-size limits, and expanded injection/isolation regression coverage. Refunds, paid-invoice
changes, deletion of financial history, and money movement remain unavailable.
V1.8 adds per-company enablement, allowlisted model selection, action-category
controls, request/cost allowances, privacy acknowledgement, configurable
read-only retention, and metadata-only audit export. V1.9 adds contract checks,
read-only live OpenAI suites, persistent evaluation history, and an initial
provider security/data-processing review. V1.10 adds a tool-free OpenAI connection
test, an in-app readiness checklist, evaluation freshness, and a deployment gate.
V1.11 adds selected-user rollout controls, response feedback, incident reporting,
an automatic failure circuit breaker, and emergency pause/resume operations.


## Focused single-action requests (V1.17)

Clear client, contact, project, note, and timer commands use a server-selected
minimal tool catalog. A client-creation request therefore exposes `create_client`
without separate search tools; the create-client preview performs the duplicate
check itself. When any write confirmation is prepared, EZ360PM returns it
immediately rather than spending another OpenAI request on a summary.

`AI_MAX_TOOL_CALLS` limits the total number of registered tool invocations in one
assistant request. Focused actions use a one-call limit. Keep the global default
small and ask users to split unrelated work into separate commands.

V1.18 adds a focused-request fast path. Complete create-client commands force the
one exposed function, omit earlier conversation summaries and unrelated page
context, and use one provider round. Focused requests also use the smaller
`AI_FOCUSED_MAX_OUTPUT_TOKENS` allowance plus the configured reasoning and verbosity
controls. Incomplete commands remain on automatic tool choice so the assistant can
ask one concise question instead of guessing.

## Environment variables

The assistant is disabled unless explicitly enabled.

```env
AI_ASSISTANT_ENABLED=true
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_ORG_ID=
OPENAI_PROJECT_ID=
AI_MODEL=gpt-5
AI_ALLOWED_MODELS=gpt-5
AI_WARN_ON_UNPINNED_MODEL=true
AI_PROVIDER_TIMEOUT_SECONDS=30
AI_MAX_TOOL_ROUNDS=4
AI_MAX_TOOL_CALLS=4
AI_MAX_OUTPUT_TOKENS=3000
AI_FOCUSED_MAX_OUTPUT_TOKENS=600
AI_FOCUSED_REASONING_EFFORT=minimal
AI_FOCUSED_VERBOSITY=low
AI_MAX_PROMPT_CHARS=4000
AI_CONVERSATION_CONTEXT_TURNS=4
AI_CONVERSATION_CONTEXT_MINUTES=60
AI_MAX_REQUEST_BYTES=12000
AI_MAX_TOOL_OUTPUT_CHARS=40000
AI_REQUIRE_EXPLICIT_WRITE_INTENT=true
AI_RATE_LIMIT_REQUESTS=10
AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS=30
AI_RATE_LIMIT_WINDOW_SECONDS=60
AI_MONTHLY_COST_LIMIT_USD=25.00
AI_COMPANY_DEFAULT_ENABLED=
AI_COMPANY_DEFAULT_EXTERNAL_COMMITS=
AI_COMPANY_DEFAULT_PRIVACY_ACKNOWLEDGED=
AI_COMPANY_DEFAULT_MONTHLY_REQUEST_LIMIT=500
AI_COMPANY_DEFAULT_RETENTION_DAYS=90
AI_COMPANY_DEFAULT_ACCESS_MODE=all_users
AI_COMPANY_DEFAULT_FAILURE_THRESHOLD=5
AI_COMPANY_DEFAULT_FAILURE_WINDOW_MINUTES=60
AI_INPUT_COST_PER_MILLION_USD=0
AI_OUTPUT_COST_PER_MILLION_USD=0
AI_MODEL_PRICING_JSON={}
AI_PROACTIVE_INSIGHTS_ENABLED=true
AI_PROACTIVE_MAX_ITEMS=4
AI_PROACTIVE_DISMISS_DAYS=7
AI_PROACTIVE_REFRESH_SECONDS=3600
AI_DRAFT_STALE_DAYS=14
AI_FOLLOW_UP_MIN_INTERVAL_HOURS=24
AI_STALE_LEAD_DAYS=14
AI_FORGOTTEN_TIMER_HOURS=8
AI_READINESS_MAX_EVALUATION_AGE_DAYS=30
```

`AI_RATE_LIMIT_REQUESTS` applies only to OpenAI-backed requests.
`AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS` separately limits deterministic zero-token
workflows such as the structured client template, so an OpenAI burst does not block
local intake while the local endpoint still has an abuse guard. Both use
`AI_RATE_LIMIT_WINDOW_SECONDS`.

Set the two per-million token rates to the current rates for the default model.
When more than one model is allowlisted and their rates differ, configure
`AI_MODEL_PRICING_JSON` as an object keyed by model name with `input` and `output`
per-million-token rates. The application records provider token usage and applies
the matching rate for the interaction model. Leaving all rates at zero keeps usage
logging but makes the dollar estimate zero.

Run `python manage.py check --deploy` after changing the settings. The assistant
check fails closed when it is enabled without an API key.

## Deployment

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
```

For a controlled pilot, set the company access mode to **Selected users** in AI
Settings, then grant access from **AI Pilot Operations**. An emergency pause affects
only the assistant. The ordinary CRM, timer, documents, payments, and reports remain
available. Suspending AI cancels every still-pending confirmation so a prepared
action cannot be revived after the incident without being prepared and reviewed again.

The same controls are available from the command line:

```bash
python manage.py manage_ai_pilot --company-id 1 --suspend --reason "Investigating pilot incident"
python manage.py manage_ai_pilot --company-id 1 --resume
python manage.py manage_ai_pilot --company-id 1 --grant-user owner@example.com
python manage.py manage_ai_pilot --company-id 1 --revoke-user owner@example.com
```

The integration uses the official OpenAI Python SDK and the Responses API with
strict registered function tools, `parallel_tool_calls=false`, bounded tool
rounds, a provider timeout, and `store=false`. The server manually carries the
minimum response items needed for the tool loop. OpenAI API data handling remains
subject to the data controls configured for the OpenAI organization/project.

## Data boundary

- The model never receives a tool field for Company or User ID.
- Every tool derives company scope from the authenticated request user.
- The model has no ORM, SQL, shell, file, web, Stripe, or email tool.
- Tool schemas reject unknown fields.
- Every tool result is wrapped in a server-owned security envelope that labels
  returned record text as untrusted business data and flags instruction-like text.
- The server rejects every write tool unless the current user message explicitly
  requests the matching action; retrieved notes or descriptions cannot authorize it.
- Oversized tool results fail closed and require a narrower search or date range.
- Public document tokens, Stripe references, secrets, and unrelated contact data
  are excluded from read-tool projections.
- Money remains calculated by existing Decimal-based application services.

## Write confirmation

Low-risk and structured-write tools do not execute during the model call. They
create an `AIActionAttempt` with:

- authenticated user and company;
- normalized arguments;
- a human-readable preview;
- ten-minute confirmation expiry;
- idempotency key;
- confirmation and execution timestamps;
- safe result or error code.

The browser sends a separate authenticated, CSRF-protected POST to confirm. The
server executes server-resolved IDs, rechecks duplicate/stale-record conditions,
and reruns ordinary domain validation. Revise cancels the original attempt and
prefills a new request; Cancel writes nothing. Repeated confirmation of a completed
action returns its saved result rather than creating a duplicate.

## Retention

Full prompts and full responses are not stored in the EZ360PM database. The app
stores redacted, length-limited summaries plus provider/model, token usage,
latency, outcome, safe error codes, and OpenAI request IDs for troubleshooting.
User-submitted feedback comments and incident details are retained as deliberate
pilot records until reviewed or administratively removed; they are not copied from
the underlying prompt or response automatically.

Recommended baseline:

- Keep interactions with action attempts as operational audit records.
- Configure read-only retention in each company's AI settings.
- Run the cleanup on a schedule; without `--days`, each company policy is used:

```bash
python manage.py purge_ai_history --dry-run
python manage.py purge_ai_history
```

Use `--company-id` for one tenant or `--days` only as an explicit administrative
override. The audit CSV intentionally excludes prompt summaries, tool arguments,
tool results, document content, recipient details, and payment references.

## Manual validation checklist

1. Ask what needs attention and compare every count to the dashboard.
2. Ask for annual revenue and fees and compare to the Revenue screen/Payment rows.
3. Search for a client, project, proposal, invoice, payment, and note.
4. Create a note, cancel it, and verify nothing was written.
5. Create a note, confirm it, and verify exactly one record exists.
6. Start a timer by exact project number, reload, pause, resume, and stop.
7. Try an ambiguous project name and verify the assistant asks for a choice.
8. Create and update a test client/contact; confirm the field diff and duplicate
   warning behavior.
9. Create and update a test project; confirm status remains a separate action.
10. Convert an intake note and verify its original text remains unchanged.
11. Prepare a proposal draft, review the generated sections and pricing in the
    normal editor, and verify it remains Draft with no delivery attempt.
12. Prepare an hourly final invoice using selected time and confirm the original
    time descriptions remain unchanged while the invoice line can use edited
    client-facing wording.
13. Prepare a fixed-fee final invoice with a paid retainer and reconcile charges,
    credit, and balance against the normal invoice screen.
14. Prepare a retainer draft from an accepted proposal and confirm existing + new
    retainers cannot exceed the accepted total.
15. Try another company's object ID/reference in a test environment and verify no
    record is disclosed or changed.
16. Disable `AI_ASSISTANT_ENABLED` and verify all ordinary workflows still work.
17. Remove the API key in a test environment and verify deployment checks fail.
18. Store instruction-like text in a test Note and Project description; request only
    a summary and verify no write confirmation is prepared.
19. Ask a clear write command, confirm it still prepares the expected confirmation,
    and verify no company/user scope field is accepted from the model.
20. Lower the tool-output limit in a test environment and verify broad lookups fail
    closed with a request to narrow the search.
21. Switch the company to Selected users, revoke the current user, and verify no
    OpenAI request occurs; grant access and verify the same command succeeds.
22. Submit helpful and not-helpful feedback and verify it appears only in the
    company pilot report.
23. Report a critical pilot incident and verify AI pauses while ordinary EZ360PM
    screens continue working.
24. Trigger the configured failure threshold in a test environment and verify the
    circuit breaker blocks the next request before an OpenAI call.
25. Ask for a follow-up on an open proposal, confirm the recipient, subject, and
    message, and verify the delivery is recorded as Client follow-up.
26. Try another follow-up inside the configured minimum interval and verify it is
    blocked before confirmation.
27. Send a test overdue-invoice reminder, record a later test payment, and verify
    the AI Follow-up Evidence report shows a subsequent payment without claiming
    the reminder caused it.

## Phase 5 consequential actions

V1.5 registers issue, issue-and-send, resend, proposal withdrawal, unpaid-invoice voiding, verified manual payment entry, project-status changes, and release of time from a void invoice. Every action is prepared first and rendered as an external-commit card. The user must check the final-review acknowledgement and click the exact confirmation button.

Issue/send recipients are restricted to email-bearing contacts already attached to the document's company-scoped client. A changed document, recipient, total, due date, payment, line item, or time attachment invalidates the confirmation. Email subject and optional message are stored on the delivery record so delivery history and resends remain auditable.

The assistant still cannot issue refunds, alter paid invoices, delete financial history, or move money.


## Phase 6 refinement

The assistant drawer loads deterministic workflow flags directly from current
EZ360PM records. No OpenAI API request is made for these alerts. The initial flags
cover stale leads, long-running timers, approved projects without a funded
retainer, completed projects with unbilled time, and clients without an email
recipient. Each condition has a stable key and can be dismissed for the configured
number of days.

The AI usage and reliability screen is available from the assistant drawer. It
reports scoped interaction volume, completion/failure counts, token usage, local
cost estimate, latency, action outcomes, and capability-level results. Correction,
ambiguity, cancellation, failure, suggestion, and dismissal events store only
small operational metadata.

Manual follow-up drafting and one-at-a-time confirmed delivery are enabled in
V1.14. Scheduled drafts, repeating reminders, batch delivery, and autonomous
sending are not enabled. Those remain subject to repeated real-world approval
evidence and a separate design review.


## V1.7 production hardening

V1.7 adds a deterministic authorization check before every non-read tool. The
current user message must directly request the matching action; text retrieved
from notes, project descriptions, defaults, time entries, or document context
cannot supply that authorization. Confirmation remains mandatory after the action
is prepared.

Provider tool results are serialized inside an `_ez360pm_security` envelope. The
envelope identifies the registered tool, labels enclosed values as untrusted
business data, and marks common instruction-like text without deleting legitimate
record content. `AI_MAX_TOOL_OUTPUT_CHARS` prevents an unexpectedly broad result
from being forwarded to the provider. Keep
`AI_REQUIRE_EXPLICIT_WRITE_INTENT=true` in production.


## V1.8 company controls and privacy

The platform feature flag remains the outer boundary. Each company may have an
`AICompanySettings` record, provisioned lazily by the AI settings screen or the first
assistant request. Creating a Company or User does not create assistant records.
Selected-user access rows are created only through an explicit staff grant. The
assistant is available only when both platform and company levels are enabled and
the company has acknowledged the in-app data-processing notice.

The company settings screen controls:

- deployment-allowlisted OpenAI model selection;
- notes/timer actions;
- client/contact/project writes;
- proposal/invoice drafts;
- confirmed sending and financial lifecycle actions;
- proactive local workflow alerts;
- monthly request and estimated-cost allowances;
- redacted-summary storage and read-only retention.

Capability controls are enforced twice: disabled tools are omitted from the
OpenAI request, and confirmation execution rechecks the current policy. The
lower of the company and platform cost guards applies. Reaching a limit never
blocks ordinary EZ360PM screens.

For a future SaaS launch, set new-company defaults explicitly to false, then map
the already implemented request/cost allowances to subscription plans only after
the billing design is finalized.


## V1.9 production evaluation

Run static tool/provider contract checks after migrations and before every production model or tool change:

```bash
python manage.py evaluate_ai_assistant
```

Run the read-only live OpenAI baseline against a controlled company user:

```bash
python manage.py evaluate_ai_assistant \
  --live \
  --user owner@example.com \
  --suite all \
  --output var/ai-evaluation.json
```

Live evaluation requests count against the company request and cost limits. They never confirm actions. Any unexpected pending action is canceled automatically and the case fails. Review `/assistant/evaluations/` after the run. See `AI_PRODUCTION_EVALUATION.md` and `OPENAI_PROVIDER_REVIEW.md`.


## V1.10 controlled-use readiness

Open `/assistant/readiness/` after configuring the company. Run the minimal
OpenAI connection test, then establish the full read-only baseline from the
command line. Use the deployment gate before enabling real work:

```bash
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py check_ai_readiness --user owner@example.com --output var/ai-readiness.json
```

See `AI_CONTROLLED_USE_READINESS.md`. A passing result covers the AI layer only;
it does not replace the full Django suite, accounting reconciliation, email and
Stripe tests, or backup/restore drill.

## AI document draft quality evidence

V1.12 creates one `AIDocumentDraftReview` record after a confirmed AI proposal or
invoice draft is successfully created. Ordinary document forms and services then
update that record when the draft changes, is issued, is successfully delivered,
or is deleted while still a draft.

The tracker stores SHA-256 hashes for customer-facing text plus field names, line
and section structure, totals, revision counts, and lifecycle timestamps. It does
not store another readable copy of proposal scope, terms, internal notes, or invoice
line descriptions. The report is available at **Assistant -> Draft quality** and
can export the same metadata as CSV. `AI_DRAFT_STALE_DAYS` controls when an active
AI draft is reported as stale; it defaults to 14 days.

## V1.13 controlled document draft revisions

Use the assistant only after the draft already exists and is still in Draft
status. A typical proposal request is:

> Revise proposal P-26-0004. Replace the scope with the updated addition scope and
> change the design fee to $5,000.

A typical invoice request is:

> Revise invoice I-26-0012. Improve the client-facing descriptions, move the due
> date to September 1, and allow online payment.

The assistant first reads the exact company-scoped draft, then prepares a
Financial Draft confirmation. Proposal confirmations show section/line counts and
any total change. Invoice confirmations show the exact date, setting, and
client-facing description changes while explicitly preserving rates, quantities,
taxes, credits, time-entry links, and totals.

Only Draft documents are eligible. A changed document invalidates the prepared
revision. Confirming opens the normal editor and leaves the document unissued.
No new environment setting or migration is required.


## Conversation and current-page context

The browser stores a random conversation identifier in session storage. EZ360PM
uses only recent redacted summaries from the same user and company. Starting a
new conversation changes that identifier; it does not delete audit history or
pending confirmations. Set `AI_CONVERSATION_CONTEXT_TURNS=0` to disable this
context entirely.

The assistant also sends the current URL path. The server resolves the route and
re-queries supported records through `request.user.company` before creating a
minimal context label. Client-supplied object ownership is never trusted.

Pending actions can be recovered from **AI Assistant → Action Center**.


## OpenAI request troubleshooting

Every logical Responses API call carries a unique `X-Client-Request-Id`. Both the client-generated ID and any provider response request ID are retained in the metadata-only interaction audit and CSV export. Configure `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` when the credential can reach more than one organization or project. Mutable model aliases are allowed, but readiness warns until the fingerprinted live evaluation is current; use a dated snapshot when predictable behavior is more important than automatically receiving model updates.


## Zero-token client template

If client creation is missing required identity information, the assistant returns a
copyable `Create this client:` template. A completed template is parsed locally by
EZ360PM and prepares the usual confirmation without an OpenAI request. This is a
reliability path, not a bypass: duplicate detection, validation, company scoping, and
confirmation still apply. Free-form client commands continue to use OpenAI.

Set the browser timeout longer than the worker timeout:

```env
AI_BROWSER_REQUEST_TIMEOUT_SECONDS=195
```


## Optional AI configuration safety

AI-only environment values are parsed defensively. A malformed number, decimal,
boolean, or `AI_MODEL_PRICING_JSON` value no longer prevents Django from importing
settings while the assistant is globally disabled. `python manage.py check --deploy`
reports those inactive values as `assistant.W007` warnings.

When `AI_ASSISTANT_ENABLED=true`, the same parse problems are deployment-blocking
`assistant.E028` errors. The assistant continues to fail closed until the environment
values are corrected. Only `AI_PROVIDER=openai` is supported; any other provider is
reported as `assistant.E029`.
