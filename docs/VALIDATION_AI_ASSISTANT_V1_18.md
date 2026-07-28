# AI Assistant V1.18 Validation

## Static checks completed

- 216 Python files passed source parsing and compilation.
- Focused client-routing checks for complete and incomplete requests.
- Provider request-shape coverage for forced function choice, focused output cap,
  reasoning effort, and verbosity.
- Existing tenant, explicit-intent, confirmation, and tool-scope guards retained.
- 57 templates passed delimiter checks and 3 project JavaScript files passed syntax checks.
- Secret-pattern and ZIP-integrity checks.

## Required in the normal project environment

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_openai_provider
python manage.py test assistant.tests.test_assistant
python manage.py test assistant
python manage.py test
```

Run live client commands with complete data, missing optional data, a missing last
name, a likely duplicate email, and a likely duplicate phone number. Confirm that a
complete command produces one OpenAI request and one review card.
