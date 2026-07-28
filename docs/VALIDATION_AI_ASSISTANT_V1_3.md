# EZ360PM V1.3 Validation Record

## Completed in the release workspace

- Parsed all 164 Python files with Python's AST parser.
- Compiled all Python files with `python -m compileall`.
- Validated balanced Django template delimiters across 46 HTML files.
- Validated `static/js/assistant.js` with `node --check`.
- Scanned registered AI tool schemas for model-supplied `company_id` and
  `user_id` fields; none are present.
- Scanned source/configuration files for common committed secret markers.
- Confirmed the official OpenAI SDK dependency and the Contact migration are
  included.
- Confirmed proposal/invoice issue, send, payment, refund, and money-movement AI
  tools are not registered in this release.

## Required in a normal development/deployment environment

The release workspace could not install the pinned Python dependencies because it
has no external package-network access. Run the following before enabling AI:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant clients projects intake
python manage.py test
```

Then complete the manual validation checklist in `AI_ASSISTANT_SETUP.md` with the
assistant pointed at a non-production OpenAI project and test company data.
