# EZ360PM V1.14 - AI Manual Client Follow-ups and Evidence

## Purpose

Bridge the gap between fully manual delivery and future reminder automation by
allowing one reviewed follow-up at a time while gathering real-use evidence.

## Included

- Company-scoped context for open proposals, retainers, final invoices, and overdue invoices.
- Exact classification as proposal follow-up, retainer reminder, invoice reminder,
  or overdue-invoice reminder.
- AI-prepared subject and client-facing message with an external-commit confirmation.
- Recipient restriction to email-bearing contacts on the document client.
- Full document/delivery snapshot revalidation before execution.
- Configurable repeat protection through `AI_FOLLOW_UP_MIN_INTERVAL_HOURS`.
- Distinct `DocumentDelivery` purpose and follow-up kind for successful and failed attempts.
- Resend support that preserves the original follow-up classification and wording.
- Company-scoped Follow-up Evidence screen and CSV export.
- Subsequent proposal-response and payment timing shown as evidence, not causal attribution.

## Safety boundary

V1.14 does not schedule, repeat, or batch-send reminders. It does not create
refunds, alter paid invoices, delete financial history, or move money. Every
follow-up requires the same exact final confirmation used by other external actions.

## Migration

```text
documents.0008_documentdelivery_follow_up_fields
```

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase14_follow_up_drafts
python manage.py test assistant documents
python manage.py test
```
