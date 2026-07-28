# EZ360PM V1.11 Validation

## Static validation completed in the packaging environment

- 191 Python files passed AST parsing and bytecode compilation.
- The assistant drawer JavaScript passed Node syntax validation.
- 51 Django templates passed delimiter balance checks.
- Migration/model field and choice comparison for V1.11 pilot models.
- Company-scope scans for feedback, incident, and user-access endpoints.
- High-confidence OpenAI secret-pattern scan found no committed API key.
- ZIP integrity validation (completed on the packaged release).

## Runtime validation required in the normal project environment

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant
python manage.py evaluate_ai_assistant
python manage.py evaluate_ai_assistant --live --user owner@example.com --suite all
python manage.py check_ai_readiness --user owner@example.com
python manage.py test
```

## Manual pilot checks

1. Set access mode to Selected users and verify a revoked user never reaches OpenAI.
2. Grant the same user and verify read-only and confirmed actions work normally.
3. Submit positive and negative feedback and confirm tenant isolation.
4. Report a critical incident from the assistant drawer and confirm only the AI layer is suspended and all pending confirmations are canceled.
5. Resume after review and verify pending stale confirmations remain blocked by their normal expiry/state checks.
6. Trigger the failure threshold in a test deployment and verify the next request fails before provider invocation.
7. Verify a nonstaff user cannot open Pilot Operations or change another user's access.
