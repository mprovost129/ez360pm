# EZ360PM AI Assistant V1.25

## Request-boundary hardening

Assistant JSON endpoints now require a top-level JSON object. Arrays, strings,
booleans, `null`, malformed JSON, and invalid UTF-8 return a controlled HTTP 400
response instead of reaching view code that expects key/value fields.

## Separate local and OpenAI throttles

OpenAI-backed requests and deterministic local actions now use separate short-term
rate-limit buckets:

```env
AI_RATE_LIMIT_REQUESTS=10
AI_LOCAL_ACTION_RATE_LIMIT_REQUESTS=30
AI_RATE_LIMIT_WINDOW_SECONDS=60
```

This keeps the zero-token structured client template available after a burst of
OpenAI questions while retaining a bounded abuse guard for local submissions.
Monthly OpenAI usage and cost accounting remain unchanged.

## Multiline client notes

The structured client template now preserves continuation lines under
`Internal note:`. The note is still validated by the existing create-client schema
and normal client service before a confirmation is prepared.

## Deployment

No database migration is required.

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase25_request_boundary
python manage.py test assistant
python manage.py test
```
