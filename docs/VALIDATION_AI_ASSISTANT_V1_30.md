# EZ360PM AI Assistant V1.30 Validation

Run in the normal project environment:

```bash
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase29_optional_integration
python manage.py test assistant.tests.test_phase30_global_feature_gate
python manage.py test assistant
python manage.py test
```

Manual checks:

1. Set `AI_ASSISTANT_ENABLED=false` and restart the application.
2. Confirm ordinary authenticated pages render without an assistant drawer.
3. Request `/assistant/ask/`, `/assistant/settings/`, and `/assistant/actions/`
   directly and confirm each returns 404.
4. Confirm no `AICompanySettings` row is created by those requests.
5. Re-enable AI, restart, and confirm the normal assistant drawer and routes return.
