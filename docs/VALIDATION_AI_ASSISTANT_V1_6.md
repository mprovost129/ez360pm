# Validation - AI Assistant V1.6

## Static validation completed

- Python source compilation and AST parsing.
- Assistant JavaScript syntax validation.
- Django template delimiter validation.
- Migration file review for company/user ownership and uniqueness.
- Proactive-query review for company scoping.
- ZIP integrity validation.

## Runtime validation required in the project environment

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
python manage.py test
```

The build environment used to package this release could not install the pinned
Python dependencies, so Django runtime checks were not executed here.

## Manual checks

1. Open the assistant drawer and verify only current-company alerts appear.
2. Dismiss an alert and verify it remains hidden after reload.
3. Resolve the underlying condition and verify the alert disappears.
4. Complete assistant actions and verify common commands reorder without exposing
   prompt text.
5. Open AI usage and reliability and reconcile request/cost totals to the
   `AIInteraction` records.
6. Click Revise and Cancel on prepared actions and verify the event totals change.
7. Disable proactive insights and verify the assistant remains fully usable.
