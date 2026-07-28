# Validation — AI Assistant V1.20

## Required runtime checks

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase19_retry_and_local_fast_path
python manage.py test assistant.tests.test_checks
python manage.py test assistant
python manage.py test
```

## Manual checks

1. Set the company OpenAI request allowance to its current used count.
2. Submit a filled `Create this client:` template.
3. Confirm that the client confirmation appears without an OpenAI request.
4. Submit a free-form client request and confirm it is blocked by the request
   allowance.
5. Repeat the test after reaching the company cost guard.
6. Confirm that disabling structured writes, suspending company AI, or removing
   user pilot access still blocks the local template.
7. Confirm that the local interaction records zero tokens and zero estimated cost.

## Safety assertions

- Local actions do not bypass company/user AI access.
- Local actions do not bypass risk-category settings.
- Local actions still require confirmation.
- OpenAI request and cost limits still block provider-backed requests.
- No database migration is required.

## Validation/circuit-breaker checks

1. Trigger a duplicate-client validation outcome twice while the failure threshold is two.
2. Confirm both interactions are recorded as **Blocked / needs correction**.
3. Confirm the company AI circuit breaker remains inactive.
4. Trigger two actual provider failures and confirm the circuit breaker still pauses AI.
5. Confirm Usage & Reliability separates needs-correction outcomes from operational failures.
