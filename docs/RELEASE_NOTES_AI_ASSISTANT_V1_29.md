# EZ360PM V1.29 — Optional AI Isolation and Lazy Company Policy

## Summary

This release keeps the restored AI assistant optional at the page-rendering boundary. Ordinary authenticated pages no longer create or query AI company-policy records when the application-level AI flag is disabled.

## Updates

- The assistant context processor returns immediately when `AI_ASSISTANT_ENABLED=false`.
- Rendering a page no longer creates `AICompanySettings` as a side effect.
- When AI is enabled and a company has no saved AI policy, the drawer is evaluated from an unsaved copy of the deployment defaults.
- The real company policy row is created only when AI settings or an AI request requires persistence.
- The client-template shortcut is shown only when the assistant is actually available and structured writes are allowed.
- Removed a duplicate tool-call counter initialization in the assistant orchestration loop.

## Why this matters

- Disabling AI keeps normal EZ360PM pages independent of assistant database tables.
- A routine GET request no longer writes to the database.
- First-time AI policy creation remains intentional and auditable.
- Deployments can keep AI off without incurring assistant-policy queries on every authenticated page.

## Deployment

No database migration or static-file collection is required.

```bash
pip install -r requirements.txt
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase29_optional_integration
python manage.py test assistant
python manage.py test
```
