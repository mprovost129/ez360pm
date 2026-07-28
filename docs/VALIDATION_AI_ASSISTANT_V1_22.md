# Validation — AI Assistant V1.22

## Required runtime checks

```bash
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase22_local_client_discovery
python manage.py test assistant
python manage.py test
```

## Manual client-template check

1. Open the assistant drawer.
2. Select **Client template**.
3. Confirm that the complete structured client form appears in the composer and
   that no request has been sent yet.
4. Enter first and last name and any optional information.
5. Send the form and confirm that a client preview appears without an OpenAI API
   call or token usage.
6. Confirm the action and verify the client and primary contact were created.
7. Put unrelated text in the composer and select **Client template**; confirm the
   existing text is not replaced unless you approve the warning.

## Route and keyboard checks

1. Prepare an action and confirm or cancel it from the assistant drawer.
2. Confirm the request uses the server-rendered Action Center route.
3. Confirm the same behavior works when the application is served behind its
   normal proxy configuration.
4. Verify `Ctrl+Enter` on Windows or `Command+Enter` on macOS submits the form.

## Safety assertions

- The template button only fills the composer; it does not save data.
- Client creation still requires duplicate validation and confirmation.
- The local route remains subject to company/user access, privacy,
  suspension, and structured-write policy.
- No new financial, delivery, refund, or autonomous action was added.
- No database migration is required.
