# EZ360PM V1.7 - AI Production Hardening

## Added

- Server-owned security envelopes around every registered tool result forwarded
  to the OpenAI Responses API.
- Explicit classification of retrieved text as untrusted business data.
- Detection and labeling of common instruction-like text stored in records.
- A deterministic explicit-write-intent check. A non-read tool is rejected unless
  the current user message directly requests the matching action.
- A configurable maximum serialized tool-output size. Oversized lookups fail
  closed and ask the user to narrow the request.
- Deployment checks for the output-size boundary and explicit-write-intent setting.
- Expanded regression coverage for prompt injection, company isolation, query
  limits, empty results, invalid dates, financial reconciliation, timer lifecycle,
  duplicate records, address persistence, cross-company references, and retries.

## Safety behavior

Stored Notes, Project descriptions, company defaults, time descriptions, and
other retrieved content can inform an answer but cannot authorize a write. Even
when the user explicitly requests a write, the existing risk-level confirmation
still applies before execution.

The hardening layer does not add autonomous sending, refunds, paid-invoice edits,
financial deletion, or money movement.

## Configuration

```env
AI_MAX_TOOL_OUTPUT_CHARS=40000
AI_REQUIRE_EXPLICIT_WRITE_INTENT=true
```

Keep explicit write intent enabled in production. The deployment check reports a
warning if it is disabled and an error when the output limit is below 1,000
characters.

## Runtime commands

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
python manage.py test
```

No database migration is required for V1.7.
