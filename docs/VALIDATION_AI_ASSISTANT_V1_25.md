# Validation: AI Assistant V1.25

## Automated coverage added

`assistant.tests.test_phase25_request_boundary` verifies:

1. Non-object JSON receives a controlled 400 response.
2. Invalid UTF-8 receives a controlled 400 response.
3. Provider-rate exhaustion does not block the local client template.
4. Local actions retain their own bounded rate limit.
5. Multiline internal notes are preserved by the local template parser.
6. Deployment checks reject zero or negative provider/local rate limits.

## Manual validation

1. Submit several OpenAI-backed questions until the short provider limit is reached.
2. Open the Client template and submit a complete local client.
3. Confirm it still prepares a zero-token confirmation.
4. Put a three-line note under `Internal note:` and verify all lines appear in the
   confirmation and saved client.
5. Submit an array such as `[]` to the assistant endpoint using an API client and
   verify a JSON-object error is returned rather than a server error.

## Required commands

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase25_request_boundary
python manage.py test assistant
python manage.py test
```
