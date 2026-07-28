# EZ360PM V1.12 - AI Document Draft Quality Evidence

## Purpose

Collect the evidence needed to decide whether AI proposal and invoice drafting is
actually saving work before any scheduled or autonomous workflow is considered.

## Included

- One metadata-only quality record for each confirmed AI-created proposal,
  retainer invoice, or final invoice.
- Initial and latest document snapshots using SHA-256 hashes for customer-facing
  text rather than readable duplicate content.
- Revision counts and changed field categories across ordinary document forms and
  services.
- Outcomes for active, used-as-is, edited-then-used, and abandoned drafts.
- Issue, first successful delivery, and deletion timestamps.
- Company-scoped Draft Quality report with adoption, revision, stale-draft, and
  time-to-issue metrics.
- Metadata-only CSV export.
- Admin visibility and company-isolation/privacy regression coverage.

## Safety boundary

This release adds observation only. It does not schedule drafts or reminders,
autonomously issue or send documents, refund money, modify paid invoices, delete
financial history, or move funds. Draft tracking is best-effort and cannot turn a
successfully created business document into a failed action.

## Migration

```text
assistant.0008_aidocumentdraftreview
```

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase12_draft_quality
python manage.py test assistant
python manage.py test
```
