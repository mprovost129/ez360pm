# EZ360PM V1.11 - AI Controlled Pilot Operations

## Purpose

Move the OpenAI assistant from technical readiness into a bounded real-use pilot
without adding scheduled actions, autonomous sending, refunds, or money movement.

## Added

- Company access modes: all users, staff only, or selected users.
- Per-user selected pilot access with same-company enforcement.
- Helpful/not-helpful response feedback tied to the exact AI interaction.
- Company-scoped incident reporting with severity and category.
- Immediate AI suspension for critical incident reports.
- Configurable automatic circuit breaker after repeated failed interactions.
- Staff-only AI Pilot Operations screen for access, feedback, incidents, and pause/resume.
- Emergency pause and explicit manual resume; ordinary EZ360PM remains available.
- Suspending AI cancels all pending confirmations so they must be prepared again after review.
- Management command for suspend/resume and selected-user grant/revoke operations.
- Readiness checks for pilot access, suspension, high-severity incidents, and pilot feedback.

## Migration

```text
assistant.0007_ai_pilot_operations
```

## Commands

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py check_ai_readiness --user owner@example.com
python manage.py test
```

Emergency operations:

```bash
python manage.py manage_ai_pilot --company-id 1 --suspend --reason "Investigating pilot incident"
python manage.py manage_ai_pilot --company-id 1 --resume
python manage.py manage_ai_pilot --company-id 1 --grant-user owner@example.com
python manage.py manage_ai_pilot --company-id 1 --revoke-user owner@example.com
```

## Boundary retained

The assistant still cannot issue refunds, alter paid invoices, delete financial
history, or move money. Scheduled drafts and reminders remain deferred until
controlled-use evidence shows the same actions are repeatedly approved safely.
