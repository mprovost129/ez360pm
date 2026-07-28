# EZ360PM V1.4 - AI Proposal and Invoice Drafting

## Added

- Company-scoped document-draft context for project data, recipients, accepted
  proposals, unbilled time, paid retainer credit, and company defaults.
- Confirmed AI proposal-draft creation with sanitized editable scope sections and
  deterministic pricing lines.
- Confirmed retainer-invoice drafts created only from accepted proposals through
  the existing retainer service and accepted-total limits.
- Confirmed final-invoice drafts for hourly and fixed-fee projects.
- Hourly time selection and individual, matching-description, or combined
  grouping through the existing time-attachment service.
- Optional AI-written client-facing invoice descriptions while preserving the
  original TimeEntry descriptions.
- Paid-retainer credit application through the existing credit service, including
  stale/availability validation and maximum-safe limits.
- Automatic return to the normal proposal or invoice detail screen after draft
  creation.
- Recursive strict validation for nested AI tool arrays and objects.
- Phase 4 regression tests covering proposal drafts, rich-text sanitization,
  accepted-proposal retainers, hourly time attachment, fixed-fee retainer credit,
  stale time, and cross-company references.

## Safety boundary

- Every document action remains a confirmation-backed financial draft.
- AI cannot issue, send, void, withdraw, record payments, release billed time,
  refund, or move money.
- Drafts have no public access and create no delivery attempt.
- EZ360PM services calculate all totals, taxes, time quantities, and credits.

## Deployment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant documents projects
python manage.py test
```

No new database migration is required for V1.4.
