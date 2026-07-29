# Validation: AI Assistant V1.24

## Automated coverage added

`assistant.tests.test_phase24_confirmation_validation` verifies:

1. Local client validation messages do not contain Python list formatting.
2. A duplicate created after preview causes confirmation to return HTTP 409.
3. The action is stored as `blocked` / **Needs correction**.
4. The event is recorded as `correction_requested`, not `tool_failure`.
5. A company failure threshold of one is not tripped by ordinary validation.

## Manual validation

1. Prepare a new client through the local client template.
2. Before confirming, create another client using the same email or phone.
3. Confirm the prepared AI action.
4. Verify the drawer shows the duplicate message cleanly.
5. Verify the old drawer confirmation is removed rather than remaining retryable.
6. Open **AI Action Center** and confirm the status is **Needs correction**.
7. Open **AI Pilot Operations** and confirm the event did not increase the
   operational-failure count or suspend AI.

## Required commands

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase24_confirmation_validation
python manage.py test assistant
python manage.py test
```
