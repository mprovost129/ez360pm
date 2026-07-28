# EZ360PM V1.10 Validation

## Static checks performed in the packaging environment

- Python AST and bytecode compilation across 188 repository Python files.
- Assistant URL/view/template linkage.
- OpenAI connection-test tool list is empty.
- Connection test uses the existing guarded provider adapter.
- Readiness queries are company-scoped.
- No model-supplied company or user scope was added.
- Template delimiter checks across 50 HTML templates.
- Assistant JavaScript syntax check.
- High-confidence secret-pattern scan.
- ZIP integrity test.

## Runtime checks required in the normal project environment

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py check_ai_readiness --user owner@example.com --output var/ai-readiness.json
python manage.py test
```

The connection test and live evaluation require the real OpenAI API key and count
against company request/cost allowances.
