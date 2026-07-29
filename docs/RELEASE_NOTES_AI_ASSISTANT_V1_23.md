# EZ360PM V1.23 — Local template validation and provider setup safety

## Purpose

V1.23 closes two runtime gaps found after the V1.22 client-intake refinements. It
adds no new AI authority.

## Changes

### Incomplete client templates remain local

- Any request beginning with `Create this client:` is now recognized as the
  deterministic local workflow, even when a required field is missing.
- Missing `Contact first name` or `Contact last name` returns a precise local
  correction message.
- Incomplete templates do not call OpenAI, consume tokens, or count against the
  monthly OpenAI request allowance.
- Customer values from an incomplete local template are omitted from retained AI
  interaction summaries, matching the complete-template privacy behavior.
- The correction is recorded as `Blocked / Needs correction`, not an operational
  failure, so it cannot trip the AI circuit breaker.

### Provider and model setup failures fail safely

- OpenAI provider construction now occurs inside the assistant execution safety
  boundary.
- A missing API key, unsupported provider, SDK setup problem, or other provider
  initialization failure produces a recorded safe assistant failure rather than
  an unhandled server error.
- Model allowlist validation is translated into the existing assistant-unavailable
  response before provider work begins.
- No write action is prepared or executed when provider setup fails.

### Evaluation and regression coverage

- The AI configuration fingerprint now includes the complete local-template
  inspection logic.
- Static contract evaluation verifies the local correction path as well as the
  complete zero-token path.
- Added regression coverage for incomplete templates, privacy, zero provider
  usage, missing API configuration, and invalid model selection.

## Deployment

No database migration or static-file collection is required for V1.23 itself.
Run the normal validation sequence:

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase23_local_validation_and_provider_setup
python manage.py test assistant
python manage.py test
```
