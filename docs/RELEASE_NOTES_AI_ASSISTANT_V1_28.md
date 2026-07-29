# EZ360PM V1.28 — Assistant Integration Recovery

## Summary

This release uses the user-supplied `ez360pm(2).zip` as the application baseline and restores the AI assistant integration that was present in the source tree but disconnected from Django and the browser interface.

## Restored application integration

- Registered `assistant.apps.AssistantConfig` in `INSTALLED_APPS`.
- Registered the assistant context processor.
- Restored `/assistant/` URL routing.
- Restored the authenticated assistant drawer and header button.
- Restored assistant JavaScript, Action Center JavaScript, templates, and styles.
- Restored AI settings and readiness links from Company Settings.
- Restored environment configuration examples and setup documentation.

## Focused and local client workflow

The release retains the focused assistant orchestration and deterministic client-template path:

- Obvious single actions receive only the relevant registered tool.
- Focused actions stop after preparing the confirmation.
- A completed `Create this client:` template is parsed locally and does not call OpenAI.
- Template payload text cannot be interpreted as another command.
- Provider and local-action rate limits are separate.
- Incomplete templates return a local correction rather than consuming API tokens.
- Duplicate/stale validation remains auditable as `Needs correction` rather than an AI outage.

## Supporting model and service repairs

The existing assistant code referenced application capabilities that were absent from the uploaded baseline. This release restores the required contracts:

- Contact email and phone may be blank for AI-created contacts.
- Client and project domain services now expose the update operations used by confirmed AI actions.
- Document delivery stores subject and optional message.
- Document delivery distinguishes client follow-ups and their follow-up kind.
- Email delivery accepts the exact reviewed subject/message used by AI confirmations.
- Shared payment-report aggregation is available to read-only AI revenue tools.

## Migrations

Apply all migrations. New migrations relative to the uploaded baseline include:

- `clients.0002_contact_optional_email_phone`
- `documents.0007_documentdelivery_subject_message`
- `documents.0008_documentdelivery_follow_up_fields`
- `assistant.0011_aiactionattempt_blocked_status`

The assistant app itself was not registered in the uploaded settings, so deployments that never applied its migrations will apply the full assistant migration chain.

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant clients projects documents
python manage.py test
```

Verify the environment still contains the existing OpenAI settings before enabling the assistant.
