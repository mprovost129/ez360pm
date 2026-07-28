# EZ360PM AI Controlled-Use Readiness

V1.10 adds one company-scoped readiness result for the OpenAI assistant. It is a
launch checklist for the AI layer, not a substitute for the complete EZ360PM
runtime, accounting, delivery, Stripe, backup, or restore validation.

## In-app checklist

Open **AI Assistant → AI readiness**. The page checks:

- application-level AI feature flag;
- OpenAI API key presence;
- company enablement and privacy acknowledgement;
- selected model against the deployment allowlist and whether it is a mutable alias or dated snapshot;
- remaining company/platform request and estimated-cost allowances;
- latest static contract evaluation;
- latest minimal OpenAI connection test for the selected model;
- latest full read-only live evaluation for the selected model;
- recent assistant failure rate; and
- expired pending confirmations.

A warning does not block the readiness result. A failed required check does.
Evaluation freshness is controlled by:

```env
AI_READINESS_MAX_EVALUATION_AGE_DAYS=30
```

Each evaluation stores a SHA-256 configuration fingerprint derived from the
selected model, system instructions, registered tool definitions, write-intent
mapping, and guarded provider request implementation. A result with a different
fingerprint fails readiness even when it is recent. Changing the model, OpenAI
SDK, instructions, tools, schemas, or provider request path therefore requires
new contract, connection, and live baseline runs.

## Minimal OpenAI connection test

The **Test OpenAI connection** button sends one tool-free Responses API request
using the company-selected allowlisted model. It expects the exact response token
`EZ360PM_OPENAI_READY`. The request:

- uses `store=false` through the ordinary provider adapter;
- exposes no EZ360PM record and registers no business tool;
- records the client-generated request ID, any provider response request ID, latency, tokens, estimated cost, and pass/fail;
- counts against the company request and cost guards; and
- never prepares or confirms an action.

A connection test proves that the configured key, project permissions, selected
model, network path, and Responses endpoint can complete the minimal contract. It
does not prove business-tool accuracy; the full read-only live suite does that.


## Model stability and troubleshooting IDs

OpenAI model aliases can change behavior as the provider updates the alias. A dated
model snapshot is treated as pinned; an alias produces a readiness warning rather
than a failure. Any model, prompt, SDK, tool, schema, or provider-path change also
changes the configuration fingerprint and requires new evaluations.

Every logical Responses API request receives a unique `X-Client-Request-Id`. The
interaction audit stores that identifier before the network call, so it remains
available for timeout investigations even when OpenAI cannot return its own request
ID. Successful and rejected API responses retain the provider request ID as well.

## Deployment command

Run after migrations and before enabling the assistant for real work:

```bash
python manage.py check_ai_readiness --user owner@example.com
```

Write a JSON artifact for a deployment record:

```bash
python manage.py check_ai_readiness \
  --user owner@example.com \
  --output var/ai-readiness.json
```

The command exits nonzero while required checks fail. Use `--no-fail` only for an
informational report; do not use it as the production deployment gate.

## Recommended controlled-use sequence

1. Run `python manage.py migrate` and the full Django test suite.
2. Run `python manage.py evaluate_ai_assistant` for the static contract suite.
3. Open AI settings and verify company controls, privacy acknowledgement, model,
   token rates, request allowance, and cost guard.
4. Run the in-app OpenAI connection test.
5. Run the full read-only baseline:

   ```bash
   python manage.py evaluate_ai_assistant \
     --live \
     --user owner@example.com \
     --suite all \
     --output var/ai-evaluation.json
   ```

6. Run `check_ai_readiness` and preserve the JSON result with release records.
7. Begin with read-only requests, notes, and timer actions. Enable financial
   drafts and external commits only after the lower-risk paths reconcile to the
   ordinary EZ360PM screens.

## What readiness does not approve

A passing result does not authorize refunds, autonomous sending, paid-invoice
changes, deletion of financial history, or money movement. Those remain outside
the assistant. It also does not establish customer-facing legal language, a DPA,
Zero Data Retention eligibility, SaaS plan mapping, or general public launch.
