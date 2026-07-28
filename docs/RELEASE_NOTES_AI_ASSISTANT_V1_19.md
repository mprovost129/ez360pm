# EZ360PM V1.19 — Retry-Safe Client Intake

## Purpose

V1.19 addresses the remaining reliability problems observed while creating clients
through the OpenAI assistant. It does not add new AI authority.

## Deterministic client-template fast path

When the assistant asks for missing client details, it now returns this exact format:

```text
Create this client:
Company/household:
Contact first name:
Contact last name:
Email:
Phone:
Billing address 1:
Billing address 2:
City:
State:
Postal code:
Country:
Internal note:
```

Submitting a filled version of that template is parsed locally by EZ360PM. The
request does not call OpenAI, uses zero model tokens, does not consume the monthly OpenAI request allowance, and immediately prepares the
normal create-client confirmation card. Only contact first and last name are
required. Validation and duplicate checks still run through the existing domain
service before confirmation and again before execution.

Free-form commands such as `Add Andrew Standring as a client` continue to use the
focused one-request OpenAI path from V1.18.

## Retry-safe pending actions

An identical active pending action is now reused across assistant requests for the
same company and user. A browser retry or repeated provider response therefore
cannot create multiple confirmation cards for the same normalized write. Expired,
canceled, completed, or failed attempts are not reused.

Preparation is serialized through a short company-row lock to close the concurrent
request race.

## Long-request user experience

The assistant drawer now:

- Changes `Working…` to `Still working…` after eight seconds.
- Explains after 25 seconds that OpenAI is still processing and no write can occur
  without confirmation.
- Applies a browser timeout that must outlast the Gunicorn worker timeout.
- Directs the user to check the Action center before retrying after a timeout,
  because a confirmation may have been prepared before the connection closed.

Configure the browser timeout with:

```env
AI_BROWSER_REQUEST_TIMEOUT_SECONDS=195
```

The deployment check requires this value to exceed `GUNICORN_TIMEOUT_SECONDS` by at
least five seconds.

## Evaluation coverage

The AI configuration fingerprint now includes focused instructions, tool routing,
the deterministic client-template parser, focused model controls, and pending-action
preparation. Static evaluation checks verify the local template path and retry-safe
confirmation reuse.

## Deployment

No database migration is required.

```bash
pip install -r requirements.txt
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase19_retry_and_local_fast_path
python manage.py test assistant
python manage.py test
```
