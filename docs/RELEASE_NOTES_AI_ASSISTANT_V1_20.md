# EZ360PM V1.20 — Local Action Budget Independence

## Purpose

V1.20 fixes one remaining mismatch in the zero-token client intake path. The
structured `Create this client:` template did not call OpenAI and did not count
against monthly usage, but it was still blocked when the company had already
reached its OpenAI request or cost allowance.

## Changes

- EZ360PM now identifies deterministic local actions before checking provider
  request and cost allowances.
- A local client-template action still requires:
  - the application and company assistant to be enabled;
  - acknowledged AI/privacy settings;
  - current-user pilot access;
  - no company AI suspension;
  - structured client/project writes to be enabled;
  - the normal confirmation, duplicate checks, and execution safeguards.
- A local action no longer depends on:
  - remaining OpenAI monthly request allowance;
  - remaining OpenAI monthly cost allowance;
  - a valid provider model override;
  - an OpenAI API request.
- Provider-backed requests remain blocked when the request or cost guard is
  reached.

## Why this matters

The client template is an ordinary deterministic EZ360PM workflow presented
inside the assistant. Reaching an OpenAI budget should disable provider-backed
language processing, not block a zero-token action that performs no provider
call.

## Deployment

No database migration is required.

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase19_retry_and_local_fast_path
python manage.py test assistant
python manage.py test
```

## Validation outcomes versus operational failures

- Domain validation outcomes now use the existing `blocked` interaction status.
- Duplicate clients, ambiguous records, and other user-correctable validation results
  remain visible in audit history but do not count toward the automatic AI circuit
  breaker.
- Historical V1.19-and-earlier failed rows with `error_code=domain_validation` are
  also excluded from circuit-breaker and reliability calculations.
- Provider, orchestration, invalid-tool, and unexpected application failures still
  count as operational failures.
- The Usage & Reliability screen now separates **Needs correction** from
  **Operational failures**.
