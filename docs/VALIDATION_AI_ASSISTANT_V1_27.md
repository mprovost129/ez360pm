# Validation: AI Assistant V1.27

## Automated checks to run

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase27_client_template_precedence
python manage.py test assistant.tests.test_phase26_local_template_routing
python manage.py test assistant.tests.test_phase25_request_boundary
python manage.py test assistant
python manage.py test
```

## Manual template-payload check

1. Open the assistant drawer and select **Client template**.
2. Fill both required contact-name fields.
3. Enter this internal note:
   `Send the invoice next week and start the timer after approval.`
4. Submit the template.
5. Confirm that EZ360PM shows only a create-client preview.
6. Confirm that no invoice or timer action is prepared.
7. Confirm in AI Usage & Reliability that the interaction is local with zero tokens
   and does not increment the OpenAI request count.
8. Repeat with the last name blank and confirm that the missing-field correction is
   returned locally.

## Static checks completed during packaging

- Python AST and bytecode compilation
- template-prefix precedence smoke check
- HTML template delimiter scan
- JavaScript syntax scan
- secret and merge-conflict scan
- ZIP integrity test

The full Django suite still requires the normal project environment with the pinned
dependencies installed.
