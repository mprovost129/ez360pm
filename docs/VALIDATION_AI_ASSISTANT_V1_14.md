# EZ360PM V1.14 Validation

## Static checks completed in the packaging environment

- Python AST parsing and bytecode compilation across application source files.
- Strict schema and explicit-write-intent mapping for `send_document_follow_up`.
- Company-scope and eligible-recipient review.
- Full document/delivery snapshot stale-check review.
- Follow-up repeat-interval and delivery-purpose review.
- Evidence-report company scope and CSV-formula-safety review.
- Template delimiter, JavaScript syntax, migration structure, secret-pattern, and ZIP integrity checks.

## Runtime checks required in the project environment

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase14_follow_up_drafts
python manage.py test assistant documents
python manage.py test
```

## Manual validation

1. Issue a test proposal and ask AI to prepare a follow-up.
2. Confirm the card shows the exact client contact, subject, message, document state,
   and that no schedule is created.
3. Send it and verify Delivery history identifies Client follow-up and Proposal follow-up.
4. Attempt a second follow-up inside the configured interval and verify it is blocked.
5. Repeat with an unpaid retainer, a current final invoice, and an overdue final invoice.
6. Change the document or recipient after preview and verify confirmation fails stale.
7. Verify another company's document/contact cannot be resolved or disclosed.
8. Verify failed email attempts remain in delivery history and in Follow-up Evidence.
9. Record a later test payment or proposal response and verify the evidence report
   labels it as a subsequent outcome without claiming causation.
10. Export CSV and verify it contains only the signed-in company's follow-ups.
