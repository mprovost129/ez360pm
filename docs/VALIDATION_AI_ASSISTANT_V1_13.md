# EZ360PM V1.13 Validation

## Static checks completed in the packaging environment

- Python AST parsing and bytecode compilation across 195 application source files.
- Strict tool-schema and explicit-write-intent mapping checks for both revision tools.
- Source review confirming invoice revision schemas contain no rate, quantity,
  tax, credit, time-entry, total, payment, issue, or send operation.
- Metadata snapshot stale-check review for documents and line items.
- Company-scope and cross-document line-reference review.
- Draft-quality privacy review confirming readable customer text is not copied
  into `AIDocumentDraftReview` snapshots.
- Template delimiter, JavaScript syntax, secret-pattern, and ZIP integrity checks.

## Runtime checks required in the project environment

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase13_document_revisions
python manage.py test assistant
python manage.py test
```

## Manual validation

1. Create a Draft proposal and ask AI to revise its scope and price.
2. Confirm the card shows section/line counts and the exact total change.
3. Confirm the proposal remains Draft and opens in the normal editor.
4. Modify a proposal after preview and verify the stale confirmation is rejected.
5. Create an hourly Draft invoice with attached time and ask AI to improve the
   client-facing description and due date.
6. Verify the line quantity, rate, tax, total, linked TimeEntry IDs, TimeEntry
   descriptions, and invoice balance remain unchanged.
7. Verify another company's document number and another invoice's line ID are rejected.
8. Verify issued or paid documents cannot be selected by the revision context tool.
9. Verify the Draft Quality report records the revision without readable copied text.
