# EZ360PM V1.29 Validation

## Completed in the packaging environment

- Parsed and compiled all Python source files.
- Verified the disabled context path does not call `get_company_policy`.
- Verified the enabled context path requests an existing policy with `create=False`.
- Verified missing policies use an unsaved default policy.
- Verified the client-template shortcut requires both assistant availability and structured-write permission.
- Checked Django template delimiters and assistant JavaScript syntax.
- Checked for merge-conflict markers and high-confidence committed OpenAI keys.
- Verified ZIP integrity.

## Required in the normal project environment

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase29_optional_integration
python manage.py test assistant
python manage.py test
```

Manual checks:

1. Set `AI_ASSISTANT_ENABLED=false`, load several authenticated pages, and confirm no `AICompanySettings` row is created.
2. Set AI defaults to enabled and acknowledged with no saved company policy; confirm the drawer can render without creating the row.
3. Open AI Settings or submit the first assistant request and confirm the company policy row is then created intentionally.
