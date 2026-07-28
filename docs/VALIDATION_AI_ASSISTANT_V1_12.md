# EZ360PM V1.12 Validation

## Static checks completed in the packaging environment

- Python AST parsing and bytecode compilation across 194 application source files.
- Migration/model field and index comparison for `AIDocumentDraftReview`.
- Template delimiter checks across 52 templates, including the new Draft Quality report.
- Route/view/template link checks for the report and CSV export.
- Source scans confirming snapshots hash customer-facing text rather than storing
  readable proposal sections, terms, notes, or line descriptions.
- Company-scope checks on report and CSV queries.
- ZIP integrity test.

## Runtime checks required in the project environment

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase12_draft_quality
python manage.py test assistant
python manage.py test
```

## Manual validation

1. Create an AI proposal draft and verify it appears as Active with zero revisions.
2. Edit terms, a scope section, and one price line through the normal UI; verify
   changed field categories and revision events update without exposing the text.
3. Issue the draft and verify it becomes Edited then used.
4. Create and issue another AI draft unchanged; verify Used as-is.
5. Send an issued AI document successfully and verify First delivery.
6. Delete an unissued AI draft and verify Abandoned remains after the Document row
   is gone.
7. Confirm another company cannot view or export any of these rows.
