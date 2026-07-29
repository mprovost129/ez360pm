# Validation — AI Assistant V1.32

## Automated checks

```bash
python manage.py check --deploy
python manage.py test assistant.tests.test_phase32_optional_ai_configuration
python manage.py test assistant
python manage.py test
```

## Manual configuration checks

1. Set `AI_ASSISTANT_ENABLED=false` and intentionally set
   `AI_PROVIDER_TIMEOUT_SECONDS=not-a-number`.
2. Confirm Django starts and `python manage.py check --deploy` reports
   `assistant.W007` rather than crashing settings import.
3. Set `AI_ASSISTANT_ENABLED=true` with the same invalid value.
4. Confirm `check --deploy` reports `assistant.E028` and deployment fails closed.
5. Set `AI_PROVIDER=unsupported` with AI enabled.
6. Confirm `check --deploy` reports `assistant.E029`.
7. Restore valid values and confirm the assistant readiness checks proceed normally.
