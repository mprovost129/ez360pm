# EZ360PM V1.8 - AI Company Controls and Privacy

## Added

- A company-owned `AICompanySettings` record with a dedicated AI settings screen.
- Per-company enable/disable control layered under the platform-wide feature flag.
- Deployment-allowlisted OpenAI model selection with optional per-model cost rates.
- Independent capability controls for:
  - notes and timer actions;
  - client/contact/project writes;
  - proposal and invoice drafts;
  - confirmed sending and financial lifecycle actions.
- Disabled capabilities are omitted from the OpenAI tool list and are rechecked
  when a pending confirmation is executed.
- Company-wide monthly request and estimated-cost limits that fail closed before
  an OpenAI API request.
- Company-specific proactive-alert control.
- Company-specific read-only interaction retention and an option to store only
  operational metadata instead of redacted prompt/response summaries.
- A required company data-processing acknowledgement before AI can remain enabled.
- An allowlisted model override while retaining the deployment default.
- Current-month usage progress on the AI usage/reliability screen.
- A company-scoped operational audit CSV containing interaction, action, and event
  metadata without prompts, action arguments, document content, or tool results.
- Retention cleanup that follows each company's configured period unless an
  explicit command-line override is supplied.
- New company defaults that can be made opt-in before a later SaaS launch.

## Safety behavior

The OpenAI API remains an interpretation layer. Company settings cannot enable
anything prohibited by the platform. Refunds, paid-invoice modifications,
financial-history deletion, unrestricted recipients, and money movement remain
unavailable.

Turning off a capability does both of the following:

1. removes those tools from subsequent OpenAI requests; and
2. blocks a previously prepared action in that category before execution.

The lower of the company cost limit and platform-wide cost limit is enforced.
Ordinary EZ360PM workflows remain available when AI is disabled or a limit is
reached.

## Migration

This release adds:

```text
assistant.0004_aicompanysettings
```

Existing companies receive enabled settings matching the prior V1.7 behavior.
New companies use the deployment defaults in `.env.ai.example`.

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
python manage.py test
```

After migration, review `/assistant/settings/`, confirm the OpenAI model allowlist,
set company limits, and verify the privacy acknowledgement before production use.

## Still deferred

Scheduled drafts, reminders, and autonomous sending remain deferred until repeated
real use shows a stable, frequently approved pattern. A formal provider security
and data-processing review is still required before enabling AI for public SaaS
customers.
