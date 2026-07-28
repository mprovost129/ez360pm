# Validation — AI Assistant V1.19

## Required runtime checks

Run in the normal EZ360PM environment:

```bash
python manage.py makemigrations --check
python manage.py check --deploy
python manage.py test assistant.tests.test_phase19_retry_and_local_fast_path
python manage.py test assistant.tests.test_checks
python manage.py test assistant
python manage.py test
```

## Manual client tests

1. Submit a complete free-form command such as `Add Andrew Standring as a client.`
   Confirm that one OpenAI request prepares one confirmation.
2. Submit an incomplete command such as `Create a client.` Confirm that the response
   provides the labeled `Create this client:` template.
3. Fill and submit that template. Confirm that the usage report records zero tokens
   and a confirmation appears immediately.
4. Submit the exact filled template twice before confirming. Confirm that only one
   active confirmation appears in the Action center.
5. Let a confirmation expire and submit the template again. Confirm that a new
   confirmation is created.
6. Simulate a slow request. Confirm that the drawer updates its progress message and
   that the timeout error instructs the user to check the Action center.
7. Confirm the client and verify duplicate email/phone checks still block a duplicate
   at execution time.

## Safety assertions

- The local template path never writes without confirmation.
- The local template path accepts no company or user identifier.
- Free-form text is not parsed locally.
- Existing external-action and financial-action safeguards remain unchanged.
