# Validation: AI Assistant V1.26

## Automated checks to run

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase26_local_template_routing
python manage.py test assistant.tests.test_phase23_local_validation_and_provider_setup
python manage.py test assistant.tests.test_phase25_request_boundary
python manage.py test assistant
python manage.py test
```

## Manual client-template check

1. Open the assistant drawer.
2. Select **Client template**.
3. Fill `Contact first name` and `Contact last name`.
4. Submit the template.
5. Confirm that a client preview appears without an OpenAI request.
6. Cancel the preview.
7. Repeat with the last name blank.
8. Confirm that EZ360PM reports the missing field locally and creates no pending action.
9. Review AI Usage & Reliability and confirm the local submission has zero tokens and
   does not increment the OpenAI request count.

## Static checks completed during packaging

- Python AST and bytecode compilation
- exact template-to-intent routing smoke check
- HTML template delimiter scan
- JavaScript syntax scan
- secret and merge-conflict scan
- ZIP integrity test

The full Django suite still requires the normal project environment with the pinned
dependencies installed.
