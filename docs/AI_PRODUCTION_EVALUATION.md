# AI Production Evaluation

V1.9 adds a repeatable evaluation path for the OpenAI-powered assistant. The goal is to detect tool-selection drift, weakened safety boundaries, unexpected write preparation, rising latency, and cost changes before enabling or upgrading a model in production.

## Contract checks

Contract checks do not call OpenAI and do not read customer business records. They verify:

- all provider tool schemas are strict and reject unknown fields;
- company/user/tenant scope cannot be supplied by the model;
- every write tool has an executor and an explicit current-message intent rule;
- prohibited refund, money-movement, paid-invoice mutation, and financial-deletion tools are absent;
- OpenAI requests retain `store=False`, disabled parallel tool calls, and bounded output;
- the system instruction retains the injection, ambiguity, payment, and refund boundaries;
- the deployment default model is inside `AI_ALLOWED_MODELS`.

Run:

```bash
python manage.py evaluate_ai_assistant
```

Use `--no-persist-contract` in CI when a database audit row is not wanted.

## Live read-only suites

Live suites call the configured OpenAI Responses API using the selected company's normal policy and usage limits. They use only read-oriented prompts. Any unexpected pending action is automatically canceled and the case fails.

```bash
python manage.py evaluate_ai_assistant \
  --live \
  --user owner@example.com \
  --suite all \
  --output var/ai-evaluation.json
```

Available suites:

- `core`: attention, invoices, revenue/fees, missing information, and timer lookup;
- `security`: stored-text injection, read-only project search, and unsupported refund behavior;
- `all`: both suites.

An optional `--model` may be supplied only when that model appears in `AI_ALLOWED_MODELS`.

## What is stored

Evaluation records store:

- case identifier and category;
- expected and actual tool names;
- pass/fail/error status;
- pending-action count;
- tokens, estimated cost, and latency;
- a short operational result.

They do not store tool outputs, business records, the full provider response, payment references, document content, or recipient addresses.

## Release gate

Before enabling AI in production or changing the selected model:

1. Run migrations and the complete Django test suite.
2. Run the contract evaluation and require 100% pass.
3. Run the live `core` and `security` suites against a controlled company.
4. Review the Evaluation History screen.
5. Compare token use, estimated cost, and latency with the prior approved baseline.
6. Manually validate one read-only question, one low-risk confirmation, one CRM confirmation, one document draft, and one consequential final-confirmation flow.
7. Do not enable a model or prompt change when any evaluation fails without a documented explanation and corrective action.

The evaluation suite supplements—not replaces—the domain test suite, tenant-isolation tests, manual financial reconciliation, and backup/restore drills.
