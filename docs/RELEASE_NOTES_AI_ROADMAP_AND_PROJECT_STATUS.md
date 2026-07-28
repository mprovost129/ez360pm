# AI Roadmap and Project Status Update

## Implemented application change

- Project status is no longer part of Edit Project.
- The Project detail dashboard now shows a visible status selector beside
  **Edit project details**.
- Status changes use a dedicated company-scoped POST endpoint and the existing
  transactional `change_project_status` service.
- The action requires the existing browser confirmation and does not modify
  proposals, invoices, payments, or time records.
- A running timer still blocks changes to On hold, Completed, or Canceled.
- Regression tests cover placement, valid changes, invalid values, running-timer
  protection, POST-only behavior, and cross-company isolation.

No database migration is required for this change.

## Planning added

- Added `docs/AI_ASSISTANT_ROADMAP.md` with Phases 0-6, safety levels, detailed
  TODO checklists, phase exit gates, and SaaS conversion requirements.
- Updated the main roadmap, architecture, and screen-flow documentation to link
  the assistant plan and document the new project-status location.

## Validation performed in this package

- All Python files parse and compile successfully.
- Stale Python bytecode and macOS metadata were removed from the package.
- Django runtime checks and tests require installing the pinned project
  dependencies; package installation was unavailable in the execution
  environment used for this update.

Run after extracting in the normal project environment:

```bash
python manage.py check
python manage.py test projects
ruff check .
```
