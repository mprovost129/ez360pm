# Validation — AI Assistant V1.33

## Automated checks

```bash
python manage.py check --deploy
python manage.py test assistant.tests.test_phase33_gunicorn_timeout_alignment
python manage.py test assistant
python manage.py test
```

## Manual production checks

1. Set `GUNICORN_TIMEOUT_SECONDS=180`.
2. Deploy and confirm the Gunicorn command includes `--timeout 180` in process or
   startup diagnostics.
3. Submit a deliberately slow, read-only assistant request and confirm the worker is
   not terminated at Gunicorn's historical 30-second default.
4. Set `GUNICORN_TIMEOUT_SECONDS=not-a-number` in a non-production test environment.
5. Confirm settings import succeeds, `check --deploy` reports `ez360pm.W006`, and the
   resolved Gunicorn timeout falls back to 180.
6. Set `GUNICORN_TIMEOUT_SECONDS=29` and confirm `check --deploy` reports
   `ez360pm.E002`.
7. Confirm ordinary deployment warnings are printed but do not stop `bin/start.sh`
   when `DJANGO_DEPLOY_CHECK_FAIL_LEVEL` is unset.
8. Optionally set `DJANGO_DEPLOY_CHECK_FAIL_LEVEL=WARNING` and confirm warnings become
   deployment-blocking for a strict environment.
