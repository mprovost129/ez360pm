# EZ360PM V1.28 Validation

## Completed in the packaging environment

- Parsed 216 Python source files successfully.
- Verified the assistant app, context processor, routes, drawer, and JavaScript integration markers.
- Verified `DocumentDelivery.FollowUpKind` is nested under `DocumentDelivery`.
- Verified subject, message, and follow-up fields exist in the model and migration chain.
- Verified local imports used by assistant production modules resolve to source modules and top-level symbols.
- Verified the exact client template parses locally, including multiline notes containing invoice/timer language.
- Checked 54 HTML templates for balanced Django delimiters.
- Checked both assistant JavaScript files with `node --check`.
- Checked for merge-conflict markers.
- Checked for high-confidence committed OpenAI secret patterns; only examples/test placeholders were present.

## Required in the normal project environment

```bash
python manage.py migrate
python manage.py makemigrations --check
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test assistant.tests.test_phase27_client_template_precedence
python manage.py test assistant
python manage.py test clients projects documents
python manage.py test
```

Then perform a live client test:

1. Open the assistant drawer.
2. Select **Client template**.
3. Complete first and last name; optionally add other fields.
4. Put text such as `send the invoice after approval` in Internal note.
5. Submit.
6. Confirm that no OpenAI request is recorded, only `create_client` is prepared, and the client is not saved until confirmation.
