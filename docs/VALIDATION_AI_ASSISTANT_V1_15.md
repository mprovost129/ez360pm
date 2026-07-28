# EZ360PM AI Assistant V1.15 Validation

## Static validation completed in the packaging environment

- Python AST parsing and bytecode compilation for application source.
- JavaScript syntax validation for the assistant drawer and Action Center.
- Django template delimiter checks.
- Migration/model field and dependency checks.
- Conversation context is scoped by company, user, conversation ID, status, and
  time window.
- Earlier turns cannot satisfy current-message write-intent checks.
- Current-page context is resolved server-side and rejects cross-company paths.
- Action Center queries are scoped by company and authenticated user.
- Expired pending actions are closed before display.
- Existing prohibited-action and tenant-scope scans remain clean.
- ZIP integrity validation.

## Required runtime validation

Run in the normal project environment:

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase15_context_and_action_center
python manage.py test assistant
python manage.py test
```

## Manual checks

1. Ask about a project, then ask a read-only follow-up using “it.”
2. Start a new conversation and confirm the earlier context is no longer used.
3. Open a project, client, proposal, and invoice page and ask “What is this?”
4. Attempt to use another company's object path and confirm no page context is
   exposed.
5. Prepare a low-risk and an external-commit action, close the drawer, and resume
   each from the Action Center.
6. Let a confirmation expire and confirm it cannot be executed.
7. Disable redacted summary retention and confirm multi-turn context is absent.
