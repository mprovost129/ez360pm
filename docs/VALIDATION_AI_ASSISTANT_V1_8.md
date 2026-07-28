# EZ360PM V1.8 Validation

## Automated checks to run

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant
python manage.py test
```

## Company-control checks

1. Disable AI for the company and confirm the drawer disappears and `/assistant/ask/`
   fails without an OpenAI request.
2. Re-enable AI, acknowledge the privacy notice, and verify read-only questions.
3. Disable each action category individually and confirm its suggestions and tools
   disappear.
4. Prepare an action, disable its category, and verify confirmation is blocked while
   the attempt remains pending/auditable.
5. Select each allowlisted model and confirm the interaction records the selected
   model. Reject a model not in `AI_ALLOWED_MODELS`.
6. Lower the company request limit, reach it, and confirm the next request stops
   before the provider call.
7. Lower the company cost limit below current-month estimated usage and confirm the
   next request fails closed.
8. Verify another company's usage, settings, and audit rows do not appear.

## Privacy and retention checks

1. Disable redacted-summary retention and confirm new interactions store the
   placeholder rather than prompt/response summaries.
2. Set a short test retention period and run:

```bash
python manage.py purge_ai_history --company-id <id> --dry-run
python manage.py purge_ai_history --company-id <id>
```

3. Confirm read-only interactions/events are deleted while write-action attempts
   and their interactions remain.
4. Export the AI audit CSV and confirm it contains operational metadata only—no
   prompt summaries, tool arguments, document content, recipient addresses, or
   payment references.

## Static validation completed during packaging

- Python AST parsing and bytecode compilation.
- Template delimiter checks.
- Migration/model field comparison.
- Registered-tool risk classification and company-scope schema scan.
- ZIP integrity verification.

The full Django runtime suite must still run in the normal development/deployment
environment because the packaging environment cannot install the pinned project
dependencies.
