# EZ360PM V1.13 - AI Controlled Document Draft Revisions

## Purpose

Let the OpenAI assistant improve an existing editable proposal or invoice without
issuing, sending, or bypassing EZ360PM's deterministic financial services.

## Included

- Company-scoped read context for one Draft proposal or invoice.
- Proposal revision with sanitized scope sections, terms, notes, and complete
  pricing-line replacement after an exact total-change preview.
- Invoice revision limited to issue/due dates, terms, internal notes, online
  payment setting, and selected client-facing line descriptions.
- Invoice rates, quantities, taxes, credits, linked time entries, and totals are
  not accepted as revision inputs and are revalidated at execution.
- Explicit current-message intent and Financial Draft confirmation requirements.
- Metadata-snapshot stale checks that reject any intervening document or line edit.
- Company isolation, ambiguous-record handling, duplicate line protection, and
  cross-document line rejection.
- Draft-quality evidence for manually created documents first revised through AI,
  using the existing metadata/hash-only tracker.
- Normal editor redirect after confirmation; the document remains Draft.

## Safety boundary

The tools cannot revise an issued, sent, viewed, accepted, declined, paid,
partially paid, withdrawn, or void document. They cannot issue or send a document,
record or refund a payment, release time, delete financial history, or move money.

## Migration

None.

## Deployment

```bash
pip install -r requirements.txt
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase13_document_revisions
python manage.py test assistant
python manage.py test
```
