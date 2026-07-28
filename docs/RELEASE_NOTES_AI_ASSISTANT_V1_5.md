# EZ360PM V1.5 - AI Controlled Delivery and Lifecycle Actions

## Added

- OpenAI-assisted document delivery context with company-scoped eligible recipients.
- Final confirmation cards for issuing, issuing and sending, and sending existing open documents.
- A required final-review acknowledgement for all external or financial commits.
- Exact previews of document type, number, client, project, recipient, total, balance, due date, payment availability, email wording, and resulting state.
- Stale-confirmation signatures covering document fields, line items, payments, and attached time.
- Stored delivery subject and optional message for auditable failures and resends.
- Confirmed proposal withdrawal, unpaid-invoice voiding, check/cash/other payment entry, and release of time from void invoices.
- Stronger external-commit handling for project status changes.

## Safety boundaries

- AI recipients must be existing contacts belonging to the document client.
- A changed recipient or document invalidates the prepared action.
- Delivery failures preserve the issued document and create a failed delivery record.
- Invoices with payments cannot be voided through AI.
- Stripe payments cannot be entered manually through AI.
- Refunds, paid-invoice changes, financial-history deletion, and movement of money remain unavailable.

## Database

Run migration `documents.0007_documentdelivery_subject_message`.

## Required validation

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant documents projects
python manage.py test
```
