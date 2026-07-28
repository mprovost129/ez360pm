# EZ360PM V1.3 - OpenAI API and Structured CRM Actions

## Added

- Official OpenAI Python SDK integration using the Responses API.
- Provider request IDs retained on the redacted interaction audit record for API troubleshooting.
- Strict function tools for creating and updating clients.
- Contact creation, contact updates, and primary-contact changes.
- Project creation and field-level project updates.
- A separate AI project-status action that calls the existing status workflow.
- Intake-note attachment to existing clients or projects.
- Reviewed conversion of an intake note into a Client, primary Contact, and lead
  Project while preserving the original note text.
- Normalized duplicate checks for email and phone, with possible name/address
  matches shown in previews.
- Server-resolved execution arguments so the model cannot swap record IDs between
  preview and confirmation.
- Stale-record checks for fields displayed in update previews.
- Confirm, Revise, and Cancel controls for prepared actions.
- Optional email and phone fields for Contacts, with a database migration.

## Deliberately not added

- Proposal or invoice drafting.
- Issuing or sending documents.
- Recording payments, voiding invoices, releasing billed time, refunds, or money
  movement.

These remain in later guarded phases.

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant clients projects intake
python manage.py test
```

Do not enable the assistant in production until the complete runtime suite and the
manual checklist in `docs/AI_ASSISTANT_SETUP.md` pass.
