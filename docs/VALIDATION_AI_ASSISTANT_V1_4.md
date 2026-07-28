# EZ360PM V1.4 Validation Record

## Completed in the release workspace

- Parsed and compiled all Python source files.
- Added strict recursive validation for nested tool arrays and objects.
- Confirmed the Phase 4 tool module does not import or register document issue,
  delivery, payment, void, refund, or money-movement services.
- Confirmed every Phase 4 write uses the Financial Draft risk level and a separate
  confirmation attempt.
- Confirmed proposal content uses the existing rich-text sanitizers.
- Confirmed invoice time and retainer operations call the existing transactional
  document services.
- Added source-level tests for hourly, fixed-fee, retainer, stale-data, and
  cross-company paths.
- Validated template delimiters, assistant JavaScript syntax, tool schemas, and
  ZIP integrity during packaging.

## Required in a normal development/deployment environment

The release workspace does not contain the pinned Django runtime dependencies.
Run these commands before enabling V1.4 in production:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant documents projects
python manage.py test
```

Then complete the expanded manual checklist in `AI_ASSISTANT_SETUP.md` using test
projects and a non-production OpenAI API project.
