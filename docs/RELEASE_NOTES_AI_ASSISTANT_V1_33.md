# EZ360PM AI Assistant V1.33

## Gunicorn timeout alignment and deployment-warning behavior

The application previously validated `GUNICORN_TIMEOUT_SECONDS`, but the production
start command did not pass that value to Gunicorn. Gunicorn therefore retained its
own default worker timeout even when EZ360PM was configured for longer OpenAI
requests.

V1.33 closes that gap:

- `GUNICORN_TIMEOUT_SECONDS` is parsed defensively during settings import.
- A malformed value falls back to 180 seconds and is reported as `ez360pm.W006`.
- Values below 30 seconds are rejected as `ez360pm.E002`.
- `bin/start.sh` resolves the sanitized Django setting and passes it to Gunicorn with
  `--timeout`.
- The browser timeout, provider timeout, tool-round checks, and actual Gunicorn worker
  timeout now refer to the same deployed configuration.
- Deployment warnings remain visible but are non-blocking by default. Errors still
  block startup. Set `DJANGO_DEPLOY_CHECK_FAIL_LEVEL=WARNING` only when a deliberately
  warning-free deployment is required.

No database migration or static-file collection is required.
